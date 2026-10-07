# Changelog

All notable changes to this repo are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions are the moving major
tags callers pin (`@v1`). See [README → Versioning](README.md#versioning).

## [Unreleased]

### Fixed
- `actions/windows-footguns`: the diff step now builds its file list
  NUL-delimited into a bash array (a path with a space used to get
  word-split by `tr '\n' ' '` into two bogus argv entries) and with
  `git diff -M --diff-filter=d`, which excludes only Deleted paths while
  keeping Renamed/Copied ones — the previous unfiltered `git diff` passed
  a deleted path's now-gone name straight to the checker. The step's own
  exit code is always exactly the checker's exit code; it never greps the
  checker's stdout (e.g. for its "NOT-APPLICABLE" line) to decide pass/fail,
  since that text can also appear in a genuinely-failing run (a matched
  source line, or a file literally named `NOT-APPLICABLE.py`).
- `ci.yml` unit-tests job: the pinned ripgrep install is x86_64/amd64 only.
  It now checks `runner.arch` first and fails the job loudly (`::error::`,
  exit 1) on anything else, before any download — previously an
  arm64/other runner would hit this step blind and either get a cryptic
  "exec format error" well into the job, or (worse, if ripgrep happened to
  run under emulation) silently never exercise the pinned binary the tests
  assume.
- `scripts/sync_labels.py`: a case-mismatch used to exit 0 with no summary, so a
  scheduled `--apply` run could never notice it. It now prints a stderr footer
  ("N label(s) need a manual case rename") and exits with a new, distinct code
  (3) when the only problem is a pending rename — 0 still means full
  convergence, and 1 (a `gh` API/auth failure) always wins over 3 even when
  both occur in the same run. See README → Label sync for the exit-code table.

### Added
- `labels.yml` + `scripts/sync_labels.py`: the shared issue-label taxonomy
  (`type:bug|friction|gap|debt|flaky`, `source:agent|human`, `status:carded`) and an
  idempotent, dry-run-by-default script that applies it to the repos you name. It never
  deletes or renames a label.
- `examples/` — placeholder-org (`<your-org>`) copy-paste caller stubs for
  external adopters, plus an external-adopter contract in the README.
- `reusable-deep-lint.yml` inputs: `default-branch`, `linter-rules-path`,
  `python-ruff-config`, `yaml-config` (defaults unchanged).
- `reusable-release.yml` input: `default-branch` (default `main`).
- `docs/marketplace-research.md`; `branding:` metadata on the composite actions.
- `reusable-content-scan.yml`: optional `secrets: patterns:` merged with the committed
  patterns file (either alone now satisfies the "at least one pattern source" check);
  findings redact to `path:line` (never the matched text) whenever the secret is in
  play, controllable via the new `redact-matches` input (default `auto`); new `pcre2`
  input for lookaround patterns. The scan logic and a pinned + SHA-256-verified `rg`
  install (amd64/arm64, for self-hosted runners without ripgrep) moved to a new
  `actions/content-scan` composite action, unit-tested in
  `scripts/tests/test_content_scan.py`. Fully backward compatible — a caller with only
  a patterns file behaves exactly as before.

### Fixed
- `actions/content-scan`: the "install ripgrep if missing" step now also installs the
  pinned, SHA-256-verified `rg` when `pcre2: true` is requested but the `rg` already on
  PATH was built without PCRE2 (a self-hosted runner's distro package, for example) —
  previously it skipped installation whenever *any* `rg` was present, so a caller with
  `pcre2: true` failed with "PCRE2 is not available in this build of ripgrep" even
  though the step reported success. The install-vs-skip decision moved to
  `scripts/rg-need-install.sh` (unit-tested in `scripts/tests/test_rg_need_install.py`),
  and the scan step now receives the exact binary to use via an `RG_BIN` env var rather
  than relying solely on `$GITHUB_PATH` ordering.
- `reusable-release.yml` no longer hardcodes `main` for checkout/push-back.
- `reusable-codeql.yml` `continue-on-error` narrowed to the SARIF-upload step so
  genuine CodeQL misconfig fails the job again.
- `reusable-python-validation.yml` meta-lint pins the actionlint installer SHA +
  tool versions (was unpinned `curl|bash` + floating pip installs).
- `reusable-crossplatform-lint.yml` dropped the dead `gh-workflows-ref` input;
  refreshed stale private-repo framing across several workflows/docs.

## [v1] — baseline

Central reusable workflows + composite actions: generic Python/Node CI, CodeQL,
OSV, gitleaks, content-scan, deep-lint, release; org-governance reusables
(python-validation, contributor-check, crossplatform-lint); composite actions
`retry`, `detect-changes`, `windows-footguns`. See the README for the full set.
