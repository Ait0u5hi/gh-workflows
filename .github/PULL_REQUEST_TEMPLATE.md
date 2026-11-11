## What does this PR do?

<!-- What problem does it solve, and why is this the right approach? -->

## Type of change

- [ ] 🐛 Bug fix (non-breaking)
- [ ] ✨ New feature (non-breaking)
- [ ] 💥 Breaking change
- [ ] 🔒 Security fix
- [ ] 📝 Documentation
- [ ] ♻️ Refactor (no behavior change)
- [ ] 🔁 Reusable-workflow change (note the version-bump impact on callers: retag `v1`, or `v2`?)

## Changes made

<!-- Specific changes, with file paths. -->

-

## Evidence

<!--
The most useful thing you can put in this PR. Give a reviewer something they can RE-RUN in one
line and see for themselves - a command and its output, an exact file:line, a paste-able script.
"I tested it" is a claim; a command a reviewer can run is evidence.
For workflow changes: which caller repo/run proves it.
-->

```
$ <command>
<output>
```

## How this was verified

- [ ] This repo's CI checks pass locally (actionlint, yamllint, zizmor, `python3 -m unittest discover -s scripts/tests -t scripts/tests` — see CONTRIBUTING.md)
- [ ] **Red before green** — for a bug fix, the new test FAILS without the fix and passes with it
- [ ] Assertions can actually fail for the reason they name (no bare `x in text` presence checks)

## Checklist

- [ ] Conventional Commit PR title (`fix(scope): …`)
- [ ] Searched existing issues and PRs (open *and* closed) for duplicates
- [ ] One concern only — no unrelated commits
- [ ] Third-party Actions pinned by commit SHA with a `# vX.Y.Z` comment (and the same SHA in `templates/`)
- [ ] For reusable-workflow edits: callers still resolve (no renamed/removed inputs without a `v2`)
- [ ] PR-controlled input (file names, contents, commit metadata, tags) never reaches a shell via `${{ }}`
- [ ] No unguarded Windows footguns in Python (or marked `# windows-footgun: ok`)
- [ ] No secrets, absolute home paths, or internal IPs — including in docs and fixtures
- [ ] Commit email mapped under `contributors/emails/` (`scripts/add_contributor.py`)
