#!/usr/bin/env bash
# Decides whether actions/content-scan needs to install its own pinned,
# SHA-256-verified ripgrep, or whether the rg already on PATH is good enough.
# Kept out of action.yml so the decision itself is unit-testable
# (scripts/tests/test_rg_need_install.py) against a stubbed `rg`, without a
# real GitHub Actions runner.
#
# Two reasons to install:
#   - no `rg` at all on PATH (a self-hosted runner may not have one), or
#   - PCRE2 was requested (PCRE2=true) but the rg on PATH can't do PCRE2 —
#     e.g. a distro package built without the pcre2 feature. `rg -P` would
#     otherwise fail at scan time with "PCRE2 is not available in this build
#     of ripgrep".
#
# Env:
#   PCRE2  true|false (default false) — mirrors actions/content-scan's pcre2 input
#
# Exit status: 0 = install the pinned rg, 1 = the existing rg is fine.
# Either way, one line of reasoning is printed to stdout.
set -uo pipefail

PCRE2="${PCRE2:-false}"

if ! command -v rg >/dev/null 2>&1; then
  echo "no rg on PATH — installing the pinned build"
  exit 0
fi

echo "found rg on PATH: $(command -v rg) ($(rg --version | head -1))"

if [ "$PCRE2" != "true" ]; then
  echo "pcre2 not requested — using the existing rg"
  exit 1
fi

# Exit status, not output text, decides: a build without PCRE2 support exits
# non-zero here (real ripgrep prints "PCRE2 is not available in this build of
# ripgrep" to stderr and exits 1).
if rg --pcre2-version >/dev/null 2>&1; then
  echo "pcre2 requested and available in the existing rg — using it"
  exit 1
fi

echo "pcre2 requested but the existing rg lacks it — installing the pinned build instead"
exit 0
