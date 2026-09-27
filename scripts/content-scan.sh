#!/usr/bin/env bash
# Core logic for the reusable content-scan job. Kept out of the workflow YAML
# so it is unit-testable (scripts/tests/test_content_scan.py) without
# spinning up a runner.
#
# Merges an optional committed patterns file with an optional secret's
# patterns (same format: one ripgrep regex per line, `#` comments and blanks
# ignored), then greps SCAN_PATHS. When a secret is in play, findings are
# reported as `path:line` only — never the matched text — because public
# Actions logs are world-readable and GitHub's secret masking will not catch
# a single matched name out of a multi-line secret.
#
# Env:
#   PATTERNS_FILE   path to the committed patterns file (optional; may not exist)
#   PATTERNS_SECRET newline-separated regexes, e.g. from a GitHub secret (optional)
#   SCAN_PATHS      space-separated paths to scan (word-split intentionally)
#   REDACT          auto|true|false (default: auto — redact iff PATTERNS_SECRET is non-empty)
#   PCRE2           true|false (default: false) — adds -P for lookaround patterns
#
# Exit status: 0 = clean, 1 = forbidden patterns found (or a bad REDACT value),
# anything else = ripgrep itself errored.
set -uo pipefail

PATTERNS_FILE="${PATTERNS_FILE:-}"
PATTERNS_SECRET="${PATTERNS_SECRET:-}"
SCAN_PATHS="${SCAN_PATHS:-.}"
REDACT="${REDACT:-auto}"
PCRE2="${PCRE2:-false}"

have_file=false
if [ -n "$PATTERNS_FILE" ] && [ -f "$PATTERNS_FILE" ]; then
  have_file=true
fi
have_secret=false
if [ -n "$PATTERNS_SECRET" ]; then
  have_secret=true
fi

if ! $have_file && ! $have_secret; then
  echo "::error::no patterns available — committed file not found${PATTERNS_FILE:+ at $PATTERNS_FILE}, and no secret patterns were provided"
  echo "Create the patterns file in the caller repo, pass secrets.patterns, or both."
  exit 1
fi

case "$REDACT" in
  auto | true | false) ;;
  *)
    echo "::error::redact-matches must be auto, true or false, got '$REDACT'"
    exit 1
    ;;
esac

RUNTIME_PATTERNS=$(mktemp)
trap 'rm -f "$RUNTIME_PATTERNS"' EXIT

if $have_file; then
  echo "Using patterns file: $PATTERNS_FILE"
  echo "Active patterns from file (comments/blanks stripped):"
  grep -vE '^\s*(#|$)' "$PATTERNS_FILE" | tee -a "$RUNTIME_PATTERNS" | sed 's/^/  /'
fi
if $have_secret; then
  echo "Using secret patterns (values not shown)"
  printf '%s\n' "$PATTERNS_SECRET" | grep -vE '^\s*(#|$)' >>"$RUNTIME_PATTERNS"
fi

if [ ! -s "$RUNTIME_PATTERNS" ]; then
  echo "No active patterns — nothing to scan."
  exit 0
fi

if [ "$REDACT" = "auto" ]; then
  redact=$have_secret
else
  redact=$REDACT
fi

# rg -f: patterns from file. -n: line numbers. --hidden: include dotfiles.
# --glob '!.git': skip git internals. The committed patterns file (if any) is
# excluded so its own regexes do not self-match. -S: smart case. -P: PCRE2
# (lookaround), opt-in since it disables some of rg's fast paths.
rg_args=(-n -S --hidden --glob '!.git')
if $have_file; then
  rg_args+=(--glob "!$PATTERNS_FILE")
fi
if [ "$PCRE2" = "true" ]; then
  rg_args+=(-P)
fi
rg_args+=(-f "$RUNTIME_PATTERNS")

# Exit status: 0 = matches, 1 = no matches, 2 = error. We invert: matches ->
# fail; no matches -> pass; error -> surface. Run the pipeline directly
# (never through a command substitution) so PIPESTATUS reflects rg itself,
# not `cut`/`sort`.
# shellcheck disable=SC2086  # SCAN_PATHS is intentionally word-split
if $redact; then
  rg "${rg_args[@]}" --no-heading -o $SCAN_PATHS | cut -d: -f1,2 | sort -u
  rc=${PIPESTATUS[0]}
else
  rg "${rg_args[@]}" $SCAN_PATHS
  rc=$?
fi

if [ "$rc" = "0" ]; then
  echo
  if $redact; then
    echo "::error::content-scan found forbidden patterns at the paths:lines above (matched text withheld). Remove them, or update the patterns if stale."
  else
    echo "::error::content-scan found forbidden patterns above. Remove them, or update $PATTERNS_FILE if the pattern is stale."
  fi
  exit 1
elif [ "$rc" = "1" ]; then
  echo "content-scan clean."
  exit 0
else
  echo "::error::ripgrep exited with $rc"
  exit "$rc"
fi
