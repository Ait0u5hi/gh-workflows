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
#   SCAN_PATHS      space-separated paths to scan (word-split and glob-expanded
#                   intentionally; always passed to rg after `--`)
#   REDACT          auto|true|false (default: auto — redact iff PATTERNS_SECRET is non-empty)
#   PCRE2           true|false (default: false) — adds -P for lookaround patterns
#   RG_BIN          ripgrep binary/path to use (default: rg, resolved from PATH)
#
# Exit status: 0 = clean, 1 = forbidden patterns found, no usable patterns,
# a refused patterns file, or a bad REDACT value; anything else = ripgrep
# itself errored.
#
# The scanned tree and the committed patterns file both come from the PR
# under test, so they are treated as hostile: the patterns file must be a
# regular, non-symlinked file inside the workspace and is never echoed; rg
# ignores .gitignore/.ignore/.rgignore and binary detection (a PR could
# otherwise hide a file from the scan); match output is printed inside a
# `::stop-commands::` window so a crafted filename or line can't issue
# workflow commands; and rg's own error text is withheld whenever secret
# patterns are in play, because it echoes the combined pattern set.
set -uo pipefail

PATTERNS_FILE="${PATTERNS_FILE:-}"
PATTERNS_SECRET="${PATTERNS_SECRET:-}"
SCAN_PATHS="${SCAN_PATHS:-.}"
REDACT="${REDACT:-auto}"
PCRE2="${PCRE2:-false}"
RG_BIN="${RG_BIN:-rg}"

echo "Using rg: $RG_BIN ($("$RG_BIN" --version | head -1))"
if "$RG_BIN" --pcre2-version >/dev/null 2>&1; then
  echo "PCRE2: $("$RG_BIN" --pcre2-version)"
else
  echo "PCRE2: not available in this build"
fi

have_file=false
if [ -n "$PATTERNS_FILE" ] && { [ -e "$PATTERNS_FILE" ] || [ -L "$PATTERNS_FILE" ]; }; then
  # Refuse anything but a regular file that really lives inside the scanned
  # workspace: a PR could otherwise symlink the patterns file to a runner
  # credential and have its lines read (and, before this check, printed).
  # A symlink to another file in the repo is fine.
  if [ ! -f "$PATTERNS_FILE" ]; then
    echo "::error::patterns file $PATTERNS_FILE is not a regular file (or is a dangling symlink); refusing to read it"
    exit 1
  fi
  # No `-e`: BSD/macOS realpath lacks it, and -f above already checked
  # that the (resolved) file exists.
  real_file=$(realpath -- "$PATTERNS_FILE")
  real_root=$(realpath -- .)
  case "$real_file" in
    "$real_root"/*) ;;
    *)
      echo "::error::patterns file $PATTERNS_FILE resolves outside the workspace; refusing to read it"
      exit 1
      ;;
  esac
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

# grep -a: a NUL byte must not make grep treat the file as binary and
# silently load zero patterns. Patterns are counted, never echoed.
count_active() { grep -a -cvE '^\s*(#|$)' || true; }
if $have_file; then
  n=$(count_active <"$PATTERNS_FILE")
  grep -a -vE '^\s*(#|$)' "$PATTERNS_FILE" >>"$RUNTIME_PATTERNS" || true
  echo "Using patterns file: $PATTERNS_FILE (${n} active pattern(s))"
fi
if $have_secret; then
  n=$(printf '%s\n' "$PATTERNS_SECRET" | count_active)
  printf '%s\n' "$PATTERNS_SECRET" | grep -a -vE '^\s*(#|$)' >>"$RUNTIME_PATTERNS" || true
  echo "Using secret patterns (${n} active pattern(s); values not shown)"
elif [[ "${GITHUB_EVENT_NAME:-}" == pull_request* ]]; then
  echo "::notice::no secret patterns in play — PRs from forks (and Dependabot) never receive secrets, so only the committed patterns file is scanned"
fi

if [ ! -s "$RUNTIME_PATTERNS" ]; then
  # Fail closed: a PR that comments out every committed pattern must not
  # turn this gate green.
  echo "::error::no active patterns — the patterns file and secret together must resolve to at least one pattern"
  exit 1
fi

if [ "$REDACT" = "auto" ]; then
  redact=$have_secret
else
  redact=$REDACT
fi

# rg -f: patterns from file. -n: line numbers. --hidden: include dotfiles.
# --no-ignore: don't honour .gitignore/.ignore/.rgignore (the PR controls
# them). -a: search binary files as text (a leading NUL byte must not hide a
# file). --glob '!.git': skip git internals. The committed patterns file (if
# any) is excluded so its own regexes do not self-match. -S: smart case.
# -P: PCRE2 (lookaround), opt-in since it disables some of rg's fast paths.
rg_args=(-n -S --hidden --no-ignore -a --glob '!.git')
if $have_file; then
  rg_args+=(--glob "!$PATTERNS_FILE")
fi
if [ "$PCRE2" = "true" ]; then
  rg_args+=(-P)
fi
rg_args+=(-f "$RUNTIME_PATTERNS")

# SCAN_PATHS is word-split and glob-expanded on purpose (callers may pass
# globs), but always after `--`, so a PR file named e.g. `--pre=bash` that a
# glob expands to is a path, never an rg option.
# shellcheck disable=SC2206  # intentional word-split + glob
scan_paths=($SCAN_PATHS)

# rg's error text (e.g. a regex parse error) echoes the combined pattern
# set, secret patterns included, so it is withheld whenever a secret is in
# play.
RG_STDERR=$(mktemp)
trap 'rm -f "$RUNTIME_PATTERNS" "$RG_STDERR"' EXIT

# Everything rg prints (paths, matched lines) comes from the PR: suspend
# workflow-command processing around it with an unguessable token.
STOP_TOKEN=$(od -An -tx1 -N16 /dev/urandom | tr -d ' \n')
echo "::stop-commands::${STOP_TOKEN}"

# Exit status: 0 = matches, 1 = no matches, 2 = error. We invert: matches ->
# fail; no matches -> pass; error -> surface. Run the pipeline directly
# (never through a command substitution) so PIPESTATUS reflects rg itself,
# not `sed`/`sort`.
if $redact; then
  # -H: always print the filename, even for a single-file target (rg omits it
  # otherwise, which used to shift the matched text into the path:line cut).
  # -o -r '': replace the match itself with nothing so the text never reaches
  # the pipe, instead of printing the full line and cutting fields — a `cut
  # -d: -f1,2` breaks the moment the path itself contains a colon (Windows
  # paths). -r '' output always ends in a bare trailing colon (path:line:),
  # which the trailing-colon strip below removes without touching colons
  # that are part of the path.
  "$RG_BIN" "${rg_args[@]}" --no-heading -H -o -r '' -- "${scan_paths[@]}" 2>"$RG_STDERR" | sed 's/:$//' | sort -u
  rc=${PIPESTATUS[0]}
else
  "$RG_BIN" "${rg_args[@]}" -- "${scan_paths[@]}" 2>"$RG_STDERR"
  rc=$?
fi
echo "::${STOP_TOKEN}::"

if [ -s "$RG_STDERR" ]; then
  if $have_secret; then
    echo "ripgrep wrote to stderr; its message is withheld because it can echo the secret patterns."
  else
    sed 's/^/rg: /' "$RG_STDERR"
  fi
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
