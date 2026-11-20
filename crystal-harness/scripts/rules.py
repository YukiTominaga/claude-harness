#!/usr/bin/env python3
"""Project rules: what this project's evaluator has learned to look for.

An evaluator starts every round knowing nothing about the rounds before it —
that is the point of a context reset — so a kind of defect it missed once it can
miss again. This script is the memory that survives the reset, kept as data and
applied by code:

- `record` appends every issue of a validated verdict to `.harness/issues.jsonl`.
  A verdict file is overwritten by the next round; this log is what remains.
- `candidates` reads that log and lists what has come back: an issue id seen in
  two or more rounds, or one source file blamed by two or more distinct issues.
  These are candidates for a rule, nothing more. A human decides.
- `add` validates a rule the human approved and appends it to
  `.harness/rules.json`. A rule has a trigger that can be read from a diff —
  path globs and/or keywords in added lines — and a concrete check.
- `match` reads a round's diff and writes the rules whose trigger it hits to
  `<round dir>/rules-to-check.json`, before the evaluator is spawned.
  `validate_verdict.py --rules` then requires the verdict to account for every
  one of them.

Triggers exist so the checklist does not grow into something nobody reads: a
round is asked only about the rules its own diff touches.

Usage:
    rules.py record .harness/final/02/verdict.json
    rules.py candidates [--json]
    rules.py add --file proposed-rule.json
    rules.py list
    rules.py match --base <commit> --out .harness/final/02/rules-to-check.json
"""

import argparse
import datetime
import fnmatch
import json
import os
import re
import subprocess
import sys

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
ISSUES = os.path.join(".harness", "issues.jsonl")
RULES = os.path.join(".harness", "rules.json")
RULE_ID = re.compile(r"^R-[0-9]+$")


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def git(project_dir, *args):
    proc = subprocess.run(["git", "-C", project_dir, *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def fail(message):
    print(f"rules: {message}", file=sys.stderr)
    return 1


# ---------------------------------------------------------------- record


def cmd_record(args):
    project_dir = os.path.abspath(args.project_dir)
    try:
        verdict = read_json(args.verdict)
    except Exception as exc:  # noqa: BLE001
        return fail(f"could not read {args.verdict}: {exc}")
    if not isinstance(verdict, dict) or not isinstance(verdict.get("blockingIssues"), list):
        return fail(f"{args.verdict} is not a verdict")
    try:
        commit = git(project_dir, "rev-parse", "HEAD").strip()
    except Exception:  # noqa: BLE001
        commit = None

    key = (verdict.get("phase"), verdict.get("sprint"), verdict.get("round"))
    path = os.path.join(project_dir, ISSUES)
    kept = []
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                # Recording the same round twice replaces it rather than doubling it.
                if (entry.get("phase"), entry.get("sprint"), entry.get("round")) != key:
                    kept.append(entry)

    added = []
    for blocking, list_key in ((True, "blockingIssues"), (False, "nonBlockingIssues")):
        for issue in verdict.get(list_key) or []:
            if not isinstance(issue, dict) or not isinstance(issue.get("id"), str):
                continue
            cause = issue.get("cause") if isinstance(issue.get("cause"), dict) else {}
            added.append({
                "ts": now_iso(),
                "phase": verdict.get("phase"),
                "sprint": verdict.get("sprint"),
                "round": verdict.get("round"),
                "commit": commit,
                "id": issue["id"],
                "blocking": blocking,
                "preExisting": issue.get("preExisting") is True,
                "dimension": issue.get("dimension"),
                "criterionId": issue.get("criterionId"),
                "summary": issue.get("summary"),
                "file": cause.get("file"),
                "mechanism": cause.get("mechanism"),
            })
    with open(path, "w", encoding="utf-8") as f:
        for entry in kept + added:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"recorded {len(added)} issue(s) for {key[0]} sprint {key[1]} round {key[2]}")
    return 0


# ---------------------------------------------------------------- candidates


def load_issues(project_dir):
    path = os.path.join(project_dir, ISSUES)
    entries = []
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                    entries.append(entry)
    return entries


def find_candidates(entries):
    def round_key(e):
        return (e.get("phase"), e.get("sprint"), e.get("round"))

    by_id, by_file = {}, {}
    for e in entries:
        by_id.setdefault(e["id"], []).append(e)
        if isinstance(e.get("file"), str) and e["file"]:
            by_file.setdefault(e["file"], []).append(e)

    candidates = []
    for issue_id, group in by_id.items():
        rounds = sorted({round_key(e) for e in group}, key=str)
        if len(rounds) >= 2:
            last = group[-1]
            candidates.append({
                "kind": "recurring-issue",
                "reason": f"{issue_id} appeared in {len(rounds)} rounds",
                "issues": [issue_id],
                "files": sorted({e["file"] for e in group if e.get("file")}),
                "summary": last.get("summary"),
                "mechanism": last.get("mechanism"),
            })
    for file, group in by_file.items():
        ids = sorted({e["id"] for e in group})
        if len(ids) >= 2:
            candidates.append({
                "kind": "repeat-offender-file",
                "reason": f"{len(ids)} distinct issues were traced to {file}",
                "issues": ids,
                "files": [file],
                "summary": "; ".join(sorted({str(e.get("summary")) for e in group}))[:600],
                "mechanism": "; ".join(sorted({str(e.get("mechanism")) for e in group}))[:600],
            })
    return candidates


def cmd_candidates(args):
    candidates = find_candidates(load_issues(os.path.abspath(args.project_dir)))
    if args.json:
        print(json.dumps(candidates, indent=2, ensure_ascii=False))
        return 0
    if not candidates:
        print("No candidates: nothing in .harness/issues.jsonl has come back yet.")
        return 0
    for i, c in enumerate(candidates, 1):
        print(f"{i}. [{c['kind']}] {c['reason']}")
        print(f"   issues: {', '.join(c['issues'])}   files: {', '.join(c['files']) or '—'}")
        print(f"   what happened: {c['summary']}")
        print(f"   why: {c['mechanism']}")
    return 0


# ---------------------------------------------------------------- rules file


def load_rules(project_dir):
    path = os.path.join(project_dir, RULES)
    if not os.path.isfile(path):
        return []
    data = read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        raise ValueError(f"{RULES} must be an object with a `rules` array")
    return data["rules"]


def validate_rule(rule):
    errors = []
    if not isinstance(rule, dict):
        return ["a rule must be a JSON object"]
    for key in ("title", "check"):
        if not isinstance(rule.get(key), str) or not rule[key].strip():
            errors.append(f"`{key}` must be a non-empty string")
    paths = rule.get("paths", [])
    keywords = rule.get("keywords", [])
    for key, value in (("paths", paths), ("keywords", keywords)):
        if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
            errors.append(f"`{key}` must be an array of non-empty strings")
    if isinstance(paths, list) and isinstance(keywords, list) and not paths and not keywords:
        errors.append(
            "a rule needs a trigger that can be read from a diff: at least one entry in `paths` "
            "(globs over changed files) or `keywords` (text in added lines). A rule that always "
            "applies is a line for the rubric, not a rule"
        )
    if isinstance(paths, list) and any(isinstance(p, str) and p.strip() in ("*", "**", "**/*") for p in paths):
        errors.append("`paths` must not match every file")
    origin = rule.get("origin", [])
    if not isinstance(origin, list) or any(not isinstance(x, str) for x in origin):
        errors.append("`origin` must be an array of issue ids")
    for key in rule:
        if key not in ("id", "title", "check", "paths", "keywords", "origin", "addedAt"):
            errors.append(f"unexpected key {key!r}")
    return errors


def cmd_add(args):
    project_dir = os.path.abspath(args.project_dir)
    try:
        proposed = read_json(args.file)
    except Exception as exc:  # noqa: BLE001
        return fail(f"could not read {args.file}: {exc}")
    proposed = proposed if isinstance(proposed, list) else [proposed]
    try:
        rules = load_rules(project_dir)
    except Exception as exc:  # noqa: BLE001
        return fail(str(exc))

    problems = []
    for i, rule in enumerate(proposed):
        problems += [f"rule {i + 1}: {e}" for e in validate_rule(rule)]
    if problems:
        for line in problems:
            print(f"invalid: {line}")
        return 1

    numbers = [int(r["id"][2:]) for r in rules if isinstance(r, dict) and RULE_ID.match(str(r.get("id")))]
    next_number = max(numbers, default=0) + 1
    for rule in proposed:
        entry = {
            "id": f"R-{next_number}",
            "title": rule["title"].strip(),
            "check": rule["check"].strip(),
            "paths": [p.strip() for p in rule.get("paths", [])],
            "keywords": [k.strip() for k in rule.get("keywords", [])],
            "origin": rule.get("origin", []),
            "addedAt": now_iso(),
        }
        rules.append(entry)
        print(f"added {entry['id']}: {entry['title']}")
        next_number += 1
    with open(os.path.join(project_dir, RULES), "w", encoding="utf-8") as f:
        json.dump({"rules": rules}, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return 0


def cmd_list(args):
    try:
        rules = load_rules(os.path.abspath(args.project_dir))
    except Exception as exc:  # noqa: BLE001
        return fail(str(exc))
    if not rules:
        print("No rules yet.")
        return 0
    for rule in rules:
        trigger = "; ".join(filter(None, [
            "paths " + ", ".join(rule.get("paths", [])) if rule.get("paths") else "",
            "keywords " + ", ".join(rule.get("keywords", [])) if rule.get("keywords") else "",
        ]))
        print(f"{rule.get('id')}: {rule.get('title')}\n   when: {trigger}\n   check: {rule.get('check')}")
    return 0


# ---------------------------------------------------------------- match


def path_matches(pattern, path):
    pattern = pattern.replace("\\", "/")
    if fnmatch.fnmatchcase(path, pattern):
        return True
    # `src/api/**` should also match files directly inside and below src/api/.
    if pattern.endswith("/**") and (path + "/").startswith(pattern[:-2]):
        return True
    return False


def cmd_match(args):
    project_dir = os.path.abspath(args.project_dir)
    try:
        rules = load_rules(project_dir)
        base = EMPTY_TREE if args.base is None else git(project_dir, "rev-parse", f"{args.base}^{{commit}}").strip()
        head = git(project_dir, "rev-parse", "HEAD").strip()
        # The harness's own files are not the product: a rule's keyword sitting in
        # .harness/rules.json must not trigger that rule the moment it is added.
        product = ["--", ".", ":(exclude).harness"]
        changed = [p for p in git(project_dir, "diff", "--name-only", "-z", base, "HEAD", *product).split("\0") if p]
        added_lines = []
        if any(rule.get("keywords") for rule in rules if isinstance(rule, dict)):
            for line in git(project_dir, "diff", "-U0", base, "HEAD", *product).splitlines():
                if line.startswith("+") and not line.startswith("+++"):
                    added_lines.append(line[1:].casefold())
    except Exception as exc:  # noqa: BLE001
        if args.out and os.path.exists(args.out):
            os.remove(args.out)  # never leave an earlier round's list to be read as this one's
        return fail(str(exc))

    matched = []
    for rule in rules:
        if not isinstance(rule, dict) or not RULE_ID.match(str(rule.get("id"))):
            continue
        hit_paths = sorted({p for p in changed for pattern in rule.get("paths", []) if path_matches(pattern, p)})
        hit_keywords = sorted({k for k in rule.get("keywords", []) if any(k.casefold() in line for line in added_lines)})
        if hit_paths or hit_keywords:
            matched.append({
                "id": rule["id"],
                "title": rule.get("title"),
                "check": rule.get("check"),
                "origin": rule.get("origin", []),
                "matchedPaths": hit_paths,
                "matchedKeywords": hit_keywords,
            })
    report = {"base": base, "head": head, "rulesTotal": len(rules), "rules": matched}
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
    sys.stdout.write(text)
    return 0


def main():
    parser = argparse.ArgumentParser(description="crystal-harness project rules")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("record")
    p.add_argument("verdict")
    p.add_argument("--project-dir", default=os.getcwd())
    p = sub.add_parser("candidates")
    p.add_argument("--json", action="store_true")
    p.add_argument("--project-dir", default=os.getcwd())
    p = sub.add_parser("add")
    p.add_argument("--file", required=True, help="a JSON rule, or an array of rules, approved by the human")
    p.add_argument("--project-dir", default=os.getcwd())
    p = sub.add_parser("list")
    p.add_argument("--project-dir", default=os.getcwd())
    p = sub.add_parser("match")
    p.add_argument("--base", default=None)
    p.add_argument("--out", default=None)
    p.add_argument("--project-dir", default=os.getcwd())
    args = parser.parse_args()
    commands = {"record": cmd_record, "candidates": cmd_candidates, "add": cmd_add, "list": cmd_list, "match": cmd_match}
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
