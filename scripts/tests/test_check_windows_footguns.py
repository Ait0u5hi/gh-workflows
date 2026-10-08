"""Tests for scripts/check-windows-footguns.py (pseudo-file open(), --all scope)."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "check-windows-footguns.py"
COUNT_RE = re.compile(r"\((\d+) file\(s\) scanned\)|across (\d+) file\(s\) scanned")


def run_script(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def scanned_count(proc: subprocess.CompletedProcess) -> int:
    m = COUNT_RE.search(proc.stdout + proc.stderr)
    assert m, proc.stdout + proc.stderr
    return int(m.group(1) or m.group(2))


class PseudoFileOpenTests(unittest.TestCase):
    def scan(self, source: str) -> subprocess.CompletedProcess:
        # Fixtures spell the call OPEN( so this file is not itself flagged.
        source = source.replace("OPEN(", "open(")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mod.py").write_text(source, encoding="utf-8")
            return run_script(["mod.py"], root)

    def test_proc_fstring_not_flagged(self):
        proc = self.scan('def f(pid):\n    return OPEN(f"/proc/{pid}/stat").read()\n')
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_proc_plain_string_not_flagged(self):
        proc = self.scan('x = OPEN("/proc/meminfo")\n')
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_sys_single_quoted_not_flagged(self):
        proc = self.scan("x = OPEN('/sys/class/net/eth0/address')\n")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_regular_file_still_flagged(self):
        proc = self.scan('x = OPEN("data.txt")\n')
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("open() without encoding=", proc.stdout)

    def test_other_absolute_path_still_flagged(self):
        proc = self.scan('x = OPEN("/etc/hosts")\n')
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)

    def test_proc_lookalike_still_flagged(self):
        proc = self.scan('x = OPEN("/procfile.txt")\n')
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)

    def test_variable_argument_still_flagged(self):
        proc = self.scan("x = OPEN(path)\n")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)

    def test_binary_mode_with_nested_call_path_not_flagged(self):
        for mode in ("ab", "rb", "wb"):
            proc = self.scan(f'x = OPEN(p.with_suffix(".lock"), "{mode}")\n')
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_binary_mode_keyword_not_flagged(self):
        proc = self.scan('x = OPEN(str(p), mode="rb")\n')
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_binary_mode_with_comma_in_nested_call_not_flagged(self):
        proc = self.scan('x = OPEN(os.path.join(a, b), "wb")\n')
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_text_mode_with_nested_call_path_still_flagged(self):
        proc = self.scan('x = OPEN(p.with_suffix(".x"))\n')
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        proc = self.scan('x = OPEN(p.with_suffix(".x"), "w")\n')
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)

    def test_nested_call_with_encoding_not_flagged(self):
        proc = self.scan('x = OPEN(p.with_suffix(".x"), "w", encoding="utf-8")\n')
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


class AllScopeTests(unittest.TestCase):
    def make_repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / "pkg" / "sub").mkdir(parents=True)
        (root / "app.py").write_text("x = 1\n", encoding="utf-8")
        (root / "pkg" / "a.py").write_text("y = 2\n", encoding="utf-8")
        (root / "pkg" / "sub" / "b.py").write_text("z = 3\n", encoding="utf-8")
        (root / "scripts").mkdir()
        (root / "scripts" / "s.py").write_text("w = 4\n", encoding="utf-8")

    def test_all_matches_dot_in_foreign_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_repo(root)
            all_proc = run_script(["--all"], root)
            dot_proc = run_script(["."], root)
            self.assertEqual(dot_proc.returncode, 0, dot_proc.stdout + dot_proc.stderr)
            self.assertEqual(scanned_count(dot_proc), 4)
            self.assertEqual(scanned_count(all_proc), scanned_count(dot_proc))

    def test_all_from_subdir_scans_git_toplevel(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_repo(root)
            proc = run_script(["--all"], root / "pkg" / "sub")
            self.assertEqual(scanned_count(proc), 4)

    def test_all_reports_findings_outside_fixed_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_repo(root)
            (root / "pkg" / "bad.py").write_text('x = open("d.txt")\n', encoding="utf-8")
            proc = run_script(["--all"], root)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            self.assertIn("bad.py:1:", proc.stdout)


class NotApplicableTests(unittest.TestCase):
    def test_no_python_files_prints_not_applicable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.js").write_text("x\n", encoding="utf-8")
            (root / "b.mjs").write_text("x\n", encoding="utf-8")
            (root / "c.sh").write_text("x\n", encoding="utf-8")
            proc = run_script(["a.js", "b.mjs", "c.sh"], root)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn(
                "NOT-APPLICABLE: 0 python file(s) in scope (3 skipped: .js, .mjs, .sh)",
                proc.stdout,
            )
            self.assertNotIn("No Windows footguns found", proc.stdout)

    def test_missing_path_counts_as_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = run_script(["gone.py"], Path(tmp))
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("NOT-APPLICABLE: 0 python file(s) in scope (1 skipped:", proc.stdout)

    def test_mixed_list_is_scanned_normally(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.js").write_text("x\n", encoding="utf-8")
            (root / "ok.py").write_text("x = 1\n", encoding="utf-8")
            proc = run_script(["a.js", "ok.py"], root)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertNotIn("NOT-APPLICABLE", proc.stdout)
            self.assertEqual(scanned_count(proc), 1)


class DiffRefTests(unittest.TestCase):
    """F4: --diff used to swallow an unresolvable ref the same way it
    swallows a resolvable ref with zero changed .py files — both reported
    NOT-APPLICABLE and exited 0. An unresolvable ref is a usage error
    (typo, renamed/unfetched base branch, ...) and must fail loudly;
    NOT-APPLICABLE stays reserved for a ref that resolves but genuinely
    has nothing to scan. These run against REPO_ROOT (this checkout) via
    `git rev-parse`/`git diff`, read-only — no network, no mutation."""

    REPO_ROOT = Path(__file__).resolve().parents[2]

    def test_unresolvable_diff_ref_fails_loudly(self):
        proc = run_script(["--diff", "no-such-ref-7f3c9-does-not-exist"], self.REPO_ROOT)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertNotIn("NOT-APPLICABLE", proc.stdout)
        self.assertIn("no-such-ref-7f3c9-does-not-exist", proc.stdout + proc.stderr)

    def test_resolvable_ref_with_no_py_changes_stays_not_applicable(self):
        """HEAD...HEAD is an empty diff — the ref resolves fine, there is
        just nothing changed. This must still be the documented
        NOT-APPLICABLE/exit-0 outcome, not the new error path."""
        proc = run_script(["--diff", "HEAD"], self.REPO_ROOT)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("NOT-APPLICABLE", proc.stdout)


class SelfLintTests(unittest.TestCase):
    """N1: scripts/tests/ (fixtures included) is the self-lint's own blind
    spot: a vendored pre-fix checker fixture is self-referential (it
    mentions the very patterns it detects), and the governance gate
    (.github/workflows/pr-governance.yml) runs this real checker over every
    changed file with no continue-on-error. Run the REAL checker over the
    real scripts/tests/ tree so a future fixture or test literal can never
    redden that gate silently again. This is the test the gate itself
    would run, not a hand-picked excerpt.

    Note this governance gate pins the composite action (and so the
    checker it runs) to a tagged release (see FixtureNotPythonTests
    below), not this repo's own HEAD. An EXCLUDED_FILES entry added here
    would never reach that pinned checker, so the fixture is kept out of
    scope by its file extension instead (see FixtureNotPythonTests);
    nothing in EXCLUDED_FILES needs to name it."""

    REPO_ROOT = Path(__file__).resolve().parents[2]

    def test_real_checker_over_scripts_tests_passes_clean(self):
        proc = run_script(["scripts/tests"], self.REPO_ROOT)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("No Windows footguns found", proc.stdout)


class FixtureNotPythonTests(unittest.TestCase):
    """N1: the governance gate (.github/workflows/pr-governance.yml ->
    reusable-crossplatform-lint.yml) runs the windows-footguns composite
    action at a pinned tag (e.g. @v1), which fetches the checker script
    AT THAT TAG, not this repo's HEAD. A fix to check-windows-footguns.py
    (an EXCLUDED_FILES entry, say) only reaches CI after the tag is
    re-cut, which is not this card's call to make. The only fix that
    works regardless of which tagged checker version runs is to keep the
    vendored 709fabb fixture out of scope by construction: every checker
    version (old and new alike) only looks at `*.py`/`*.pyw`/`*.pyi`
    files (see should_scan_file), so a fixture with any other extension
    is never scanned by any of them. The fixture was renamed to
    check_windows_footguns_709fabb.py.txt for exactly this reason; this
    test fails loudly if a future vendored fixture is ever added back
    under a `.py` name."""

    FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

    def test_fixtures_dir_has_no_python_file(self):
        python_files = sorted(
            p.name for p in self.FIXTURES_DIR.iterdir()
            if p.suffix in (".py", ".pyw", ".pyi")
        )
        self.assertEqual(
            python_files, [],
            "a *.py fixture here is scanned by every tagged checker "
            "version, including ones that predate any EXCLUDED_FILES "
            "fix in this repo's HEAD; rename it to a non-.py extension "
            "instead (the tests already read fixture content as text "
            "regardless of extension)",
        )


class SuppressionMarkerScopeTests(unittest.TestCase):
    """(b): confirm the existing `# windows-footgun: ok` marker's semantics
    before relying on it for N1. It is checked per LINE (SUPPRESS_MARKER
    is tested inside the per-line loop in scan_file), not per file and not
    for a following block. A second, unmarked line with the same footgun
    right after a suppressed one must still be flagged."""

    def test_marker_suppresses_only_its_own_line(self):
        # "os." and "killpg(" are concatenated at runtime, never adjacent
        # in this file's own source, so this test's source (itself scanned
        # by SelfLintTests above) is never a footgun match.
        call = "os." + "killpg("
        source = (
            f"import os\n"
            f"{call}1, 2)  # windows-footgun: ok\n"
            f"{call}3, 4)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "mod.py").write_text(source, encoding="utf-8")
            proc = run_script(["mod.py"], root)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            self.assertIn("mod.py:3:", proc.stdout)
            self.assertNotIn("mod.py:2:", proc.stdout)


class SeparatorHandlingTests(unittest.TestCase):
    """ATTACK SURFACE row for F2 (a file literally named '--'), exercised
    directly against the checker's own argparse — never through the
    action/git, since a bare '--' has no .py suffix and can never survive
    the action's `-- '*.py'` pathspec to reach FILES in the first place."""

    def test_literal_dashdash_survives_as_a_path_after_the_boundary(self):
        """The composite action always sends its own `--` ahead of the
        file list (see actions/windows-footguns/action.yml). argparse
        treats only the FIRST `--` it sees as the options/positionals
        boundary, so a second, literal `--` token — standing in for a
        changed file that happens to be named exactly that — survives as
        an ordinary positional path. It has no .py suffix, so it's
        correctly counted as skipped (not silently eaten as a second
        separator, and not a crash)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "--").write_text("not python\n", encoding="utf-8")
            proc = run_script(["--", "--"], root)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn(
                "NOT-APPLICABLE: 0 python file(s) in scope (1 skipped: (no extension))",
                proc.stdout,
            )

    def test_bare_dashdash_alone_is_ordinary_separator_syntax_not_a_bypass(self):
        """A single `--` with nothing after it is just argparse's normal
        'end of options, zero positionals follow' — it falls through to
        the same default (staged-changes) behaviour as no arguments at
        all. This is not the F2 bypass (nothing is hidden: there was
        nothing to hide), it just documents the boundary."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = run_script(["--"], Path(tmp))
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("No staged files to scan", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
