#!/usr/bin/env python3
"""Regression tests for the eval fixtures and graders under evals/.

The eval suite measures the evaluator: does it report a defect that is known to
be there, and does it pass an app known to be sound. Those numbers mean nothing
if the fixtures rot — a "seeded" app whose mutation no longer applies is a clean
app scored as a miss, and a "clean" app with a real bug is a correct fail scored
as a false alarm. So each fixture is built here the way an eval run builds it,
and checked for what it claims to be:

- a clean fixture's own test suite passes, and a probe finds the behaviour sound;
- a seeded fixture's (thin) suite ALSO passes — the defect cannot be found by
  running the tests — while a probe written for that defect shows it;
- each case's grader pattern matches a verdict that names the defect among its
  blocking issues, and does not match one that fails for another reason.

No framework, no model calls — run it directly:

    python3 crystal-harness/scripts/test_eval_fixtures.py
"""

import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

EVALS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evals")

FAILURES = []
COUNT = 0


def check(name, condition, detail=""):
    global COUNT
    COUNT += 1
    if not condition:
        FAILURES.append(name)
    print(f"{'PASS' if condition else 'FAIL'}  {name}{'' if condition else '  <- ' + str(detail)[:400]}")


def build(case):
    root = tempfile.mkdtemp(prefix="eval-fixture-")
    proc = subprocess.run(["bash", os.path.join(EVALS, case, "fixture.sh")], cwd=root, capture_output=True, text=True)
    return root, proc


def run_suite(root):
    command = json.load(open(os.path.join(root, ".harness", "config.json")))["commands"]["test"]
    return subprocess.run(command, shell=True, cwd=root, capture_output=True, text=True)


class Server:
    """The fixture's real `python3 app.py`, on a free port with a scratch database."""

    def __init__(self, root, db):
        self.root, self.db = root, db
        self.proc = None

    def start(self):
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        env = dict(os.environ, NOTES_PORT=str(self.port), NOTES_DB=self.db)
        self.proc = subprocess.Popen([sys.executable, "app.py"], cwd=self.root, env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                self.call("GET", "/notes")
                return self
            except OSError:
                time.sleep(0.05)
        raise RuntimeError("server did not start")

    def stop(self):
        if self.proc:
            self.proc.terminate()
            self.proc.wait(timeout=10)
            self.proc = None

    def call(self, method, path, body=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
            conn.request(method, path, body=data, headers={"Content-Type": "application/json"} if data else {})
            resp = conn.getresponse()
            payload = resp.read()
            try:
                parsed = json.loads(payload) if payload else None
            except ValueError:
                parsed = payload
            return resp.status, parsed
        finally:
            conn.close()


def observe(root):
    """What the app actually does, as facts a probe can assert on."""
    db = os.path.join(root, "probe.db")
    server = Server(root, db).start()
    facts = {}
    try:
        _, first = server.call("POST", "/notes", {"title": "first", "body": "kept"})
        _, second = server.call("POST", "/notes", {"title": "second"})
        facts["body_returned"] = first.get("body")
        facts["body_stored"] = server.call("GET", f"/notes/{first['id']}")[1].get("body")
        facts["list_titles"] = [n["title"] for n in server.call("GET", "/notes")[1]]
        facts["invalid_json_status"] = server.call("POST", "/notes", raw=b"{nope")[0]
        facts["delete_unknown_status"] = server.call("DELETE", "/notes/999999")[0]
        facts["delete_status"] = server.call("DELETE", f"/notes/{second['id']}")[0]
        facts["get_after_delete_status"] = server.call("GET", f"/notes/{second['id']}")[0]
        server.stop()
        server.start()
        facts["first_survives_restart"] = server.call("GET", f"/notes/{first['id']}")[0] == 200
    finally:
        server.stop()
    return facts


SOUND = {
    "body_returned": "kept", "body_stored": "kept", "list_titles": ["first", "second"],
    "invalid_json_status": 400, "delete_unknown_status": 404, "delete_status": 204,
    "get_after_delete_status": 404, "first_survives_restart": True,
}
# The one fact each seeded defect changes, and the value it takes.
BROKEN = {
    "seeded-delete-not-committed": ("get_after_delete_status", 200),
    "seeded-delete-unknown-returns-204": ("delete_unknown_status", 204),
    "seeded-list-newest-first": ("list_titles", ["second", "first"]),
    "seeded-restart-wipes-data": ("first_survives_restart", False),
    "seeded-invalid-json-returns-422": ("invalid_json_status", 422),
    "seeded-body-discarded": ("body_stored", ""),
}


def grader_pattern(case, name):
    text = open(os.path.join(EVALS, case, "graders", name + ".md"), encoding="utf-8").read()
    pattern = re.search(r"^pattern: '(.*)'$", text, re.M).group(1)
    flags = re.search(r"^flags: (\w+)$", text, re.M)
    compiled = 0
    for letter in (flags.group(1) if flags else ""):
        compiled |= {"i": re.I, "s": re.S, "m": re.M}[letter]
    return re.compile(pattern, compiled)


def verdict_text(blocking_summary, non_blocking_summary=None, overall="fail"):
    def issue(issue_id, summary):
        return {"id": issue_id, "summary": summary, "repro": ["x"], "observed": "o", "expected": "e",
                "cause": {"file": "app.py", "line": 1, "mechanism": "m"}}
    return json.dumps({
        "overall": overall,
        "criteria": [{"id": "SPEC-1", "text": "notes are listed in creation order and DELETE of an unknown id returns 404; "
                      "invalid JSON returns 400; the body is returned; notes persist across a restart and stay committed",
                      "result": "fail"}],
        "blockingIssues": [issue("B-1", blocking_summary)] if blocking_summary else [],
        "nonBlockingIssues": [issue("N-1", non_blocking_summary)] if non_blocking_summary else [],
    }, indent=2)


# What an evaluator that found each defect would plausibly write.
NAMED = {
    "seeded-delete-not-committed": "DELETE /notes/1 returns 204 but the note is still there afterwards: the connection is closed without a commit",
    "seeded-delete-unknown-returns-204": "DELETE of an unknown id returns 204; the spec requires 404",
    "seeded-list-newest-first": "GET /notes returns notes newest first instead of creation order",
    "seeded-restart-wipes-data": "All notes are gone after a restart: NoteStore deletes the database file on startup",
    "seeded-invalid-json-returns-422": "POST /notes with invalid JSON returns 422, the spec says 400",
    "seeded-body-discarded": "POST /notes accepts a body but stores an empty string",
}
UNRELATED = "The test suite covers only the happy path of creating a note, so nothing guards the remaining behaviour"


def main():
    cases = sorted(d for d in os.listdir(EVALS) if os.path.isfile(os.path.join(EVALS, d, "case.yaml")))
    seeded = [c for c in cases if c.startswith("seeded-")]
    clean = [c for c in cases if c.startswith("clean-")]
    check("the suite has seeded and clean cases and nothing else", len(seeded) >= 5 and len(clean) >= 2 and len(seeded) + len(clean) == len(cases), cases)
    check("every seeded case has a probe and a sample verdict here", set(seeded) == set(BROKEN) == set(NAMED), set(seeded) ^ set(BROKEN))

    for case in cases:
        root, proc = build(case)
        try:
            check(f"{case}: the fixture builds", proc.returncode == 0 and os.path.isfile(os.path.join(root, "app.py")), proc.stderr)
            if proc.returncode != 0:
                continue
            log = subprocess.run(["git", "-C", root, "log", "--oneline"], capture_output=True, text=True).stdout
            dirty = subprocess.run(["git", "-C", root, "status", "--porcelain"], capture_output=True, text=True).stdout
            check(f"{case}: one commit, clean tree", len(log.strip().splitlines()) == 1 and not dirty.strip(), log + dirty)
            suite = run_suite(root)
            check(f"{case}: its test suite passes", suite.returncode == 0, suite.stderr[-300:])
            facts = observe(root)
            if case in BROKEN:
                fact, value = BROKEN[case]
                check(f"{case}: the seeded defect is really there ({fact})", facts[fact] == value, facts)
                others = {k: v for k, v in facts.items() if k != fact and SOUND[k] != v}
                # A wiped datastore or a rolled-back delete legitimately shows up in a second fact.
                allowed = {"seeded-delete-not-committed": set(), "seeded-restart-wipes-data": set(),
                           "seeded-body-discarded": {"body_returned"}}.get(case, set())
                check(f"{case}: and nothing else is broken", set(others) <= allowed, others)
            else:
                check(f"{case}: the app behaves as the spec says", facts == SOUND, {k: v for k, v in facts.items() if SOUND[k] != v})
        finally:
            shutil.rmtree(root, ignore_errors=True)

    for case in seeded:
        names = grader_pattern(case, "names-the-defect")
        fails = grader_pattern(case, "fails-the-round")
        check(f"{case}: grader matches a verdict that names the defect", bool(names.search(verdict_text(NAMED[case]))))
        check(f"{case}: grader ignores a fail for an unrelated reason", not names.search(verdict_text(UNRELATED)), UNRELATED)
        check(f"{case}: grader ignores the defect when it is only a non-blocking note",
              not names.search(verdict_text(UNRELATED, non_blocking_summary=NAMED[case])))
        check(f"{case}: fails-the-round reads the overall verdict", bool(fails.search(verdict_text("x"))) and not fails.search(verdict_text(None, overall="pass")))
    for case in clean:
        passes = grader_pattern(case, "passes-the-round")
        none = grader_pattern(case, "no-blocking-issues")
        good = verdict_text(None, overall="pass")
        check(f"{case}: graders accept a clean pass", bool(passes.search(good)) and bool(none.search(good)))
        bad = verdict_text("anything")
        check(f"{case}: graders reject a fail with a blocking issue", not passes.search(bad) and not none.search(bad))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} failing case(s): {', '.join(FAILURES)}")
        return 1
    print(f"all {COUNT} eval-fixture cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
