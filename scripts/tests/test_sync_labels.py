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


if __name__ == "__main__":
    unittest.main()
