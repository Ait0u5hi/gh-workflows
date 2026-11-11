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

    Since v2 the governance gate reaches the composite action with
    `uses: $/actions/windows-footguns`, i.e. at the PR's own commit, so it
    runs THIS checker. The fixture is still kept out of scope by its file
    extension (see FixtureNotPythonTests) so no checker version, old or new,
    ever scans it."""

    REPO_ROOT = Path(__file__).resolve().parents[2]

    def test_real_checker_over_scripts_tests_passes_clean(self):
        proc = run_script(["scripts/tests"], self.REPO_ROOT)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("No Windows footguns found", proc.stdout)


class FixtureNotPythonTests(unittest.TestCase):
    """N1: keep vendored fixtures out of the checker's scope by construction.
    Every checker version (old and new alike) only looks at
    `*.py`/`*.pyw`/`*.pyi` files (see should_scan_file), so a fixture with any
    other extension is never scanned by any of them — including the
    pre-v2 releases whose governance gate ran a tagged checker rather than
    the PR's own. The vendored 709fabb fixture was renamed to
    check_windows_footguns_709fabb.py.txt for exactly this reason; this test
    fails loudly if a future vendored fixture is added back under a `.py`
    name."""

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
    """The `# windows-footgun: ok` marker covers the STATEMENT whose comment
    carries it (every row of a multi-line statement; see
    TokenizerMaskTests.test_marker_covers_a_multi_line_statement), never
    the file or a following block: a second, unmarked statement with the
    same footgun right after a suppressed one must still be flagged."""

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



# Footgun spellings are assembled at runtime (never adjacent in this file's
# own source) so SelfLintTests, which scans this file, stays clean.
KILLPG = "os." + "killpg(1, 2)"
DESKTOP = "~/" + "Desktop"


class TokenizerMaskTests(unittest.TestCase):
    """The scanner masks comments and docstrings with the tokenizer instead
    of a line-based triple-quote counter, which one stray `\"\"\"` in a
    comment or a string used to desynchronise for the rest of the file."""

    def scan(self, source: str, name: str = "mod.py") -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / name).write_text(source, encoding="utf-8", newline="")
            return run_script([name], root)

    def assertFlaggedAt(self, proc, line: int):
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn(f"mod.py:{line}:", proc.stdout)

    def test_triple_quote_inside_a_comment_does_not_hide_the_rest(self):
        self.assertFlaggedAt(self.scan(f'import os\n# """\n{KILLPG}\n'), 3)

    def test_triple_quote_inside_a_string_does_not_hide_the_rest(self):
        self.assertFlaggedAt(self.scan(f"import os\nQ = '\"\"\"'\n{KILLPG}\n"), 3)

    def test_code_after_a_closing_docstring_is_scanned(self):
        src = f'import os\nx = """doc\nmore"""; {KILLPG}\n'
        self.assertFlaggedAt(self.scan(src), 3)

    def test_docstring_prose_is_not_a_finding(self):
        proc = self.scan(f'def f():\n    """Never call {KILLPG} here."""\n')
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_api_name_inside_an_ordinary_string_is_not_a_finding(self):
        proc = self.scan(f'msg = "{KILLPG} is unsupported on Windows"\n')
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    @unittest.skipUnless(sys.version_info >= (3, 12), "PEP 701 f-string tokens")
    def test_code_inside_an_fstring_expression_is_scanned(self):
        self.assertFlaggedAt(self.scan('import os\nx = f"""a {' + KILLPG + '} b"""\n'), 2)

    def test_path_rules_still_match_inside_strings(self):
        self.assertFlaggedAt(self.scan(f'p = "{DESKTOP}/x.txt"\n'), 1)

    def test_guard_hint_inside_a_comment_does_not_excuse_the_line(self):
        self.assertFlaggedAt(self.scan(f"import os\n{KILLPG}  # unsafe if IS_WINDOWS\n"), 2)

    def test_marker_inside_a_string_does_not_suppress(self):
        self.assertFlaggedAt(self.scan(f'import os\nx = "# windows-footgun: ok"; {KILLPG}\n'), 2)

    def test_marker_covers_a_multi_line_statement(self):
        src = f"import os\nx = (\n    {KILLPG}\n)  # windows-footgun: ok\n"
        proc = self.scan(src)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("1 match(es) suppressed", proc.stderr)

    def test_line_numbers_ignore_form_feeds_and_unicode_separators(self):
        self.assertFlaggedAt(self.scan(f"import os\n\x0c\n{KILLPG}\n"), 3)
        self.assertFlaggedAt(self.scan(f'import os\ns = "a b"\n{KILLPG}\n'), 3)

    def test_bom_does_not_break_tokenizing(self):
        proc = self.scan(f"﻿import os\n{KILLPG}\n")
        self.assertFlaggedAt(proc, 2)
        self.assertNotIn("does not tokenize", proc.stderr)

    def test_open_with_encoding_on_a_continuation_line_is_not_flagged(self):
        src = "with OPEN(path, 'w',\n          encoding='utf-8') as f:\n    pass\n".replace("OPEN(", "open(")
        proc = self.scan(src)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_multi_line_open_without_encoding_is_still_flagged(self):
        src = "with OPEN(path,\n          'w') as f:\n    pass\n".replace("OPEN(", "open(")
        self.assertFlaggedAt(self.scan(src), 1)

    def test_untokenizable_file_falls_back_and_still_reports(self):
        proc = self.scan(f"import os\n{KILLPG}\nx = '''never closed\n")
        self.assertFlaggedAt(proc, 2)
        self.assertIn("does not tokenize", proc.stderr)


class PathHandlingTests(unittest.TestCase):
    def test_checkout_under_a_build_directory_is_still_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "build" / "repo"
            root.mkdir(parents=True)
            (root / "mod.py").write_text(f"import os\n{KILLPG}\n", encoding="utf-8")
            for args in (["mod.py"], ["."]):
                with self.subTest(args=args):
                    proc = run_script(args, root)
                    self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)

    def test_excluded_dir_inside_the_repo_is_still_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "build").mkdir()
            (root / "build" / "gen.py").write_text(f"import os\n{KILLPG}\n", encoding="utf-8")
            (root / "ok.py").write_text("x = 1\n", encoding="utf-8")
            proc = run_script(["."], root)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_symlink_is_judged_by_its_own_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "real.txt").write_text(f"import os\n{KILLPG}\n", encoding="utf-8")
            (root / "mod.py").symlink_to("real.txt")
            proc = run_script(["mod.py"], root)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)

    def test_unreadable_file_is_an_error_not_a_clean_scan(self):
        import importlib.util
        from unittest import mock

        spec = importlib.util.spec_from_file_location("cwf_under_test", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod  # dataclasses resolve their module here
        self.addCleanup(sys.modules.pop, spec.name, None)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "mod.py"
            target.write_text("x = 1\n", encoding="utf-8")
            with mock.patch.object(Path, "read_text", side_effect=PermissionError(13, "Permission denied")):
                rc = mod.main([str(target)])
            self.assertEqual(rc, 2)

class ReviewRegressionTests(unittest.TestCase):
    """Cases from the pre-merge review of the tokenizer rewrite."""

    scan = TokenizerMaskTests.scan
    assertFlaggedAt = TokenizerMaskTests.assertFlaggedAt

    def test_other_calls_encoding_or_kwargs_in_the_statement_do_not_excuse_open(self):
        for src in ("df = read_csv(\n    OPEN(path),\n    encoding='utf-8',\n)\n",
                    "call(\n    OPEN(path),\n    **opts,\n)\n",
                    "x = (OPEN(a, encoding='utf-8'),\n     OPEN(b))\n"):
            with self.subTest(src=src):
                self.assertFlaggedAt(self.scan(src.replace("OPEN(", "open(")), 2)

    def test_open_at_column_zero_of_a_continuation_row_is_judged_itself(self):
        src = "x = [\nOPEN(a),\n  OPEN(b, encoding='utf-8')]\n".replace("OPEN(", "open(")
        self.assertFlaggedAt(self.scan(src), 2)

    def test_fstring_field_code_is_scanned_on_every_python(self):
        self.assertFlaggedAt(self.scan("import os\nx = f'{" + KILLPG + "}'\n"), 2)

    def test_a_huge_single_statement_scans_in_linear_time(self):
        import time
        rows = "".join(f"    'k{i}': 'v{i}',\n" for i in range(30000))
        start = time.monotonic()
        proc = self.scan("D = {\n" + rows + "}\n")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertLess(time.monotonic() - start, 20, "statement handling went quadratic")

    def test_dangling_symlink_in_a_walked_dir_is_skipped_like_an_explicit_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ok.py").write_text("x = 1\n", encoding="utf-8")
            (root / "gone.py").symlink_to("missing.py")
            for args in (["."], ["gone.py", "ok.py"]):
                with self.subTest(args=args):
                    proc = run_script(args, root)
                    self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_diff_from_a_subdirectory_under_a_build_named_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "build" / "repo"
            (repo / "pkg").mkdir(parents=True)
            git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
            subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
            (repo / "pkg" / "base.py").write_text("x = 1\n", encoding="utf-8")
            subprocess.run([*git, "-C", str(repo), "add", "-A"], check=True)
            subprocess.run([*git, "-C", str(repo), "commit", "-qm", "base"], check=True)
            subprocess.run([*git, "-C", str(repo), "checkout", "-qb", "pr"], check=True)
            # The changed file is OUTSIDE the cwd (repo/pkg), so it can't be
            # made relative to the cwd: the exclusion must use the repo root.
            (repo / "lib").mkdir()
            (repo / "lib" / "mod.py").write_text(f"import os\n{KILLPG}\n", encoding="utf-8")
            subprocess.run([*git, "-C", str(repo), "add", "-A"], check=True)
            subprocess.run([*git, "-C", str(repo), "commit", "-qm", "pr"], check=True)
            # The checker resolves --diff paths against its own REPO_ROOT, so
            # run a copy of it from inside the repo.
            (repo / "scripts").mkdir()
            (repo / "scripts" / "check.py").write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
            proc = subprocess.run([sys.executable, str(repo / "scripts" / "check.py"), "--diff", "main"],
                                  cwd=repo / "pkg", capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            self.assertIn("mod.py:2:", proc.stdout)


if __name__ == "__main__":
    unittest.main()
