#!/usr/bin/env python3
"""Tests for actions/detect-changes: the composite action's `run:` step is
extracted from action.yml and executed against a throwaway git repo.

File names are PR-controlled. A name git would quote (non-ASCII, a quote, a
backslash, a tab) must still be classified into its lane — otherwise every
lane reads false and the jobs they gate are skipped, which GitHub counts as
passing.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ACTION = Path(__file__).resolve().parents[2] / "actions/detect-changes/action.yml"
FILTERS = "workflows: .github/workflows/**\npython: **/*.py\n"


def step_script():
    return yaml.safe_load(ACTION.read_text())["runs"]["steps"][0]["run"]


class Repo:
    def __init__(self):
        self.dir = Path(tempfile.mkdtemp())
        self.git("init", "-q", "-b", "main")
        (self.dir / "README.md").write_text("x\n")
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("checkout", "-q", "-b", "pr")

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.dir, check=True, capture_output=True)

    def add(self, name, content="x\n"):
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "change")

    def run(self, event="pull_request"):
        out = self.dir.parent / (self.dir.name + ".out")
        script = self.dir.parent / (self.dir.name + ".sh")
        out.write_text("")
        script.write_text(step_script())
        try:
            res = subprocess.run(
                ["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)],
                cwd=self.dir, capture_output=True, text=True, timeout=30,
                env=dict(os.environ, FILTERS=FILTERS, BASE_REF="main",
                         EVENT_NAME=event, GITHUB_OUTPUT=str(out)))
            outputs = dict(line.split("=", 1) for line in out.read_text().splitlines())
            return res, json.loads(outputs["changes"]), outputs["any"]
        finally:
            out.unlink()
            script.unlink()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        shutil.rmtree(self.dir, ignore_errors=True)


class TestDetectChanges(unittest.TestCase):
    def test_plain_names_classify(self):
        with Repo() as r:
            r.add("src/app.py")
            _, changes, any_ = r.run()
            self.assertEqual(changes, {"workflows": False, "python": True})
            self.assertEqual(any_, "true")

    def test_names_git_would_quote_still_classify(self):
        for name in (".github/workflows/ci-é.yml", '.github/workflows/q"uote.yml',
                     ".github/workflows/tab\there.yml", ".github/workflows/back\\slash.yml"):
            with self.subTest(name=name), Repo() as r:
                r.add(name)
                _, changes, any_ = r.run()
                self.assertTrue(changes["workflows"], name)
                self.assertEqual(any_, "true")

    def test_non_pr_event_fails_open(self):
        with Repo() as r:
            r.add("docs/x.md")
            _, changes, any_ = r.run(event="push")
            self.assertEqual(changes, {"workflows": True, "python": True})
            self.assertEqual(any_, "true")

    def test_file_names_are_echoed_inside_stop_commands(self):
        with Repo() as r:
            r.add("a\n::warning::forged.py")
            res, _, _ = r.run()
            lines = res.stdout.splitlines()
            start = next(i for i, l in enumerate(lines) if l.startswith("::stop-commands::"))
            token = lines[start].split("::", 2)[2]
            end = lines.index(f"::{token}::")
            forged = lines.index("::warning::forged.py")
            self.assertLess(start, forged)
            self.assertLess(forged, end)


if __name__ == "__main__":
    unittest.main(verbosity=2)
