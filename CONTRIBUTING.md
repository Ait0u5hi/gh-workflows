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
5. **`actionlint` clean.** Run `./actionlint` (vendored) before pushing.

## Governance this repo provides (and dogfoods)

Four reusable checks, wired into new repos via `templates/pr-governance.yml`:

- **Contributor Attribution Check** (`.github/workflows/reusable-contributor-check.yml`)
  — fails a PR whose commit author emails aren't mapped under
  `contributors/emails/<email>`. Add yours once:
  ```bash
  python3 scripts/add_contributor.py <your-git-email> <your-github-login>
  ```
  Bot emails (github-actions, dependabot, `+…@users.noreply.github.com`) auto-resolve.
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
5. Make the PR-title check mean something by disabling non-squash merges, so the title you lint is
   the subject that actually lands:
   ```bash
   gh api -X PATCH repos/Ait0u5hi/<repo> -F allow_merge_commit=false -F allow_rebase_merge=false
   ```

## PR checklist

See `.github/PULL_REQUEST_TEMPLATE.md` — it's enforced by the governance workflow.

## Attribution

Cross-platform linter and the attribution-check pattern are adapted from
[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) (MIT).
Credit the human contributor first (they are the commit author); any AI
assistant is a secondary co-author at most.
