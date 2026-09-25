#!/usr/bin/env python3
"""Converge repos onto the shared issue-label taxonomy in labels.yml.

Dry-run by default: without --apply it lists each repo's labels, prints what
it would create or update, and calls nothing that changes a repo.

Idempotent: a label whose color and description already match is left alone,
so a second --apply run makes no calls beyond the listing.

It never deletes or renames a label. Repo-specific labels (harness-improvement
on fleet-harness, daily-summary on ml-dev) are outside the taxonomy and stay.

Repos are arguments, not a list kept here: which repos exist is fleet
knowledge, not org-CI law.

Usage (from the repo root):
    python3 scripts/sync_labels.py OWNER/REPO [OWNER/REPO ...]           # plan
    python3 scripts/sync_labels.py --apply OWNER/REPO [OWNER/REPO ...]   # apply

Exit 0 when every repo converged (or would), 1 when any repo failed; a
failure on one repo does not stop the others.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LABELS_FILE = REPO_ROOT / "labels.yml"
GH_TIMEOUT_S = 60


class SyncError(Exception):
    pass


def load_taxonomy(path=LABELS_FILE):
    try:
        import yaml
    except ImportError:
        raise SyncError("PyYAML is required to read labels.yml (pip install pyyaml)") from None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    labels = data.get("labels") or []
    for lab in labels:
        if not lab.get("name") or not lab.get("description"):
            raise SyncError(f"labels.yml: every label needs a name and a description: {lab}")
        lab["color"] = str(lab.get("color", "")).lower().lstrip("#")
    return labels


def gh(*args):
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=GH_TIMEOUT_S)
    except FileNotFoundError:
        raise SyncError("gh is not installed or not on PATH") from None
    except subprocess.TimeoutExpired:
        raise SyncError(f"gh {args[0]} {args[1]} timed out") from None
    if r.returncode != 0:
        raise SyncError((r.stderr or r.stdout).strip()[:300] or f"gh exited {r.returncode}")
    return r.stdout


def current_labels(repo):
    out = gh("label", "list", "-R", repo, "--limit", "500", "--json", "name,color,description")
    return {lab["name"]: lab for lab in json.loads(out or "[]")}


def plan(taxonomy, existing):
    """(action, label) pairs: 'create' when absent, 'update' when color or
    description differ. Matching is exact on the name."""
    actions = []
    for lab in taxonomy:
        have = existing.get(lab["name"])
        if have is None:
            actions.append(("create", lab))
        elif (have.get("color", "").lower() != lab["color"]
              or (have.get("description") or "") != lab["description"]):
            actions.append(("update", lab))
    return actions


def sync_repo(repo, taxonomy, apply):
    actions = plan(taxonomy, current_labels(repo))
    if not actions:
        print(f"{repo}: up to date")
        return
    for action, lab in actions:
        verb = action if apply else f"would {action}"
        print(f"{repo}: {verb} {lab['name']}")
        if apply:
            # --force updates color/description of an existing label in
            # place. It never renames and never deletes.
            gh("label", "create", lab["name"], "--color", lab["color"],
               "--description", lab["description"], "--force", "-R", repo)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("repos", nargs="+", metavar="OWNER/REPO")
    p.add_argument("--apply", action="store_true",
                   help="make the changes (default: print the plan only)")
    args = p.parse_args(argv)
    try:
        taxonomy = load_taxonomy()
    except SyncError as e:
        print(f"sync_labels: {e}", file=sys.stderr)
        return 1
    failed = []
    for repo in args.repos:
        try:
            sync_repo(repo, taxonomy, args.apply)
        except SyncError as e:
            print(f"{repo}: FAILED: {e}", file=sys.stderr)
            failed.append(repo)
    if failed:
        print(f"sync_labels: {len(failed)} repo(s) failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
