# gh-workflows

Central reusable GitHub Actions workflows for Ait0u5hi repos. Per-repo CI is a
small caller stub (`templates/`); all logic lives here, tested once, upgraded
in one place.

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
needed (and zizmor flags it). If a reusable ever needs a custom secret,
declare it explicitly in its `workflow_call.secrets` block.

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
| `reusable-python-ci.yml` | ruff lint (once) + pytest across a **version matrix**; test-existence guard skips cleanly until tests exist. **No plugin.yaml coupling** — the generic Python entry point | `python-versions` (`["3.10","3.11","3.12","3.13"]`), `run-ruff` (true), `test-command` (""), `extra-deps` ("") |
| `reusable-node-ci.yml` | setup-node + npm cache, `npm ci`, build/typecheck `--if-present`, optional test command; optional **version matrix** | `node-version` ("" = use matrix), `node-versions` (`["20","22"]`), `run-build` (true), `run-typecheck` (false), `test-command` ("") |
| `reusable-python-eval.yml` | pytest with test-existence guard, single version. Kept for existing callers — new repos should prefer `reusable-python-ci.yml` (adds ruff + a matrix) | `python-version` (3.10), `extra-deps` (pyyaml) |
| `reusable-codeql.yml` | CodeQL code scanning (SAST), matrix by language; SARIF to the Security tab. **Public repos only** — auto-skips on private personal repos (no GitHub Advanced Security). Caller grants `security-events: write` | `languages` (`["python"]`), `build-mode` (none) |
| `reusable-security.yml` | gitleaks secret scan over full history — caller must grant `pull-requests: read` | — |
| `reusable-osv.yml` | OSV-Scanner dependency-CVE scan; SARIF to the Security tab — caller must grant `security-events: write`. Language-agnostic (auto-detects manifests) | `scan-args` (`--recursive .`), `fail-on-vuln` (false) |
| `reusable-deep-lint.yml` | super-linter slim, full codebase, whitelist: ruff/yaml/actions/bash/markdown. Weekly + dispatch only — never per-PR (image pull burns metered private-repo minutes) | — |
| `reusable-release.yml` | git-cliff release notes + CHANGELOG regen + GitHub Release; needs caller `cliff.toml`, `contents: write` | `plugin-manifest` (false — sync plugin.yaml version) |

### Org governance (opt-in)

Ait0u5hi-specific contribution governance. **Generic consumers never inherit
these** — they live behind separate reusables and opt-in boolean inputs, and are
distributed via separate templates (`templates/pr-governance.yml`,
`templates/python-plugin/`). Adopt only when you want the org standard.

| Workflow | What it runs | Key inputs (defaults) |
|---|---|---|
| `reusable-python-validation.yml` | ruff (repo's `ruff.toml`) + meta-lint (actionlint + yamllint + zizmor); the **`plugin-validate` path** (Hermes `plugin.yaml` keys + compileall) is opt-in governance | `python-version` (3.10), `plugin-validate` (false), `meta-lint` (true) |
| `reusable-contributor-check.yml` | fails a PR whose commit author emails aren't mapped under `contributors/emails/<email>` (add with `scripts/add_contributor.py`); bots auto-resolve | `base-ref` (main) |
| `reusable-crossplatform-lint.yml` | scans changed Python for Windows footguns via `scripts/check-windows-footguns.py`; suppress a platform-gated line with `# windows-footgun: ok` | `gh-workflows-ref` (main), `base-ref` (main) |

Every reusable takes `runs-on` (default `ubuntu-latest`). To move a repo to a
self-hosted runner later, set it in the stub — one line. Caveats when that
day comes: docker-container actions (gitleaks, git-cliff, super-linter)
generally need an x86 host; runners register per-repo on a personal account;
registration needs repo admin; never attach a self-hosted runner to a public
repo.

## Composite actions

Reference intra-org, ref-pinned (`@v1`), same as the reusables:

| Action | Purpose |
|---|---|
| `actions/windows-footguns` | wraps the vendored cross-platform linter; used by `reusable-crossplatform-lint.yml` |
| `actions/retry` | run a shell command with retries — wrap flaky installs (`npm ci`, `uv sync`) so CI self-heals on transient network flakes; optional `stdout` output |
| `actions/detect-changes` | diff changed files against `base-ref` and match caller-supplied `filters` (newline `name: glob…`); emits a JSON `changes` map + `any` bool for job gating. Fails open on push/dispatch. Generalized from hermes-agent's repo-specific classifier |

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
- `templates/codeql.yml` — CodeQL code scanning (SAST); reports on public repos, skips on private
- `templates/python-plugin/` — validation, eval, security, release (Hermes plugin repos)
- `templates/deep-lint.yml` — weekly super-linter sweep
- `templates/osv.yml` — dependency-CVE scan (copy to `.github/workflows/`)
- `templates/dependabot.yml` — copy to `.github/dependabot.yml`; keeps SHA-pinned
  actions current (github-actions ecosystem only — source-dep pins stay manual)
- `templates/zizmor.yml` — copy to `.github/zizmor.yml` alongside any stub
- `templates/automation/` — optional: `stale.yml` (warn-only, never closes —
  the fleet ledger tracks open PRs) and `label.yml` + `labeler.yml` starter
- `templates/pr-governance.yml` — contributor-attribution + cross-platform
  footgun checks (copy to `.github/workflows/`)

## Contribution governance

`CONTRIBUTING.md`, `.github/PULL_REQUEST_TEMPLATE.md`, and the two governance
reusables above are the shared contribution standard for Ait0u5hi repos
(conventional commits, one-concern PRs, SHA-pinned actions, mapped contributor
attribution, cross-platform code). To adopt in another repo: copy
`templates/pr-governance.yml` + `scripts/add_contributor.py`, seed your
`contributors/emails/` mapping, and crib the CONTRIBUTING / PR template.
The cross-platform linter + attribution pattern are adapted from
[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) (MIT).

## Versioning

Callers pin `@v1`. Moving-major-tag convention, same as official actions:

- compatible change → retag: `git tag -f v1 && git push -f origin v1`
- breaking change (renamed/removed input, changed behavior) → new `v2` tag,
  migrate callers deliberately

## Design notes

Derived from the workspace-guard CI pilot (validated 2026-07-07/08) plus
selective adoption from `actions/starter-workflows`: the Node CI shape comes
from `ci/node.js.yml`; the Python starters (flake8-based) were rejected in
favor of the already-hardened ruff setup; super-linter runs weekly instead of
per-PR; zizmor was adopted into meta-lint as the one super-linter component
the targeted setup lacked.

Distribution is copy-a-stub + reusable `workflow_call` (works on a personal
account). GitHub's native *New workflow* starter picker is Organization-only;
if Ait0u5hi ever becomes an org, [`docs/org-migration.md`](docs/org-migration.md)
documents the exact `.github/workflow-templates/` layout to surface these as
starter workflows.
