#!/usr/bin/env python3
"""The "refuse untrusted PR code on a self-hosted runner" guard.

Every reusable workflow that checks out and runs PR code must start each job
with the guard step, before any checkout, and expose the opt-out input. The
guard's shell is extracted from the workflow and run for each event shape.

This is a misconfiguration guard, not a security boundary (the PR author
controls the calling workflow on `pull_request`); see README -> Security
model. What it must get right is the decision itself: a deleted head repo,
a fork, or a comment trigger is refused; the repo's own branches are not.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
GUARDED = ["python-ci", "python-eval", "node-ci", "go-ci", "content-scan", "crossplatform-lint"]
GUARD_NAME = "Refuse untrusted PR code on a self-hosted runner"
OPT_OUT = "allow-untrusted-prs-on-self-hosted"


def load(name):
    wf = yaml.safe_load((WORKFLOWS / f"reusable-{name}.yml").read_text())
    on = wf.get("on", wf.get(True))
    return wf, on["workflow_call"]


class GuardPresence(unittest.TestCase):
    def test_every_job_starts_with_the_guard_and_input_exists(self):
        for name in GUARDED:
            wf, call = load(name)
            with self.subTest(workflow=name):
                inp = call["inputs"][OPT_OUT]
                self.assertEqual(inp["type"], "boolean")
                self.assertIs(inp["default"], False)
                for job_id, job in wf["jobs"].items():
                    first = job["steps"][0]
                    self.assertEqual(first.get("name"), GUARD_NAME, f"{name}:{job_id}")
                    self.assertIn("runner.environment == 'self-hosted'", first["if"])
                    self.assertIn(OPT_OUT, first["if"])


class GuardDecision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        wf, _ = load("python-eval")
        cls.script = next(iter(wf["jobs"].values()))["steps"][0]["run"]

    def run_guard(self, event, head_repo, this_repo="Owner/lib"):
        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as fh:
            fh.write(self.script)
        try:
            return subprocess.run(
                ["bash", "--noprofile", "--norc", "-e", fh.name],
                env=dict(os.environ, EVENT_NAME=event, HEAD_REPO=head_repo, THIS_REPO=this_repo),
                capture_output=True, text=True, timeout=30)
        finally:
            os.unlink(fh.name)

    def test_refused(self):
        for event, head in [("pull_request", "attacker/lib"),
                            ("pull_request_target", "attacker/lib"),
                            ("pull_request", ""),          # head repo deleted
                            ("workflow_run", "attacker/lib"),
                            ("issue_comment", "")]:
            with self.subTest(event=event, head=head):
                r = self.run_guard(event, head)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn("::error::", r.stdout)

    def test_allowed(self):
        for event, head in [("pull_request", "Owner/lib"),
                            ("pull_request", "owner/LIB"),  # GitHub names are case-insensitive
                            ("push", ""), ("schedule", ""), ("workflow_dispatch", "")]:
            with self.subTest(event=event, head=head):
                r = self.run_guard(event, head)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
