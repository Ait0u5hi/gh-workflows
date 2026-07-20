#!/usr/bin/env python3
"""Add a contributor email -> GitHub login mapping.

Writes one file per email under contributors/emails/ (filename = email,
content = login). One-file-per-email additions never merge-conflict, unlike a
shared dict. The reusable Contributor Attribution Check (gh-workflows) fails a
PR whose commit author emails have no mapping here.

Adapted from NousResearch/hermes-agent (MIT, (c) 2025 Nous Research);
generalized (dropped the repo-specific legacy AUTHOR_MAP fallback).

Usage (from the repo root):
    python3 scripts/add_contributor.py <email> <github-login> [comment...]

Idempotent: same mapping -> "present", exit 0. A different login for the same
email is refused (exit 1) so a typo can't silently reassign commits.
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EMAILS_DIR = REPO_ROOT / "contributors" / "emails"

_EMAIL_RE = re.compile(r"^[^/\\\s]+@[^/\\\s]+$")
_LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")


def _read_login(path: Path) -> str | None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line
    except OSError:
        pass
    return None


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: add_contributor.py <email> <github-login> [comment...]", file=sys.stderr)
        return 2
    email, login = sys.argv[1], sys.argv[2]
    comment = " ".join(sys.argv[3:]).strip()

    if not _EMAIL_RE.match(email):
        print(f"invalid email: {email!r}", file=sys.stderr)
        return 2
    if not _LOGIN_RE.match(login):
        print(f"invalid GitHub login: {login!r}", file=sys.stderr)
        return 2

    EMAILS_DIR.mkdir(parents=True, exist_ok=True)
    path = EMAILS_DIR / email
    existing = _read_login(path)
    if existing is not None:
        if existing == login:
            print(f"present: contributors/emails/{email} -> {login}")
            return 0
        print(f"REFUSED: {email} already maps to {existing!r}, not {login!r}. "
              "Delete the file first if this is truly a reassignment.", file=sys.stderr)
        return 1

    body = f"{login}\n"
    if comment:
        body = f"# {comment}\n{login}\n"
    path.write_text(body, encoding="utf-8")
    print(f"added: contributors/emails/{email} -> {login}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
