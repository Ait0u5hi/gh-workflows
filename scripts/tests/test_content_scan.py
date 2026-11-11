#!/usr/bin/env python3
"""Tests for scripts/content-scan.sh: the core logic behind the
reusable-content-scan workflow (actions/content-scan).

Runs the real script as a subprocess against a throwaway tree with a real
`rg` on PATH (this repo's CI already has ripgrep available), rather than
re-implementing its behavior in Python — the point is to catch drift between
the script and what the workflow actually invokes.

The PCRE2 tests need a ripgrep built with PCRE2, which some distro packages
are not. They use the rg named by the RG_BIN environment variable when it is
set, else the rg on the pinned test PATH, and skip with a reason naming
RG_BIN only when that rg fails `--pcre2-version`. A PCRE2-capable rg runs
every assertion unchanged, so a run that enforces this suite should supply
one and treat any skip as a failure.
"""
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "content-scan.sh"
REAL_RG = shutil.which("rg")
PINNED_PATH = "/usr/bin:/bin:/usr/local/bin"


def resolve_rg():
    """The rg the PCRE2 tests use: RG_BIN when set, else rg on PINNED_PATH."""
    rg_bin = os.environ.get("RG_BIN")
    if rg_bin:
        return shutil.which(rg_bin) or rg_bin
    return shutil.which("rg", path=PINNED_PATH)


def pcre2_rg_or_skip(test):
    """Return the resolved rg if it answers `--pcre2-version`, else skip the
    test with a reason naming RG_BIN (never a silent pass)."""
    rg = resolve_rg()
    ok = False
    if rg is not None:
        try:
            ok = subprocess.run([rg, "--pcre2-version"], capture_output=True,
                                timeout=10).returncode == 0
        except OSError:
            ok = False
    if not ok:
        found = f"{rg} fails --pcre2-version" if rg else f"no rg on {PINNED_PATH}"
        test.skipTest(f"no PCRE2-capable rg ({found}); "
                      "set RG_BIN to a ripgrep built with PCRE2 to run this test")
    return rg


class Tree:
    """A throwaway directory scanned by the script."""

    def __init__(self, **files):
        self.dir = Path(tempfile.mkdtemp())
        for name, content in files.items():
            p = self.dir / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)

    def run(self, patterns_file=".github/content-scan-patterns.txt", patterns_secret="",
             paths=".", redact="auto", pcre2="false", rg_bin=None, path=PINNED_PATH):
        env = {
            "PATTERNS_FILE": patterns_file,
            "PATTERNS_SECRET": patterns_secret,
            "SCAN_PATHS": paths,
            "REDACT": redact,
            "PCRE2": pcre2,
            "PATH": path,
            "HOME": str(self.dir),
        }
        if rg_bin is not None:
            env["RG_BIN"] = rg_bin
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

    def test_no_active_patterns_fails_closed(self):
        # A PR can comment out every pattern in the committed file; that must
        # not turn the gate green ("either source must resolve to at least
        # one pattern" is the documented contract).
        with Tree(**{
            ".github/content-scan-patterns.txt": "# only comments\n\n",
            "file.txt": "anything\n",
        }) as t:
            r = t.run()
            self.assertEqual(r.returncode, 1)
            self.assertIn("::error::", r.stdout)
            self.assertIn("no active patterns", r.stdout)


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

    def test_single_file_target_still_redacts(self):
        # ripgrep omits the filename when the scan target is a single file
        # (unlike a directory target), so a caller passing e.g. `paths:
        # README.md` used to leak the matched secret text into the output.
        with Tree(**{"leaky.txt": "the alpha secret is here\n"}) as t:
            r = t.run(patterns_file=".github/does-not-exist.txt",
                      patterns_secret="alpha\n", paths="leaky.txt")
            self.assertEqual(r.returncode, 1)
            self.assertNotIn("alpha", r.stdout)
            self.assertRegex(r.stdout, re.compile(r"^leaky\.txt:1$", re.MULTILINE))

    def test_colon_in_path_is_not_mistaken_for_a_field_separator(self):
        # A naive `path:line:match` split on the first colons breaks once the
        # path itself contains one (e.g. Windows drive-letter paths).
        with Tree(**{"sub/fi:le.txt": "the alpha secret is here\n"}) as t:
            r = t.run(patterns_file=".github/does-not-exist.txt",
                      patterns_secret="alpha\n")
            self.assertEqual(r.returncode, 1)
            self.assertNotIn("alpha", r.stdout)
            self.assertRegex(r.stdout, re.compile(r"^\./sub/fi:le\.txt:1$", re.MULTILINE))


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
                      patterns_secret=r"home/(?!dev|user|runner)", pcre2="false",
                      rg_bin=resolve_rg())
            self.assertNotEqual(r.returncode, 1, "expected an rg error, not a clean 'no match'")

    def test_lookaround_pattern_with_pcre2_matches_only_the_unguarded_path(self):
        rg = pcre2_rg_or_skip(self)
        with Tree(**{
            "guarded.txt": "home/dev/x\n",
            "unguarded.txt": "home/other/x\n",
        }) as t:
            r = t.run(patterns_file=".github/does-not-exist.txt",
                      patterns_secret=r"home/(?!dev|user|runner)", pcre2="true",
                      rg_bin=rg)
            self.assertEqual(r.returncode, 1)
            self.assertIn("./unguarded.txt", r.stdout)
            self.assertNotIn("./guarded.txt", r.stdout)


class TestRgBin(unittest.TestCase):
    """actions/content-scan hands the script an explicit RG_BIN (the exact
    binary the install step decided on) rather than relying solely on
    $GITHUB_PATH prepending correctly. These tests put a PCRE2-incapable
    stub `rg` first on PATH — mimicking a self-hosted runner's distro
    package — and check that RG_BIN, not PATH order, decides which binary
    actually runs the scan.
    """

    def setUp(self):
        if REAL_RG is None:
            self.skipTest("no real rg on PATH in this environment")
        self.stub_dir = Path(tempfile.mkdtemp())
        stub_rg = self.stub_dir / "rg"
        stub_rg.write_text(
            "#!/bin/bash\n"
            'case "$1" in\n'
            '  --version) echo "ripgrep 13.0.0 (rev fake)"; exit 0 ;;\n'
            '  --pcre2-version) echo "PCRE2 is not available in this build of ripgrep" >&2; exit 1 ;;\n'
            "  *) exit 2 ;;\n"
            "esac\n"
        )
        stub_rg.chmod(stub_rg.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        self.path = f"{self.stub_dir}:/usr/bin:/bin"

    def tearDown(self):
        shutil.rmtree(self.stub_dir, ignore_errors=True)

    def test_without_rg_bin_the_path_first_stub_is_used_and_pcre2_fails(self):
        with Tree(**{
            "guarded.txt": "home/dev/x\n",
            "unguarded.txt": "home/other/x\n",
        }) as t:
            r = t.run(patterns_file=".github/does-not-exist.txt",
                      patterns_secret=r"home/(?!dev|user|runner)", pcre2="true",
                      path=self.path)
            self.assertNotEqual(r.returncode, 1, "expected an rg error from the PCRE2-incapable stub")

    def test_rg_bin_overrides_path_order(self):
        rg = pcre2_rg_or_skip(self)
        with Tree(**{
            "guarded.txt": "home/dev/x\n",
            "unguarded.txt": "home/other/x\n",
        }) as t:
            r = t.run(patterns_file=".github/does-not-exist.txt",
                      patterns_secret=r"home/(?!dev|user|runner)", pcre2="true",
                      path=self.path, rg_bin=rg)
            self.assertEqual(r.returncode, 1)
            self.assertIn(f"Using rg: {rg}", r.stdout)
            self.assertIn("./unguarded.txt", r.stdout)
            self.assertNotIn("./guarded.txt", r.stdout)


class TestAdversarialTree(unittest.TestCase):
    """The scanned tree (and the committed patterns file) come from the PR,
    so they are attacker-controlled. None of these may turn the gate green
    or leak data into the (public) log."""

    def test_patterns_symlink_out_of_the_workspace_is_refused_and_not_printed(self):
        outside = Path(tempfile.mkdtemp())
        try:
            (outside / "credentials").write_text("TOPSECRET-RUNNER-TOKEN\n")
            with Tree(**{"file.txt": "anything\n"}) as t:
                (t.dir / ".github").mkdir()
                os.symlink(outside / "credentials", t.dir / ".github/content-scan-patterns.txt")
                r = t.run()
                self.assertEqual(r.returncode, 1)
                self.assertIn("resolves outside the workspace", r.stdout)
                self.assertNotIn("TOPSECRET-RUNNER-TOKEN", r.stdout + r.stderr)
        finally:
            shutil.rmtree(outside, ignore_errors=True)

    def test_patterns_symlink_inside_the_workspace_is_accepted(self):
        with Tree(**{"patterns/real.txt": "alpha\n", "leaky.txt": "alpha\n"}) as t:
            (t.dir / ".github").mkdir()
            os.symlink("../patterns/real.txt", t.dir / ".github/content-scan-patterns.txt")
            r = t.run()
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("1 active pattern(s)", r.stdout)
            self.assertIn("leaky.txt", r.stdout)

    def test_committed_patterns_are_counted_not_echoed(self):
        with Tree(**{
            ".github/content-scan-patterns.txt": "alpha-pattern\nbeta-pattern\n",
            "clean.txt": "nothing\n",
        }) as t:
            r = t.run()
            self.assertEqual(r.returncode, 0)
            self.assertIn("2 active pattern(s)", r.stdout)
            self.assertNotIn("alpha-pattern", r.stdout)

    def test_ignore_files_cannot_hide_a_match(self):
        for ignore_name in (".rgignore", ".ignore"):
            with self.subTest(ignore_name=ignore_name), Tree(**{
                ".github/content-scan-patterns.txt": "alpha\n",
                ignore_name: "*\n",
                "leaky.txt": "alpha\n",
            }) as t:
                r = t.run()
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_gitignored_tracked_file_is_still_scanned(self):
        with Tree(**{
            ".github/content-scan-patterns.txt": "alpha\n",
            ".gitignore": "leaky.txt\n",
            "leaky.txt": "alpha\n",
        }) as t:
            subprocess.run(["git", "init", "-q"], cwd=t.dir, check=True)
            r = t.run()
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_nul_byte_does_not_make_a_file_skippable(self):
        with Tree(**{".github/content-scan-patterns.txt": "alpha\n"}) as t:
            (t.dir / "leaky.bin").write_bytes(b"\x00\x00\nthe alpha secret\n")
            r = t.run()
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_nul_byte_in_patterns_file_does_not_drop_patterns(self):
        with Tree(**{"leaky.txt": "alpha\n"}) as t:
            (t.dir / ".github").mkdir()
            (t.dir / ".github/content-scan-patterns.txt").write_bytes(b"alpha\n\x00\n")
            r = t.run()
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_regex_error_in_redact_mode_does_not_leak_secret_patterns(self):
        with Tree(**{"file.txt": "anything\n"}) as t:
            r = t.run(patterns_file=".github/does-not-exist.txt",
                      patterns_secret="topsecret-internal-host\n(unbalanced\n")
            self.assertNotEqual(r.returncode, 0)
            self.assertNotIn("topsecret-internal-host", r.stdout + r.stderr)

    def test_option_shaped_filename_from_a_glob_is_not_an_rg_option(self):
        with Tree(**{
            ".github/content-scan-patterns.txt": "alpha\n",
            "--pre=bash": "",
            "payload.sh": "touch PWNED\n",
        }) as t:
            r = t.run(paths="*")
            self.assertFalse((t.dir / "PWNED").exists(), "rg ran a PR-named --pre command")
            # "--pre=bash" is scanned as a (empty) file, not consumed as an option.
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("content-scan clean", r.stdout)

    def test_match_output_is_bracketed_by_stop_commands(self):
        # A newline in a PR filename puts attacker text at the start of a log
        # line, where the runner would parse it as a workflow command.
        with Tree(**{".github/content-scan-patterns.txt": "alpha\n"}) as t:
            (t.dir / "a\n::warning::forged").write_text("alpha\n")
            r = t.run()
            self.assertEqual(r.returncode, 1)
            lines = r.stdout.splitlines()
            stop = [i for i, l in enumerate(lines) if l.startswith("::stop-commands::")]
            self.assertEqual(len(stop), 1, r.stdout)
            token = lines[stop[0]].split("::", 2)[2]
            self.assertGreaterEqual(len(token), 16)
            resume = lines.index(f"::{token}::")
            forged = lines.index(next(l for l in lines if l.startswith("::warning::forged")))
            self.assertLess(stop[0], forged)
            self.assertLess(forged, resume)

if __name__ == "__main__":
    unittest.main(verbosity=2)
