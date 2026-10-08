#!/usr/bin/env python3
"""Tests for the composite action's shell logic in
actions/windows-footguns/action.yml (the "Scan changed Python files" step).

Extracts the step's actual `run:` script out of the YAML (via PyYAML —
never a flat grep of a .yml file) and executes it as a real bash script
against fixture git repos built under mktemp, with a STUB checker standing
in for scripts/check-windows-footguns.py. The stub logs the argv it
received, with the step's own `--` separator (see action.yml) dropped from
the front if present — that separator is argparse-prefix-attack plumbing
for the REAL checker, not part of the file list this stub exists to verify
(--diff-filter behaviour, NUL-delimited paths with spaces, renames). The
real checker's own handling of `--` and of option-shaped filenames is
exercised separately, against the real script, in
WindowsFootgunsActionRealCheckerTests below. The stub exits with a
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

The "red" half of each before/after test reads the pre-fix action and
checker from scripts/tests/fixtures/ (vendored at build time from the
rejected parent commit 709fabb — named only in the fixtures' own header
comments) rather than running `git show 709fabb:...` live: this module used
to do that at import time, which works in a full clone but raises
CalledProcessError in a `git clone --depth 1` checkout (CI's unit-tests job
checks out with the default fetch-depth), and would break for good after
any squash merge that drops 709fabb from history.
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
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
OLD_ACTION_YML = FIXTURES_DIR / "action_709fabb.yml"
OLD_CHECKER_PATH = FIXTURES_DIR / "check_windows_footguns_709fabb.py"

STUB_CHECKER = """#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
# The step always passes a leading `--` (see action.yml) so an option-shaped
# filename can't be swallowed by the real checker's argparse. Strip just
# that one separator before logging: this stub verifies the file LIST the
# action computed, not argparse's own `--` handling (that's covered against
# the real checker in WindowsFootgunsActionRealCheckerTests).
if argv and argv[0] == "--":
    argv = argv[1:]
with open(os.environ["STUB_LOG"], "w") as f:
    json.dump(argv, f)
# Deliberately misleading: a genuinely-failing run (STUB_EXIT != 0) that
# still prints the checker's own "NOT-APPLICABLE" phrasing, the way an
# attacker-named file (NOT-APPLICABLE.py) or a matched source line could.
print("NOT-APPLICABLE: deliberately misleading text on this run")
sys.exit(int(os.environ.get("STUB_EXIT", "0")))
"""


def _extract_run_step(data) -> str:
    steps = data["runs"]["steps"]
    for step in steps:
        if step.get("name") == "Scan changed Python files":
            return step["run"]
    raise AssertionError("action.yml: 'Scan changed Python files' step not found")


def _run_step_script() -> str:
    """The step script as it stands in the working tree right now."""
    return _extract_run_step(yaml.safe_load(ACTION_YML.read_text(encoding="utf-8")))


def _old_run_step_script() -> str:
    """The step script as it stood at the rejected parent commit 709fabb —
    lets a single test demonstrate an exploit was real (red, against the old
    script) and is closed (green, against the current working tree).

    Reads a vendored fixture (scripts/tests/fixtures/action_709fabb.yml),
    never `git show 709fabb:...`: a CI checkout with fetch-depth 1 (see
    ci.yml's unit-tests job) does not carry that history, so a live `git
    show` at import time made this whole module fail to import there; and a
    future squash merge would drop 709fabb for good either way."""
    return _extract_run_step(yaml.safe_load(OLD_ACTION_YML.read_text(encoding="utf-8")))


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

    # -- F-C: a ::notice:: on the merge-base-fails fallback -----------------

    NOTICE_PREFIX = "::notice::windows-footguns: "

    def test_no_merge_base_emits_a_notice_of_the_fallback(self):
        """A human reading the job log should see that the scan silently
        widened to every tracked .py file, not just a shorter FILES list
        with no explanation."""
        self._write("tracked.py", "x = 1\n")
        self._base()
        proc = self._run(base_ref="does-not-exist", stub_exit="0")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn(self.NOTICE_PREFIX, proc.stdout)

    def test_notice_is_a_fixed_string_not_shaped_by_base_ref(self):
        """base-ref is a workflow `inputs:` value (caller-controlled). A
        base-ref containing its own `::` (or worse, an embedded newline)
        must not let a second, forged workflow command ride along inside
        this notice line — so the notice text is a fixed string with no
        base-ref or filename interpolated into it at all. Assert the exact
        fixed line appears, and that the attacker-chosen ref text itself
        never does."""
        self._write("tracked.py", "x = 1\n")
        self._base()
        poison_ref = "evil::error::pwned"
        proc = self._run(base_ref=poison_ref, stub_exit="0")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn(
            self.NOTICE_PREFIX
            + "merge-base not found against the base ref; "
            "scanning every tracked .py file",
            proc.stdout,
        )
        self.assertNotIn("pwned", proc.stdout)
        self.assertNotIn("evil", proc.stdout)

    def test_resolvable_merge_base_emits_no_notice(self):
        """The fallback notice is specific to the no-merge-base case — a
        normal diff against a real base must not print it."""
        self._write("a.py", "x = 1\n")
        self._base()
        self._write("a.py", "x = 2\n")
        self._head()
        proc = self._run(stub_exit="0")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("::notice::", proc.stdout)


REAL_CHECKER = (REPO_ROOT / "scripts" / "check-windows-footguns.py").read_text(encoding="utf-8")

# The checker exactly as it stood at the rejected parent commit (709fabb) —
# i.e. BEFORE this card's F4 fix too. The reviewer's key evidence for F2
# ("a diff adding a footgun in bad.py plus a file named --diff=HEAD.py made
# the action step print NOT-APPLICABLE and exit 0") was gathered against
# THIS checker: an unresolvable --diff ref silently reported zero files in
# scope. F4 later makes an unresolvable ref fail loudly (exit 2) instead —
# a real improvement, but a different signal — so reproducing the original
# evidence needs the original checker, not today's doubly-patched one.
#
# Read from a vendored fixture (scripts/tests/fixtures/check_windows_footguns_709fabb.py),
# never `git show 709fabb:...` at import time — see _old_run_step_script's
# docstring for why a live git-history read breaks a depth-1 CI checkout.
OLD_CHECKER = OLD_CHECKER_PATH.read_text(encoding="utf-8")

# A real, unsuppressed footgun (no `# windows-footgun: ok`, no encoding=):
# open() without an explicit encoding= on a text-mode call.
FOOTGUN_LINE = 'x = open("data.txt")\n'


class WindowsFootgunsActionRealCheckerTests(unittest.TestCase):
    """ATTACK SURFACE for F2: the REAL checker (scripts/check-windows-footguns.py),
    run through the REAL yaml-extracted step script — never the STUB used
    above, since the exploit lives in the checker's own argparse. Each
    fixture plants FOOTGUN_LINE so a false NOT-APPLICABLE/exit-0 is
    distinguishable from a genuine scan that caught it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        gh_workflows_root = self.tmp / "gh-workflows-checkout"
        self.action_path = gh_workflows_root / "actions" / "windows-footguns"
        self.action_path.mkdir(parents=True)
        self.checker_file = gh_workflows_root / "scripts" / "check-windows-footguns.py"
        self.checker_file.parent.mkdir(parents=True)
        self._use_checker(REAL_CHECKER)
        self.repo = self.tmp / "consumer-repo"
        self.repo.mkdir()
        _git(["init", "-q", str(self.repo)], cwd=self.tmp)

    def _use_checker(self, src):
        self.checker_file.write_text(src, encoding="utf-8")

    def _base(self, message="base"):
        sha = _commit(self.repo, message)
        _git(["update-ref", "refs/remotes/origin/main", sha], cwd=self.repo)
        return sha

    def _head(self, message="head"):
        return _commit(self.repo, message)

    def _write(self, rel, content=""):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def _run(self, run_script, base_ref="main"):
        env = {
            "PATH": "/usr/bin:/bin",
            "BASE_REF": base_ref,
            "GITHUB_ACTION_PATH": str(self.action_path),
        }
        return subprocess.run(
            ["bash", "-c", run_script], cwd=self.repo, env=env,
            capture_output=True, text=True, timeout=30,
        )

    # -- the reviewer's key evidence -----------------------------------

    def test_diff_equals_filename_no_longer_hides_a_real_footgun(self):
        """Red on 709fabb (the rejected parent commit, missing `--`), with
        the checker AS IT STOOD THEN (before this card's F4 too — see
        OLD_CHECKER): a changed file named '--diff=HEAD.py' is consumed by
        the checker's own --diff option — not the file list — silently
        replacing the whole scan with get_diff_files("HEAD.py") (an
        unresolvable ref, silently empty on the old checker), which
        reports NOT-APPLICABLE and exits 0 while the real footgun in
        bad.py is never scanned. Green on the current (fixed) script and
        checker: `--` keeps '--diff=HEAD.py' positional, bad.py is
        scanned, and the step fails on the real footgun."""
        self._write("bad.py", "x = 1\n")
        self._base()
        self._write("bad.py", FOOTGUN_LINE)
        self._write("--diff=HEAD.py", "z = 1\n")
        self._head("introduce a footgun alongside a poison filename")

        self._use_checker(OLD_CHECKER)
        old = self._run(_old_run_step_script())
        self.assertEqual(old.returncode, 0, old.stdout + old.stderr)
        self.assertIn("NOT-APPLICABLE", old.stdout)

        self._use_checker(REAL_CHECKER)
        new = self._run(_run_step_script())
        self.assertEqual(new.returncode, 1, new.stdout + new.stderr)
        self.assertIn("bad.py", new.stdout)
        self.assertIn("open() without encoding=", new.stdout)

    def test_diff_abbreviation_no_longer_hides_a_real_footgun(self):
        """Same exploit via argparse's prefix-abbreviation of --diff:
        '--dif=x.py' resolves to the same --diff option. Uses OLD_CHECKER
        for the red case for the same reason as above."""
        self._write("bad.py", "x = 1\n")
        self._base()
        self._write("bad.py", FOOTGUN_LINE)
        self._write("--dif=x.py", "z = 1\n")
        self._head("introduce a footgun alongside an abbreviated poison filename")

        self._use_checker(OLD_CHECKER)
        old = self._run(_old_run_step_script())
        self.assertEqual(old.returncode, 0, old.stdout + old.stderr)
        self.assertIn("NOT-APPLICABLE", old.stdout)

        self._use_checker(REAL_CHECKER)
        new = self._run(_run_step_script())
        self.assertEqual(new.returncode, 1, new.stdout + new.stderr)
        self.assertIn("bad.py", new.stdout)

    # -- every other option-shaped filename in the ATTACK SURFACE -------

    def _scan_one_option_shaped_file(self, name):
        self._write(name, "x = 1\n")
        self._base()
        self._write(name, FOOTGUN_LINE)
        self._head(f"add a footgun in a file named {name!r}")
        return self._run(_run_step_script())

    def test_dashdash_all_py_reaches_the_checker_as_a_path(self):
        proc = self._scan_one_option_shaped_file("--all.py")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("--all.py", proc.stdout)

    def test_single_dash_x_py_reaches_the_checker_as_a_path(self):
        proc = self._scan_one_option_shaped_file("-x.py")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("-x.py", proc.stdout)

    def test_dashdash_dot_py_reaches_the_checker_as_a_path(self):
        proc = self._scan_one_option_shaped_file("--.py")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("--.py", proc.stdout)

    # A file literally named `--` can never appear in FILES here: the
    # action's own git diff is already scoped to `-- '*.py'`, and `--` has
    # no .py suffix to match. That row of the ATTACK SURFACE is a property
    # of the checker's own argparse boundary handling, not of this
    # action's file-list construction — see
    # test_check_windows_footguns.py's SeparatorHandlingTests, which
    # exercises it directly against the real checker without git in the
    # way.


class FailClosedGitListingTests(unittest.TestCase):
    """F3: the step used to build FILES via `while read ... < <(git diff
    ...)` process substitution, which runs the git command in a subshell
    whose exit status `set -e` never observes — a failing `git diff` /
    `git ls-files` (not a git repository, a corrupted checkout, ...) was
    silently read as empty output, so FILES stayed empty and the step
    printed its own benign 'No Python files to scan.' and exited 0,
    indistinguishable from a genuinely empty diff."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        gh_workflows_root = self.tmp / "gh-workflows-checkout"
        self.action_path = gh_workflows_root / "actions" / "windows-footguns"
        self.action_path.mkdir(parents=True)
        stub_dir = gh_workflows_root / "scripts"
        stub_dir.mkdir(parents=True)
        stub = stub_dir / "check-windows-footguns.py"
        stub.write_text(STUB_CHECKER, encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        self.stub_log = self.tmp / "stub.log"
        # Deliberately NOT a git repository: `git merge-base` / `git diff` /
        # `git ls-files` must all fail here.
        self.non_git_dir = self.tmp / "not-a-repo"
        self.non_git_dir.mkdir()

    def _run(self, run_script):
        env = {
            "PATH": "/usr/bin:/bin",
            "BASE_REF": "main",
            "GITHUB_ACTION_PATH": str(self.action_path),
            "STUB_LOG": str(self.stub_log),
            "STUB_EXIT": "1",  # would fail loudly if ever invoked
        }
        return subprocess.run(
            ["bash", "-c", run_script], cwd=self.non_git_dir, env=env,
            capture_output=True, text=True, timeout=30,
        )

    def test_old_script_masks_a_failing_git_listing_as_not_applicable(self):
        proc = self._run(_old_run_step_script())
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("No Python files to scan.", proc.stdout)
        self.assertFalse(self.stub_log.exists())

    def test_fixed_script_fails_closed_on_a_failing_git_listing(self):
        proc = self._run(_run_step_script())
        self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("No Python files to scan.", proc.stdout)
        self.assertFalse(self.stub_log.exists(), "checker ran despite a failed git listing")


if __name__ == "__main__":
    unittest.main(verbosity=2)
