#!/usr/bin/env python3
"""Every pinned action's SHA must agree with the version its comment claims.

Why this exists: on 2026-09-21, thirteen `actions/checkout` pins in this repo
carried a `# v4` comment while the SHA they pinned
(3d3c42e5aac5ba805825da76410c181273ba90b1) resolves to tags v7 and v7.0.1.
The pin was right and the LABEL was wrong, for weeks. CONTRIBUTING.md
documents the `# vX.Y.Z` comment as a supply-chain control, and a control that
can quietly assert the wrong version is worse than none: an auditor reading
the file reasons about an action the workflow is not running.

Deliberately OFFLINE. Resolving each SHA against the GitHub API would be the
stronger check, but it would make the suite need network and a token. Instead
the expected (action, version) -> SHA mapping is recorded here, so the two
halves of a pin can only change TOGETHER: edit the SHA without the comment, or
the comment without this table, and the test fails. Verifying a NEW SHA
against upstream stays a human step at review time, which is where the
judgement belongs.
"""
import pathlib
import re
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
WORKFLOWS = REPO / ".github" / "workflows"
TEMPLATES = REPO / "templates"
ACTIONS = REPO / "actions"

# action -> {version comment: full commit SHA}, each verified against the
# upstream tag at the time it was added. Add a row only after resolving the
# tag yourself (git/ref/tags/<v>, dereferencing an annotated tag to its commit).
EXPECTED = {
    "actions/checkout": {
        "v7.0.1": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    },
}

USES = re.compile(
    r"uses:\s*(?P<action>[\w.-]+/[\w./-]+)@(?P<sha>[0-9a-f]{40})(?P<rest>.*)$")
VERSION = re.compile(r"\bv\d+(?:\.\d+)*\b")
FULL_VERSION = re.compile(r"\bv\d+\.\d+\.\d+\b")


def pinned_files():
    """Workflows, the caller templates we ship, and our composite actions.
    Templates are copied into other repos and Dependabot never sees them, so
    they are exactly where a stale pin survives unnoticed."""
    files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
    files += sorted(TEMPLATES.rglob("*.yml")) + sorted(ACTIONS.glob("*/action.yml"))
    return files


def pins():
    """(path, lineno, action, sha, trailing comment) for every SHA-pinned use."""
    for f in pinned_files():
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            m = USES.search(line)
            if m:
                yield (str(f.relative_to(REPO)), n, m.group("action"),
                       m.group("sha"), m.group("rest"))


class ActionPins(unittest.TestCase):
    def test_there_are_pins_to_check(self):
        """Guard the guard: a parser that silently matches nothing would make
        every assertion below pass vacuously."""
        found = [p for p in pins() if p[2] in EXPECTED]
        self.assertGreater(len(found), 10,
                           "expected many pinned uses of a tracked action; "
                           "the `uses:` parser is probably broken")

    def test_every_tracked_pin_declares_a_version(self):
        for name, n, action, sha, rest in pins():
            if action not in EXPECTED:
                continue
            with self.subTest(f"{name}:{n}"):
                self.assertTrue(
                    VERSION.search(rest),
                    f"{name}:{n}: {action} pinned to {sha[:10]} with no vX.Y.Z "
                    f"comment — the pin cannot be audited by a human reading it",
                )

    def test_declared_version_matches_the_pinned_sha(self):
        for name, n, action, sha, rest in pins():
            if action not in EXPECTED:
                continue
            m = VERSION.search(rest)
            if not m:
                continue  # reported by the test above
            claimed = m.group(0)
            with self.subTest(f"{name}:{n}"):
                known = EXPECTED[action]
                self.assertIn(
                    claimed, known,
                    f"{name}:{n}: comment claims {claimed}, which is not a "
                    f"version this repo has recorded for {action} "
                    f"(known: {sorted(known)}). Resolve the tag upstream and "
                    f"add it to EXPECTED before pinning it.",
                )
                self.assertEqual(
                    sha, known[claimed],
                    f"{name}:{n}: comment claims {claimed} but the SHA is "
                    f"{sha[:10]}…, which is {claimed} for nobody. "
                    f"{claimed} is {known[claimed][:10]}…",
                )

    def test_every_pin_names_a_full_version(self):
        """`# v4` / `# v9` hide which release is pinned (and that a bump
        happened); CONTRIBUTING.md requires a `# vX.Y.Z` comment."""
        for name, n, action, sha, rest in pins():
            with self.subTest(f"{name}:{n}"):
                self.assertTrue(
                    FULL_VERSION.search(rest),
                    f"{name}:{n}: {action}@{sha[:10]} needs a full `# vX.Y.Z` comment")

    def test_one_sha_per_action_across_workflows_templates_and_actions(self):
        """The templates once shipped labeler v5 / stale v9 (node20) while
        self-CI ran labeler v7: a bump must land everywhere at once."""
        seen = {}
        for name, n, action, sha, rest in pins():
            seen.setdefault(action, {}).setdefault(sha, []).append(f"{name}:{n}")
        for action, by_sha in seen.items():
            with self.subTest(action):
                self.assertEqual(
                    len(by_sha), 1,
                    f"{action} is pinned to {len(by_sha)} different SHAs: "
                    + "; ".join(f"{sha[:10]} at {', '.join(where)}" for sha, where in by_sha.items()))

    def test_no_retired_sha_survives(self):
        """v4.2.2 was superseded repo-wide; leaving one behind is the split
        state that made the drift hard to see in the first place."""
        retired = {"11bd71901bbe5b1630ceea73d27597364c9af683": "actions/checkout v4.2.2"}
        for name, n, action, sha, rest in pins():
            with self.subTest(f"{name}:{n}"):
                self.assertNotIn(sha, retired,
                                 f"{name}:{n}: still pinned to retired {retired.get(sha)}")


class GolangciPin(unittest.TestCase):
    """The go-ci default must follow GOLANGCI_PINNED: "" means "the pinned
    release", so bumping GOLANGCI_PINNED can never leave callers on a value
    the install step refuses."""

    def test_default_is_empty_and_the_step_accepts_it(self):
        import yaml

        wf = yaml.safe_load((WORKFLOWS / "reusable-go-ci.yml").read_text())
        on = wf.get("on", wf.get(True))
        self.assertEqual(on["workflow_call"]["inputs"]["golangci-version"]["default"], "")
        step = next(s for s in wf["jobs"]["lint"]["steps"]
                    if s.get("name", "").startswith("Install golangci-lint"))
        self.assertIn('[ -n "$GOLANGCI_VERSION" ]', step["run"])
        self.assertRegex(step["env"]["GOLANGCI_PINNED"], r"^v\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main(verbosity=2)
