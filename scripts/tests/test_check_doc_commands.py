#!/usr/bin/env python3
"""Tests for scripts/check-doc-commands.py.

Each case is a way a doc could carry an invalid command past the checker:
fence-parsing desync (a non-shell block before the bash block), fence
styles the old regex ignored, and flag spellings it didn't normalise.
"""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "check-doc-commands.py"
spec = importlib.util.spec_from_file_location("check_doc_commands", SCRIPT)
cdc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cdc)

BAD = "gh search prs --state all"


class TestExtract(unittest.TestCase):
    def test_non_shell_block_before_bash_block_does_not_hide_it(self):
        md = "```text\nhello\n```\n\n```bash\n" + BAD + "\n```\n"
        self.assertEqual(cdc.extract(md), [BAD])

    def test_fence_variants_are_all_read(self):
        for md in ("~~~bash\n" + BAD + "\n~~~\n",
                   "```Bash\n" + BAD + "\n```\n",
                   "```bash title=x\n" + BAD + "\n```\n",
                   "```bash\r\n" + BAD + "\r\n```\r\n",
                   "````bash\n" + BAD + "\n````\n",
                   "```\n" + BAD + "\n```\n"):
            with self.subTest(md=md):
                self.assertEqual(cdc.extract(md), [BAD])

    def test_fence_indented_inside_a_nested_list_is_read(self):
        md = "1. Step\n   - sub\n\n     ```bash\n     " + BAD + "\n     ```\n"
        self.assertEqual(cdc.extract(md), [BAD])

    def test_non_shell_blocks_are_ignored(self):
        self.assertEqual(cdc.extract("```yaml\nrun: " + BAD + "\n```\n"), [])

    def test_line_continuation_and_env_prefix(self):
        md = "```bash\nGH_HOST=x gh search prs \\\n  --state all\n```\n"
        self.assertEqual(len(cdc.extract(md)), 1)
        self.assertIsNotNone(cdc.validate(cdc.extract(md)[0]))


class TestValidate(unittest.TestCase):
    def test_flag_spellings_are_normalised(self):
        for cmd in (BAD, "gh search prs --state=all", "gh search prs -s all",
                    "gh search prs --state open --state all"):
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(cdc.validate(cmd))

    def test_valid_and_placeholder_values_pass(self):
        for cmd in ("gh search prs --state open", "gh pr list --state all",
                    "gh search prs --state <state>", "git log --oneline"):
            with self.subTest(cmd=cmd):
                self.assertIsNone(cdc.validate(cmd))


class TestMain(unittest.TestCase):
    def run_on(self, text):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
            fh.write(text)
        try:
            return subprocess.run([sys.executable, str(SCRIPT), fh.name],
                                  capture_output=True, text=True, timeout=30)
        finally:
            Path(fh.name).unlink()

    def test_desynced_doc_now_fails(self):
        r = self.run_on("```text\nx\n```\n\n```bash\n" + BAD + "\n```\n")
        self.assertEqual(r.returncode, 1, r.stdout)

    def test_no_commands_warns_but_passes(self):
        r = self.run_on("# Title\n\nNo commands here.\n")
        self.assertEqual(r.returncode, 0)
        self.assertIn("::warning::", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
