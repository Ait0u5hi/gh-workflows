#!/usr/bin/env python3
"""Tests for sync_labels.py.

The only gh these tests reach is a fake on PATH that logs its argv and serves
`label list` from a per-repo JSON file, so no repo is ever touched. The
assertions that matter are on the log: a dry run must make no mutating call,
and no run may ever delete or rename a label.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "sync_labels", Path(__file__).resolve().parents[1] / "sync_labels.py"
)
sl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sl)

EXPECTED = {"type:bug", "type:friction", "type:gap", "type:debt", "type:flaky",
            "source:agent", "source:human", "status:carded"}

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as f:
    f.write(json.dumps(args) + "\n")
repo = args[args.index("-R") + 1] if "-R" in args else ""
state = os.path.join(os.environ["FAKE_GH_DIR"], repo.replace("/", "__") + ".json")
if repo.endswith("/broken"):
    print("HTTP 404: Not Found", file=sys.stderr); sys.exit(1)
if args[:2] == ["label", "list"]:
    print(open(state).read() if os.path.exists(state) else "[]"); sys.exit(0)
if args[:2] == ["label", "create"]:
    sys.exit(0)
print("unexpected: " + " ".join(args), file=sys.stderr); sys.exit(1)
'''


class FakeGh:
    def __init__(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "gh").write_text(FAKE_GH, encoding="utf-8")
        (self.dir / "gh").chmod(0o755)
        self.log = self.dir / "gh.log"
        self._env = {k: os.environ.get(k) for k in ("PATH", "FAKE_GH_LOG", "FAKE_GH_DIR")}
        os.environ["PATH"] = f"{self.dir}:{os.environ['PATH']}"
        os.environ["FAKE_GH_LOG"] = str(self.log)
        os.environ["FAKE_GH_DIR"] = str(self.dir)

    def holds(self, repo, labels):
        (self.dir / (repo.replace("/", "__") + ".json")).write_text(json.dumps(labels))

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def close(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.dir, ignore_errors=True)


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = sl.main(argv)
    return rc, out.getvalue(), err.getvalue()


class SyncLabels(unittest.TestCase):
    def setUp(self):
        self.gh = FakeGh()

    def tearDown(self):
        calls = self.gh.calls()
        # Across every test: never delete, never rename.
        for c in calls:
            self.assertNotIn(c[:2], (["label", "delete"], ["label", "edit"]), c)
        self.gh.close()

    def test_taxonomy_file(self):
        labels = sl.load_taxonomy()
        self.assertEqual({lab["name"] for lab in labels}, EXPECTED)
        for lab in labels:
            self.assertRegex(lab["color"], r"^[0-9a-f]{6}$", lab)
            self.assertTrue(lab["description"].strip(), lab)

    def test_dry_run_makes_no_mutating_call(self):
        rc, out, _ = run(["EXAMPLE-owner/a"])
        self.assertEqual(rc, 0)
        self.assertEqual({tuple(c[:2]) for c in self.gh.calls()}, {("label", "list")})
        self.assertEqual(out.count("would create"), len(EXPECTED), out)

    def test_apply_creates_every_missing_label(self):
        rc, _, _ = run(["--apply", "EXAMPLE-owner/a"])
        self.assertEqual(rc, 0)
        creates = [c for c in self.gh.calls() if c[:2] == ["label", "create"]]
        self.assertEqual({c[2] for c in creates}, EXPECTED)
        for c in creates:
            for flag in ("--color", "--description", "--force", "-R"):
                self.assertIn(flag, c)
            self.assertEqual(c[c.index("-R") + 1], "EXAMPLE-owner/a")

    def test_second_run_is_a_no_op(self):
        converged = [{"name": lab["name"], "color": lab["color"].upper(),
                      "description": lab["description"]} for lab in sl.load_taxonomy()]
        converged.append({"name": "harness-improvement", "color": "1D76DB",
                          "description": "repo-specific, must survive"})
        self.gh.holds("EXAMPLE-owner/a", converged)
        rc, out, _ = run(["--apply", "EXAMPLE-owner/a"])
        self.assertEqual(rc, 0)
        self.assertEqual([c for c in self.gh.calls() if c[:2] != ["label", "list"]], [])
        self.assertIn("up to date", out)

    def test_changed_description_is_updated_only(self):
        tax = sl.load_taxonomy()
        held = [{"name": lab["name"], "color": lab["color"], "description": lab["description"]}
                for lab in tax]
        held[0] = dict(held[0], description="old wording")
        self.gh.holds("EXAMPLE-owner/a", held)
        rc, _, _ = run(["--apply", "EXAMPLE-owner/a"])
        self.assertEqual(rc, 0)
        creates = [c[2] for c in self.gh.calls() if c[:2] == ["label", "create"]]
        self.assertEqual(creates, [tax[0]["name"]])

    def test_one_failing_repo_does_not_stop_the_rest(self):
        rc, _, err = run(["--apply", "EXAMPLE-owner/broken", "EXAMPLE-owner/b"])
        self.assertEqual(rc, 1)
        self.assertIn("EXAMPLE-owner/broken: FAILED", err)
        b_creates = [c for c in self.gh.calls()
                     if c[:2] == ["label", "create"] and "EXAMPLE-owner/b" in c]
        self.assertEqual(len(b_creates), len(EXPECTED))

    def _held_all_but(self, skip):
        return [{"name": lab["name"], "color": lab["color"], "description": lab["description"]}
                for lab in sl.load_taxonomy() if lab["name"] != skip]

    def _mutations(self):
        return [c for c in self.gh.calls() if c[:2] != ["label", "list"]]

    def test_case_only_difference_is_reported_not_created(self):
        tax = {lab["name"]: lab for lab in sl.load_taxonomy()}
        held = self._held_all_but("type:bug")
        # Different color AND description: still must not be touched.
        held.append({"name": "Type:Bug", "color": "000000", "description": "old"})
        self.gh.holds("EXAMPLE-owner/a", held)
        for argv in (["EXAMPLE-owner/a"], ["--apply", "EXAMPLE-owner/a"]):
            with self.subTest(argv=argv):
                rc, out, err = run(argv)
                # A case-mismatch is NOT full convergence: a scheduled
                # --apply run must see a distinct nonzero code, not 0, or it
                # silently never notices the pending rename (follow-up from
                # the PR #50/#51 review: exit 0 hid this).
                # Pin the literal contract value, not the module constant:
                # a test that only mirrors sl.EXIT_CASE_MISMATCH back at
                # itself can't catch a regression in the constant, and
                # against a checkout that predates it, assertEqual would
                # raise AttributeError instead of failing as a normal
                # assertion.
                self.assertEqual(rc, 3)
                self.assertIn("case-mismatch", out)
                self.assertIn("Type:Bug", out)
                self.assertIn("type:bug", out)
                self.assertIn("1 label(s) need a manual case rename", err)
                self.assertEqual(self._mutations(), [])
        self.assertIn("type:bug", tax)

    def test_case_mismatch_alone_is_a_distinct_code_from_error(self):
        """The case-mismatch code must not collide with the gh-failure code
        (1) or success (0) — a caller checking $? needs to tell the three
        apart without parsing output."""
        self.assertNotEqual(sl.EXIT_CASE_MISMATCH, sl.EXIT_OK)
        self.assertNotEqual(sl.EXIT_CASE_MISMATCH, sl.EXIT_ERROR)

    def test_exact_case_match_still_wins_and_updates(self):
        held = self._held_all_but("type:bug")
        held.append({"name": "type:bug", "color": "000000", "description": "old"})
        self.gh.holds("EXAMPLE-owner/a", held)
        rc, out, _ = run(["--apply", "EXAMPLE-owner/a"])
        self.assertEqual(rc, 0)
        self.assertNotIn("case-mismatch", out)
        self.assertEqual([c[2] for c in self._mutations()], ["type:bug"])

    def test_two_existing_labels_differing_only_by_case_are_reported(self):
        held = self._held_all_but("type:bug")
        held += [{"name": "Type:Bug", "color": "ffffff", "description": "x"},
                 {"name": "TYPE:BUG", "color": "ffffff", "description": "y"}]
        self.gh.holds("EXAMPLE-owner/a", held)
        rc, out, err = run(["--apply", "EXAMPLE-owner/a"])
        self.assertEqual(rc, sl.EXIT_CASE_MISMATCH)
        self.assertIn("case-mismatch", out)
        self.assertIn("Type:Bug", out)
        self.assertIn("TYPE:BUG", out)
        self.assertIn("1 label(s) need a manual case rename", err)
        self.assertEqual(self._mutations(), [])

    def test_error_wins_over_case_mismatch_in_the_same_run(self):
        """The ATTACK SURFACE case: one repo fails (gh/API error) while
        another repo in the SAME run only has a case-mismatch. The run must
        exit with the ERROR code, never the case-mismatch code — a scheduled
        --apply run checking $? == EXIT_CASE_MISMATCH to mean 'just a rename
        pending' must not be fooled into ignoring a real failure."""
        held = self._held_all_but("type:bug")
        held.append({"name": "Type:Bug", "color": "ffffff", "description": "x"})
        self.gh.holds("EXAMPLE-owner/a", held)
        rc, _, err = run(["--apply", "EXAMPLE-owner/broken", "EXAMPLE-owner/a"])
        self.assertEqual(rc, sl.EXIT_ERROR)
        self.assertNotEqual(rc, sl.EXIT_CASE_MISMATCH)
        self.assertIn("EXAMPLE-owner/broken: FAILED", err)
        # Both conditions are still reported, even though the error wins the
        # exit code — a human reading stderr sees the full picture.
        self.assertIn("1 label(s) need a manual case rename", err)
        self.assertEqual(self._mutations(), [])

    def test_exact_among_case_duplicates_is_used(self):
        held = self._held_all_but("type:bug")
        held += [{"name": "Type:Bug", "color": "ffffff", "description": "x"},
                 {"name": "type:bug", "color": "ffffff", "description": "y"}]
        self.gh.holds("EXAMPLE-owner/a", held)
        rc, out, _ = run(["--apply", "EXAMPLE-owner/a"])
        self.assertEqual([c[2] for c in self._mutations()], ["type:bug"])
        self.assertNotIn("case-mismatch", out)

    def test_help_documents_case_mismatch(self):
        self.assertIn("case-mismatch", sl.__doc__)

    def test_docstring_documents_the_exit_codes(self):
        doc = sl.__doc__
        self.assertIn("0  every repo converged", doc)
        self.assertIn("1  at least one repo's gh call failed", doc)
        self.assertIn("3  no repo failed, but at least one label is a case-mismatch", doc)
        # The "error wins" rule must be spelled out, not just implemented.
        self.assertIn("wins even when a case-mismatch", doc)

    def test_readme_documents_the_exit_codes(self):
        """Keep README and the docstring from drifting apart the way a pin's
        SHA and its `# vX.Y.Z` comment once did (see test_action_pins.py)."""
        readme = (Path(__file__).resolve().parents[2] / "README.md").read_text(encoding="utf-8")
        self.assertIn("sync_labels.py", readme)
        self.assertIn("case-mismatch", readme.lower())
        self.assertIn("exit 3", readme.lower())
        self.assertIn("manual case rename", readme.lower())


if __name__ == "__main__":
    unittest.main()
