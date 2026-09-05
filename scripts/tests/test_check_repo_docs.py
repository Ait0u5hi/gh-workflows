#!/usr/bin/env python3
"""Tests for check-repo-docs.py.

Every assertion must be able to FAIL for the reason it names. In particular the malformed-file
cases exist because a presence check that passes on a truncated or degenerate read is worse than
no check at all - it reports green while seeing almost nothing.
"""
import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "crd", Path(__file__).resolve().parents[1] / "check-repo-docs.py"
)
crd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(crd)

GOOD_LINK = (
    "See https://github.com/Ait0u5hi/gh-workflows/blob/main/docs/CONTRIBUTION-STANDARD.md for the rules."
)


class Repo:
    """A throwaway repo tree."""

    def __init__(self, **files):
        self.dir = Path(tempfile.mkdtemp())
        base = {
            "CONTRIBUTING.md": GOOD_LINK,
            "CODE_OF_CONDUCT.md": "Contributor Covenant",
            "SECURITY.md": "Report privately",
            "LICENSE": "MIT",
            ".github/PULL_REQUEST_TEMPLATE.md": "## What",
        }
        base.update(files)
        for name, content in base.items():
            if content is None:  # explicit "this file does not exist"
                continue
            p = self.dir / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)

    def check(self, skip=frozenset(), require_link=True):
        return crd.check(self.dir, set(skip), require_link)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        shutil.rmtree(self.dir, ignore_errors=True)


class TestComplete(unittest.TestCase):
    def test_complete_repo_passes(self):
        with Repo() as r:
            self.assertEqual(r.check(), [])


class TestMissing(unittest.TestCase):
    def test_each_required_file_is_actually_required(self):
        # Parameterised so a file silently dropped from REQUIRED makes this fail.
        for name in crd.REQUIRED:
            with self.subTest(name=name), Repo(**{name: None}) as r:
                fails = r.check()
                self.assertTrue(fails, f"removing {name} produced no failure")
                self.assertTrue(any(name in f for f in fails), f"failure did not name {name}")

    def test_missing_two_files_reports_both(self):
        with Repo(**{"SECURITY.md": None, "CODE_OF_CONDUCT.md": None}) as r:
            fails = r.check()
            self.assertEqual(len(fails), 2)
            self.assertTrue(any("SECURITY.md" in f for f in fails))
            self.assertTrue(any("CODE_OF_CONDUCT.md" in f for f in fails))


class TestDegenerateFiles(unittest.TestCase):
    """A file that exists but says nothing must not satisfy the gate."""

    def test_empty_file_fails(self):
        with Repo(**{"SECURITY.md": ""}) as r:
            fails = r.check()
            self.assertTrue(any("SECURITY.md" in f and "empty" in f for f in fails))

    def test_truncated_contributing_fails_on_the_link(self):
        # The trap: a stub that looks plausible but never links the standard. If this passed,
        # a repo could satisfy the gate while sharing none of the rules.
        with Repo(**{"CONTRIBUTING.md": "# Contributing\n\nBe nice.\n"}) as r:
            fails = r.check()
            self.assertTrue(any("does not link the shared standard" in f for f in fails))

    def test_link_found_even_after_an_indented_bolded_bullet(self):
        # Regression for the field-truncation class of bug: a parser that stops at
        # `^\s*[-*+]\s*\*\*` would never reach the link on the last line and would report a
        # false failure. Reading the whole file is what makes this pass.
        body = "# Contributing\n\n  - **Note:** something bolded and indented\n\n" + GOOD_LINK + "\n"
        with Repo(**{"CONTRIBUTING.md": body}) as r:
            self.assertEqual(r.check(), [])

    def test_link_found_when_it_is_the_very_last_byte(self):
        with Repo(**{"CONTRIBUTING.md": GOOD_LINK}) as r:  # no trailing newline
            self.assertEqual(r.check(), [])


class TestOptions(unittest.TestCase):
    def test_skip_waives_a_required_file(self):
        with Repo(**{"SECURITY.md": None}) as r:
            self.assertTrue(r.check())                       # fails by default
            self.assertEqual(r.check(skip={"SECURITY.md"}), [])  # waived

    def test_no_require_link_relaxes_only_the_link(self):
        with Repo(**{"CONTRIBUTING.md": "# Contributing\n"}) as r:
            self.assertTrue(r.check())
            self.assertEqual(r.check(require_link=False), [])

    def test_no_require_link_still_requires_the_file(self):
        with Repo(**{"CONTRIBUTING.md": None}) as r:
            self.assertTrue(r.check(require_link=False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
