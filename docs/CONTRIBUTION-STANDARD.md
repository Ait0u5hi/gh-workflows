# The Ait0u5hi contribution standard

The shared rules for contributing to any repo in this fleet. Each repo keeps a short
`CONTRIBUTING.md` that links here and adds only what is specific to it — build commands, language
gotchas, where its decision records live. This document is the part that does not vary.

If you are reading this because you want to change something: the short version is **one concern per
PR, a Conventional-Commit title, and evidence a reviewer can re-run in one line.**

---

## 1. Contribution priorities

Roughly the order things get attention:

1. **Bug fixes** — crashes, wrong behaviour, data loss.
2. **Security hardening** — injection, path traversal, credential exposure, supply chain.
3. **Cross-platform correctness** — these repos target portable Linux and Windows.
4. **Robustness** — error handling, retries, graceful degradation.
5. **Features** — welcome, but say what problem they solve before building.
6. **Documentation** — especially fixing something that is wrong or unrunnable.

## 2. Before you start: search first

Duplicates are common and a minute up front keeps the queue clean.

```bash
# --state takes open OR closed, not "all" - run it twice.
gh search issues --repo Ait0u5hi/<repo> --state open  "<your terms>"
gh search issues --repo Ait0u5hi/<repo> --state closed "<your terms>"
gh search prs    --repo Ait0u5hi/<repo> --state closed "<your terms>"
```

**The tracker lags the code.** Plenty of requested features already exist in-tree, so search the
source too, not just issues.

> Search the source with the **codesearch MCP**, not with bare `grep`. The ambient `grep` in these
> agent harnesses silently skips gitignored files and exits 0, so an incomplete answer looks like a
> clean one. If you must use ripgrep directly, pass `rg -uu`.

## 3. Ground rules

1. **Conventional Commits.** `fix(scope):`, `feat(scope):`, `docs(scope):`, `ci(scope):`, … The PR
   title must also be a Conventional Commit — it becomes the squashed commit subject, and it is
   checked (see §7).
2. **One concern per PR.** No unrelated commits riding along. A drive-by cleanup in a bug-fix PR
   makes the bug fix harder to review and harder to revert.
3. **Pin third-party GitHub Actions by commit SHA**, with a `# vX.Y.Z` comment. A moving tag is a
   supply-chain hole. Reusables from this org may be referenced as `@v1` or `@main`.
4. **Cross-platform Python.** No unguarded `os.killpg`, `signal.SIGKILL`, `os.fork`, or hardcoded
   `/tmp`. Use `tempfile`, `pathlib`, and `subprocess` timeouts. If a line is genuinely
   platform-gated, mark it `# windows-footgun: ok`. The `crossplatform-lint` check enforces this.
5. **No secrets, ever** — not in code, tests, fixtures or examples. Config takes environment
   variable references. Note that some repos scan *every tracked text file* for absolute home paths
   and IPs, so write paths as `~/...` or relative even in documentation.

## 4. Attribution

Map your commit email once so CI passes:

```bash
python3 scripts/add_contributor.py <your-git-email> <your-github-login>
```

Bot emails (`github-actions`, `dependabot`, `+…@users.noreply.github.com`) resolve automatically.

**Credit the human first.** The person who made the decisions is the commit author. An AI assistant
is a co-author at most, never the author.

## 5. Architecture Decision Records

When a change settles a durable question — why this design and not the obvious alternative — write
an ADR in the repo's `adr/` directory rather than burying the reasoning in a PR description.

Write one when the decision is expensive to reverse, when you rejected a reasonable alternative for
a non-obvious reason, or when the next person will otherwise ask "why on earth is it like this".

When a decision replaces an earlier one, retire the old one in the same PR: mark it superseded and
have the new one name what it supersedes. A decision record that quietly stops being true is worse
than none.

> **Format is under review.** These repos currently use four different ADR header shapes. A research
> pass is choosing a canonical format before any automated check lands. Until then: follow the shape
> already used in the repo you are working in.

## 6. Security

- **Do not open a public issue for a vulnerability.** Use the repo's private advisory form
  (Security → Report a vulnerability) — see that repo's `SECURITY.md`.
- Treat anything from outside the process as untrusted: web pages, tool output, model output, file
  contents. Validate at the boundary; never pass it to a shell unquoted.
- **Dependency pinning:** post-1.0 dependencies get a compatible-release bound with an upper limit;
  pre-1.0 gets a tight minor window. No unbounded requirements.

## 7. Pull requests

**Branch naming:** `fix/short-description`, `feat/short-description`, `docs/short-description`.

**Before you open it:**
- Run the repo's full verification (`make validate` / `make ci` — the repo's `CONTRIBUTING.md` says
  which). Do not stop at the type checker.
- Re-read your own diff. Most review comments are things the author would have caught on a re-read.

**In the description, give evidence a reviewer can re-run.** This is the single thing that most
speeds up review: a claim plus the one-line command that checks it — an exact `file:line`, a
paste-able script, the actual command output. "I tested it" is not evidence; a command a reviewer
can run and see the same result is.

**What must be green:** the `pr-governance` checks (attribution, cross-platform lint, required repo
docs, PR title).

## 8. The verification bar

**A test must be able to fail for the reason it names.**

That sounds obvious and is routinely violated. The common shape:

```python
# Useless. Cannot fail when the feature breaks.
assert "setError" in bundle_source
```

Substring-presence assertions are **monotone under text addition** — `x in text` can never start
failing because someone *added* code. So a test built only from `in` checks cannot detect a missing
render, a value written but never read, or a branch that stopped executing. It will sit green
through the exact regression it was written to catch. (Measured case: a regression test asserted a
state declaration and two setter calls while claiming to pin a *rendered* error surface; the value
was written four times and read zero times, the feature was broken, and the suite was green.)

Instead:

- **Red before green.** Confirm the test fails *before* the fix and passes after. A test that has
  never failed has never been tested.
- **Assert on behaviour** — the returned value, the rendered output, the side effect — not on the
  presence of the code that is supposed to produce it.
- **A self-report is not evidence.** "I verified this" from a person or an agent is a claim. The
  command output is the evidence.
- **Prefer a gate that refuses over a document that asks.** Where these two disagree, only the gate
  is load-bearing. Adopted is not the same as enforced.

## 9. Where enforcement is real, and where it is not

Being straight about this, because pretending otherwise is the failure mode §8 warns about.

- **`gh-workflows` is public**, so its checks are wired to branch protection and genuinely block a
  merge, admins included.
- **The other repos in this fleet are private on a free plan**, where GitHub branch protection and
  rulesets are unavailable (`403 Upgrade to GitHub Pro or make this repository public`). Their
  checks run and report, but **nothing stops a merge past a red check**. Treat them as advisory.
- For those repos, the gate that actually refuses is the **fleet publish path**, which requires a
  reviewer attestation from a different identity than the builder before a change can be published.

If you are contributing to a private repo here, the checks are a courtesy to you, not a wall. Read
them.
