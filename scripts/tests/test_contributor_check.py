#!/usr/bin/env python3
"""Tests for the inline script in .github/workflows/reusable-contributor-check.yml.

The step's `run:` block is extracted from the workflow YAML and executed
against a throwaway git repo, so the test exercises exactly what CI runs.
Commit author name/email are fully controlled by the PR author, so each case
here is a way a PR could previously slip an unmapped (or path-shaped) author
past the check, or forge a workflow command in its log.
"""
import os
import subprocess
import tempfile
import shutil
import unittest
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/reusable-contributor-check.yml"
STEP_NAME = "Check for unmapped contributor emails"


def step_script():
    wf = yaml.safe_load(WORKFLOW.read_text())
    for step in wf["jobs"]["check-attribution"]["steps"]:
        if step.get("name") == STEP_NAME:
            return step["run"]
    raise AssertionError(f"step {STEP_NAME!r} not found")


class Repo:
    def __init__(self):
        self.dir = Path(tempfile.mkdtemp())
        self.git("init", "-q", "-b", "main")
        self.commit("base", "Base", "ait0u5hi@users.noreply.github.com")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("checkout", "-q", "-b", "pr")

    def git(self, *args, env=None):
        return subprocess.run(["git", *args], cwd=self.dir, check=True,
                              capture_output=True, text=True, env=env).stdout

    def commit(self, msg, name, email):
        env = dict(os.environ, GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email,
                   GIT_COMMITTER_NAME="c", GIT_COMMITTER_EMAIL="c@example.com")
        self.git("commit", "-q", "--allow-empty", "-m", msg, env=env)

    def map(self, email, login="someone"):
        p = self.dir / "contributors/emails" / email
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(login + "\n")

    def run(self):
        script = self.dir.parent / (self.dir.name + ".sh")
        script.write_text(step_script())
        try:
            return subprocess.run(
                ["bash", "--noprofile", "--norc", "-e", str(script)], cwd=self.dir,
                env=dict(os.environ, BASE_REF="main", HEAD_SHA="HEAD"),
                capture_output=True, text=True, timeout=30)
        finally:
            script.unlink()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        shutil.rmtree(self.dir, ignore_errors=True)


class TestContributorCheck(unittest.TestCase):
    def test_mapped_email_passes(self):
        with Repo() as r:
            r.map("dev@example.com")
            r.commit("feat", "Dev", "dev@example.com")
            self.assertEqual(r.run().returncode, 0)

    def test_unmapped_email_fails(self):
        with Repo() as r:
            r.commit("feat", "Dev", "dev@example.com")
            res = r.run()
            self.assertEqual(res.returncode, 1)
            self.assertIn("dev@example.com", res.stdout)

    def test_exact_bot_and_noreply_addresses_pass(self):
        with Repo() as r:
            for email in ("49699333+dependabot[bot]@users.noreply.github.com",
                          "41898282+github-actions[bot]@users.noreply.github.com",
                          "123+someone@users.noreply.github.com",
                          "noreply@github.com", "noreply@anthropic.com"):
                r.commit("x", "Bot", email)
            res = r.run()
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_lookalike_exempt_addresses_are_not_exempt(self):
        for email in ("x@anthropic.com.evil.io", "dependabot@evil.io", "me@notcursor.com",
                      "1+victim@users.noreply.github.com.evil.io",
                      "evil+1+x@users.noreply.github.com"):
            with self.subTest(email=email), Repo() as r:
                r.commit("x", "Evil", email)
                self.assertEqual(r.run().returncode, 1)

    def test_path_shaped_email_cannot_point_at_an_existing_file(self):
        with Repo() as r:
            (r.dir / "LICENSE").write_text("MIT\n")
            r.map("placeholder@example.com")  # makes contributors/emails/ exist
            r.commit("x", "Evil", "../../LICENSE")
            res = r.run()
            self.assertEqual(res.returncode, 1, res.stdout)
            self.assertIn("not a usable email address", res.stdout)

    def test_merge_commit_author_is_checked(self):
        with Repo() as r:
            r.map("dev@example.com")
            r.commit("feat", "Dev", "dev@example.com")
            r.git("checkout", "-q", "-b", "side", "main")
            r.commit("side", "Dev", "dev@example.com")
            r.git("checkout", "-q", "pr")
            env = dict(os.environ, GIT_AUTHOR_NAME="Hidden", GIT_AUTHOR_EMAIL="hidden@evil.io",
                       GIT_COMMITTER_NAME="c", GIT_COMMITTER_EMAIL="c@example.com")
            r.git("merge", "-q", "--no-ff", "-m", "merge", "side", env=env)
            res = r.run()
            self.assertEqual(res.returncode, 1)
            self.assertIn("hidden@evil.io", res.stdout)

    def test_symlinked_alias_mapping_is_accepted(self):
        with Repo() as r:
            r.map("dev@example.com")
            os.symlink("dev@example.com", r.dir / "contributors/emails/alias@example.com")
            r.commit("feat", "Dev", "alias@example.com")
            res = r.run()
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_missing_head_commit_fails_with_a_clear_error(self):
        with Repo() as r:
            r.commit("feat", "Dev", "dev@example.com")
            script = r.dir.parent / (r.dir.name + ".sh")
            script.write_text(step_script())
            try:
                res = subprocess.run(
                    ["bash", "--noprofile", "--norc", "-e", str(script)], cwd=r.dir,
                    env=dict(os.environ, BASE_REF="main", HEAD_SHA="0" * 40),
                    capture_output=True, text=True, timeout=30)
            finally:
                script.unlink()
            self.assertEqual(res.returncode, 1)
            self.assertIn("::error::the PR head commit is not in this checkout", res.stdout)

    def test_author_name_cannot_forge_a_workflow_command(self):
        with Repo() as r:
            r.commit("x", "a\\n::error::forged", "dev@example.com")
            res = r.run()
            self.assertEqual(res.returncode, 1)
            for line in res.stdout.splitlines():
                self.assertFalse(line.lstrip().startswith("::error::forged"), res.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
