# Starter-workflows notes

This library's shapes were selectively adopted from GitHub's official
[`actions/starter-workflows`](https://github.com/actions/starter-workflows)
(the Node CI shape from `ci/node.js.yml`; the flake8-based Python starters were
rejected in favor of the already-hardened ruff setup). See the **Design notes**
section of the root [README](../README.md) for the rationale.

Reference material:

- [GitHub Actions quickstart](https://docs.github.com/en/actions/get-started/quickstart)
- [actions/starter-workflows](https://github.com/actions/starter-workflows)
- [Using starter workflows](https://docs.github.com/en/actions/writing-workflows/using-starter-workflows)

GitHub's native *New workflow* starter picker is Organization-only; if Ait0u5hi
ever becomes an org, [`org-migration.md`](org-migration.md) documents the exact
`.github/workflow-templates/` layout to surface these reusables as starter
workflows.
