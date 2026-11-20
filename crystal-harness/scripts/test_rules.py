#!/usr/bin/env python3
"""Regression tests for scripts/rules.py.

Project rules are how a defect the evaluator missed once stops being missable.
That only works if the plumbing is exact: an issue log that doubles or drops
rounds proposes the wrong rules, and a matcher that fails to trigger a rule
means the evaluator is never asked the question the rule exists to ask — with
nothing to show that it was skipped.

No framework — run it directly:

    python3 crystal-harness/scripts/test_rules.py

Exits 0 when every case passes, 1 otherwise.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules.py")

FAILURES = []
COUNT = 0


def check(name, condition, detail=""):
    global COUNT
    COUNT += 1
    if not condition:
        FAILURES.append(name)
    print(f"{'PASS' if condition else 'FAIL'}  {name}{'' if condition else '  <- ' + str(detail)[:500]}")


def run(root, *args):
    return subprocess.run(["python3", SCRIPT, *args, "--project-dir", root], capture_output=True, text=True, cwd=root)


def git(root, *args):
    return subprocess.run(["git", "-C", root, *args], check=True, capture_output=True, text=True).stdout.strip()


def write(root, path, content):
    full = os.path.join(root, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content if isinstance(content, str) else json.dumps(content))
    return full


def fixture(root, name, content):
    """A verdict or proposed-rule file, kept outside the repo so `git add -A` never commits it."""
    return write(root + "-fixtures", name, content)


def issue(issue_id, file="app/notes.py", summary="delete does not commit", **extra):
    return {"id": issue_id, "summary": summary, "repro": ["x"], "observed": "o", "expected": "e",
            "cause": {"file": file, "line": 4, "mechanism": "handler never commits"}, **extra}


def verdict(round_number, blocking=(), non_blocking=(), phase="final", sprint=None):
    return {"phase": phase, "sprint": sprint, "round": round_number,
            "blockingIssues": list(blocking), "nonBlockingIssues": list(non_blocking)}


def new_project():
    root = tempfile.mkdtemp(prefix="rules-test-")
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    write(root, ".harness/state.json", "{}")
    write(root, "app/notes.py", "def delete(conn, nid):\n    conn.execute('delete from notes where id=?', (nid,))\n")
    write(root, "web/page.html", "<p>notes</p>\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    return root, git(root, "rev-parse", "HEAD")


def issues(root):
    path = os.path.join(root, ".harness", "issues.jsonl")
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main():
    root, base = new_project()
    try:
        # ---- record and candidates
        v1 = fixture(root, "v1.json", verdict(1, [issue("B-api-1")], [issue("N-api-1", file="app/cli.py", summary="slow list")]))
        proc = run(root, "record", v1)
        log = issues(root)
        check("record appends every issue of a verdict", proc.returncode == 0 and [e["id"] for e in log] == ["B-api-1", "N-api-1"], proc.stdout + proc.stderr)
        check("a recorded issue keeps its round, cause and blocking flag",
              log and log[0]["round"] == 1 and log[0]["file"] == "app/notes.py" and log[0]["blocking"] is True and log[1]["blocking"] is False, log[:1])
        run(root, "record", v1)
        check("recording the same round again replaces it rather than doubling it", len(issues(root)) == 2, issues(root))

        proc = run(root, "candidates")
        check("nothing has come back after one round", proc.returncode == 0 and "No candidates" in proc.stdout, proc.stdout)

        v2 = fixture(root, "v2.json", verdict(2, [issue("B-api-1"), issue("B-api-2", summary="delete of unknown id returns 204", preExisting=True)]))
        run(root, "record", v2)
        check("a pre-existing mark is kept in the log", [e["preExisting"] for e in issues(root) if e["id"] == "B-api-2"] == [True])
        proc = run(root, "candidates", "--json")
        candidates = json.loads(proc.stdout)
        kinds = {c["kind"]: c for c in candidates}
        check("an issue seen in two rounds is a candidate", "recurring-issue" in kinds and kinds["recurring-issue"]["issues"] == ["B-api-1"], candidates)
        check("a file blamed by two distinct issues is a candidate",
              "repeat-offender-file" in kinds and kinds["repeat-offender-file"]["files"] == ["app/notes.py"]
              and kinds["repeat-offender-file"]["issues"] == ["B-api-1", "B-api-2"], candidates)
        check("a file blamed once is not", all("app/cli.py" not in c["files"] for c in candidates))
        sprint = fixture(root, "v3.json", verdict(1, [issue("B-9", file="x.py")], phase="sprint", sprint=2))
        run(root, "record", sprint)
        check("a sprint round with the same number does not replace a final round", len([e for e in issues(root) if e["round"] == 1]) == 3, issues(root))
        proc = run(root, "record", fixture(root, "bad.json", "{ nope"))
        check("an unreadable verdict is an error", proc.returncode == 1, proc.stderr)

        # ---- add and list
        good = {"title": "Writes must commit", "check": "For every handler that writes, confirm the row is there from a second connection.",
                "paths": ["app/**"], "keywords": ["conn.execute"], "origin": ["B-api-1"]}
        proc = run(root, "add", "--file", fixture(root, "r1.json", good))
        rules = json.load(open(os.path.join(root, ".harness/rules.json")))["rules"]
        check("add stores an approved rule under the next id", proc.returncode == 0 and rules[0]["id"] == "R-1" and rules[0]["origin"] == ["B-api-1"], proc.stdout + proc.stderr)
        proc = run(root, "add", "--file", fixture(root, "r2.json", [{"title": "Pages escape titles", "check": "Render a title containing <b>.", "paths": ["web/*.html"]},
                                                                  {"title": "No bare except", "check": "Look at each new except.", "keywords": ["except:"]}]))
        rules = json.load(open(os.path.join(root, ".harness/rules.json")))["rules"]
        check("add takes several rules and numbers them on", proc.returncode == 0 and [r["id"] for r in rules] == ["R-1", "R-2", "R-3"], proc.stdout)

        def refused(name, rule, needle):
            before = open(os.path.join(root, ".harness/rules.json")).read()
            proc = run(root, "add", "--file", fixture(root, "bad-rule.json", rule))
            check(name, proc.returncode == 1 and needle in proc.stdout and open(os.path.join(root, ".harness/rules.json")).read() == before, proc.stdout)

        refused("a rule with no trigger is refused", {"title": "Be careful", "check": "Check everything."}, "needs a trigger")
        refused("a rule that matches every file is refused", {"title": "x", "check": "y", "paths": ["**"]}, "every file")
        refused("a rule with no check is refused", {"title": "x", "paths": ["a/**"]}, "`check`")
        refused("a rule with an unknown key is refused", {"title": "x", "check": "y", "paths": ["a/**"], "severity": "high"}, "unexpected key")
        refused("one bad rule in a batch stores none of them",
                [{"title": "ok", "check": "ok", "paths": ["a/**"]}, {"title": "bad", "check": "bad"}], "rule 2")
        proc = run(root, "list")
        check("list shows each rule with its trigger and check", proc.returncode == 0 and "R-2: Pages escape titles" in proc.stdout and "paths web/*.html" in proc.stdout, proc.stdout)

        # ---- match
        out = os.path.join(root, ".harness/final/03/rules-to-check.json")
        proc = run(root, "match", "--base", base, "--out", out)
        check("an unchanged tree triggers no rule", proc.returncode == 0 and json.loads(proc.stdout)["rules"] == [], proc.stdout)

        write(root, "app/notes.py", "def delete(conn, nid):\n    conn.execute('delete from notes where id=?', (nid,))\n    conn.commit()\n")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "fix")
        report = json.loads(run(root, "match", "--base", base, "--out", out).stdout)
        check("a changed file under a rule's path triggers it", [r["id"] for r in report["rules"]] == ["R-1"] and report["rules"][0]["matchedPaths"] == ["app/notes.py"], report)
        check("the report says how many rules exist in all, and --out writes it",
              report["rulesTotal"] == 3 and json.load(open(out)) == report)

        write(root, "worker/job.py", "try:\n    run()\nexcept:\n    pass\n")
        write(root, "web/page.html", "<p>{{ title }}</p>\n")
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "more")
        report = json.loads(run(root, "match", "--base", base).stdout)
        by_id = {r["id"]: r for r in report["rules"]}
        check("a keyword in an added line triggers a rule with no path", by_id.get("R-3", {}).get("matchedKeywords") == ["except:"], report)
        check("a glob over a single directory level matches", by_id.get("R-2", {}).get("matchedPaths") == ["web/page.html"], report)
        check("all three rules are now triggered", sorted(by_id) == ["R-1", "R-2", "R-3"])
        head = git(root, "rev-parse", "HEAD")
        report = json.loads(run(root, "match", "--base", head).stdout)
        check("a keyword already in the file before the round does not trigger", report["rules"] == [], report)

        proc = run(root, "match", "--base", "no-such-commit", "--out", out)
        check("an unknown base exits 1 and removes a stale list", proc.returncode == 1 and not os.path.exists(out), proc.stderr)

        write(root, ".harness/rules.json", "{ nope")
        check("an unreadable rules file is an error, not zero rules", run(root, "match", "--base", base).returncode == 1)
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(root + "-fixtures", ignore_errors=True)

    root, base = new_project()
    try:
        proc = run(root, "match", "--base", base)
        check("a project with no rules file triggers nothing", proc.returncode == 0 and json.loads(proc.stdout)["rulesTotal"] == 0, proc.stdout)
        proc = run(root, "list")
        check("list says so when there are no rules", "No rules yet" in proc.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(root + "-fixtures", ignore_errors=True)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} failing case(s): {', '.join(FAILURES)}")
        return 1
    print(f"all {COUNT} rules cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
