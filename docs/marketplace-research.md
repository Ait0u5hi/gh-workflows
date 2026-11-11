# GitHub Marketplace listing — research + recommendation

*Written 2026-08-20; last reviewed 2026-11-11 (verdict unchanged).*

**Question:** can this repo be listed on the GitHub Marketplace to make it more
discoverable, and is it worth doing?

## What Marketplace can and cannot list

- **Reusable workflows** (`.github/workflows/reusable-*.yml`, called via
  `uses: … .yml@<ref>`) **cannot** be published to the Marketplace. The Marketplace
  only lists **Actions** (a repo with an `action.yml`/`action.yaml` at its root,
  or a Docker/JS action). So the bulk of this library — every `reusable-*.yml` —
  is not Marketplace-eligible regardless of what we do.
- **Composite actions** are eligible, but Marketplace lists **one action per repo,
  at the repo root**. This repo keeps its actions under `actions/*/action.yml`
  (subdirectories), which are usable via `uses: owner/repo/actions/name@<ref>` but
  are **not** Marketplace-listable from subdirectories.

Of the four composite actions, only two could stand alone:

- `actions/retry` — run a shell command with retries
- `actions/detect-changes` — path-filter → job-gating map

The other two depend on this repo's layout and are not standalone listings:

- `actions/windows-footguns` runs `scripts/check-windows-footguns.py` from this
  repo and encodes the org governance standard.
- `actions/content-scan` is generic in purpose, but runs
  `scripts/content-scan.sh` and `scripts/rg-need-install.sh` from this repo;
  extracting it would mean vendoring those scripts into the action repo.

## Options

**A. Extract each generic action to its own dedicated repo**
(`<owner>/action-retry`, `<owner>/action-detect-changes`), each with a root
`action.yml`, a `branding:` block, a README, and a Marketplace listing.
- Pro: genuinely discoverable; canonical `owner/action-retry@v1` refs; badges.
- Con: two new repos to version/maintain/release; this repo's internal callers
  must repoint (or we keep a thin re-export here); split docs. The actions are
  small (roughly 80–110 lines of YAML each) — a lot of repo overhead for them.

**B. Status quo — keep actions in-repo, referenced by path.**
- Pro: zero new maintenance surface; single source of truth; the actions were
  built for intra-org reuse and that already works (`@v1`, README-documented).
- Con: not discoverable outside anyone who reads this repo.

## Recommendation

**Stay with B.** The discoverability upside is small (two small utility
actions, both adaptations of NousResearch/hermes-agent originals), and the cost
(two maintained repos + release plumbing + repointed internal callers) is
disproportionate. Marketplace cannot list the part of this library that has
real external value — the reusable workflows — so a listing would advertise
the least valuable slice of the repo.

**Cheap half-step taken:** every `actions/*/action.yml` carries a `branding:`
block (icon + color). It is harmless where the action is referenced by path,
and if we ever extract to A the listing metadata is already in place.

Revisit A if either generic action grows into a standalone tool people ask for
by name.
