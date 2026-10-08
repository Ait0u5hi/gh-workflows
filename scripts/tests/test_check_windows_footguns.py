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
