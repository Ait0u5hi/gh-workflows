#!/usr/bin/env python3
"""Tests for ci.yml's unit-tests job: an unsupported runner.arch must fail
the ripgrep-install step loudly, before any network call — never skip the
PCRE2 ripgrep tests silently.

Extracts the actual `run:` script of the "Install ripgrep (pinned +
SHA-256 verified)" step out of ci.yml (via PyYAML, never a flat grep of the
YAML) and executes it in a throwaway environment, with `curl` and `sudo`
stubbed to record that they were called and then fail loudly — so a guard
that doesn't trigger shows up as a test failure (a sentinel file), not a
real network download or `sudo install`, both off-limits for this test to
perform for real.

Only the FAILING (unsupported-arch) path is executed end-to-end. The happy
path (runner.arch == "X64") would reach the pinned `curl` download and
`sudo install` — this test checks that path structurally instead
(test_x64_is_the_only_arch_let_through), never by running it.
"""
from __future__ import annotations

import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
STEP_NAME = "Install ripgrep (pinned + SHA-256 verified)"

SENTINEL_STUB = """#!/usr/bin/env bash
echo "STUB-{name}-CALLED: $*" >> "$SENTINEL_LOG"
exit 17
"""


def _install_step_run() -> str:
    data = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    steps = data["jobs"]["unit-tests"]["steps"]
    for step in steps:
        if step.get("name") == STEP_NAME:
            return step["run"]
    raise AssertionError(f"ci.yml: '{STEP_NAME}' step not found")


class RgArchGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_script = _install_step_run()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.stub_dir = self.tmp / "stubs"
        self.stub_dir.mkdir()
        self.sentinel_log = self.tmp / "sentinel.log"
        # Stub out anything the un-guarded path would do for real: a
        # network download and a system-wide install, both forbidden here.
        for name in ("curl", "sudo", "tar", "sha256sum"):
            stub = self.stub_dir / name
            stub.write_text(SENTINEL_STUB.format(name=name.upper()), encoding="utf-8")
            stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    def _run(self, runner_arch):
        runner_temp = Path(tempfile.mkdtemp(dir=self.tmp))
        env = {
            "PATH": f"{self.stub_dir}:/usr/bin:/bin",
            "RUNNER_ARCH": runner_arch,
            "RUNNER_TEMP": str(runner_temp),
            "RG_VERSION": "14.1.1",
            "RG_SHA256_AMD64": "4cf9f2741e6c465ffdb7c26f38056a59e2a2544b51f7cc128ef28337eeae4d8e",
            "SENTINEL_LOG": str(self.sentinel_log),
        }
        return subprocess.run(
            ["bash", "-c", self.run_script], env=env,
            capture_output=True, text=True, timeout=30,
        )

    def _assert_nothing_was_called(self, arch):
        self.assertFalse(
            self.sentinel_log.exists(),
            f"curl/sudo/tar/sha256sum was invoked for runner.arch={arch!r} instead of "
            "the guard failing first: " +
            (self.sentinel_log.read_text() if self.sentinel_log.exists() else ""),
        )

    def test_unsupported_arches_fail_loudly_before_any_network_or_install(self):
        for arch in ("ARM64", "ARM", "X86", "bogus-arch"):
            with self.subTest(arch=arch):
                proc = self._run(arch)
                self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
                self.assertIn("::error::", proc.stderr)
                self.assertIn("X64", proc.stderr)
                self.assertIn(arch, proc.stderr)
                self._assert_nothing_was_called(arch)

    def test_empty_runner_arch_also_fails_loudly(self):
        proc = self._run("")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("::error::", proc.stderr)
        self._assert_nothing_was_called("")

    def test_x64_is_the_only_arch_let_through(self):
        # Structural check only — the X64 path reaches a real `curl`
        # download and `sudo install`, both off-limits for this test to
        # execute for real. Confirm the guard's comparison is exactly the
        # string "X64" (not e.g. a prefix/substring check that would also
        # accept "X64-ish" or be bypassable).
        self.assertIn('"$RUNNER_ARCH" != "X64"', self.run_script)
        self.assertIn("exit 1", self.run_script)


if __name__ == "__main__":
    unittest.main(verbosity=2)
