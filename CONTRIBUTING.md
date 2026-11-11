# Contributing to gh-workflows

Central reusable GitHub Actions workflows for Ait0u5hi repos. Logic lives here
once; each repo calls it via a thin caller-stub. Changes here ripple to every
consumer, so the bar is: **small, tested, and backward-compatible for callers.**

This repo also defines and dogfoods the shared
[Ait0u5hi contribution standard](https://github.com/Ait0u5hi/gh-workflows/blob/main/docs/CONTRIBUTION-STANDARD.md)
— read that first; the rules below are what is specific to *this* repo.

## Before you start: search first

Check [existing PRs](https://github.com/Ait0u5hi/gh-workflows/pulls) and issues —
duplicates are common and a minute up front keeps the queue clean.

## Ground rules

1. **Conventional Commits** — `fix(scope):`, `feat(scope):`, `ci(scope):`,
   `docs(scope):`. The scope is usually the reusable name (e.g. `reusable-security`).
2. **One concern per PR.** No unrelated commits.
3. **Backward compatibility for callers.** Renaming/removing an input or a
   reusable is breaking — it changes every consumer's `uses:` contract. Add new
   inputs with defaults; deprecate before removing; call it out in the PR.
4. **Pin third-party actions by commit SHA** (with a `# vX.Y.Z` comment), never a
   moving tag. Reusables in *this* repo may be referenced by callers as `@main`
   (always-current) or `@v1` (stable).
5. **Lint and test clean.** CI (`.github/workflows/ci.yml`) runs exactly the checks below,
   at pinned versions; run them before pushing. actionlint is not vendored (it's gitignored) —
   fetch the pinned release with its installer, pinned by commit SHA:
   ```bash
   bash <(curl -sSfL https://raw.githubusercontent.com/rhysd/actionlint/914e7df21a07ef503a81201c76d2b11c789d3fca/scripts/download-actionlint.bash) 1.7.12
   ./actionlint -color
   pip install yamllint==1.38.0 zizmor==1.32.0 pyyaml==6.0.3
   yamllint .
   zizmor --no-online-audits .github/workflows/ actions/
   python3 -m unittest discover -s scripts/tests -t scripts/tests
   ```
   The content-scan tests need a ripgrep built with PCRE2 (`rg --pcre2-version`); point `RG_BIN`
   at one if your distro's isn't. CI treats any skipped test as a failure.
6. **Treat PR content as hostile.** Anything a check reads from the tree under test (file names,
   symlinks, ignore/config files, commit metadata) is attacker-controlled: never echo it outside a
   `::stop-commands::` window, never pass it to a tool without `--`, never follow a symlink out of
   the workspace, and never interpolate `${{ }}` into a `run:` script — go through `env:`. Each
   hardening fix lands with a test that fails without it.
7. **A template pin moves with its workflow pin.** Dependabot only updates `.github/workflows/`;
   `scripts/tests/test_action_pins.py` fails if the same action is pinned to different SHAs in a
   workflow and a `templates/` stub.

## Governance this repo provides (and dogfoods)

Five reusable checks, wired into new repos via `templates/pr-governance.yml`:

- **Contributor Attribution Check** (`.github/workflows/reusable-contributor-check.yml`)
  — fails a PR whose commit author emails aren't mapped under
  `contributors/emails/<email>`. Add yours once:
  ```bash
  python3 scripts/add_contributor.py <your-git-email> <your-github-login>
  ```
  GitHub `id+login@users.noreply.github.com` addresses (including dependabot and github-actions)
  and a few exact bot addresses auto-resolve. Merge commits are checked too.
- **Cross-platform lint** (`.github/workflows/reusable-crossplatform-lint.yml`)
  — scans changed Python for Windows footguns (bare `os.killpg`, `signal.SIGKILL`,
  `os.fork`, hardcoded `/tmp`, …) with `scripts/check-windows-footguns.py`.
  Fix cross-platform first; suppress a genuinely platform-gated line with
  `# windows-footgun: ok`.
- **Required contribution docs** (`.github/workflows/reusable-repo-docs.yml`) — fails a PR when
  `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `LICENSE` or the PR template is missing,
  or when `CONTRIBUTING.md` does not link the shared standard. Presence only, by design: presence
  is decidable, so refusing on it is sound; content quality is heuristic and stays advisory.
  Run it locally with `python3 scripts/check-repo-docs.py <repo>`; unit tests in `scripts/tests/`.
- **Conventional-Commit PR title** (`.github/workflows/reusable-pr-title.yml`) — see the soundness
  note in that file: it only guarantees the landed subject if the repo squash-merges.
- **Documented commands** (`.github/workflows/reusable-doc-commands.yml`) — statically validates
  the `gh`/`git` commands in fenced shell blocks of the given docs (e.g. `gh search prs --state`
  accepts only `open|closed`). Executes nothing. Run it locally with
  `python3 scripts/check-doc-commands.py CONTRIBUTING.md`.

## Adopt the governance in another repo

1. Copy `templates/pr-governance.yml` → `<repo>/.github/workflows/pr-governance.yml`.
   Note this is a **copy, not a reference** — editing the template later does not reach repos that
   already copied it.
2. Copy `scripts/add_contributor.py` and add your `contributors/emails/` mapping.
3. Copy the doc templates and fill their `{{PLACEHOLDERS}}`:
   `templates/CONTRIBUTING.md`, `templates/CODE_OF_CONDUCT.md`, `templates/SECURITY.md`,
   `templates/PULL_REQUEST_TEMPLATE.md` and `templates/ISSUE_TEMPLATE/`.
4. Check it locally before pushing — the `repo-docs` job runs exactly this:
   ```bash
   python3 scripts/check-repo-docs.py /path/to/repo
   ```
   Adopting gradually? `repo-docs` takes a `skip` input so you can land the docs one at a time.
5. Make the PR-title check mean something: disable non-squash merges and make the squash subject
   the PR title (by default a single-commit PR lands its *commit* subject instead):
   ```bash
   gh api -X PATCH repos/Ait0u5hi/<repo> -F allow_merge_commit=false -F allow_rebase_merge=false -f squash_merge_commit_title=PR_TITLE
   ```
6. Make the checks blocking: add a ruleset on the default branch that requires the PR Governance
   checks. Without it every check is advisory — and a PR can edit the workflow that checks it.

## PR checklist

See `.github/PULL_REQUEST_TEMPLATE.md`. The governance workflow checks that the template exists;
filling it in honestly is on you and your reviewer.

## Attribution

Cross-platform linter and the attribution-check pattern are adapted from
[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) (MIT).
Credit the human contributor first (they are the commit author); any AI
assistant is a secondary co-author at most.
