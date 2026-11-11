#!/usr/bin/env python3
# Adapted from NousResearch/hermes-agent (MIT, (c) 2025 Nous Research):
# scripts/check-windows-footguns.py. Vendored into gh-workflows so all Ait0u5hi
# repos can share one cross-platform linter via the reusable workflow.
"""
Grep-based checker for Windows cross-platform footguns.

Flags common patterns that break silently on Windows. Run before PRs —
cheap, fast, catches regressions in a codebase that runs on three OSes.

Usage:
    # Scan staged changes (default when run from a git checkout)
    python scripts/check-windows-footguns.py

    # Scan the full tree (full-repo audit)
    python scripts/check-windows-footguns.py --all

    # Scan a specific file or directory
    python scripts/check-windows-footguns.py path/to/file.py path/to/dir/

    # Scan only modified files vs. main
    python scripts/check-windows-footguns.py --diff main

Exit status:
    0 — no Windows footguns found (or all matches suppressed), OR zero Python
        files were in scope. The zero-file case prints a distinct
        "NOT-APPLICABLE: 0 python file(s) in scope (...)" line instead of the
        "No Windows footguns found" pass line; it is NOT a pass. Exit stays 0
        because the shared composite action can legitimately hand this script
        a file list with nothing in scope (a deleted or excluded .py), and a
        non-zero code would turn that job red. Callers that gate a handoff
        should grep for NOT-APPLICABLE.
    1 — at least one unsuppressed match
    2 — --diff was given a ref that doesn't resolve to a commit (bad ref
        name, typo, a base branch that was renamed or never fetched, ...).
        This is distinct from the 0/NOT-APPLICABLE case above: a ref that
        DOES resolve but has zero changed .py files is still NOT-APPLICABLE/
        exit 0 (nothing to report, but the lookup itself worked); a ref that
        doesn't resolve at all is a usage error and must fail loudly, never
        get silently counted as "zero files changed." Also returned when a
        file in scope could not be read: an unreadable file is never
        counted as scanned-and-clean.

How it reads code: each file is tokenized (stdlib `tokenize`). Comments and
triple-quoted strings (docstrings) are blanked before matching; rules that
name a Python API also ignore the contents of ordinary string literals,
while path/command rules (~/Desktop, wmic, ./script) match inside them. A
`# windows-footgun: ok` marker is honoured only in a real comment, and a
marker on any row of a multi-line statement covers the whole statement. A file that does not
tokenize is scanned line by line with only `#` comments stripped (it can
only report more, never less).

Suppress an intentional use (e.g. tests or platform-gated code) with:
    os.kill(pid, 0)  # windows-footgun: ok — only called on POSIX
"""

from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
import tokenize
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent


def rel_to_repo(path: Path) -> str:
    """Path for display / exclusion lookup, tolerant of files outside REPO_ROOT.

    The linter normally runs inside the repo it scans (REPO_ROOT == that repo).
    When invoked on another checkout's files — e.g. the shared reusable workflow
    scanning a consumer repo via the windows-footguns composite action — the
    scanned paths live under a different root, so relative_to(REPO_ROOT) raises.
    Fall back to a cwd-relative path, then to the absolute path.
    """
    for base in (REPO_ROOT, Path.cwd()):
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            continue
    return path.as_posix()


SUPPRESS_MARKER = re.compile(r"#\s*windows-footgun\s*:\s*ok\b", re.IGNORECASE)

# Line-level guard hints. If a line contains any of these tokens, we assume
# the programmer wrote the line in full awareness of the Windows pitfall —
# e.g. `if hasattr(os, 'setsid'): ... os.setsid()`, or the classic
# `getattr(signal, 'SIGKILL', signal.SIGTERM)`, or `shutil.which("wmic")`.
# False negatives are fine here — the inline `# windows-footgun: ok` marker
# is still the authoritative suppression. This is just to reduce the noise
# floor on obviously-guarded lines so the signal-to-noise stays useful.
GUARD_HINTS = (
    "hasattr(os,",
    "hasattr(signal,",
    "getattr(os,",
    "getattr(signal,",
    "shutil.which(",
    "if platform.system() != \"Windows\"",
    "if platform.system() != 'Windows'",
    "if sys.platform == \"win32\"",
    "if sys.platform != \"win32\"",
    "if sys.platform == 'win32'",
    "if sys.platform != 'win32'",
    "IS_WINDOWS",
    "is_windows",
)

# Dirs we never scan.
EXCLUDED_DIRS = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "site-packages",
    "website/build",
    "optional-skills",  # external skills
}

# File globs we never scan (beyond the dirs above).
EXCLUDED_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".so",
    ".dll",
    ".exe",
    ".png",
    ".jpg",
    ".gif",
    ".ico",
    ".svg",
    ".mp4",
    ".mp3",
    ".wav",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".whl",
    ".lock",
    ".min.js",
    ".min.css",
}

# Files we never scan (self-referential — this script mentions the
# patterns it detects — and the CONTRIBUTING docs that list them).
EXCLUDED_FILES = {
    "scripts/check-windows-footguns.py",
    "CONTRIBUTING.md",
}


@dataclass
class Footgun:
    """A Windows cross-platform footgun pattern."""

    name: str
    pattern: re.Pattern
    message: str
    fix: str
    # If set, matches in files/paths containing any of these substrings are
    # silently ignored (e.g. tests that legitimately exercise the footgun
    # behind a platform guard). Prefer `# windows-footgun: ok` inline
    # suppression over this list; only use path_allowlist for whole files
    # that are inherently tests of the footgun itself.
    path_allowlist: tuple[str, ...] = ()
    # Optional post-match predicate. Takes the re.Match and returns True
    # if the match is a REAL footgun (not a false positive). Use this when
    # the regex can't fully distinguish (e.g. open() where mode may contain
    # "b" for binary). Called as post_filter(text, head_end): `text` is the
    # "keep" view (comments and triple-quoted blocks blanked, ordinary string
    # literals intact) of the whole logical statement the match is in, rows
    # joined with one space, and `head_end` is the index in `text` just past
    # the match's `head` group (for open(): just after the paren).
    post_filter: "callable | None" = None
    # True for rules whose evidence lives INSIDE string literals (a path
    # like "~/Desktop", "wmic", "./script"). Those search the "keep" view.
    # Every other rule names a Python API and searches the "blank" view,
    # where string contents are spaced out, so prose such as
    # "os.killpg(...) is unsupported" inside a string is not a finding.
    needs_strings: bool = False


_PSEUDO_FILE_ARG = re.compile(r"""^[rRfF]{0,2}['"]/(?:proc|sys)/""")


def _is_pseudo_file_arg(arg: str) -> bool:
    """True if the first open() argument is a str/f-string literal naming a
    Linux-only pseudo-file under /proc/ or /sys/."""
    return bool(_PSEUDO_FILE_ARG.match(arg.strip()))


def _split_call_args(line: str, start: int) -> list[str]:
    """Top-level comma-separated arguments of the call whose argument list
    begins at ``line[start]`` (just after the opening paren).

    Balanced-paren scan that honours quotes, so a nested call such as
    ``p.with_suffix(".lock")`` or ``os.path.join(a, b)`` does not end the
    argument early. Stops at the call's closing paren, or at end of line for a
    call that continues on the next line.
    """
    args: list[str] = []
    depth = 0
    quote: str | None = None
    cur: list[str] = []
    i = start
    n = len(line)
    while i < n:
        c = line[i]
        if quote:
            cur.append(c)
            if c == "\\" and i + 1 < n:
                cur.append(line[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
            cur.append(c)
        elif c in "([{":
            depth += 1
            cur.append(c)
        elif c in ")]}":
            if depth == 0:
                break
            depth -= 1
            cur.append(c)
        elif c == "," and depth == 0:
            args.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    tail = "".join(cur).strip()
    if tail or args:
        args.append(tail)
    return args


_STR_LITERAL = re.compile(r"""^[rRbBuUfF]{0,2}(['"])(?P<body>.*)\1$""")


def _open_call_parts(args: list[str]) -> tuple[str, str | None]:
    """(first argument, literal mode or None) of an open() call's arguments."""
    first = args[0] if args else ""
    mode_arg = None
    if len(args) > 1 and not re.match(r"^\w+\s*=(?!=)", args[1]):
        mode_arg = args[1]
    for a in args[1:]:
        kw = re.match(r"^mode\s*=(?!=)\s*(.*)$", a)
        if kw:
            mode_arg = kw.group(1)
    lit = _STR_LITERAL.match(mode_arg.strip()) if mode_arg else None
    return first, (lit.group("body") if lit else None)


def _open_is_text_footgun(text: str, head_end: int) -> bool:
    """Decide from THIS call's own arguments only: an `encoding=` or `**`
    belonging to another call in the same statement must not excuse it."""
    stripped = text.lstrip()
    # Skip `def open(` and `async def open(` (method definitions).
    if stripped.startswith("def ") or stripped.startswith("async def "):
        return False
    args = _split_call_args(text, head_end)
    if any(re.match(r"^encoding\s*=(?!=)", a) for a in args[1:]):
        return False
    # open(path, **kwargs): encoding may be in the dict. Too expensive to
    # trace; trust the author (or they can add a # windows-footgun: ok).
    if any(a.startswith("**") for a in args):
        return False
    first, mode = _open_call_parts(args)
    # Binary mode needs no encoding. Literal Linux pseudo-files (/proc/...,
    # /sys/...) exist only on Linux and are always ASCII, so encoding is moot.
    return "b" not in (mode or "") and not _is_pseudo_file_arg(first)


FOOTGUNS: list[Footgun] = [
    Footgun(
        name="open() without encoding= on text mode",
        # Match builtins.open() specifically — NOT os.open(), .open()
        # method calls (Path.open, tarfile.open, zf.open, webbrowser.open,
        # Image.open, wave.open, etc), or `async def open()` method
        # definitions.  The pattern requires a start-of-identifier boundary
        # before `open(` so `os.open`, `.open`, `def open` are all skipped.
        # Note: Path.open() is ALSO affected by the encoding default, but
        # rather than flagging all `.open(` (huge noise), we require an
        # explicit builtins-style open() call.  Path.open() is rare in the
        # codebase compared to open() and can be audited separately.
        pattern=re.compile(
            r"""(?:^|[\s\(,;=])(?<![.\w])(?P<head>open\s*\()"""
        ),
        message=(
            "open() without an explicit encoding= uses the platform default "
            "(UTF-8 on POSIX, cp1252/mbcs on Windows) — files round-tripped "
            "between hosts get mojibake. Always pass encoding='utf-8' for "
            "text files, or use open(path, 'rb')/'wb' for binary."
        ),
        fix=(
            "open(path, 'r', encoding='utf-8')  # or 'utf-8-sig' if the "
            "file may have a BOM"
        ),
        # Filter: only flag if mode is missing-or-text AND the line doesn't
        # already pass encoding=. The mode comes from a balanced-paren scan of
        # the call's arguments (see _open_is_text_footgun), so a nested call
        # in the first argument cannot hide a binary mode.
        post_filter=_open_is_text_footgun,
    ),
    Footgun(
        name="os.kill(pid, 0)",
        pattern=re.compile(r"\bos\.kill\s*\(\s*[^,]+,\s*0\s*\)"),
        message=(
            "os.kill(pid, 0) is NOT a no-op on Windows — it sends "
            "CTRL_C_EVENT to the target's console process group, "
            "hard-killing the target and potentially unrelated siblings. "
            "See bpo-14484."
        ),
        fix=(
            "Use psutil.pid_exists(pid) (psutil is a core dependency). "
            "Or gateway.status._pid_exists(pid) for the hermes wrapper "
            "with a stdlib fallback."
        ),
    ),
    Footgun(
        name="bare os.setsid",
        pattern=re.compile(r"(?<!hasattr\()\bos\.setsid\b"),
        message=(
            "os.setsid does not exist on Windows and raises "
            "AttributeError. Subprocesses that need detachment on "
            "Windows use creationflags instead."
        ),
        fix=(
            "if platform.system() != 'Windows':\n"
            "    kwargs['preexec_fn'] = os.setsid\n"
            "else:\n"
            "    kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP"
        ),
    ),
    Footgun(
        name="bare os.killpg",
        pattern=re.compile(r"\bos\.killpg\b"),
        message="os.killpg does not exist on Windows.",
        fix=(
            "Use psutil for cross-platform process-tree kill:\n"
            "  p = psutil.Process(pid)\n"
            "  for c in p.children(recursive=True): c.kill()\n"
            "  p.kill()"
        ),
    ),
    Footgun(
        name="bare os.getuid / os.geteuid / os.getgid",
        pattern=re.compile(r"\bos\.(?:getuid|geteuid|getgid|getegid)\b"),
        message=(
            "os.getuid / os.geteuid / os.getgid do not exist on Windows "
            "and raise AttributeError at import time if referenced."
        ),
        fix=(
            "Use getpass.getuser() for the username, or gate with "
            "hasattr(os, 'getuid')."
        ),
    ),
    Footgun(
        name="bare os.fork",
        pattern=re.compile(r"(?<!hasattr\()\bos\.fork\s*\("),
        message="os.fork does not exist on Windows.",
        fix=(
            "Use subprocess.Popen for daemonization, or guard with "
            "hasattr(os, 'fork') and a Windows fallback path."
        ),
    ),
    Footgun(
        name="bare signal.SIGKILL",
        pattern=re.compile(r"\bsignal\.SIGKILL\b"),
        message=(
            "signal.SIGKILL does not exist on Windows and raises "
            "AttributeError at import time."
        ),
        fix="Use getattr(signal, 'SIGKILL', signal.SIGTERM).",
    ),
    Footgun(
        name="bare signal.SIGHUP / SIGUSR1 / SIGUSR2 / SIGALRM / SIGCHLD / SIGPIPE / SIGQUIT",
        pattern=re.compile(
            r"\bsignal\.(?:SIGHUP|SIGUSR1|SIGUSR2|SIGALRM|SIGCHLD|SIGPIPE|SIGQUIT)\b"
        ),
        message=(
            "These POSIX signals don't exist on Windows; referencing "
            "them raises AttributeError at import time."
        ),
        fix=(
            "Use getattr(signal, 'SIGXXX', None) and check for None "
            "before using, or gate the whole block behind a platform check."
        ),
    ),
    Footgun(
        name="subprocess shebang script invocation",
        pattern=re.compile(
            r"subprocess\.(?:run|Popen|call|check_output|check_call)\s*\(\s*\[\s*['\"]\./"
        ),
        message=(
            "Running a script via './scriptname' doesn't work on Windows — "
            "shebang lines aren't honored. CreateProcessW can't execute "
            "bash/python scripts without an explicit interpreter."
        ),
        fix="Use [sys.executable, 'scriptname.py', ...] explicitly.",
        needs_strings=True,
    ),
    Footgun(
        name="wmic invocation without shutil.which guard",
        # Match wmic appearing as a subprocess argument — NOT the
        # shutil.which("wmic") guard pattern itself. Looks for wmic in a
        # list or as first arg of subprocess.run/Popen.
        pattern=re.compile(
            r"""(?:subprocess\.\w+\s*\(\s*\[\s*['"]wmic['"]|['"]wmic\.exe['"])"""
        ),
        message=(
            "wmic was removed in Windows 10 21H1 and later. Always "
            "gate with shutil.which('wmic') and fall back to "
            "PowerShell (Get-CimInstance Win32_Process)."
        ),
        fix=(
            "if shutil.which('wmic'):\n"
            "    ... wmic path ...\n"
            "else:\n"
            "    subprocess.run(['powershell', '-NoProfile', '-Command',\n"
            "                    'Get-CimInstance Win32_Process | ...'])"
        ),
        needs_strings=True,
    ),
    Footgun(
        name="hardcoded ~/Desktop (OneDrive trap)",
        pattern=re.compile(
            r"""['"](?:~|~/|[A-Z]:[/\\]Users[/\\][^/\\'"]+[/\\])Desktop\b"""
        ),
        message=(
            "When OneDrive Backup is enabled on Windows, the real Desktop "
            "is at %USERPROFILE%\\OneDrive\\Desktop, not %USERPROFILE%\\"
            "Desktop (which exists as an empty husk)."
        ),
        fix=(
            "On Windows, resolve via ctypes + SHGetKnownFolderPath, or "
            "read the Shell Folders registry key, or run PowerShell "
            "[Environment]::GetFolderPath('Desktop')."
        ),
        needs_strings=True,
    ),
    Footgun(
        name="asyncio add_signal_handler without try/except",
        pattern=re.compile(r"\.add_signal_handler\s*\("),
        message=(
            "loop.add_signal_handler raises NotImplementedError on "
            "Windows — always wrap in try/except or gate with a "
            "platform check."
        ),
        fix=(
            "try:\n"
            "    loop.add_signal_handler(sig, handler, sig)\n"
            "except NotImplementedError:\n"
            "    pass  # Windows asyncio doesn't support signal handlers"
        ),
    ),
]


def should_scan_file(path: Path, base: Path | None = None) -> bool:
    """Return True if this file is in scope for the checker.

    Excluded directory names are matched against the path RELATIVE to the
    scan base (the walked root, or the current directory for explicit
    paths), never against the absolute path: a checkout that happens to live
    under e.g. /home/runner/work/build/build/ must not exclude every file.
    """
    bases = [base] if base is not None else [Path.cwd(), REPO_ROOT]
    rel_parts = path.parts
    for b in bases:
        try:
            rel_parts = path.relative_to(b).parts
            break
        except ValueError:
            continue
    if set(rel_parts) & EXCLUDED_DIRS:
        return False
    # Skip excluded suffixes
    for suffix in EXCLUDED_SUFFIXES:
        if str(path).endswith(suffix):
            return False
    # Skip self and docs that intentionally mention the patterns
    rel = rel_to_repo(path)
    if rel in EXCLUDED_FILES:
        return False
    # Only scan text files (rough heuristic — .py, .md, .sh, .ps1, .yaml, etc.)
    if path.suffix in {".py", ".pyw", ".pyi"}:
        return True
    # Other file types are read but only Python-specific patterns would match;
    # that's fine and cheap to skip.
    return False


def iter_files(paths: Iterable[Path]) -> Iterable[Path]:
    for p in paths:
        if p.is_file():
            if should_scan_file(p):
                yield p
        elif p.is_dir():
            for root, dirs, files in os.walk(p):
                # prune excluded dirs in-place for speed
                dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
                for fname in files:
                    fpath = Path(root) / fname
                    # A dangling symlink is skipped here exactly as it is
                    # when named explicitly (is_file() is False for it).
                    if not fpath.is_file():
                        continue
                    if should_scan_file(fpath, base=p):
                        yield fpath


def _strip_code(line: str) -> str:
    """Fallback only (a file that fails to tokenize): drop a trailing
    ``# ...`` comment using a simple quote-aware scan. No docstring state is
    kept, so the fallback can only report MORE than the tokenizer path."""
    stripped = line.lstrip()
    if stripped.startswith("#"):
        return ""
    hash_idx = _find_unquoted_hash(line)
    if hash_idx is not None:
        return line[:hash_idx]
    return line


def _find_unquoted_hash(line: str) -> int | None:
    """Index of the first `#` not inside a single/double-quoted string."""
    i = 0
    n = len(line)
    in_s = False  # single-quote string
    in_d = False  # double-quote string
    while i < n:
        c = line[i]
        if c == "\\" and (in_s or in_d) and i + 1 < n:
            i += 2
            continue
        if not in_d and c == "'":
            in_s = not in_s
        elif not in_s and c == '"':
            in_d = not in_d
        elif c == "#" and not in_s and not in_d:
            return i
        i += 1
    return None


# Token types that only exist on newer Pythons (PEP 701 f-strings on 3.12+,
# PEP 750 t-strings on 3.14+). Looked up by name so older interpreters work.
_FSTART = {t for t in (getattr(tokenize, "FSTRING_START", None),
                       getattr(tokenize, "TSTRING_START", None)) if t is not None}
_FMIDDLE = {t for t in (getattr(tokenize, "FSTRING_MIDDLE", None),
                        getattr(tokenize, "TSTRING_MIDDLE", None)) if t is not None}
_FEND = {t for t in (getattr(tokenize, "FSTRING_END", None),
                     getattr(tokenize, "TSTRING_END", None)) if t is not None}
_PREFIX_CHARS = "rRbBuUfFtT"
_LEGACY_FSTRINGS = sys.version_info < (3, 12)


def _is_triple(token_text: str) -> bool:
    return token_text.lstrip(_PREFIX_CHARS)[:3] in ('"""', "'''")


def _blank(buf: list[list[str]], start: tuple[int, int], end: tuple[int, int]) -> None:
    """Replace buf's characters in [start, end) (1-based rows, 0-based
    columns, as tokenize reports them) with spaces, keeping lengths."""
    (sr, sc), (er, ec) = start, end
    for r in range(sr, er + 1):
        row = buf[r - 1]
        lo = sc if r == sr else 0
        hi = ec if r == er else len(row)
        for c in range(lo, min(hi, len(row))):
            row[c] = " "


@dataclass
class _Views:
    """Column-aligned views of a file, one string per physical line.

    keep:  comments and triple-quoted strings (docstrings, prose blocks)
           blanked; ordinary string literals intact.
    blank: like keep, but the contents of EVERY string literal blanked too
           (prefix and quotes kept).
    comments: row -> COMMENT token texts on that row.
    statement: row -> (first_row, last_row) of the logical statement that
           row belongs to: a suppression marker in a comment on ANY row of a
           multi-line statement covers every row of it (flake8 `noqa`
           semantics), and post_filters see the whole statement.
    """

    keep: list[str]
    blank: list[str]
    comments: dict
    statement: dict


def _build_views(lines: list[str]) -> _Views | None:
    """Tokenize and build the views; None if the file does not tokenize."""
    text = "\n".join(lines)
    try:
        # tokenize reports errors lazily, while iterating: materialise it
        # inside the try. IndentationError/TabError subclass SyntaxError.
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError):
        return None
    keep = [list(line) for line in lines]
    blank = [list(line) for line in lines]
    comments: dict = defaultdict(list)
    statement: dict = {}
    fstack: list[bool] = []
    stmt_first: int | None = None
    for tok in toks:
        ttype, ttext, start, end = tok.type, tok.string, tok.start, tok.end
        if ttype in (tokenize.NL, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER):
            continue
        if ttype == tokenize.COMMENT:
            comments[start[0]].append(ttext)
            _blank(keep, start, end)
            _blank(blank, start, end)
            continue
        if ttype == tokenize.NEWLINE:
            if stmt_first is not None:
                for r in range(stmt_first, start[0] + 1):
                    statement[r] = (stmt_first, start[0])
            stmt_first = None
            continue
        if stmt_first is None:
            stmt_first = start[0]
        if ttype == tokenize.STRING:
            if _is_triple(ttext):
                _blank(keep, start, end)
                _blank(blank, start, end)
            elif _LEGACY_FSTRINGS and "f" in ttext[: len(ttext) - len(ttext.lstrip(_PREFIX_CHARS))].lower():
                # Before 3.12 an f-string is ONE STRING token, so blanking it
                # would also hide the code in its {...} fields. Leave it.
                pass
            else:
                body = ttext.lstrip(_PREFIX_CHARS)
                open_len = len(ttext) - len(body) + 1  # prefix + one quote
                inner_start = (start[0], start[1] + open_len)
                inner_end = (end[0], end[1] - 1)
                if inner_start < inner_end:
                    _blank(blank, inner_start, inner_end)
        elif ttype in _FSTART:
            fstack.append(_is_triple(ttext))
        elif ttype in _FMIDDLE:
            _blank(blank, start, end)
            if fstack and fstack[-1]:
                _blank(keep, start, end)
        elif ttype in _FEND:
            if fstack:
                fstack.pop()
    return _Views(
        keep=["".join(r) for r in keep],
        blank=["".join(r) for r in blank],
        comments=comments,
        statement=statement,
    )


class UnreadableFile(Exception):
    """A file in scope could not be read; reported, never counted as clean."""


def scan_file(path: Path, footguns: list[Footgun]) -> tuple[list[tuple[int, str, Footgun]], int]:
    """Return ((line_number, line, footgun) unsuppressed matches, suppressed count)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise UnreadableFile(f"{e.strerror or e}") from e
    text = text.removeprefix("\ufeff")
    # split("\n"), NOT splitlines(): splitlines() also breaks on form feeds,
    # \x1c-\x1e, \x85, \u2028 and \u2029, which tokenize (and editors'
    # line numbers) do not, so reported line numbers drifted.
    lines = text.split("\n")
    views = _build_views(lines)
    if views is None:
        print(f"note: {rel_to_repo(path)} does not tokenize; scanned line by line "
              "(comments stripped, no docstring detection)", file=sys.stderr)

    matches: list[tuple[int, str, Footgun]] = []
    suppressed = 0
    # Per-statement data, computed once and only when a rule matches there
    # (a 16k-row literal must not cost O(rows^2)).
    stmt_cache: dict[tuple[int, int], tuple[bool, str, list[int]]] = {}

    def statement_info(i: int) -> tuple[bool, str, int]:
        """(suppressed?, keep text of the statement, column offset of row i)."""
        if views is None:
            return bool(SUPPRESS_MARKER.search(lines[i - 1])), _strip_code(lines[i - 1]), 0
        span = views.statement.get(i, (i, i))
        if span not in stmt_cache:
            first, last = span
            marked = any(
                SUPPRESS_MARKER.search(c)
                for r in range(first, last + 1)
                for c in views.comments.get(r, ())
            )
            rows = views.keep[first - 1:last]
            offsets, pos = [], 0
            for row in rows:
                offsets.append(pos)
                pos += len(row) + 1  # rows are joined with one space
            stmt_cache[span] = (marked, " ".join(rows), offsets)
        marked, text, offsets = stmt_cache[span]
        return marked, text, offsets[i - span[0]]

    for i, raw in enumerate(lines, start=1):
        if views is None:
            keep = blank = _strip_code(raw)
        else:
            keep, blank = views.keep[i - 1], views.blank[i - 1]
        if not keep.strip():
            continue
        # A guard hint counts only in code (not in a comment): e.g.
        # `os.killpg(1)  # unsafe if IS_WINDOWS` is still a finding.
        if any(hint in keep for hint in GUARD_HINTS):
            continue
        for fg in footguns:
            if fg.path_allowlist and any(s in str(path) for s in fg.path_allowlist):
                continue
            match = fg.pattern.search(keep if fg.needs_strings else blank)
            if not match:
                continue
            marked, stmt_text, row_offset = statement_info(i)
            if fg.post_filter is not None:
                try:
                    # Views are column-aligned, so the row's column plus the
                    # row's offset is the same position in the statement.
                    if not fg.post_filter(stmt_text, row_offset + match.end("head")):
                        continue
                except (IndexError, AttributeError):
                    # Post-filter assumed a named group that isn't there — skip.
                    continue
            if marked:
                suppressed += 1
                continue
            matches.append((i, raw.rstrip(), fg))
    return matches, suppressed


def get_staged_files() -> list[Path]:
    """Return paths staged in the current git index. Empty on non-git trees."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [REPO_ROOT / f for f in out.splitlines() if f.strip()]


class DiffRefError(Exception):
    """--diff was given a ref that doesn't resolve to a commit."""


def _diff_ref_exists(ref: str) -> bool:
    try:
        subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return True


def get_diff_files(ref: str) -> list[Path]:
    """Return paths modified vs. the given git ref.

    Raises DiffRefError if `ref` does not resolve to a commit. An
    unresolvable ref must fail loudly: NOT-APPLICABLE is reserved for a ref
    that DOES resolve but has zero changed .py files, never for "couldn't
    even figure out what you meant" — the two used to share the same
    silent exit 0, which let a typo'd or renamed base ref report a clean
    scan that never actually ran.
    """
    if not _diff_ref_exists(ref):
        raise DiffRefError(f"--diff: {ref!r} is not a valid git ref")
    try:
        out = subprocess.check_output(
            ["git", "diff", f"{ref}...HEAD", "--name-only", "--diff-filter=ACMR"],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise DiffRefError(f"--diff: git diff against {ref!r} failed") from e
    return [REPO_ROOT / f for f in out.splitlines() if f.strip()]


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Flag Windows cross-platform footguns in Python code."
    )
    p.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Specific files/dirs to scan (default: staged changes).",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help=("Scan the full repository: the hermes-agent package dirs inside a "
              "hermes-agent checkout, otherwise the git toplevel of the current directory."),
    )
    p.add_argument(
        "--diff",
        metavar="REF",
        help="Scan files changed vs. the given git ref (e.g. --diff main).",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="List all known footgun rules and exit.",
    )
    return p.parse_args(argv)


def print_rules() -> None:
    print("Known Windows footguns checked by this script:\n")
    for i, fg in enumerate(FOOTGUNS, start=1):
        print(f"{i:2}. {fg.name}")
        print(f"    {fg.message}")
        print(f"    Fix: {fg.fix}")
        print()


HERMES_ROOT_NAMES = (
    "hermes_cli",
    "gateway",
    "tools",
    "cron",
    "agent",
    "plugins",
    "scripts",
    "acp_adapter",
    "acp_registry",
)
# Roots that identify a hermes-agent checkout. "scripts", "tools", "plugins",
# "agent" and "cron" are generic names that exist in many repos, so they do
# not count as evidence on their own.
HERMES_MARKER_NAMES = ("hermes_cli", "gateway", "acp_adapter", "acp_registry")


def git_toplevel(cwd: Path) -> Path:
    """Git toplevel of cwd, or cwd itself when not inside a git work tree."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return cwd
    return Path(out) if out else cwd


def default_all_roots() -> list[Path]:
    """Roots for --all.

    Inside a hermes-agent checkout: its known package directories. Anywhere
    else those directories are absent, so scan the git toplevel of the current
    working directory with the same walker used for explicit paths.
    """
    if any((REPO_ROOT / n).exists() for n in HERMES_MARKER_NAMES):
        return [r for r in (REPO_ROOT / n for n in HERMES_ROOT_NAMES) if r.exists()]
    return [git_toplevel(Path.cwd()).resolve()]


def main(argv: list[str]) -> int:
    # Windows terminals default to cp1252, which can't encode the ✓/✗
    # characters used in the output. Reconfigure streams to UTF-8 so the
    # script works correctly on the very platform it is designed to help.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    args = parse_args(argv)

    if args.list:
        print_rules()
        return 0

    if args.all:
        roots = default_all_roots()
    elif args.diff:
        try:
            roots = get_diff_files(args.diff)
        except DiffRefError as e:
            print(f"check-windows-footguns: {e}", file=sys.stderr)
            return 2
    elif args.paths:
        # absolute(), not resolve(): a symlink is judged by its own name, so
        # `mod.py -> mod.txt` is scanned as the .py file it presents as.
        roots = [p.absolute() for p in args.paths]
    else:
        # Default: staged changes
        roots = get_staged_files()
        if not roots:
            print(
                "No staged files to scan. Pass --all for a full-repo scan, "
                "--diff <ref> for a range diff, or paths explicitly.",
                file=sys.stderr,
            )
            return 0

    total_matches = 0
    total_suppressed = 0
    files_scanned = 0
    unreadable: list[str] = []
    # Remember what was passed so a zero-scope run can say what it skipped.
    passed = [] if args.all else [Path(r) for r in roots]
    for path in iter_files(roots):
        files_scanned += 1
        try:
            matches, suppressed = scan_file(path, FOOTGUNS)
        except UnreadableFile as e:
            unreadable.append(f"{rel_to_repo(path)}: {e}")
            continue
        total_suppressed += suppressed
        for lineno, line, fg in matches:
            rel = rel_to_repo(path)
            print(f"{rel}:{lineno}: [{fg.name}]")
            print(f"    {line.strip()}")
            print(f"    — {fg.message}")
            print(f"    Fix: {fg.fix.splitlines()[0]}")
            print()
            total_matches += 1

    if total_suppressed:
        print(f"note: {total_suppressed} match(es) suppressed with `# windows-footgun: ok`.",
              file=sys.stderr)

    if unreadable:
        # Never let a file we could not read count as scanned-and-clean.
        for msg in unreadable:
            print(f"check-windows-footguns: could not read {msg}", file=sys.stderr)
        print(f"\n✗ {len(unreadable)} file(s) in scope could not be read.", file=sys.stderr)
        return 2

    if total_matches:
        print(
            f"\n✗ {total_matches} Windows footgun(s) found across "
            f"{files_scanned} file(s) scanned.",
            file=sys.stderr,
        )
        print(
            "  If an individual match is a false positive or intentionally "
            "platform-gated, suppress it with `# windows-footgun: ok` on "
            "the same line.\n  Run with --list to see all rules.",
            file=sys.stderr,
        )
        return 1

    if files_scanned == 0:
        exts = sorted({p.suffix or "(no extension)" for p in passed})
        detail = f"{len(passed)} skipped: {', '.join(exts)}" if passed else "0 skipped"
        print(f"NOT-APPLICABLE: 0 python file(s) in scope ({detail}).")
        print("  Nothing was checked; this is not a pass. The checker scans Python only.")
        return 0

    print(
        f"✓ No Windows footguns found ({files_scanned} file(s) scanned)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
