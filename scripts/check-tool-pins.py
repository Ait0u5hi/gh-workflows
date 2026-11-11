#!/usr/bin/env python3
"""Report tool pins that have fallen behind their latest upstream release.

Dependabot tracks the SHA-pinned `uses:` actions and the /requirements pip
lock, but not the tools this repo downloads by version (ripgrep, lychee,
git-cliff, golangci-lint, actionlint) or the `pip install pkg==X` pins inside
the reusable workflows. This script finds those pins and compares each with
the newest stable upstream release:

- GitHub releases via `git ls-remote --tags` (no token, no API rate limit);
- PyPI via its JSON API.

It only reports. Bumping a pin is a reviewed change: download the release,
verify its SHA-256 against upstream, update the hash next to the version.

Exit status: 0 = every pin is current; 1 = at least one pin is behind;
2 = an upstream lookup failed (never silently treated as "current").
The weekly .github/workflows/tool-pins.yml runs this; a red run is the
notification.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCAN_GLOBS = (".github/workflows/*.yml", "actions/*/action.yml", "requirements/*.in")

# env var name -> (GitHub repo, tag prefix). The pinned value may carry the
# tag prefix itself (e.g. LYCHEE_VERSION: v0.24.2 for tag lychee-v0.24.2).
GITHUB_PINS = {
    "ACTIONLINT_VERSION": ("rhysd/actionlint", "v"),
    "RG_VERSION": ("BurntSushi/ripgrep", ""),
    "LYCHEE_VERSION": ("lycheeverse/lychee", "lychee-v"),
    "GIT_CLIFF_VERSION": ("orhun/git-cliff", "v"),
    "GOLANGCI_PINNED": ("golangci/golangci-lint", "v"),
}
ENV_PIN = re.compile(r"^\s*(?P<name>[A-Z_]+):\s*[\"']?(?P<value>v?\d+(?:\.\d+)+)[\"']?\s*(?:#.*)?$")
PIP_PIN = re.compile(r"(?<![\w.-])(?P<pkg>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<ver>\d+(?:\.\d+)+)\b")
STABLE = re.compile(r"^\d+(?:\.\d+)+$")


def vtuple(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.split("."))


def latest_github(repo: str, prefix: str) -> str:
    """Newest stable X.Y.Z tag of a public GitHub repo (prefix stripped)."""
    out = subprocess.run(
        ["git", "ls-remote", "--tags", "--refs", f"https://github.com/{repo}"],
        capture_output=True, text=True, timeout=60, check=True,
    ).stdout
    versions = []
    for line in out.splitlines():
        tag = line.rsplit("refs/tags/", 1)[-1]
        if tag.startswith(prefix) and STABLE.match(tag[len(prefix):]):
            versions.append(tag[len(prefix):])
    if not versions:
        raise LookupError(f"no stable tags with prefix {prefix!r} in {repo}")
    return max(versions, key=vtuple)


def latest_pypi(pkg: str) -> str:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{pkg}/json", timeout=60) as resp:
        return json.load(resp)["info"]["version"]


def find_pins(root: Path = REPO) -> list[tuple[str, str, str, str]]:
    """(kind, name, pinned version, where) for every pin found, deduplicated."""
    seen: dict[tuple[str, str, str], str] = {}
    for pattern in SCAN_GLOBS:
        for path in sorted(root.glob(pattern)):
            rel = path.relative_to(root).as_posix()
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                m = ENV_PIN.match(line)
                if m and m.group("name") in GITHUB_PINS:
                    key = ("github", m.group("name"), m.group("value").lstrip("v"))
                    seen.setdefault(key, f"{rel}:{n}")
                for pm in PIP_PIN.finditer(line):
                    key = ("pypi", pm.group("pkg").lower(), pm.group("ver"))
                    seen.setdefault(key, f"{rel}:{n}")
    return [(kind, name, ver, where) for (kind, name, ver), where in sorted(seen.items())]


def main(argv: list[str]) -> int:
    pins = find_pins()
    behind = 0
    errors = 0
    for kind, name, pinned, where in pins:
        try:
            if kind == "github":
                repo, prefix = GITHUB_PINS[name]
                label, latest = repo, latest_github(repo, prefix)
            else:
                label, latest = name, latest_pypi(name)
        except Exception as e:  # network, parse, no tags: never "current"
            print(f"ERROR    {name:<20} {pinned:<10} lookup failed: {e}  ({where})")
            errors += 1
            continue
        if STABLE.match(latest) and vtuple(latest) > vtuple(pinned):
            print(f"BEHIND   {label:<28} {pinned:<10} -> {latest:<10} ({where})")
            behind += 1
        else:
            print(f"ok       {label:<28} {pinned:<10}            ({where})")
    print(f"\n{len(pins)} pin(s) checked: {behind} behind, {errors} lookup error(s).")
    if errors:
        return 2
    return 1 if behind else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
