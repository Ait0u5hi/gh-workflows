# Examples — using gh-workflows from outside Ait0u5hi

These are copy-paste caller stubs for **external adopters**. They differ from
[`templates/`](../templates/) in one way: every `uses:` points at a placeholder
`<your-org>/gh-workflows`. If you fork this repo, replace `<your-org>` with your
own login/org in each stub. (The `templates/` stubs are the Ait0u5hi-internal
copies, already pinned at `Ait0u5hi/gh-workflows@v1`.)

Adoption is: copy a stub into `.github/workflows/`, copy
[`templates/zizmor.yml`](../templates/zizmor.yml) to `.github/zizmor.yml` (and
edit its `"Ait0u5hi/*"` policy line to `"<your-org>/*"`), then enable
*Settings → Actions → General → Access → "Accessible from repositories owned by
`<your-org>`"*. See the root [README](../README.md) for the full contract.

All stubs own **triggers, concurrency, and permissions**; the reusables own
jobs, steps, and timeouts.

## Python CI (ruff + pytest matrix)

```yaml
# .github/workflows/ci.yml
name: CI
on:
  pull_request:
  push:
    branches: [main]
  workflow_dispatch:
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
permissions:
  contents: read
jobs:
  ci:
    uses: <your-org>/gh-workflows/.github/workflows/reusable-python-ci.yml@v1
    # with:
    #   python-versions: '["3.11","3.12"]'
    #   test-command: "python -m pytest -q"
```

## Node CI (npm)

```yaml
# .github/workflows/ci.yml
name: CI
on:
  pull_request:
  push:
    branches: [main]
  workflow_dispatch:
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
permissions:
  contents: read
jobs:
  ci:
    uses: <your-org>/gh-workflows/.github/workflows/reusable-node-ci.yml@v1
    with:
      node-versions: '["20","22"]'
      # run-typecheck: true
      # test-command: "npm test --if-present"
```

## Security bundle (CodeQL SAST + OSV dependency CVEs)

CodeQL reports on **public** repos only (needs GitHub Advanced Security, which
personal-account private repos lack — it skips cleanly there). Both upload SARIF
to the Security tab, so both need `security-events: write`.

```yaml
# .github/workflows/security.yml
name: Security
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    - cron: "23 4 * * 1"
  workflow_dispatch:
permissions:
  contents: read
  security-events: write
  actions: read
jobs:
  codeql:
    uses: <your-org>/gh-workflows/.github/workflows/reusable-codeql.yml@v1
    # with:
    #   languages: '["python","javascript-typescript"]'
  osv:
    uses: <your-org>/gh-workflows/.github/workflows/reusable-osv.yml@v1
```

## Secret scanning (gitleaks)

> **Org adopters:** `gitleaks-action` requires a `GITLEAKS_LICENSE` for
> **organizations** (it is free for individual accounts and public repos). If
> your fork lives under an org, set that secret or the scan will fail.

```yaml
# .github/workflows/secret-scan.yml
name: Secret scan
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
  pull-requests: read
jobs:
  gitleaks:
    uses: <your-org>/gh-workflows/.github/workflows/reusable-security.yml@v1
```

## Release (git-cliff changelog + GitHub Release)

Needs a `cliff.toml` in your repo and `contents: write`. Set `default-branch`
if your default branch is not `main`.

```yaml
# .github/workflows/release.yml
name: Release
on:
  push:
    tags: ["v*"]
permissions:
  contents: write
jobs:
  release:
    uses: <your-org>/gh-workflows/.github/workflows/reusable-release.yml@v1
    # with:
    #   default-branch: master
```
