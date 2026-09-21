#!/usr/bin/env python3
"""The title dependabot generates must satisfy our own pr-title gate.

Why this test exists: on 2026-09-21 every weekly dependabot PR in this repo was
failing `pr-title / conventional PR title` (observed on PR #30, run
35568957476 — the other four governance jobs passed). `.github/dependabot.yml`
set BOTH `commit-message.prefix: "chore(actions)"` and `include: "scope"`, and
dependabot concatenates them, emitting `chore(actions)(deps): ...`. The gate's
pattern allows exactly one parenthesised scope, so it refused. The gate was
right; the emitter was wrong.

Two properties are pinned, and the second is the one that keeps this honest:

1. The pattern is READ OUT OF the workflow, never restated here. A copy would
   let the gate and this test drift apart silently, which is the failure mode
   the test is supposed to prevent.
2. The title is DERIVED from dependabot.yml the way dependabot derives it, so
   changing the config changes what is asserted. A hardcoded expected string
   would keep passing after someone reintroduced `include: scope`.
"""
import re
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
PR_TITLE_WORKFLOW = REPO / ".github" / "workflows" / "reusable-pr-title.yml"
DEPENDABOT = REPO / ".github" / "dependabot.yml"
TEMPLATE_DEPENDABOT = REPO / "templates" / "dependabot.yml"

# A real dependabot subject, from PR #30.
SUBJECT = "bump the actions-minor-patch group across 1 directory with 6 updates"


def gate_pattern():
    """The regex the gate actually applies, rebuilt from the workflow.

    The step interpolates ${TYPES} into `pattern="^(${TYPES})(\\(...\\))?!?: .+"`,
    so this reads both the literal pattern line and the `types` input default
    and substitutes one into the other. Parsed out of the file rather than
    copied, so a change to either side is seen here.
    """
    wf = yaml.safe_load(PR_TITLE_WORKFLOW.read_text(encoding="utf-8"))
    # YAML 1.1 parses a bare `on:` key as the boolean True, so the key is not
    # the string "on" — accept either rather than depending on the loader.
    on = next(v for k, v in wf.items() if k is True or k == "on")
    inputs = on["workflow_call"]["inputs"]
    types = inputs["types"]["default"]

    raw = PR_TITLE_WORKFLOW.read_text(encoding="utf-8")
    m = re.search(r'pattern="(?P<pat>[^"]+)"', raw)
    assert m, "could not find the pattern= line in reusable-pr-title.yml"
    return m.group("pat").replace("${TYPES}", types)


def dependabot_title(config_path, subject=SUBJECT):
    """The PR title dependabot produces for a github-actions update.

    Mirrors dependabot's documented composition: `prefix` verbatim, then its
    own `(deps)` scope appended when `include: "scope"` is set, then `: `.
    """
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    update = next(u for u in cfg["updates"]
                  if u["package-ecosystem"] == "github-actions")
    cm = update.get("commit-message") or {}
    prefix = cm.get("prefix", "")
    if cm.get("include") == "scope":
        prefix += "(deps)"
    return f"{prefix}: {subject}"


class PrTitlePattern(unittest.TestCase):
    def setUp(self):
        # re.I: the gate greps with -qiE.
        self.pattern = re.compile(gate_pattern(), re.I)

    def test_the_old_double_scope_form_is_refused(self):
        """Red-before-green anchor: the shape that broke PR #30 must NOT match.

        If this ever passes, the gate stopped catching the bug and the rest of
        this test is worthless.
        """
        self.assertIsNone(
            self.pattern.match(f"chore(actions)(deps): {SUBJECT}"),
            "a double scope must be refused — this is the exact title that "
            "failed pr-title on PR #30",
        )

    def test_the_generated_title_passes_the_gate(self):
        title = dependabot_title(DEPENDABOT)
        self.assertIsNotNone(
            self.pattern.match(title),
            f"dependabot would generate {title!r}, which our own pr-title gate "
            f"refuses (pattern: {self.pattern.pattern})",
        )

    def test_the_template_we_ship_to_consumers_passes_too(self):
        """templates/dependabot.yml is copied into adopting repos, so the same
        defect there would propagate rather than stay local."""
        if not TEMPLATE_DEPENDABOT.exists():
            self.skipTest("no templates/dependabot.yml in this repo")
        title = dependabot_title(TEMPLATE_DEPENDABOT)
        self.assertIsNotNone(
            self.pattern.match(title),
            f"the shipped template would generate {title!r}, which the gate refuses",
        )

    def test_pattern_really_came_from_the_workflow(self):
        """Guard the guard: if the pattern extraction silently returned
        something permissive, every assertion above would pass vacuously."""
        pat = gate_pattern()
        self.assertIn("chore", pat, "types were not substituted into the pattern")
        self.assertTrue(pat.startswith("^("), f"unexpected pattern shape: {pat!r}")
        self.assertIsNone(re.compile(pat, re.I).match("not a conventional title"),
                          "the extracted pattern accepts anything — extraction is broken")


if __name__ == "__main__":
    unittest.main(verbosity=2)
