#!/usr/bin/env python3
"""Tests for the composite action's shell logic in
actions/windows-footguns/action.yml (the "Scan changed Python files" step).

Extracts the step's actual `run:` script out of the YAML (via PyYAML —
never a flat grep of a .yml file) and executes it as a real bash script
against fixture git repos built under mktemp, with a STUB checker standing
in for scripts/check-windows-footguns.py. The stub logs the exact argv it
received (to prove the file list the action computed is right: --diff-filter
behaviour, NUL-delimited paths with spaces, renames) and exits with a
caller-chosen code (to prove the step's own exit code tracks the checker's
exit code only, never a text-grep of its output — including when the
checker's own stdout contains the literal string "NOT-APPLICABLE", which an
attacker-controlled file name or matched source line could produce on a
genuinely failing run).

Each fixture repo gets a real BASE commit and a real HEAD commit (not an
uncommitted working-tree edit — the step diffs commit..commit, not the
working tree), and `refs/remotes/origin/main` is pointed at the base commit
with `git update-ref` so `git merge-base "origin/${BASE_REF}" HEAD` actually
resolves — without that ref, every scenario would silently fall through to
the no-merge-base/ls-files branch instead of exercising the diff-filter
logic this file exists to test.

This is the real run-step script, not a hand-copied duplicate: a future edit
to action.yml that reintroduces `tr '\\n' ' '` or an allow-list diff-filter
is caught here without anyone updating this file.
"""
from __future__ import annotations

import json
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTION_YML = REPO_ROOT / "actions" / "windows-footguns" / "action.yml"

STUB_CHECKER = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["STUB_LOG"], "w") as f:
    json.dump(sys.argv[1:], f)
# Deliberately misleading: a genuinely-failing run (STUB_EXIT != 0) that
# still prints the checker's own "NOT-APPLICABLE" phrasing, the way an
# attacker-named file (NOT-APPLICABLE.py) or a matched source line could.
print("NOT-APPLICABLE: deliberately misleading text on this run")
sys.exit(int(os.environ.get("STUB_EXIT", "0")))
"""


def _run_step_script() -> str:
    data = yaml.safe_load(ACTION_YML.read_text(encoding="utf-8"))
    steps = data["runs"]["steps"]
    for step in steps:
        if step.get("name") == "Scan changed Python files":
            return step["run"]
    raise AssertionError("action.yml: 'Scan changed Python files' step not found")


def _git(args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                           capture_output=True, text=True).stdout


def _commit(repo, message):
    # Per-invocation -c overrides: no .git/config is written, no global
    # `git config` state is touched.
    _git(["add", "-A"], cwd=repo)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
         "commit", "-q", "-m", message],
        cwd=repo, check=True, capture_output=True, text=True,
    )
    return _git(["rev-parse", "HEAD"], cwd=repo).strip()


class WindowsFootgunsActionScript(unittest.TestCase):
    """Fixtures: a git repo with a BASE commit (pointed to by a synthetic
    refs/remotes/origin/main, so merge-base resolves offline) and a HEAD
    commit on top, diffed by the extracted script exactly as the real
    composite step would."""

    @classmethod
    def setUpClass(cls):
        cls.run_script = _run_step_script()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # The gh-workflows action code is fetched into ITS OWN location
        # alongside a consumer repo's checkout (see action.yml's header
        # comment) — never mixed into the scanned repo's own git history.
        # Model that split here: gh_workflows_root (action + stub checker)
        # and self.repo (the fixture repo actually being diffed) are
        # siblings, not one nested inside the other.
        gh_workflows_root = self.tmp / "gh-workflows-checkout"
        self.action_path = gh_workflows_root / "actions" / "windows-footguns"
        self.action_path.mkdir(parents=True)
        stub_dir = gh_workflows_root / "scripts"
        stub_dir.mkdir(parents=True)
        stub = stub_dir / "check-windows-footguns.py"
        stub.write_text(STUB_CHECKER, encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        self.repo = self.tmp / "consumer-repo"
        self.repo.mkdir()
        self.stub_log = self.tmp / "stub.log"
        _git(["init", "-q", str(self.repo)], cwd=self.tmp)

    def _base(self, message="base"):
        """Commit the current working tree as the base, then make it
        resolvable as 'origin/main' without any real remote — a local-only
        `update-ref`, not a network operation."""
        sha = _commit(self.repo, message)
        _git(["update-ref", "refs/remotes/origin/main", sha], cwd=self.repo)
        return sha

    def _head(self, message="head"):
        return _commit(self.repo, message)

    def _run(self, base_ref="main", stub_exit="0", extra_env=None):
        env = {
            "PATH": "/usr/bin:/bin",
            "BASE_REF": base_ref,
            "GITHUB_ACTION_PATH": str(self.action_path),
            "STUB_LOG": str(self.stub_log),
            "STUB_EXIT": stub_exit,
        }
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            ["bash", "-c", self.run_script], cwd=self.repo, env=env,
            capture_output=True, text=True, timeout=30,
        )

    def _stub_argv(self):
        return json.loads(self.stub_log.read_text(encoding="utf-8"))

    def _write(self, rel, content=""):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    # -- exit-code-only reliance (the core ATTACK SURFACE property) --------

    def test_step_exit_code_tracks_checker_exit_code_not_its_text(self):
        """A failing checker run whose own stdout contains the literal text
        'NOT-APPLICABLE' must NOT be laundered into a passing step."""
        self._write("a.py", "x = 1\n")
        self._base()
        self._write("a.py", "x = 2\n")
        self._head()
        proc = self._run(stub_exit="1")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("NOT-APPLICABLE", proc.stdout)  # visible, but not acted on

    def test_step_exit_code_zero_passes_through(self):
        self._write("a.py", "x = 1\n")
        self._base()
        self._write("a.py", "x = 2\n")
        self._head()
        proc = self._run(stub_exit="0")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    # -- --diff-filter=d: exclude deletions, keep everything else ----------

    def test_deleted_only_short_circuits_before_the_checker(self):
        """A path deleted since base must not reach the checker at all —
        FILES is empty, so the step prints its own message and exits clean
        without the stub ever running."""
        self._write("gone.py", "x = 1\n")
        self._base()
        (self.repo / "gone.py").unlink()
        self._head("delete gone.py")
        proc = self._run(stub_exit="1")  # would fail loudly if ever invoked
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("No Python files to scan.", proc.stdout)
        self.assertFalse(self.stub_log.exists(), "checker ran on a deleted-only diff")

    def test_all_non_py_short_circuits_before_the_checker(self):
        self._write("a.txt", "x\n")
        self._base()
        self._write("a.txt", "y\n")
        self._head()
        proc = self._run(stub_exit="1")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertFalse(self.stub_log.exists())

    def test_mixed_py_and_deleted_py_passes_only_the_surviving_file(self):
        self._write("keep.py", "x = 1\n")
        self._write("gone.py", "y = 1\n")
        self._base()
        self._write("keep.py", "x = 2\n")
        (self.repo / "gone.py").unlink()
        self._head("edit keep, delete gone")
        proc = self._run(stub_exit="0")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self._stub_argv(), ["keep.py"])

    def test_mixed_py_and_non_py_passes_only_the_py_file(self):
        self._write("keep.py", "x = 1\n")
        self._write("ignore.txt", "y = 1\n")
        self._base()
        self._write("keep.py", "x = 2\n")
        self._write("ignore.txt", "z = 1\n")
        self._head("edit both")
        proc = self._run(stub_exit="0")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self._stub_argv(), ["keep.py"])

    def test_renamed_with_edit_keeps_the_new_path_not_the_old(self):
        """Simulate a rename (old path deleted, new path added, enough
        content in common for -M to pair them). -M + --diff-filter=d must
        surface the new name, never drop the file because the OLD path's
        status is Deleted."""
        old_content = "\n".join(f"line_{i} = {i}" for i in range(40)) + "\n"
        self._write("old_name.py", old_content)
        self._base()
        (self.repo / "old_name.py").unlink()
        self._write("new_name.py", old_content + "extra = 1\n")
        self._head("rename with a small edit")
        proc = self._run(stub_exit="0")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        argv = self._stub_argv()
        self.assertIn("new_name.py", argv)
        self.assertNotIn("old_name.py", argv)

    def test_pure_rename_no_edit_still_keeps_the_new_path(self):
        """A rename with NO content change: without -M, git diff shows a
        plain D (old) + A (new) pair, and --diff-filter=d would correctly
        keep the new path anyway. With -M it is a single R entry. Either
        way the new name must survive."""
        content = "\n".join(f"line_{i} = {i}" for i in range(40)) + "\n"
        self._write("old2.py", content)
        self._base()
        (self.repo / "old2.py").unlink()
        self._write("new2.py", content)
        self._head("pure rename")
        proc = self._run(stub_exit="0")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        argv = self._stub_argv()
        self.assertIn("new2.py", argv)
        self.assertNotIn("old2.py", argv)

    # -- paths with spaces survive NUL-delimited, not word-split -----------

    def test_path_with_spaces_survives_as_one_argument(self):
        self._write("has space.py", "x = 1\n")
        self._base()
        self._write("has space.py", "x = 2\n")
        self._head()
        proc = self._run(stub_exit="0")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self._stub_argv(), ["has space.py"])

    def test_renamed_path_with_spaces_in_new_name_survives(self):
        content = "\n".join(f"line_{i} = {i}" for i in range(40)) + "\n"
        self._write("old3.py", content)
        self._base()
        (self.repo / "old3.py").unlink()
        self._write("new name with spaces.py", content + "extra = 1\n")
        self._head("rename into a spacey name")
        proc = self._run(stub_exit="0")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self._stub_argv(), ["new name with spaces.py"])

    # -- no merge-base (shallow / unrelated history): ls-files fallback -----

    def test_no_merge_base_falls_back_to_ls_files(self):
        self._write("tracked.py", "x = 1\n")
        self._base()
        proc = self._run(base_ref="does-not-exist", stub_exit="0")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(self._stub_argv(), ["tracked.py"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
