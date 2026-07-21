# Contributing to gh-workflows

Central reusable GitHub Actions workflows for Ait0u5hi repos. Logic lives here
once; each repo calls it via a thin caller-stub. Changes here ripple to every
consumer, so the bar is: **small, tested, and backward-compatible for callers.**

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

Two reusable checks, wired into new repos via `templates/pr-governance.yml`:

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

## Adopt the governance in another repo

1. Copy `templates/pr-governance.yml` → `<repo>/.github/workflows/pr-governance.yml`.
2. Copy `scripts/add_contributor.py` and add your `contributors/emails/` mapping.
3. Add a `CONTRIBUTING.md` + `.github/PULL_REQUEST_TEMPLATE.md` (crib from here).

## PR checklist

See `.github/PULL_REQUEST_TEMPLATE.md` — it's enforced by the governance workflow.

## Attribution

Cross-platform linter and the attribution-check pattern are adapted from
[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) (MIT).
Credit the human contributor first (they are the commit author); any AI
assistant is a secondary co-author at most.
