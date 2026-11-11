# Changelog

All notable changes to this repo are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions are the moving major
tags callers pin (`@v2`). See [README → Versioning](README.md#versioning).

## [v2] — 2026-11-11

`v1` is frozen at `b43f688` and gets no backports. Everything below is new
relative to it; items marked **behavior change** can turn a caller's CI red.

### Migrating from v1
1. Change every `Ait0u5hi/gh-workflows/...@v1` in your stubs to `@v2`
   (copy fresh stubs from `templates/` — they already say `@v2`), and copy
   the new `templates/zizmor.yml` (disables `self-repository`).
2. github.com only, and self-hosted runners must be **v2.336.0+** (the
   reusables use `uses: $/...`). Not available on GitHub Enterprise Server.
3. Expect new findings, all real: link-check now actually checks links;
   gitleaks ignores your repo's `.gitleaks.toml` unless `use-repo-config:
   true`; zizmor 1.32 in meta-lint (new audits, e.g. `issue_comment`); the
   Windows-footgun checker now sees code a stray `"""` used to hide.
4. Defaults moved: Python 3.12 (eval/validation), python-ci matrix
   3.11–3.14, Node 22+24, golangci-lint v2.15.0 (`golangci-version` now
   defaults to "" = the pinned release; any other version is refused).
   python-ci / python-eval install `pytest>=8` (`pytest-cov>=5`): a caller
   pinning pytest 7 in `extra-deps` must move to 8+.
5. Content-scan with zero active patterns fails; a release tag must be
   SemVer-shaped; release, golangci-lint and content-scan need a Linux
   X64/ARM64 runner.
6. A fork's PR on a self-hosted runner is refused unless you set
   `allow-untrusted-prs-on-self-hosted: true` (ephemeral runners only).
7. Pinning a commit SHA instead of `@v2` now pins everything the workflow
   runs, its own composite actions and helper scripts included.

### Added
- **Native self-references.** The reusables reach this repo's composite
  actions with `uses: $/actions/content-scan` / `$/actions/windows-footguns`
  and check out their helper scripts at `job.workflow_repository` /
  `job.workflow_sha`, so the inner code always matches the caller's pin
  (was hard-coded `@v1` / `refs/tags/v1`, which ran different code than a
  caller pinned to `@main` or a SHA). The governance dogfood therefore lints
  each PR with that PR's own checker (closes #52, #53). `tools-ref` now
  defaults to `""` and is only an override. actionlint 1.7.12 doesn't know
  these features yet; `.github/actionlint.yaml` ignores exactly those errors
  in exactly those files (rhysd/actionlint#732, #707), kept narrow by a test.
- **Self-hosted guard** (python-ci, python-eval, node-ci, go-ci,
  content-scan, crossplatform-lint, codeql): fails a job, before checkout, when a
  fork's PR (or a comment trigger) lands on a self-hosted runner. Opt out
  with `allow-untrusted-prs-on-self-hosted`. A misconfiguration guard, not a
  security boundary — see README → Security model.
- `scripts/check-tool-pins.py` + weekly `tool-pins.yml`: fails when a
  version-pinned tool (ripgrep, lychee, git-cliff, golangci-lint, actionlint,
  pip pins) falls behind upstream.
- Dependabot `cooldown: default-days: 7` (here and in the template) and a
  pip entry for this repo's hash-locked `requirements/`.

### Security
- `reusable-release.yml`: the tag name reached a shell unquoted through
  git-cliff-action's `run: … ${{ inputs.args }}` and through the plugin.yaml
  `sed`, in a job holding `contents: write` + persisted credentials. Tags are
  now validated (SemVer-shaped: `v1`, `v1.2.3`, `v1.2.3-rc.1`,
  `v1.0.0-alpha-1`, `v1.2.3-beta.1+exp`) before anything else runs, and git-cliff 2.14.2 is installed directly (pinned +
  SHA-256 verified) instead of via the action, whose installer downloads the
  binary unverified. **Behavior change:** other tag shapes are refused.
- `reusable-release.yml`: release notes are git-cliff `--current` on a
  worktree of the tag, honouring `cliff.toml` tag filters (was `--latest` on
  the default branch's HEAD, which published the wrong notes for backport tags
  and filed post-tag commits under the release); the GitHub Release is
  created/updated before the changelog push, which retries on the latest
  default branch when several tags race; backport tags skip the changelog
  commit; `permissions: {}` at the top, `contents: write` on the job.
  **Behavior change:** Linux X64/ARM64 runners only (as with the pinned
  binaries elsewhere).
- `scripts/content-scan.sh` / `actions/content-scan`: a symlinked patterns file
  was read and echoed (e.g. a runner credential); `.gitignore`/`.ignore`/
  `.rgignore` entries or a leading NUL byte hid files from the scan; a regex
  error echoed the secret patterns; with a glob in `paths`, a PR file named
  `--pre=bash` made rg execute PR content; PR-controlled output could forge
  workflow commands. All fixed and regression-tested. **Behavior change:**
  zero active patterns now fails instead of passing, binary/ignored files are
  now scanned, and committed patterns are counted rather than printed.
- `reusable-contributor-check.yml`: substring exemptions
  (`x@anthropic.com.evil.io`), an unanchored noreply regex, a path-shaped email
  (`../../LICENSE`) and `--no-merges` each let an unmapped author through; names
  could forge workflow commands via `echo -e`. **Behavior change:** exemptions
  are exact addresses and merge commits are checked.
- `actions/detect-changes`: git-quoted file names (non-ASCII, `"`, `\`, tab)
  matched no lane, so gated jobs were skipped (and a skipped job satisfies a
  required check). Now NUL-delimited and unquoted.
- `reusable-security.yml`: gitleaks loaded the PR's own `.gitleaks.toml`, so a
  PR could allowlist its own leak. **Behavior change:** it now runs gitleaks'
  built-in rules unless `use-repo-config: true`. `GITLEAKS_LICENSE` is now a
  declared (optional) secret that actually reaches gitleaks-action.
- `reusable-codeql.yml`: `continue-on-error` hid every analysis failure;
  analysis is now fatal and only the separate SARIF upload is tolerated.
- `reusable-repo-docs.yml` / `reusable-doc-commands.yml`: the checker is no
  longer fetched from a bare `v1` (which resolves a branch named `v1` before
  the tag); see Added → native self-references.
- `scripts/check-repo-docs.py`: a directory or a symlink (e.g. to `/dev/null`)
  satisfied "presence". `scripts/check-doc-commands.py`: a non-shell fence
  before a bash block hid it; `~~~`, info strings, CRLF, `--state=all`, `-s`
  and repeated flags were missed.
- `reusable-osv.yml` removes PR-committed report files before scanning;
  `reusable-link-check.yml` and `actions/content-scan` download tools outside
  the PR tree; `actions/retry` uses a random `GITHUB_OUTPUT` delimiter.
- `label.yml`: top-level `permissions: {}`, timeout, concurrency.

### Changed
- **Behavior change:** `scripts/check-windows-footguns.py` reads code with
  the stdlib tokenizer: comments, docstrings and (for API-name rules) string
  contents are masked column-aligned; guard hints count only in code; the
  `# windows-footgun: ok` marker counts only in a real comment and covers a
  whole multi-line statement; `open()` is judged over its whole statement;
  excluded dirs are matched relative to the scan root; symlinks are judged by
  their own name; an unreadable file exits 2. Over CPython 3.12's stdlib it
  drops 9 false positives and misses nothing the old checker found.
- **Behavior change:** content-scan always installs its pinned ripgrep
  (now 15.2.0) and never uses an `rg` already on the runner;
  `scripts/rg-need-install.sh` is gone.
- **Behavior change:** go-ci installs golangci-lint v2.15.0 as a
  hash-verified download (the old `curl | sh` installer exited 0 on a failed
  download); `golangci-version` defaults to "" (the pinned release) and
  other versions are refused.
- **Behavior change:** meta-lint zizmor 1.26.1 → 1.32.0; python-ci /
  python-eval install `pytest>=8` / `pytest-cov>=5` (were unpinned; a floor
  rather than an exact pin, so callers on Python 3.9 or with their own
  pytest pin still resolve).
- This repo's CI installs its lint tools with `pip --require-hashes` from
  `requirements/ci.txt` (`uv pip compile --universal --generate-hashes`).
- **Behavior change (defaults):** `reusable-python-eval` /
  `reusable-python-validation` `python-version` `3.10` → `3.12`;
  `reusable-python-ci` `python-versions` → `["3.11","3.12","3.13","3.14"]`;
  `reusable-node-ci` `node-versions` → `["22","24"]` (Python 3.10 and Node 20
  are end-of-life). Callers that pass their own versions are unaffected.
- **Behavior change:** `reusable-link-check.yml`'s default
  `--no-progress './**/*.md'` reached lychee with its quotes intact, so it
  checked 0 links and passed. The default is now `--no-progress ./**/*.md` and
  quotes in `args` are stripped — callers on the default will start seeing real
  broken links.
- `scripts/check-doc-commands.py` warns (does not fail) when a doc has no
  `gh`/`git` commands.
- Templates: `actions/labeler` v5 → v7.0.0 and `actions/stale` v9 → v11.0.0
  (both were node20); full `# vX.Y.Z` pin comments; a test keeps one SHA per
  action across workflows, templates and actions.
- Self-CI: zizmor 1.26.1 → 1.32.0, now also auditing `actions/`; pr-governance
  re-runs on PR title edits (matching the template) with a concurrency group.
- Docs: README catalog completed (repo-docs, doc-commands, every input), new
  Security model and Docs sections; CONTRIBUTING gains the local lint/test
  commands; `docs/marketplace-research.md` refreshed; `actions/windows-footguns`
  gains `branding:`; `docs/starter-workflows-notes.md` folded into the README
  and removed.

### Fixed
- `scripts/check-windows-footguns.py`: the `open()` mode is decided by a
  balanced-paren scan (#42); zero Python files in scope reports
  `NOT-APPLICABLE` rather than a pass (#45); `/proc` and `/sys` `open()`
  literals are skipped, and `--all` scans the git toplevel.
- `scripts/sync_labels.py`: existing labels match case-insensitively and
  case-only differences are reported (#34).
- `reusable-python-validation.yml` installs a pinned `pyyaml==6.0.3`.
- `ci.yml` runs the `scripts/tests` suite with a pinned PCRE2 ripgrep and
  fails on any skipped test.
- Dependabot bumps of the codeql, osv and release pins.
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
- `actions/windows-footguns` further hardening of the same diff step: a
  changed file literally named e.g. `--diff=HEAD.py` (or its unambiguous
  abbreviation `--dif=x.py`) used to be consumed by the checker's own
  argparse as the `--diff` option instead of reaching the file list,
  silently replacing the whole scan and hiding a real footgun in another
  changed file — a `--` separator now makes every token after it
  positional. The file list is also built via a plain temp file, never
  `while read ... < <(git diff ...)` process substitution: that ran the
  git command in a subshell whose exit status `set -e` never observed, so
  a failing `git diff`/`git ls-files` (not a git repo, a corrupted
  checkout) was silently read as an empty diff instead of failing the
  step. That temp directory is now removed by a `trap ... EXIT`, not only
  by an `rm -rf` reached solely on the success path, so it's no longer
  leaked on that same failure path; the trap doesn't call `exit` itself,
  so it never changes the step's own exit code. When the merge-base
  lookup itself fails (a shallow or unrelated-history base ref) and the
  step falls back to scanning every tracked `.py` file, it now prints a
  fixed-string `::notice::` saying so — never the base-ref or a filename,
  since either is caller-influenced and an `::...::` line is a GitHub
  Actions workflow command an attacker-shaped value could otherwise forge
  a second one inside.
- `scripts/check-windows-footguns.py`: `--diff <ref>` with a ref that doesn't
  resolve to a commit (a typo, a renamed or never-fetched base branch) used
  to be indistinguishable from a ref that resolves cleanly but has zero
  changed `.py` files — both silently reported `NOT-APPLICABLE`/exit 0. An
  unresolvable ref now exits 2 with a stderr message instead; a resolvable
  ref with nothing changed still gets the documented `NOT-APPLICABLE`/exit 0
  (the lookup worked, there's just nothing to report).
- `scripts/sync_labels.py`: a case-mismatch used to exit 0 with no summary, so a
  scheduled `--apply` run could never notice it. It now prints a stderr footer
  ("N label(s) need a manual case rename") and exits with a new, distinct code
  (3) when the only problem is a pending rename — 0 still means full
  convergence, and 1 (a `gh` API/auth failure) always wins over 3 even when
  both occur in the same run. See README → Label sync for the exit-code table.
- `scripts/tests/fixtures/check_windows_footguns_709fabb.py`: this vendored
  pre-fix checker fixture is self-referential, like `check-windows-footguns.py`
  itself, and reddened the repo's own self-lint. The governance gate
  (`reusable-crossplatform-lint.yml`) runs the windows-footguns composite action
  at a pinned tag, which fetches the checker script at that tag, so a fix in
  `check-windows-footguns.py` on this repo's HEAD would never reach it. Renamed
  the fixture to `check_windows_footguns_709fabb.py.txt` instead: every checker
  version only scans `*.py`/`*.pyw`/`*.pyi` files, so a fixture under any other
  extension is out of scope regardless of which tag is pinned. A new unit test
  asserts `scripts/tests/fixtures/` contains no `*.py` file, and another runs
  the real checker over `scripts/tests/` (fixtures included) and asserts a
  clean pass, so neither this fixture nor a future one can redden the gate
  silently again.
- `actions/windows-footguns`: a changed file whose name starts with `::` used
  to reach the job log at column 0 through the checker's own finding lines, so
  a file named e.g. `::add-mask::x.py` could forge a GitHub Actions workflow
  command. The step now brackets the checker call with
  `::stop-commands::<token>` ... `::<token>::`, where the token is fresh per
  run from `/dev/urandom` (never the run id, `$$`, or a timestamp) and the
  resume is unconditional in the existing EXIT trap, so it fires on every exit
  path: a real footgun, a clean pass, a missing checker script, or a `set -e`
  abort from a failing git listing outside a repo. The existing fixed-string
  `::notice::` (merge-base fallback) is emitted before the window opens and
  stays a real command.

## [v1] — retagged 2026-09-27 (`b43f688`)

What `@v1` callers currently run.

### Added
- New reusables (2026-08-20): `reusable-go-ci`, `reusable-pr-title`,
  `reusable-dependency-review`, `reusable-spellcheck`, `reusable-link-check`,
  `reusable-content-scan`; `upload-coverage` in `reusable-python-ci`.
- Contribution governance (2026-09-05): `reusable-repo-docs`,
  `reusable-doc-commands`, `docs/CONTRIBUTION-STANDARD.md` and the doc templates
  under `templates/`.
- `labels.yml` + `scripts/sync_labels.py`: the shared issue-label taxonomy
  (`type:bug|friction|gap|debt|flaky`, `source:agent|human`, `status:carded`) and an
  idempotent, dry-run-by-default script that applies it to the repos you name. It never
  deletes or renames a label.
- `examples/` — placeholder-org (`<your-org>`) copy-paste caller stubs for
  external adopters, plus an external-adopter contract in the README.
- `reusable-deep-lint.yml` inputs: `default-branch`, `linter-rules-path`,
  `python-ruff-config`, `yaml-config` (defaults unchanged).
- `reusable-release.yml` input: `default-branch` (default `main`).
- `docs/marketplace-research.md`; `branding:` metadata on `retry` and
  `detect-changes` (later `content-scan`; `windows-footguns` in Unreleased).
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
- `reusable-codeql.yml` `continue-on-error` narrowed from the whole job to the
  analyze step (it was still too wide — see Unreleased → Security).
- `reusable-python-validation.yml` meta-lint pins the actionlint installer SHA +
  tool versions (was unpinned `curl|bash` + floating pip installs).
- `reusable-crossplatform-lint.yml` dropped the dead `gh-workflows-ref` input;
  refreshed stale private-repo framing across several workflows/docs.

## [v1] — baseline (2026-07-08)

Central reusable workflows + composite actions: generic Python/Node CI, CodeQL,
OSV, gitleaks, deep-lint, release; org-governance reusables
(python-validation, contributor-check, crossplatform-lint); composite actions
`retry`, `detect-changes`, `windows-footguns`. See the README for the full set.
