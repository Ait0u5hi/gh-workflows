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


if __name__ == "__main__":
    unittest.main()
