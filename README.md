# gh-workflows

[![CI](https://github.com/Ait0u5hi/gh-workflows/actions/workflows/ci.yml/badge.svg)](https://github.com/Ait0u5hi/gh-workflows/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Central reusable GitHub Actions workflows for Ait0u5hi repos. Per-repo CI is a
small caller stub (`templates/`); all logic lives here, tested once, upgraded
in one place.

**Adopting from outside Ait0u5hi?** See
[`examples/`](examples/) for placeholder-org copy-paste stubs and the
[external-adopter contract](#using-this-from-outside-ait0u5hi) below.

## Usage

Copy the matching stub from `templates/` into the target repo's
`.github/workflows/` and adjust inputs. Stubs own **triggers, concurrency, and
permissions**; the reusables own jobs, steps, and timeouts.

```yaml
jobs:
  validation:
    uses: Ait0u5hi/gh-workflows/.github/workflows/reusable-python-validation.yml@v1
    with:
      plugin-validate: true
```

`GITHUB_TOKEN` flows to reusables automatically — no `secrets: inherit`
needed (and zizmor flags it). The two reusables that take a custom secret
declare it in their `workflow_call.secrets` block, so pass it by name:
`reusable-security.yml` (`GITLEAKS_LICENSE`, organizations only) and
`reusable-content-scan.yml` (`patterns`).

Also copy `templates/zizmor.yml` to the repo's `.github/zizmor.yml` so the
meta-lint zizmor pass accepts the `@v1` ref-pin into this repo while still
requiring hash-pins for third-party actions.

One-time repo setting (admin, web UI): *Settings → Actions → General →
Access → "Accessible from repositories owned by Ait0u5hi"* — without it every
caller fails at workflow-resolution time.

## Adopt in 2 minutes

Standard CI for a new repo — no governance, no Hermes coupling:

1. Copy `templates/python/ci.yml` **or** `templates/node/ci.yml` → `.github/workflows/ci.yml`
2. Copy `templates/codeql.yml` → `.github/workflows/codeql.yml` (SAST; reports on public repos)
3. Copy `templates/osv.yml` → `.github/workflows/osv.yml` (dependency CVEs)
4. Copy `templates/zizmor.yml` → `.github/zizmor.yml`
5. *Settings → Actions → General → Access →* allow "Accessible from repositories owned by Ait0u5hi"

Done. To also adopt the org governance standard, add `templates/pr-governance.yml`
(see [Org governance](#org-governance-opt-in) and [Contribution governance](#contribution-governance)).

## Reusable workflows

### Generic CI (adopt anywhere)

Standard, project-agnostic CI. None of these pull in Ait0u5hi-specific
governance — adopt them in any repo, yours or otherwise.

| Workflow | What it runs | Key inputs (defaults) |
|---|---|---|
| `reusable-python-ci.yml` | ruff lint (once) + pytest across a **version matrix**; test-existence guard skips cleanly until tests exist. **No plugin.yaml coupling** — the generic Python entry point | `python-versions` (`["3.11","3.12","3.13","3.14"]`), `run-ruff` (true), `test-command` (""), `extra-deps` (""), `upload-coverage` (false — pytest-cov → `coverage.xml` artifact, no external service) |
| `reusable-node-ci.yml` | setup-node + npm cache, `npm ci`, build/typecheck `--if-present`, optional test command; optional **version matrix** | `node-version` ("" = use matrix), `node-versions` (`["22","24"]`), `run-build` (true), `run-typecheck` (false), `test-command` (""), `install-command` (`npm ci`) |
| `reusable-go-ci.yml` | `go build` + `go vet` + `go test` across a Go **version matrix** (`-race` opt-out); optional golangci-lint (installer SHA-pinned). No third-party actions — first-party `setup-go` + toolchain only. No-module guard skips cleanly | `go-versions` (`["stable"]`), `run-vet` (true), `run-race` (true), `run-lint` (false), `golangci-version` (v2.13.0), `test-command` ("") |
| `reusable-pr-title.yml` | enforce a Conventional-Commits PR title (the squash-merge subject) via **pure inline bash** — no third-party action. Complements the commit-message convention CONTRIBUTING already requires | `types` (`feat\|fix\|docs\|…`) |
| `reusable-python-eval.yml` | pytest with test-existence guard, single version. Kept for existing callers — new repos should prefer `reusable-python-ci.yml` (adds ruff + a matrix) | `python-version` (3.12), `extra-deps` (pyyaml) |
| `reusable-codeql.yml` | CodeQL code scanning (SAST), matrix by language; SARIF to the Security tab. An analysis failure fails the job; only the SARIF upload is tolerated (no GHAS). **Public repos only** — auto-skips on private personal repos (no GitHub Advanced Security). Caller grants `security-events: write` | `languages` (`["python"]`), `build-mode` (none) |
| `reusable-security.yml` | gitleaks secret scan over full history — caller must grant `pull-requests: read`. **Org adopters:** `gitleaks-action` needs a `GITLEAKS_LICENSE` secret for organizations (free for individual accounts + public repos) — pass `secrets: GITLEAKS_LICENSE: ${{ secrets.GITLEAKS_LICENSE }}`; `scanner: local` runs the runner's own pinned `gitleaks` binary instead (no action, no license key). Runs gitleaks' built-in rules, **not** the scanned repo's `.gitleaks.toml` (a PR could otherwise allowlist everything) unless `use-repo-config: true`; per-finding `.gitleaksignore` fingerprints and inline `gitleaks:allow` comments are still honoured, so review them like code | `scanner` (`action` \| `local`), `use-repo-config` (false); `secrets.GITLEAKS_LICENSE` (optional) |
| `reusable-content-scan.yml` | ripgrep sweep for **caller-supplied** patterns (private hostnames, internal jargon, journal-voice phrases), from a committed file, an optional `secrets: patterns:`, or both. Ships no wordlist itself. Findings from the secret redact to `path:line` (never the matched text) since public Actions logs are world-readable; the committed file's findings print full lines as before. Installs a pinned, SHA-256-verified `rg` (amd64/arm64) when the runner doesn't have one. Complements gitleaks: catches leaks that are not secrets. Fails closed: zero active patterns, a symlinked patterns file, or `.gitignore`/`.rgignore`/binary tricks can't turn it green | `patterns-file` (`.github/content-scan-patterns.txt`), `paths` (`.`), `redact-matches` (`auto`), `pcre2` (false); `secrets.patterns` (optional) |
| `reusable-osv.yml` | OSV-Scanner dependency-CVE scan; SARIF to the Security tab — caller must grant `security-events: write`. Language-agnostic (auto-detects manifests). The default `action` scanner is a **docker** action; `scanner: local` runs the runner's own pinned `osv-scanner` binary (self-hosted runners without docker) | `scanner` (`action` \| `local`), `scan-args` (`--recursive .`), `fail-on-vuln` (false) |
| `reusable-dependency-review.yml` | first-party `dependency-review-action` — blocks a PR that adds a vulnerable/disallowed dep. Needs the Dependency Graph (default-on for public repos) | `fail-on-severity` (high) |
| `reusable-spellcheck.yml` | codespell over the repo (pinned pip install, no action). Reads `.codespellrc` / `[tool.codespell]` for ignores | `codespell-args` ("") |
| `reusable-link-check.yml` | lychee link check — the release binary is pinned + **SHA-256 verified** before it runs (no action). Weekly/dispatch (external links flap). Globs in `args` are passed to lychee unexpanded (it globs itself); one level of surrounding quotes is stripped | `args` (`--no-progress ./**/*.md`) |
| `reusable-deep-lint.yml` | super-linter slim, full codebase, whitelist: ruff/yaml/actions/bash/markdown. Weekly + dispatch only — never per-PR (image pull burns metered private-repo minutes) | `default-branch` (main), `linter-rules-path` (.), `python-ruff-config` (ruff.toml), `yaml-config` (.yamllint.yml) |
| `reusable-release.yml` | git-cliff (pinned binary, SHA-256 verified — no action) release notes for this tag (git-cliff `--current` on the tag itself, so `cliff.toml` tag filters such as `ignore_tags` apply) + CHANGELOG regen + GitHub Release; needs caller `cliff.toml`, `contents: write`, a Linux X64/ARM64 runner. Accepts SemVer-shaped `v` tags only (`v1`, `v1.2.3`, `v1.2.3-rc.1`, `v1.2.3-beta.1+exp`); backport tags get a Release but no CHANGELOG commit | `default-branch` (main), `plugin-manifest` (false — sync plugin.yaml version) |

### Org governance (opt-in)

Ait0u5hi-specific contribution governance. **Generic consumers never inherit
these** — they live behind separate reusables and opt-in boolean inputs, and are
distributed via separate templates (`templates/pr-governance.yml`,
`templates/python-plugin/`). Adopt only when you want the org standard.

| Workflow | What it runs | Key inputs (defaults) |
|---|---|---|
| `reusable-python-validation.yml` | ruff (repo's `ruff.toml`) + meta-lint (actionlint + yamllint + zizmor); the **`plugin-validate` path** (Hermes `plugin.yaml` keys + compileall) is opt-in governance | `python-version` (3.12), `plugin-validate` (false), `meta-lint` (true) |
| `reusable-contributor-check.yml` | fails a PR whose commit author emails (merge commits included) aren't mapped under `contributors/emails/<email>` (add with `scripts/add_contributor.py`); GitHub `id+login@users.noreply.github.com` addresses and a short list of exact bot addresses auto-resolve | `base-ref` (main) |
| `reusable-crossplatform-lint.yml` | scans changed Python for Windows footguns via `scripts/check-windows-footguns.py`; suppress a platform-gated line with `# windows-footgun: ok` | `base-ref` (main) |
| `reusable-repo-docs.yml` | fails a PR when the repo lacks its required contribution docs (CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, LICENSE, PR template — regular files, not symlinks out of the repo) or CONTRIBUTING doesn't link the shared standard. Presence only | `tools-ref` (`refs/tags/v1`), `skip` (""), `require-standard-link` (true) |
| `reusable-doc-commands.yml` | statically validates the `gh`/`git` commands in fenced shell blocks of the given docs (flag values like `gh search prs --state`); executes nothing | `tools-ref` (`refs/tags/v1`), `paths` (`CONTRIBUTING.md`) |

Every reusable takes `runs-on` (default `ubuntu-latest`). To move a repo to a
self-hosted runner later, set it in the stub — one line. Caveats when that
day comes: docker-container actions (osv-scanner, super-linter) and the pinned
x86_64 binaries (lychee, git-cliff) need an x86 host; runners register per-repo
on a personal account; registration needs repo admin; never attach a
self-hosted runner to a public repo, and only use **ephemeral** runners for
anything that runs PR code — a persistent runner lets one PR leave a planted
`rg`, `gitleaks` or `~/.gitconfig` behind for the next job.

## Composite actions

Reference intra-org, ref-pinned (`@v1`), same as the reusables:

| Action | Purpose |
|---|---|
| `actions/windows-footguns` | wraps the vendored cross-platform linter; used by `reusable-crossplatform-lint.yml` |
| `actions/retry` | run a shell command with retries — wrap flaky installs (`npm ci`, `uv sync`) so CI self-heals on transient network flakes; optional `stdout` output |
| `actions/detect-changes` | diff changed files against `base-ref` and match caller-supplied `filters` (newline `name: glob…`); emits a JSON `changes` map + `any` bool for job gating. Fails open on push/dispatch. Generalized from hermes-agent's repo-specific classifier |
| `actions/content-scan` | installs a pinned, SHA-256-verified `rg` if missing, then runs `scripts/content-scan.sh`; used by `reusable-content-scan.yml` |

```yaml
- uses: Ait0u5hi/gh-workflows/actions/retry@v1
  with:
    command: npm ci
- id: detect
  uses: Ait0u5hi/gh-workflows/actions/detect-changes@v1
  with:
    filters: |
      python: **/*.py pyproject.toml
      workflows: .github/workflows/**
# later job: if: fromJSON(needs.detect.outputs.changes).python
```

## Templates

- `templates/python/ci.yml` — **generic** Python CI (ruff + pytest matrix, no plugin coupling)
- `templates/node/ci.yml` — Node/npm-workspaces CI
- `templates/go/ci.yml` — Go CI (build + vet + test matrix, opt-in golangci-lint)
- `templates/pr-title.yml` — Conventional-Commits PR-title check
- `templates/dependency-review.yml` — block PRs adding vulnerable deps
- `templates/spellcheck.yml` — codespell; `templates/link-check.yml` — lychee (weekly)
- `templates/codeql.yml` — CodeQL code scanning (SAST); reports on public repos, skips on private
- `templates/python-plugin/` — validation, eval, security, release (Hermes plugin repos)
- `templates/deep-lint.yml` — weekly super-linter sweep
- `templates/osv.yml` — dependency-CVE scan (copy to `.github/workflows/`)
- `templates/content-scan.yml` — ripgrep sweep for caller-supplied forbidden patterns; complements gitleaks. Also create `.github/content-scan-patterns.txt` in the caller repo
- `templates/dependabot.yml` — copy to `.github/dependabot.yml`; keeps SHA-pinned
  actions current (github-actions ecosystem only — source-dep pins stay manual)
- `templates/zizmor.yml` — copy to `.github/zizmor.yml` alongside any stub
- `templates/automation/` — optional: `stale.yml` (warn-only, never closes
  PRs) and `label.yml` + `labeler.yml` starter
- `templates/pr-governance.yml` — the five governance checks: contributor
  attribution, cross-platform footguns, required docs, PR title, documented
  commands (copy to `.github/workflows/`)
- `templates/CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`,
  `PULL_REQUEST_TEMPLATE.md`, `ISSUE_TEMPLATE/` — fill-in-the-placeholders
  docs that satisfy `reusable-repo-docs.yml`

## Label sync

`scripts/sync_labels.py` converges one or more repos onto the shared taxonomy
in `labels.yml`. Dry run by default (prints the plan, makes no `gh` call that
changes a repo); pass `--apply` to make the changes. It never deletes or
renames a label — a label whose only drift is case (`Type:Bug` held,
`type:bug` in the taxonomy) is reported as `case-mismatch` and left alone in
both modes, because `gh label create --force` would case-rename the existing
label.

```
python3 scripts/sync_labels.py OWNER/REPO [OWNER/REPO ...]           # plan
python3 scripts/sync_labels.py --apply OWNER/REPO [OWNER/REPO ...]   # apply
```

Exit status, checked by a caller's `$?` (dry run and `--apply` behave the
same way):

| Code | Meaning |
|---|---|
| 0 | Every repo converged (or would): no `gh` failure, no case-mismatch. |
| 1 | At least one repo's `gh` call failed (API/auth error, timeout, missing `gh`, a repo that doesn't exist, ...). A failure on one repo does not stop the others. This code wins even when a case-mismatch also occurred in the same run — a scheduled `--apply` run must never read "exit 1" as "only a rename is pending" when a repo actually failed. |
| 3 | No repo failed, but at least one label is a case-mismatch needing a manual rename. Exit 3 is distinct from 0 so a scheduled run notices instead of silently exiting clean, and distinct from 1 so "needs a rename" and "gh is broken" are never confused. |

Either nonzero case prints a stderr footer naming the count: exit 1 prints
`sync_labels: N repo(s) failed: <repo>, <repo>, ...`; exit 3 prints
`sync_labels: N label(s) need a manual case rename`. Both footers can print
in the same run (a failure on one repo alongside a case-mismatch on
another) — the exit code still follows the precedence above (1 wins).

## Contribution governance

[`docs/CONTRIBUTION-STANDARD.md`](docs/CONTRIBUTION-STANDARD.md), this repo's
`CONTRIBUTING.md` and PR template, and the governance reusables above are the
shared contribution standard for Ait0u5hi repos (conventional commits,
one-concern PRs, SHA-pinned actions, mapped contributor attribution,
cross-platform code). To adopt in another repo: copy
`templates/pr-governance.yml` + `scripts/add_contributor.py`, seed your
`contributors/emails/` mapping, and copy the doc templates
(`templates/{CONTRIBUTING,CODE_OF_CONDUCT,SECURITY,PULL_REQUEST_TEMPLATE}.md`,
`templates/ISSUE_TEMPLATE/`), filling their `{{PLACEHOLDERS}}`. `repo-docs`
fails until those exist; its `skip` input lets you land them one at a time.

These checks are only as strong as the repo settings around them — see
[Security model](#security-model).
The cross-platform linter + attribution pattern are adapted from
[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) (MIT).

## Using this from outside Ait0u5hi

The library is generic (see the *Generic CI* table), but the distribution is
wired to this org. To adopt in a fork under `<your-org>`:

1. **Fork this repo** and tag it `v1` (`git tag v1 && git push origin v1`), so
   your callers can pin `<your-org>/gh-workflows/...@v1`.
2. **Repoint every `uses:`** in the stubs you copy from `Ait0u5hi/gh-workflows`
   to `<your-org>/gh-workflows`. The [`examples/`](examples/) stubs already use a
   `<your-org>` placeholder for exactly this.
3. **Edit `templates/zizmor.yml`** — its policy allows the `@v1` ref-pin for
   `"Ait0u5hi/*"`; change that to `"<your-org>/*"` or the meta-lint rejects your
   own reusables.
4. **`reusable-security.yml`**: `gitleaks-action` requires a `GITLEAKS_LICENSE`
   secret for **organizations** (free for individual accounts + public repos);
   pass it as `secrets: GITLEAKS_LICENSE: ${{ secrets.GITLEAKS_LICENSE }}`. A
   repo-local `.gitleaks.toml` is ignored unless you set `use-repo-config: true`.
5. **Hardcoded self-references** — repoint these to `<your-org>` in your fork:
   - `reusable-content-scan.yml` → `Ait0u5hi/gh-workflows/actions/content-scan@v1`
   - `reusable-crossplatform-lint.yml` → `Ait0u5hi/gh-workflows/actions/windows-footguns@v1`
   - `reusable-repo-docs.yml`, `reusable-doc-commands.yml` → `repository: Ait0u5hi/gh-workflows`
   - `scripts/check-repo-docs.py` → its "Templates to copy" link
   The governance reusables also assume the `contributors/emails/` layout —
   adopt them only if you want the org standard.

## Versioning

Callers pin `@v1` (governance stubs may pin `@main` while bootstrapping).
Moving-major-tag convention, same as official actions:

- compatible change → retag: `git tag -f v1 && git push -f origin v1`
- breaking change (renamed/removed input, changed behavior) → new `v2` tag,
  migrate callers deliberately

Because `v1` moves, protect it: a tag ruleset on `v*` (no deletion, no
force-push except by maintainers) keeps a compromised token from swapping the
code every caller runs. Callers who need immutability can pin a commit SHA
instead of `@v1` — note that the composite actions and `tools-ref` inside the
reusables still resolve `v1` today.

## Security model

- **Governance checks run the PR's own workflow files.** On `pull_request`,
  GitHub uses the workflow definitions from the PR's merge commit, so a PR can
  edit the very checks that judge it. They only block anything once the
  default branch requires them (a ruleset with required status checks) and
  changes to `.github/workflows/` need review.
- **The scanned tree is hostile.** Checks treat PR content (file names,
  symlinks, ignore files, config files like `.gitleaks.toml`) as attacker
  input: they refuse symlinks out of the workspace, ignore PR-supplied
  `.gitignore`/`.rgignore` files and gitleaks' repo-wide `.gitleaks.toml` by
  default, and print PR-controlled text inside `::stop-commands::` windows.
  Narrow, per-finding suppressions (`.gitleaksignore` fingerprints,
  `gitleaks:allow`, `# windows-footgun: ok`) are still honoured — they are
  visible in the diff, so review them like code.
- **Release tags are validated** before they reach a shell (`reusable-release.yml`).
- **Self-hosted runners** must be ephemeral for anything that runs PR code (see
  above).

## Docs

- [`CONTRIBUTING.md`](CONTRIBUTING.md) · [`SECURITY.md`](SECURITY.md) ·
  [`CHANGELOG.md`](CHANGELOG.md) · [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)
- [`docs/CONTRIBUTION-STANDARD.md`](docs/CONTRIBUTION-STANDARD.md) — the shared
  contribution standard the governance checks enforce
- [`docs/org-migration.md`](docs/org-migration.md) — moving to a GitHub
  Organization and the native workflow-template picker
- [`docs/marketplace-research.md`](docs/marketplace-research.md) — why this
  library isn't listed on the GitHub Marketplace

## Design notes

Derived from an internal CI pilot (validated 2026-07-07/08) plus selective
adoption from [`actions/starter-workflows`](https://github.com/actions/starter-workflows):
the Node CI shape comes from `ci/node.js.yml`; the Python starters
(flake8-based) were rejected in favor of the already-hardened ruff setup;
super-linter runs weekly instead of per-PR; zizmor was adopted into meta-lint
as the one super-linter component the targeted setup lacked.

Third-party actions are kept to a minimum: where a tool ships a release binary,
the reusables download it at a pinned version and verify its SHA-256 instead of
running a third-party action (lychee, git-cliff, ripgrep, golangci-lint's
installer by commit SHA).

Distribution is copy-a-stub + reusable `workflow_call` (works on a personal
account). GitHub's native *New workflow* template picker is Organization-only;
if Ait0u5hi ever becomes an org, [`docs/org-migration.md`](docs/org-migration.md)
documents the `workflow-templates/` layout (in the org's `.github` repo) to
surface these as workflow templates. Reference:
[GitHub Actions quickstart](https://docs.github.com/en/actions/get-started/quickstart),
[using workflow templates](https://docs.github.com/en/actions/how-tos/write-workflows/use-workflow-templates).
