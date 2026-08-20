# Changelog

All notable changes to this repo are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); versions are the moving major
tags callers pin (`@v1`). See [README → Versioning](README.md#versioning).

## [Unreleased]

### Added
- `examples/` — placeholder-org (`<your-org>`) copy-paste caller stubs for
  external adopters, plus an external-adopter contract in the README.
- `reusable-deep-lint.yml` inputs: `default-branch`, `linter-rules-path`,
  `python-ruff-config`, `yaml-config` (defaults unchanged).
- `reusable-release.yml` input: `default-branch` (default `main`).
- `docs/marketplace-research.md`; `branding:` metadata on the composite actions.

### Fixed
- `reusable-release.yml` no longer hardcodes `main` for checkout/push-back.
- `reusable-codeql.yml` `continue-on-error` narrowed to the SARIF-upload step so
  genuine CodeQL misconfig fails the job again.
- `reusable-python-validation.yml` meta-lint pins the actionlint installer SHA +
  tool versions (was unpinned `curl|bash` + floating pip installs).
- `reusable-crossplatform-lint.yml` dropped the dead `gh-workflows-ref` input;
  refreshed stale private-repo framing across several workflows/docs.

## [v1] — baseline

Central reusable workflows + composite actions: generic Python/Node CI, CodeQL,
OSV, gitleaks, content-scan, deep-lint, release; org-governance reusables
(python-validation, contributor-check, crossplatform-lint); composite actions
`retry`, `detect-changes`, `windows-footguns`. See the README for the full set.
