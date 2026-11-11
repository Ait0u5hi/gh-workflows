#!/usr/bin/env python3
"""v2 self-references and the actionlint ignores they need.

The reusable workflows must reach this repository's own composite actions
and scripts via GitHub's native self-references — `uses: $/actions/...` and
`job.workflow_repository` / `job.workflow_sha` — which resolve to the commit
the caller pinned. A hard-coded `Ait0u5hi/gh-workflows/...@v1` (or a
`refs/tags/v1` checkout) silently runs different code than the caller
pinned. And the actionlint ignores that `$/` currently needs must stay
exactly as narrow as they are.
"""
import re
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SCANNED = (sorted((REPO / ".github/workflows").glob("*.yml"))
           + sorted((REPO / "actions").glob("*/action.yml")))
SELF_ACTION = re.compile(r"^\s*-?\s*uses:\s*(?P<ref>\S+)", re.M)


class SelfReferences(unittest.TestCase):
    def test_no_hard_coded_self_reference_or_v1_tag(self):
        for path in SCANNED:
            text = path.read_text(encoding="utf-8")
            code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
            with self.subTest(path=path.relative_to(REPO).as_posix()):
                self.assertNotRegex(code, r"Ait0u5hi/gh-workflows/actions/")
                self.assertNotRegex(code, r"repository:\s*Ait0u5hi/gh-workflows")
                self.assertNotIn("refs/tags/v1", code)

    def test_own_actions_are_used_via_self_repository_syntax(self):
        uses = {}
        for path in sorted((REPO / ".github/workflows").glob("reusable-*.yml")):
            for m in SELF_ACTION.finditer(path.read_text(encoding="utf-8")):
                ref = m.group("ref")
                if "actions/content-scan" in ref or "actions/windows-footguns" in ref:
                    uses[path.name] = ref
        self.assertEqual(uses, {
            "reusable-content-scan.yml": "$/actions/content-scan",
            "reusable-crossplatform-lint.yml": "$/actions/windows-footguns",
        })

    def test_script_checkouts_follow_the_workflows_own_commit(self):
        for name in ("reusable-repo-docs.yml", "reusable-doc-commands.yml"):
            wf = yaml.safe_load((REPO / ".github/workflows" / name).read_text())
            step = next(s for j in wf["jobs"].values() for s in j["steps"]
                        if s.get("name") == "Fetch the checker from gh-workflows")
            with self.subTest(workflow=name):
                self.assertEqual(step["with"]["repository"], "${{ job.workflow_repository }}")
                self.assertEqual(step["with"]["ref"], "${{ inputs.tools-ref || job.workflow_sha }}")


class ActionlintIgnoresStayNarrow(unittest.TestCase):
    ALLOWED = {
        ".github/workflows/reusable-content-scan.yml":
            ['specifying action "\\$/actions/content-scan" in invalid format because ref is missing'],
        ".github/workflows/reusable-crossplatform-lint.yml":
            ['specifying action "\\$/actions/windows-footguns" in invalid format because ref is missing'],
        ".github/workflows/reusable-repo-docs.yml":
            ['property "workflow_(repository|sha)" is not defined in object type \\{check_run_id'],
        ".github/workflows/reusable-doc-commands.yml":
            ['property "workflow_(repository|sha)" is not defined in object type \\{check_run_id'],
    }

    def test_ignore_list_is_exactly_the_self_reference_errors(self):
        cfg = yaml.safe_load((REPO / ".github/actionlint.yaml").read_text())
        got = {p: v.get("ignore") for p, v in (cfg.get("paths") or {}).items()}
        self.assertEqual(got, self.ALLOWED)
        self.assertEqual(set(cfg), {"paths"})

    def test_ignores_do_not_swallow_neighbouring_errors(self):
        pattern = re.compile(self.ALLOWED[".github/workflows/reusable-repo-docs.yml"][0])
        self.assertIsNotNone(pattern.search('property "workflow_sha" is not defined in object type {check_run_id: number}'))
        self.assertIsNone(pattern.search('property "workflow_foo" is not defined in object type {check_run_id: number}'))
        action = re.compile(self.ALLOWED[".github/workflows/reusable-content-scan.yml"][0])
        self.assertIsNone(action.search('specifying action "$/actions/other" in invalid format because ref is missing'))


if __name__ == "__main__":
    unittest.main(verbosity=2)
