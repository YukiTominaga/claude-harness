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
import sqlite3
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

    def __init__(self, root, db, prefix="NOTES", health="/notes"):
        self.root, self.db, self.prefix, self.health = root, db, prefix, health
        self.proc = None

    def start(self):
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        env = dict(os.environ, **{f"{self.prefix}_PORT": str(self.port), f"{self.prefix}_DB": self.db})
        self.proc = subprocess.Popen([sys.executable, "app.py"], cwd=self.root, env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                self.call("GET", self.health)
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


def observe_notes(root):
    """What the Notes app actually does, as facts a probe can assert on."""
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


def observe_tracker(root):
    """The same for the Tracker app: one walk through every rule a defect or a
    decoy touches, in an order that keeps each fact independent of the others."""
    db = os.path.join(root, "probe.db")
    server = Server(root, db, prefix="TRACKER", health="/projects").start()
    facts = {}

    def post(path, body=None):
        return server.call("POST", path, body)

    def get(path):
        return server.call("GET", path)[1]

    def task(project, **fields):
        return post(f"/projects/{project['id']}/tasks", dict({"title": "t"}, **fields))[1]

    def go(task_id, to):
        return post(f"/tasks/{task_id}/transition", {"to": to})

    def block(task_id, blocker_id):
        return server.call("PUT", f"/tasks/{task_id}/blockers/{blocker_id}")[0]

    def count(sql, *params):
        conn = sqlite3.connect(db)
        try:
            return conn.execute(sql, params).fetchone()[0]
        finally:
            conn.close()

    try:
        alpha, beta = post("/projects", {"name": "Alpha"})[1], post("/projects", {"name": "Beta"})[1]
        facts["duplicate_name_status"] = post("/projects", {"name": "ALPHA"})[0]
        facts["invalid_json_status"] = server.call("POST", "/projects", raw=b"{nope")[0]

        # workflow, and the two ways tags get in
        first = task(alpha, tags=[" Urgent ", "urgent", "Home"])
        facts["created_tags"] = first["tags"]
        facts["todo_to_done_status"] = go(first["id"], "done")[0]
        go(first["id"], "doing")
        facts["done_sets_completed_at"] = isinstance(go(first["id"], "done")[1]["completed_at"], str)
        facts["reopened_completed_at"] = go(first["id"], "doing")[1]["completed_at"]
        facts["counts"] = get(f"/projects/{alpha['id']}")["task_counts"]
        facts["patched_tags"] = server.call("PATCH", f"/tasks/{first['id']}", {"tags": [" Later", "LATER", "Home"]})[1]["tags"]
        facts["tag_filter_finds_patched"] = [t["id"] for t in get("/tasks?tag=later")["items"]] == [first["id"]]

        # listing: three tasks, a page of two
        made = [task(beta, priority=p)["id"] for p in (3, 5, 3)]
        page = get(f"/tasks?project_id={beta['id']}&limit=2")
        facts["page_order"] = [made.index(t["id"]) for t in page["items"]]
        facts["total_beyond_the_page"] = page["total"]
        facts["total_on_one_page"] = get(f"/tasks?project_id={beta['id']}")["total"]

        # blocking: x waits on y, y on z
        x, y, z = (task(alpha)["id"] for _ in range(3))
        facts["block_status"] = block(x, y)
        facts["direct_cycle_status"] = block(y, x)
        block(y, z)
        facts["indirect_cycle_status"] = block(z, x)
        go(x, "doing")
        facts["blocked_done_status"] = go(x, "done")[0]
        facts["delete_task_status"] = server.call("DELETE", f"/tasks/{y}")[0]
        facts["blocked_by_after_blocker_deleted"] = get(f"/tasks/{x}")["blocked_by"]
        facts["done_after_blocker_deleted_status"] = go(x, "done")[0]

        # archiving and moving
        gamma = post("/projects", {"name": "Gamma"})[1]
        mover = task(alpha)["id"]
        facts["archive_status"] = post(f"/projects/{gamma['id']}/archive")[0]
        facts["create_in_archived_status"] = post(f"/projects/{gamma['id']}/tasks", {"title": "late"})[0]
        facts["move_into_archived_status"] = post(f"/tasks/{mover}/move", {"project_id": gamma["id"]})[0]
        facts["task_stayed_where_it_was"] = get(f"/tasks/{mover}")["project_id"] == alpha["id"]
        facts["move_status"] = post(f"/tasks/{mover}/move", {"project_id": beta["id"]})[0]
        facts["listed_projects"] = [p["name"] for p in get("/projects")]

        # deleting a project whose task something else waits on
        waiter = task(alpha)["id"]
        block(waiter, made[0])
        facts["delete_project_status"] = server.call("DELETE", f"/projects/{beta['id']}")[0]
        facts["task_of_deleted_project_status"] = server.call("GET", f"/tasks/{made[0]}")[0]
        facts["blocked_by_after_project_deleted"] = get(f"/tasks/{waiter}")["blocked_by"]
        facts["rows_left_behind"] = (
            count("SELECT COUNT(*) FROM tasks WHERE project_id = ?", beta["id"])
            + count("SELECT COUNT(*) FROM blockers WHERE blocker_id NOT IN (SELECT id FROM tasks) OR task_id NOT IN (SELECT id FROM tasks)")
            + count("SELECT COUNT(*) FROM task_tags WHERE task_id NOT IN (SELECT id FROM tasks)")
        )

        before = (get("/projects?include_archived=true"), get("/tasks?limit=100"))
        server.stop()
        server.start()
        facts["survives_restart"] = (get("/projects?include_archived=true"), get("/tasks?limit=100")) == before
    finally:
        server.stop()
    return facts


def is_tracker(case):
    return "-tracker-" in case


def observe(case, root):
    return observe_tracker(root) if is_tracker(case) else observe_notes(root)


SOUND_NOTES = {
    "body_returned": "kept", "body_stored": "kept", "list_titles": ["first", "second"],
    "invalid_json_status": 400, "delete_unknown_status": 404, "delete_status": 204,
    "get_after_delete_status": 404, "first_survives_restart": True,
}
SOUND_TRACKER = {
    "duplicate_name_status": 409, "invalid_json_status": 400,
    "created_tags": ["urgent", "home"], "todo_to_done_status": 409, "done_sets_completed_at": True,
    "reopened_completed_at": None, "counts": {"todo": 0, "doing": 1, "done": 0},
    "patched_tags": ["later", "home"], "tag_filter_finds_patched": True,
    "page_order": [1, 0], "total_beyond_the_page": 3, "total_on_one_page": 3,
    "block_status": 200, "direct_cycle_status": 409, "indirect_cycle_status": 409, "blocked_done_status": 409,
    "delete_task_status": 204, "blocked_by_after_blocker_deleted": [], "done_after_blocker_deleted_status": 200,
    "archive_status": 200, "create_in_archived_status": 409, "move_into_archived_status": 409,
    "task_stayed_where_it_was": True, "move_status": 200, "listed_projects": ["Alpha", "Beta"],
    "delete_project_status": 204, "task_of_deleted_project_status": 404, "blocked_by_after_project_deleted": [],
    "rows_left_behind": 0, "survives_restart": True,
}


def sound(case):
    return SOUND_TRACKER if is_tracker(case) else SOUND_NOTES


SOMETHING = object()  # stands for "a non-empty value" where the value itself is not fixed (a timestamp, an id)

# Every fact each seeded defect changes, and the value it takes. Exactly these
# must differ from SOUND: a defect that also broke something else would be two.
BROKEN = {
    "seeded-delete-not-committed": {"get_after_delete_status": 200},
    "seeded-delete-unknown-returns-204": {"delete_unknown_status": 204},
    "seeded-list-newest-first": {"list_titles": ["second", "first"]},
    "seeded-restart-wipes-data": {"first_survives_restart": False},
    "seeded-invalid-json-returns-422": {"invalid_json_status": 422},
    "seeded-body-discarded": {"body_stored": "", "body_returned": ""},
    "seeded-tracker-reopen-keeps-completed-at": {"reopened_completed_at": SOMETHING},
    "seeded-tracker-move-into-archived-project": {"move_into_archived_status": 200, "task_stayed_where_it_was": False},
    "seeded-tracker-deleted-blocker-still-blocks": {"blocked_by_after_blocker_deleted": SOMETHING, "done_after_blocker_deleted_status": 409,
                                                    "rows_left_behind": 1},
    "seeded-tracker-indirect-cycle-accepted": {"indirect_cycle_status": 200},
    "seeded-tracker-total-counts-the-page": {"total_beyond_the_page": 2},
    "seeded-tracker-patch-tags-not-normalised": {"patched_tags": ["Later", "LATER", "Home"], "tag_filter_finds_patched": False},
}


def differences(case, facts):
    """(what differs from sound, whether it is exactly what the case's defect predicts)."""
    expected = BROKEN.get(case, {})
    differing = {k: v for k, v in facts.items() if sound(case)[k] != v}
    as_predicted = set(differing) == set(expected) and all(
        bool(differing[k]) if want is SOMETHING else differing[k] == want
        for k, want in expected.items()
    )
    return differing, as_predicted


def grader_pattern(case, name):
    text = open(os.path.join(EVALS, case, "graders", name + ".md"), encoding="utf-8").read()
    pattern = re.search(r"^pattern: '(.*)'$", text, re.M).group(1)
    flags = re.search(r"^flags: (\w+)$", text, re.M)
    compiled = 0
    for letter in (flags.group(1) if flags else ""):
        compiled |= {"i": re.I, "s": re.S, "m": re.M}[letter]
    return re.compile(pattern, compiled)


def verdict_text(blocking_summary, non_blocking_summary=None, overall="fail", criteria_last=None):
    """A verdict as an evaluator writes it. `criteria_last` puts a criteria array
    mentioning that text AFTER blockingIssues — a key order the schema does not
    forbid — to check a grader does not read a criterion as a blocking issue."""
    def issue(issue_id, summary):
        return {"id": issue_id, "summary": summary, "repro": ["x"], "observed": "o", "expected": "e",
                "cause": {"file": "app.py", "line": 1, "mechanism": "m"}}
    criteria = [{"id": "SPEC-1", "text": "notes are listed in creation order and DELETE of an unknown id returns 404; "
                 "invalid JSON returns 400; the body is returned; notes persist across a restart and stay committed",
                 "result": "fail"}]
    verdict = {"overall": overall}
    if criteria_last is None:
        verdict["criteria"] = criteria
    verdict["blockingIssues"] = [issue("B-1", blocking_summary)] if blocking_summary else []
    if criteria_last is not None:
        verdict["criteria"] = criteria + [{"id": "SPEC-2", "text": criteria_last, "result": "pass"}]
    verdict["nonBlockingIssues"] = [issue("N-1", non_blocking_summary)] if non_blocking_summary else []
    return json.dumps(verdict, indent=2)


# What an evaluator that found each defect would plausibly write — two phrasings
# for the tracker defects, since their patterns have more to get wrong.
NAMED = {
    "seeded-delete-not-committed": ["DELETE /notes/1 returns 204 but the note is still there afterwards: the connection is closed without a commit"],
    "seeded-delete-unknown-returns-204": ["DELETE of an unknown id returns 204; the spec requires 404"],
    "seeded-list-newest-first": ["GET /notes returns notes newest first instead of creation order"],
    "seeded-restart-wipes-data": ["All notes are gone after a restart: NoteStore deletes the database file on startup"],
    "seeded-invalid-json-returns-422": ["POST /notes with invalid JSON returns 422, the spec says 400"],
    "seeded-body-discarded": ["POST /notes accepts a body but stores an empty string"],
    "seeded-tracker-reopen-keeps-completed-at": [
        "Re-opening a done task (done -> doing) leaves completed_at set; the spec says it goes back to null",
        "A task that left done still carries its completion timestamp",
    ],
    "seeded-tracker-move-into-archived-project": [
        "POST /tasks/{id}/move into an archived project returns 200 and moves the task; the spec requires 409",
        "An archived project still accepts tasks through move",
    ],
    "seeded-tracker-deleted-blocker-still-blocks": [
        "After DELETE /tasks/{blocker}, the waiting task still lists it in blocked_by and can never enter done",
        "blocked_by keeps the id of a removed task: delete_task only clears relations where the task is the waiter",
    ],
    "seeded-tracker-indirect-cycle-accepted": [
        "PUT /tasks/C/blockers/A is accepted although A waits on B and B on C: a three-task cycle",
        "Only direct mutual blocking is refused; an indirect loop through a third task goes through with 200",
    ],
    "seeded-tracker-total-counts-the-page": [
        "GET /tasks?limit=2 reports total 2 when 3 tasks match: total is the length of the page",
        "The total in a task listing changes with limit and offset",
    ],
    "seeded-tracker-patch-tags-not-normalised": [
        "PATCH /tasks/{id} stores tags without lower-casing them, so ?tag= no longer finds the task",
        "Duplicate and upper-case tags survive a PATCH; only creation normalises the tags array",
    ],
}
UNRELATED = "The test suite covers only the happy path of creating a note, so nothing guards the remaining behaviour"
UNRELATED_TRACKER = ("The test suite covers only the happy path of filing a task and starting it; "
                     "nothing guards the workflow rules, listing or archiving")


def main():
    cases = sorted(d for d in os.listdir(EVALS) if os.path.isfile(os.path.join(EVALS, d, "case.yaml")))
    seeded = [c for c in cases if c.startswith("seeded-")]
    clean = [c for c in cases if c.startswith("clean-")]
    check("the suite has seeded and clean cases and nothing else", len(seeded) >= 5 and len(clean) >= 2 and len(seeded) + len(clean) == len(cases), cases)
    check("every seeded case has a probe and a sample verdict here", set(seeded) == set(BROKEN) == set(NAMED), set(seeded) ^ set(BROKEN))
    check("both fixtures have seeded and clean cases",
          all(any(is_tracker(c) == tracker for c in group) for group in (seeded, clean) for tracker in (True, False)), cases)

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
            facts = observe(case, root)
            check(f"{case}: the probe covers every fact it is compared on", set(facts) == set(sound(case)), set(facts) ^ set(sound(case)))
            differing, as_predicted = differences(case, facts)
            if case in BROKEN:
                check(f"{case}: the seeded defect is really there, and nothing else is broken ({', '.join(BROKEN[case])})",
                      as_predicted, differing)
            else:
                check(f"{case}: the app behaves as the spec says", not differing, differing)
            if "decoy" in case:
                base = open(os.path.join(EVALS, "_fixtures", "tracker", "app.py"), encoding="utf-8").read()
                check(f"{case}: the decoys really rewrote the app", open(os.path.join(root, "app.py"), encoding="utf-8").read() != base)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    for case in seeded:
        names = grader_pattern(case, "names-the-defect")
        fails = grader_pattern(case, "fails-the-round")
        unrelated = UNRELATED_TRACKER if is_tracker(case) else UNRELATED
        for index, text in enumerate(NAMED[case], 1):
            check(f"{case}: grader matches a verdict that names the defect (phrasing {index})", bool(names.search(verdict_text(text))), text)
        check(f"{case}: grader ignores a fail for an unrelated reason", not names.search(verdict_text(unrelated)), unrelated)
        check(f"{case}: grader ignores the defect when it is only a non-blocking note",
              not names.search(verdict_text(unrelated, non_blocking_summary=NAMED[case][0])))
        check(f"{case}: grader ignores the defect when only a criterion written after the blocking issues mentions it",
              not names.search(verdict_text(unrelated, criteria_last=NAMED[case][0])))
        check(f"{case}: fails-the-round reads the overall verdict", bool(fails.search(verdict_text("x"))) and not fails.search(verdict_text(None, overall="pass")))
    # A tracker verdict that names one defect must not be scored as naming another.
    tracker_seeded = [c for c in seeded if is_tracker(c)]
    for case in tracker_seeded:
        names = grader_pattern(case, "names-the-defect")
        mistaken = [other for other in tracker_seeded if other != case
                    and any(names.search(verdict_text(text)) for text in NAMED[other])]
        check(f"{case}: grader does not take another tracker defect for its own", not mistaken, mistaken)
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
