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
import subprocess
import sys
from pathlib import Path

FENCE = re.compile(r"```(?:bash|sh|console|shell)?\n(.*?)```", re.S)

# flag -> the values the tool actually accepts, per tool prefix.
ENUMS: dict[tuple[str, ...], dict[str, set[str]]] = {
    ("gh", "search", "issues"): {"--state": {"open", "closed"}},
    ("gh", "search", "prs"): {"--state": {"open", "closed"}},
    ("gh", "issue", "list"): {"--state": {"open", "closed", "all"}},
    ("gh", "pr", "list"): {"--state": {"open", "closed", "merged", "all"}},
}


def extract(md: str) -> list[str]:
    cmds: list[str] = []
    for block in FENCE.findall(md):
        for raw in block.splitlines():
            line = raw.strip().lstrip("$").strip()
            if not line or line.startswith("#"):
                continue
            if line.split() and line.split()[0] in ("gh", "git"):
                cmds.append(line)
    return cmds


def validate(cmd: str) -> str | None:
    """Return an error string, or None if the command looks valid."""
    try:
        parts = shlex.split(cmd)
    except ValueError as exc:
        return f"unparseable: {exc}"

    for prefix, flags in ENUMS.items():
        if tuple(parts[: len(prefix)]) != prefix:
            continue
        for flag, allowed in flags.items():
            if flag in parts:
                i = parts.index(flag)
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
    if failures:
        print(f"FAIL: {failures} invalid command(s) of {checked} checked")
        return 1
    print(f"PASS: {checked} documented command(s) valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
