#!/usr/bin/env python3
"""Tests for scripts/rg-need-install.sh: the install-vs-skip decision behind
actions/content-scan's "Install ripgrep if missing" step.

A self-hosted runner's distro `rg` can be built without PCRE2 support, so a
caller with `pcre2: true` used to fail with "PCRE2 is not available in this
build of ripgrep" even though the step reported ripgrep as already
installed — the old inline logic in action.yml skipped installation whenever
*any* `rg` was on PATH, without checking PCRE2 support at all.

Stubs a fake `rg` on PATH (real ripgrep isn't necessarily available, and we
need to simulate a non-PCRE2 build, which this environment's rg may not be)
and runs the real script as a subprocess, rather than reimplementing its
logic in Python.
"""
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "rg-need-install.sh"
BASH = shutil.which("bash")

RG_WITH_PCRE2 = """#!/bin/bash
case "$1" in
  --version) echo "ripgrep 14.1.1 (rev fake)"; exit 0 ;;
  --pcre2-version) echo "PCRE2 10.42 is available (JIT is available)"; exit 0 ;;
  *) exit 2 ;;
esac
"""

RG_WITHOUT_PCRE2 = """#!/bin/bash
case "$1" in
  --version) echo "ripgrep 13.0.0 (rev fake)"; exit 0 ;;
  --pcre2-version) echo "PCRE2 is not available in this build of ripgrep" >&2; exit 1 ;;
  *) exit 2 ;;
esac
"""


class FakePath:
    """A throwaway PATH directory, optionally with a stubbed `rg` on it.

    When a stub is present, real /usr/bin:/bin are appended (after the fake
    dir, so the stub always shadows any real rg) so the script's own use of
    `head` and the stub's `#!/bin/bash` shebang still resolve. The no-stub
    case omits them entirely so a real system rg can never be found.
    """

    def __init__(self, rg_script=None):
        self.dir = Path(tempfile.mkdtemp())
        self.path = str(self.dir)
        if rg_script is not None:
            rg = self.dir / "rg"
            rg.write_text(rg_script)
            rg.chmod(rg.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
            self.path = f"{self.dir}:/usr/bin:/bin"

    def run(self, pcre2="false"):
        env = {"PATH": self.path, "PCRE2": pcre2}
        return subprocess.run(
            [BASH, str(SCRIPT)], env=env,
            capture_output=True, text=True, timeout=30,
        )

    def __enter__(self):
        return self

    def __exit__(self, *a):
        shutil.rmtree(self.dir, ignore_errors=True)


class TestNoRg(unittest.TestCase):
    def test_no_rg_on_path_needs_install_regardless_of_pcre2(self):
        with FakePath() as p:
            r = p.run(pcre2="false")
            self.assertEqual(r.returncode, 0)
            self.assertIn("installing the pinned build", r.stdout)

    def test_no_rg_on_path_needs_install_with_pcre2_requested(self):
        with FakePath() as p:
            r = p.run(pcre2="true")
            self.assertEqual(r.returncode, 0)


class TestRgWithoutPcre2(unittest.TestCase):
    def test_pcre2_not_requested_uses_existing_rg(self):
        # Today's behaviour: any rg on PATH is fine when pcre2 isn't asked for.
        with FakePath(RG_WITHOUT_PCRE2) as p:
            r = p.run(pcre2="false")
            self.assertEqual(r.returncode, 1)
            self.assertIn("using the existing rg", r.stdout)

    def test_pcre2_requested_but_unsupported_needs_install(self):
        # The bug: a distro rg without PCRE2, with pcre2: true. Must install.
        with FakePath(RG_WITHOUT_PCRE2) as p:
            r = p.run(pcre2="true")
            self.assertEqual(r.returncode, 0)
            self.assertIn("lacks it — installing the pinned build instead", r.stdout)


class TestRgWithPcre2(unittest.TestCase):
    def test_pcre2_requested_and_supported_uses_existing_rg(self):
        with FakePath(RG_WITH_PCRE2) as p:
            r = p.run(pcre2="true")
            self.assertEqual(r.returncode, 1)
            self.assertIn("available in the existing rg", r.stdout)

    def test_pcre2_not_requested_uses_existing_rg(self):
        with FakePath(RG_WITH_PCRE2) as p:
            r = p.run(pcre2="false")
            self.assertEqual(r.returncode, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
