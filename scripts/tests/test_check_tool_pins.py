#!/usr/bin/env python3
"""Tests for scripts/check-tool-pins.py, with the upstream lookups stubbed
(no network): pins are found in a throwaway tree and compared."""
import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "check-tool-pins.py"
spec = importlib.util.spec_from_file_location("check_tool_pins", SCRIPT)
ctp = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ctp
spec.loader.exec_module(ctp)

WORKFLOW = """\
jobs:
  x:
    steps:
      - env:
          RG_VERSION: "15.2.0"
          LYCHEE_VERSION: v0.24.2
          # ACTIONLINT_VERSION: 0.0.1   (comment, ignored)
        run: |
          pip install --quiet pytest==9.2.0 pytest-cov==7.1.0 $EXTRA
"""


class FindPins(unittest.TestCase):
    def test_finds_env_and_pip_pins_and_skips_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".github/workflows").mkdir(parents=True)
            (root / ".github/workflows/a.yml").write_text(WORKFLOW)
            pins = {(k, n, v) for k, n, v, _ in ctp.find_pins(root)}
            self.assertEqual(pins, {
                ("github", "RG_VERSION", "15.2.0"),
                ("github", "LYCHEE_VERSION", "0.24.2"),
                ("pypi", "pytest", "9.2.0"),
                ("pypi", "pytest-cov", "7.1.0"),
            })


class PickPypi(unittest.TestCase):
    def test_skips_releases_younger_than_the_cooldown_and_yanked_ones(self):
        from datetime import datetime, timezone
        now = datetime(2026, 11, 11, tzinfo=timezone.utc)
        f = lambda day, yanked=False: [{"upload_time_iso_8601": f"2026-11-{day:02d}T00:00:00.000000Z",
                                        "yanked": yanked}]
        data = {"releases": {"1.9.0": f(1), "1.10.0": f(2), "1.11.0": f(3, yanked=True),
                             "2.0.0": f(10), "2.0.0rc1": f(1)}}
        self.assertEqual(ctp.pick_pypi(data, now=now), "1.10.0")


class Main(unittest.TestCase):
    def run_main(self, pins, gh=None, pypi=None):
        out = io.StringIO()
        with mock.patch.object(ctp, "find_pins", return_value=pins), \
             mock.patch.object(ctp, "latest_github", side_effect=gh or (lambda r, p: "1.0.0")), \
             mock.patch.object(ctp, "latest_pypi", side_effect=pypi or (lambda p: "1.0.0")), \
             redirect_stdout(out):
            return ctp.main([]), out.getvalue()

    def test_current_pins_pass(self):
        rc, out = self.run_main([("github", "RG_VERSION", "1.0.0", "f:1"), ("pypi", "x", "1.0.0", "f:2")])
        self.assertEqual(rc, 0, out)

    def test_behind_pin_fails_and_is_named(self):
        rc, out = self.run_main([("github", "RG_VERSION", "1.0.0", "f:1")], gh=lambda r, p: "1.10.0")
        self.assertEqual(rc, 1)
        self.assertIn("BEHIND", out)
        self.assertIn("-> 1.10.0", out)  # numeric, not string, comparison

    def test_lookup_error_is_never_reported_as_current(self):
        def boom(_):
            raise OSError("network down")
        rc, out = self.run_main([("pypi", "x", "1.0.0", "f:1")], pypi=boom)
        self.assertEqual(rc, 2)
        self.assertIn("lookup failed", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
