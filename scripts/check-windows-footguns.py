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
        get silently counted as "zero files changed."

Suppress an intentional use (e.g. tests or platform-gated code) with:
    os.kill(pid, 0)  # windows-footgun: ok — only called on POSIX
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
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
    # "b" for binary, or the line may have `encoding=` elsewhere).
    post_filter: "callable | None" = None


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


def _open_call_parts(m: re.Match, line: str) -> tuple[str, str | None]:
    """(first argument, literal mode or None) of the open() call matched by m."""
    args = _split_call_args(line, m.end("head"))
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


def _open_is_text_footgun(m: re.Match, line: str) -> bool:
    first, mode = _open_call_parts(m, line)
    return (
        "b" not in (mode or "")
        and "encoding=" not in line
        and "encoding =" not in line
        # Skip `def open(` and `async def open(` (method definitions)
        and not line.lstrip().startswith("def ")
        and not line.lstrip().startswith("async def ")
        # Skip open(path, **kwargs) patterns — encoding may be in the dict.
        # Too expensive to trace; require the author to set encoding in
        # the dict and trust them (or they can add a # windows-footgun: ok).
        and "**" not in line
        # Skip literal Linux pseudo-files (/proc/..., /sys/...): they
        # exist only on Linux and are always ASCII, so encoding is moot.
        and not _is_pseudo_file_arg(first)
    )


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


def should_scan_file(path: Path) -> bool:
    """Return True if this file is in scope for the checker."""
    # Skip the excluded dirs
    parts = set(path.parts)
    if parts & EXCLUDED_DIRS:
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
                    if should_scan_file(fpath):
                        yield fpath


def _strip_code(line: str) -> str:
    """Return just the code portion of a line — strip trailing comments and
    skip lines that are entirely inside a string literal or comment.

    Heuristic only (we don't parse Python); good enough to avoid flagging
    our own `# ``os.kill(pid, 0)`` is NOT a no-op` docstring-style comments.
    """
    stripped = line.lstrip()
    # Line starts with # — entirely a comment.
    if stripped.startswith("#"):
        return ""
    # Remove trailing "# ..." inline comment. Naive — doesn't handle `#`
    # inside strings — but on balance reduces noise far more than it adds.
    hash_idx = _find_unquoted_hash(line)
    if hash_idx is not None:
        return line[:hash_idx]
    return line


def _find_unquoted_hash(line: str) -> int | None:
    """Index of the first `#` not inside a single/double/triple-quoted string.

    Simple state machine — good enough for the 99% case of "code, then
    optional trailing comment."
    """
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


def scan_file(path: Path, footguns: list[Footgun]) -> list[tuple[int, str, Footgun]]:
    """Return a list of (line_number, line, footgun) for unsuppressed matches."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    matches: list[tuple[int, str, Footgun]] = []

    # Track whether we're inside a triple-quoted string (docstring/raw block).
    # Simple state machine — handles both ''' and """, toggled by the FIRST
    # triple-quote we see; we don't try to handle nested or f-string cases.
    in_triple: str | None = None  # None, "'''", or '"""'

    for i, line in enumerate(text.splitlines(), start=1):
        # Update triple-quote state based on this line's occurrences.
        code_for_scan = line
        if in_triple:
            # We're inside a docstring — skip the whole line's scan.
            # Check if it closes here.
            if in_triple in line:
                # Find the closing delimiter; anything after it is real code.
                after = line.split(in_triple, 1)[1]
                in_triple = None
                code_for_scan = after
            else:
                continue
        # Now check for docstring-open in the (possibly after-triple) portion.
        # Scan for the first unescaped '''/""" in the current code_for_scan.
        stripped = code_for_scan.strip()
        for delim in ('"""', "'''"):
            if delim in code_for_scan:
                # Count occurrences — even count means single-line docstring,
                # odd means we've entered a multi-line one.
                count = code_for_scan.count(delim)
                if count % 2 == 1:
                    # Odd — we're now inside the triple-quoted block.
                    # Scan only the part BEFORE the opening delimiter.
                    before = code_for_scan.split(delim, 1)[0]
                    code_for_scan = before
                    in_triple = delim
                    break
                else:
                    # Even — entire docstring fits on one line. Strip it
                    # from the scan text to avoid matching on prose.
                    parts = code_for_scan.split(delim)
                    # Keep the "outside" parts (every other chunk, starting
                    # with index 0) as code, drop the "inside" parts.
                    code_for_scan = "".join(parts[::2])
                    break

        if SUPPRESS_MARKER.search(line):
            continue
        # Skip if the line has an obvious guard — e.g. hasattr/getattr/
        # shutil.which or a platform check. False negatives are acceptable;
        # the inline suppression marker is the authoritative override.
        if any(hint in line for hint in GUARD_HINTS):
            continue
        code = _strip_code(code_for_scan)
        if not code.strip():
            continue
        for fg in footguns:
            if fg.path_allowlist and any(s in str(path) for s in fg.path_allowlist):
                continue
            match = fg.pattern.search(code)
            if not match:
                continue
            if fg.post_filter is not None:
                try:
                    if not fg.post_filter(match, line):
                        continue
                except (IndexError, AttributeError):
                    # Post-filter assumed a named group that isn't there — skip.
                    continue
            matches.append((i, line.rstrip(), fg))
    return matches


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
        roots = [p.resolve() for p in args.paths]
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
    files_scanned = 0
    # Remember what was passed so a zero-scope run can say what it skipped.
    passed = [] if args.all else [Path(r) for r in roots]
    for path in iter_files(roots):
        files_scanned += 1
        matches = scan_file(path, FOOTGUNS)
        for lineno, line, fg in matches:
            rel = rel_to_repo(path)
            print(f"{rel}:{lineno}: [{fg.name}]")
            print(f"    {line.strip()}")
            print(f"    — {fg.message}")
            print(f"    Fix: {fg.fix.splitlines()[0]}")
            print()
            total_matches += 1

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
