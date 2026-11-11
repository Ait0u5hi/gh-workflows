#!/usr/bin/env python3
"""Verify that shell commands printed in our docs actually parse and accept their flags.

Why this exists: hermes-agent's CONTRIBUTING shipped `gh search prs --state all` in its
most-followed section for months. It is invalid - gh accepts only {open|closed} - so the one
instruction a doc exists to give could not be followed. A doc whose purpose is to be run should
have its commands run.

This does NOT execute commands (that would be side-effecting and network-dependent). It extracts
`gh` and `git` invocations from fenced blocks and validates each one's flag VALUES against the
tool's own accepted set, which is where the real rot is.

Exit 0 = every extracted command is valid. Exit 1 = at least one is not.
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from pathlib import Path

# A fence opener: any indentation (fences nested in list items are indented
# 4+ spaces), then >=3 backticks or tildes, then an
# optional info string ("bash", "bash title=x", "Bash"). Parsed line by line,
# not with one multi-line regex: a regex like ```(bash)?\n(.*?)``` treats the
# CLOSING fence of a preceding ```text block as an opener and silently skips
# the real bash block after it.
FENCE_OPEN = re.compile(r"^\s*(`{3,}|~{3,})[ \t]*([^\s`]*)")
SHELL_LANGS = {"", "bash", "sh", "console", "shell", "zsh", "shell-session"}
ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# Short aliases for the long flags checked below.
ALIASES = {"-s": "--state"}

# flag -> the values the tool actually accepts, per tool prefix.
ENUMS: dict[tuple[str, ...], dict[str, set[str]]] = {
    ("gh", "search", "issues"): {"--state": {"open", "closed"}},
    ("gh", "search", "prs"): {"--state": {"open", "closed"}},
    ("gh", "issue", "list"): {"--state": {"open", "closed", "all"}},
    ("gh", "pr", "list"): {"--state": {"open", "closed", "merged", "all"}},
}


def shell_blocks(md: str) -> list[list[str]]:
    """Lines of every shell-ish fenced block (``` or ~~~, any info string)."""
    blocks: list[list[str]] = []
    fence: str | None = None
    current: list[str] = []
    shell = False
    for line in md.splitlines():  # also splits \r\n
        if fence is None:
            m = FENCE_OPEN.match(line)
            if m:
                fence = m.group(1)
                shell = m.group(2).lower() in SHELL_LANGS
                current = []
            continue
        stripped = line.strip()
        if stripped and set(stripped) == {fence[0]} and len(stripped) >= len(fence):
            if shell:
                blocks.append(current)
            fence = None
            continue
        current.append(line)
    if fence is not None and shell:  # unterminated fence runs to end of file
        blocks.append(current)
    return blocks


def extract(md: str) -> list[str]:
    cmds: list[str] = []
    for block in shell_blocks(md):
        joined: list[str] = []
        pending = ""
        for raw in block:
            line = raw.rstrip()
            if line.endswith("\\"):  # shell line continuation
                pending += line[:-1] + " "
                continue
            joined.append(pending + line)
            pending = ""
        if pending:
            joined.append(pending)
        for raw in joined:
            line = raw.strip().lstrip("$").strip()
            if not line or line.startswith("#"):
                continue
            words = line.split()
            while words and ENV_ASSIGN.match(words[0]):  # FOO=1 gh ...
                words.pop(0)
            if words and words[0] in ("gh", "git"):
                cmds.append(" ".join(words) if words != line.split() else line)
    return cmds


def normalize(parts: list[str]) -> list[str]:
    """Split --flag=value into two tokens and map short aliases to long flags."""
    out: list[str] = []
    for part in parts:
        if part.startswith("--") and "=" in part:
            flag, _, val = part.partition("=")
            out += [flag, val]
        else:
            out.append(ALIASES.get(part, part))
    return out


def validate(cmd: str) -> str | None:
    """Return an error string, or None if the command looks valid."""
    try:
        parts = shlex.split(cmd)
    except ValueError as exc:
        return f"unparseable: {exc}"
    parts = normalize(parts)

    for prefix, flags in ENUMS.items():
        if tuple(parts[: len(prefix)]) != prefix:
            continue
        for flag, allowed in flags.items():
            # Every occurrence: `--state open --state all` must not pass on
            # the first one.
            for i, part in enumerate(parts):
                if part != flag:
                    continue
                if i + 1 >= len(parts):
                    return f"{flag} has no value"
                val = parts[i + 1].strip("\"'")
                if val.startswith("<") or val.startswith("{"):
                    continue  # a documented placeholder, not a literal
                if val not in allowed:
                    return (
                        f"{' '.join(prefix)} {flag}={val!r} is invalid; "
                        f"accepted: {'|'.join(sorted(allowed))}"
                    )
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="markdown files to check")
    a = ap.parse_args()

    failures = 0
    checked = 0
    for path in a.paths:
        p = Path(path)
        if not p.is_file():
            print(f"  MISSING  {path}", file=sys.stderr)
            failures += 1
            continue
        for cmd in extract(p.read_text(encoding="utf-8", errors="replace")):
            checked += 1
            err = validate(cmd)
            if err:
                print(f"  INVALID  {p}: {cmd}\n           -> {err}")
                failures += 1
            else:
                print(f"  ok       {cmd[:88]}")

    print()
    if checked == 0 and not failures:
        print("::warning::no gh/git commands found in fenced shell blocks of: " + " ".join(a.paths))
    if failures:
        print(f"FAIL: {failures} invalid command(s) of {checked} checked")
        return 1
    print(f"PASS: {checked} documented command(s) valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
