#!/usr/bin/env python3
"""Tests for scripts/content-scan.sh: the core logic behind the
reusable-content-scan workflow (actions/content-scan).

Runs the real script as a subprocess against a throwaway tree with a real
`rg` on PATH (this repo's CI already has ripgrep available), rather than
re-implementing its behavior in Python — the point is to catch drift between
the script and what the workflow actually invokes.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "content-scan.sh"


class Tree:
    """A throwaway directory scanned by the script."""

    def __init__(self, **files):
        self.dir = Path(tempfile.mkdtemp())
        for name, content in files.items():
            p = self.dir / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)

    def run(self, patterns_file=".github/content-scan-patterns.txt", patterns_secret="",
             paths=".", redact="auto", pcre2="false"):
        env = {
            "PATTERNS_FILE": patterns_file,
            "PATTERNS_SECRET": patterns_secret,
            "SCAN_PATHS": paths,
            "REDACT": redact,
            "PCRE2": pcre2,
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(self.dir),
        }
        return subprocess.run(
            ["bash", str(SCRIPT)], cwd=self.dir, env=env,
            capture_output=True, text=True, timeout=30,
        )

    def __enter__(self):
        return self

    def __exit__(self, *a):
        shutil.rmtree(self.dir, ignore_errors=True)


class TestFileOnly(unittest.TestCase):
    def test_match_fails_with_full_line(self):
        with Tree(**{
            ".github/content-scan-patterns.txt": "# comment\nalpha\n",
            "leaky.txt": "the alpha secret is here\n",
        }) as t:
            r = t.run()
            self.assertEqual(r.returncode, 1)
            self.assertIn("alpha secret is here", r.stdout)  # full line, not redacted

    def test_clean_passes(self):
        with Tree(**{
            ".github/content-scan-patterns.txt": "nowhere-to-be-found\n",
            "clean.txt": "nothing interesting\n",
        }) as t:
            r = t.run()
            self.assertEqual(r.returncode, 0)
            self.assertIn("content-scan clean", r.stdout)

    def test_no_active_patterns_is_a_clean_no_op(self):
        with Tree(**{
            ".github/content-scan-patterns.txt": "# only comments\n\n",
            "file.txt": "anything\n",
        }) as t:
            r = t.run()
            self.assertEqual(r.returncode, 0)


class TestSecretOnly(unittest.TestCase):
    def test_match_is_redacted_to_path_and_line(self):
        with Tree(**{"leaky.txt": "the alpha secret is here\n"}) as t:
            r = t.run(patterns_file=".github/does-not-exist.txt", patterns_secret="alpha\n")
            self.assertEqual(r.returncode, 1)
            self.assertNotIn("alpha secret is here", r.stdout)
            self.assertRegex(r.stdout, r"leaky\.txt:1\b")

    def test_secret_comments_and_blanks_are_stripped(self):
        with Tree(**{"leaky.txt": "alpha\n"}) as t:
            r = t.run(patterns_file=".github/does-not-exist.txt",
                      patterns_secret="# a comment\n\nalpha\n")
            self.assertEqual(r.returncode, 1)


class TestBoth(unittest.TestCase):
    def test_patterns_from_file_and_secret_both_apply(self):
        with Tree(**{
            ".github/content-scan-patterns.txt": "beta\n",
            "a.txt": "has alpha in it\n",
            "b.txt": "has beta in it\n",
            "c.txt": "has neither\n",
        }) as t:
            r = t.run(patterns_secret="alpha\n")
            self.assertEqual(r.returncode, 1)
            self.assertIn("a.txt", r.stdout)
            self.assertIn("b.txt", r.stdout)
            self.assertNotIn("c.txt", r.stdout)

    def test_redact_true_forces_redaction_even_with_only_file_matching(self):
        with Tree(**{
            ".github/content-scan-patterns.txt": "beta\n",
            "b.txt": "has beta in it\n",
        }) as t:
            r = t.run(patterns_secret="alpha\n", redact="true")
            self.assertEqual(r.returncode, 1)
            self.assertNotIn("has beta in it", r.stdout)
            self.assertRegex(r.stdout, r"b\.txt:1\b")


class TestNeither(unittest.TestCase):
    def test_missing_file_and_no_secret_errors(self):
        with Tree(**{"file.txt": "anything\n"}) as t:
            r = t.run(patterns_file=".github/does-not-exist.txt", patterns_secret="")
            self.assertEqual(r.returncode, 1)
            self.assertIn("::error::", r.stdout)
            self.assertIn("no patterns available", r.stdout)


class TestRedactNeverLeaksMatchedText(unittest.TestCase):
    def test_redacted_output_never_contains_the_secret_pattern_or_match(self):
        with Tree(**{"leaky.txt": "internal-codename-zephyr lives here\n"}) as t:
            r = t.run(patterns_file=".github/does-not-exist.txt",
                      patterns_secret="internal-codename-zephyr")
            self.assertEqual(r.returncode, 1)
            self.assertNotIn("internal-codename-zephyr", r.stdout)
            self.assertNotIn("internal-codename-zephyr", r.stderr)

    def test_redact_false_override_prints_full_line_even_with_secret(self):
        with Tree(**{"leaky.txt": "internal-codename-zephyr lives here\n"}) as t:
            r = t.run(patterns_file=".github/does-not-exist.txt",
                      patterns_secret="internal-codename-zephyr", redact="false")
            self.assertEqual(r.returncode, 1)
            self.assertIn("internal-codename-zephyr lives here", r.stdout)

    def test_bad_redact_value_errors(self):
        with Tree(**{".github/content-scan-patterns.txt": "x\n"}) as t:
            r = t.run(redact="sometimes")
            self.assertEqual(r.returncode, 1)
            self.assertIn("::error::", r.stdout)


class TestPcre2(unittest.TestCase):
    def test_lookaround_pattern_needs_pcre2_flag(self):
        with Tree(**{
            "guarded.txt": "home/dev/x\n",
            "unguarded.txt": "home/other/x\n",
        }) as t:
            # Without -P, ripgrep rejects the lookaround pattern outright.
            r = t.run(patterns_file=".github/does-not-exist.txt",
                      patterns_secret=r"home/(?!dev|user|runner)", pcre2="false")
            self.assertNotEqual(r.returncode, 1, "expected an rg error, not a clean 'no match'")

    def test_lookaround_pattern_with_pcre2_matches_only_the_unguarded_path(self):
        with Tree(**{
            "guarded.txt": "home/dev/x\n",
            "unguarded.txt": "home/other/x\n",
        }) as t:
            r = t.run(patterns_file=".github/does-not-exist.txt",
                      patterns_secret=r"home/(?!dev|user|runner)", pcre2="true")
            self.assertEqual(r.returncode, 1)
            self.assertIn("./unguarded.txt", r.stdout)
            self.assertNotIn("./guarded.txt", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
