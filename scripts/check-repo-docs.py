#!/usr/bin/env python3
"""Fail when a repo is missing its required contribution docs.

PRESENCE ONLY, deliberately. Presence is decidable: a file is there or it is not, and a gate that
refuses on a decidable fact is trustworthy. Content quality ("does the CoC mention enforcement")
is heuristic, and a heuristic gate that REFUSES is worse than no gate - it trains people to work
around it. So this checks that the files exist and that CONTRIBUTING actually links the shared
standard; everything else is advisory output.

The one parsing step (the standard link) reads the whole file and searches it. It does not parse
line-by-line into fields: a related validator in this fleet silently truncated a field at 179
characters because its terminator regex also matched an indented bolded bullet, and every check
downstream scored a prefix while reporting green. A presence check that passes on a truncated read
is worse than no check, so this one never partially reads a file.

Exit 0 = all required docs present. Exit 1 = something missing. Exit 2 = bad usage.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

STANDARD_URL = "gh-workflows/blob/main/docs/CONTRIBUTION-STANDARD.md"

# name -> why it is required (printed on failure, so the message teaches rather than scolds)
REQUIRED = {
    "CONTRIBUTING.md": "how to contribute; must link the shared standard",
    "CODE_OF_CONDUCT.md": "the behavioural baseline participants agree to",
    "SECURITY.md": "where to report a vulnerability privately, instead of a public issue",
    "LICENSE": "what others may legally do with this code",
    ".github/PULL_REQUEST_TEMPLATE.md": "the PR checklist contributors are held to",
}

ADVISORY = {
    ".github/ISSUE_TEMPLATE": "issue templates make reports actionable",
    "adr/": "durable decisions are worth recording",
}


def check(root: Path, skip: set[str], require_link: bool) -> list[str]:
    failures: list[str] = []

    for name, why in REQUIRED.items():
        if name in skip:
            print(f"  skip     {name} (waived)")
            continue
        p = root / name
        if not p.exists():
            failures.append(f"{name} is missing - {why}")
            print(f"  MISSING  {name}")
            continue
        if p.is_file() and p.stat().st_size == 0:
            failures.append(f"{name} exists but is empty")
            print(f"  EMPTY    {name}")
            continue
        print(f"  ok       {name}")

    # The one content assertion, and it is decidable: does CONTRIBUTING point at the standard?
    # Without this a repo can satisfy the gate with an empty-ish stub and drift silently.
    contributing = root / "CONTRIBUTING.md"
    if require_link and "CONTRIBUTING.md" not in skip and contributing.is_file():
        text = contributing.read_text(encoding="utf-8", errors="replace")  # whole file, never partial
        if STANDARD_URL not in text:
            failures.append(
                "CONTRIBUTING.md does not link the shared standard "
                f"(expected a URL containing '{STANDARD_URL}')"
            )
            print("  NO LINK  CONTRIBUTING.md -> CONTRIBUTION-STANDARD.md")
        else:
            print("  ok       CONTRIBUTING.md links the shared standard")

    for name, why in ADVISORY.items():
        if not (root / name.rstrip("/")).exists():
            print(f"  note     {name} not present - {why} (advisory, not failing)")

    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", nargs="?", default=".", help="repo root to check")
    ap.add_argument("--skip", default="", help="comma-separated required files to waive")
    ap.add_argument("--no-require-link", action="store_true",
                    help="do not require CONTRIBUTING.md to link the shared standard")
    a = ap.parse_args()

    root = Path(a.root).resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    print(f"Checking required contribution docs in {root.name}/")
    failures = check(root, {s.strip() for s in a.skip.split(",") if s.strip()}, not a.no_require_link)

    print()
    if failures:
        print(f"FAIL: {len(failures)} problem(s)")
        for f in failures:
            print(f"  - {f}")
        print()
        print("Templates to copy: https://github.com/Ait0u5hi/gh-workflows/tree/main/templates")
        return 1
    print("PASS: all required contribution docs present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
