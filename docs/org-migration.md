# Org migration: native starter-workflow picker

**Status: future / not yet done.** This documents how to surface these workflows
in GitHub's native *Actions → New workflow* starter picker. It is a "stub now,
org later" plan — today the library ships via the copy-a-stub + reusable
`workflow_call` model, which is all a personal account can do.

## The constraint (why this is deferred)

GitHub's **custom starter workflows** (the recommended templates shown in the
*New workflow* UI, with language auto-suggestion) are an **Organization-only**
feature. They require:

- an **Organization** (not a personal user account), and
- a repo in that org literally named **`.github`**, with the templates in a
  top-level **`workflow-templates/`** directory (note: `workflow-templates/`,
  **not** `.github/workflow-templates/`).

`Ait0u5hi` is a personal **User** account, so a personal `.github` repo cannot
feed the picker. The generic built-in "recommended Python" starters you already
see come from [`actions/starter-workflows`](https://github.com/actions/starter-workflows)
and are global to every account — you cannot add your own to that set on a
personal account.

## Target layout (once an org exists)

In `<org>/.github`:

```
workflow-templates/
  python-ci.yml            + python-ci.properties.json
  node-ci.yml              + node-ci.properties.json
  codeql.yml               + codeql.properties.json
```

Each `workflow-templates/<name>.yml` is a **thin caller** into the reusables in
this repo — the same body as the `templates/` stubs, but using GitHub's
placeholder tokens that are substituted when a user instantiates the template:

- `$default-branch` → the new repo's default branch
- `$protected-branches` → the repo's protected branches

```yaml
# workflow-templates/python-ci.yml
name: CI
on:
  push:
    branches: [$default-branch]
  pull_request:
jobs:
  ci:
    uses: <org>/gh-workflows/.github/workflows/reusable-python-ci.yml@v1
```

Each `<name>.properties.json` controls how the template appears in the picker.
`filePatterns` is what makes GitHub *suggest* it (e.g. show Python CI when a repo
has a `pyproject.toml`):

```json
{
  "name": "Python CI (Ait0u5hi)",
  "description": "pytest + ruff across a Python version matrix.",
  "iconName": "python",
  "categories": ["Continuous integration", "Python"],
  "filePatterns": ["pyproject\\.toml$", "requirements.*\\.txt$"]
}
```

Fields: `name`, `description`, `iconName` (an octicon name or an SVG under
`icons/`), `categories` (grouping in the picker), `filePatterns` (regex over
root files that gate/suggest the template).

## Migration steps

1. Create the Organization (or convert `Ait0u5hi` to one).
2. Transfer or fork `gh-workflows` into `<org>/gh-workflows`; re-create the `v1`
   tag there.
3. Create the `<org>/.github` repo; add `workflow-templates/` with a `<name>.yml`
   + `<name>.properties.json` pair per generic template (Python CI, Node CI,
   CodeQL). Point each `uses:` at `<org>/gh-workflows/...@v1`.
4. Bulk-update caller `uses:` refs in consumer repos from `Ait0u5hi/*` to
   `<org>/*`.
5. Update the zizmor policy key in `templates/zizmor.yml` (and any `.github/zizmor.yml`)
   from `Ait0u5hi/*: ref-pin` to `<org>/*: ref-pin`.
6. Org setting: *Settings → Actions → General → Access* so consumer repos can
   resolve the reusables.

CodeQL note: on an org you *may* have GitHub Advanced Security available (paid),
which would let the CodeQL templates report on private repos too — at which point
the visibility guard in `reusable-codeql.yml` can be relaxed.
