#!/usr/bin/env python3
"""Converge repos onto the shared issue-label taxonomy in labels.yml.

Dry-run by default: without --apply it lists each repo's labels, prints what
it would create or update, and calls nothing that changes a repo.

Idempotent: a label whose color and description already match is left alone,
so a second --apply run makes no calls beyond the listing.

Label names are case-insensitive on GitHub, so existing labels are matched on
the casefolded name. When the only match differs in case ('Type:Bug' held,
'type:bug' in the taxonomy) the action is 'case-mismatch': it is printed (dry
run and --apply alike) and nothing is created, renamed or edited, because
'gh label create --force' would case-rename the existing label. Its color and
description are not synced either; fix the name by hand, then re-run. Two
existing labels differing only by case with no exact match are reported the
same way. An exact-case match behaves as before (update on drift).

It never deletes or renames a label. Repo-specific labels (harness-improvement
on one private consumer repo, daily-summary on another) are outside the taxonomy and stay.

Repos are arguments, not a list kept here: which repos exist is fleet
knowledge, not org-CI law.

Usage (from the repo root):
    python3 scripts/sync_labels.py OWNER/REPO [OWNER/REPO ...]           # plan
    python3 scripts/sync_labels.py --apply OWNER/REPO [OWNER/REPO ...]   # apply

Exit status (dry run and --apply alike — a dry run never calls the mutating
`gh label create`, it only plans and prints what --apply would do):
    0  every repo converged (or would): no gh failure, no case-mismatch.
    1  at least one repo's gh call failed (API/auth error, timeout, missing
       gh, a repo that does not exist, ...). A failure on one repo does not
       stop the others. This code wins even when a case-mismatch ALSO
       occurred in the same run: a scheduled --apply run must never read
       "exit 1" as "only a rename is pending" when a repo actually failed.
    3  no repo failed, but at least one label is a case-mismatch: every
       repo's gh calls succeeded, yet something is still not converged and
       needs a human to rename a label by hand before the next run. Exit 3
       is distinct from 0 so a scheduled run notices instead of silently
       exiting clean, and distinct from 1 so "needs a rename" and "gh is
       broken" are never confused by a caller checking $?. Either way a
       stderr footer reports the count: "N label(s) need a manual case
       rename".
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LABELS_FILE = REPO_ROOT / "labels.yml"
GH_TIMEOUT_S = 60

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CASE_MISMATCH = 3


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
    """(action, label, detail) triples. 'create' when no label matches even
    case-insensitively, 'update' when the exact-case match differs in color or
    description, 'case-mismatch' (detail = the existing name(s)) when the only
    matches differ in case. detail is '' for create/update."""
    folded = {}
    for name in existing:
        folded.setdefault(name.casefold(), []).append(name)
    actions = []
    for lab in taxonomy:
        have = existing.get(lab["name"])
        if have is None:
            near = folded.get(lab["name"].casefold())
            if near:
                actions.append(("case-mismatch", lab, ", ".join(sorted(near))))
            else:
                actions.append(("create", lab, ""))
        elif (have.get("color", "").lower() != lab["color"]
              or (have.get("description") or "") != lab["description"]):
            actions.append(("update", lab, ""))
    return actions


def sync_repo(repo, taxonomy, apply):
    """Sync one repo. Returns the number of case-mismatch labels found (0 if
    none converge-but-for-a-rename). Raises SyncError on a gh failure."""
    actions = plan(taxonomy, current_labels(repo))
    if not actions:
        print(f"{repo}: up to date")
        return 0
    case_mismatches = 0
    for action, lab, detail in actions:
        if action == "case-mismatch":
            case_mismatches += 1
            print(f"{repo}: case-mismatch {lab['name']} (repo has {detail}); "
                  "left untouched, rename by hand")
            continue
        verb = action if apply else f"would {action}"
        print(f"{repo}: {verb} {lab['name']}")
        if apply:
            # --force updates color/description of an existing label in
            # place. It never renames and never deletes.
            gh("label", "create", lab["name"], "--color", lab["color"],
               "--description", lab["description"], "--force", "-R", repo)
    return case_mismatches


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
        return EXIT_ERROR
    failed = []
    case_mismatch_total = 0
    for repo in args.repos:
        try:
            case_mismatch_total += sync_repo(repo, taxonomy, args.apply)
        except SyncError as e:
            print(f"{repo}: FAILED: {e}", file=sys.stderr)
            failed.append(repo)
    if case_mismatch_total:
        print(f"sync_labels: {case_mismatch_total} label(s) need a manual case rename",
              file=sys.stderr)
    if failed:
        print(f"sync_labels: {len(failed)} repo(s) failed: {', '.join(failed)}", file=sys.stderr)
        # Error wins: a gh failure must never be masked by the (lower-severity,
        # still-nonzero) case-mismatch code in the same run.
        return EXIT_ERROR
    if case_mismatch_total:
        return EXIT_CASE_MISMATCH
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
