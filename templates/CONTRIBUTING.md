<!--
Copy to <your-repo>/CONTRIBUTING.md and fill the {{PLACEHOLDERS}}.
Keep it thin: the shared rules live in the canonical standard, and restating them here just
creates two copies that drift. Add only what is specific to THIS repo.
The repo-docs check requires that the link to CONTRIBUTION-STANDARD.md below stays intact.
-->
# Contributing to {{REPO_NAME}}

Thanks for contributing. This repo follows the shared
[Ait0u5hi contribution standard](https://github.com/Ait0u5hi/gh-workflows/blob/main/docs/CONTRIBUTION-STANDARD.md)
— Conventional Commits, one concern per PR, SHA-pinned Actions, cross-platform Python, contributor
attribution, and the verification bar. **Read that first.** What follows is only what differs here.

## What this repo is

{{ONE_PARAGRAPH: what it does and what it is not, so a contributor can tell whether their idea belongs here.}}

## Setup

```bash
{{SETUP_COMMANDS}}
```

## Build and test

```bash
{{VERIFY_COMMAND}}   # must be green before you open a PR
```

{{NOTES: language/toolchain gotchas — pinned versions, non-obvious PATH requirements, tests that
need a service running. Anything that has cost someone an hour belongs here.}}

## Decision records

Durable decisions live in [`adr/`]({{ADR_PATH}}). {{WHEN_TO_WRITE_ONE}}

## Reporting a security issue

Do not open a public issue — see [SECURITY.md](SECURITY.md).

## Code of conduct

By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md).
