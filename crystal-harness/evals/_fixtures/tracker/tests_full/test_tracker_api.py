"""Tests for the Tracker API, through HTTP against a real server and a scratch database."""

import http.client
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import app  # noqa: E402


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "tracker.db")
        self.start()

    def tearDown(self):
        self.stop()
        self.tmp.cleanup()

    def start(self):
        self.server = app.make_server(port=0, db_path=self.db, quiet=True)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    def call(self, method, path, body=None, raw=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
            conn.request(method, path, body=data, headers={"Content-Type": "application/json"} if data else {})
            resp = conn.getresponse()
            payload = resp.read()
            return resp.status, (json.loads(payload) if payload else None)
        finally:
            conn.close()

    def rows(self, sql, params=()):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    # helpers that assert the happy path and return the body
    def project(self, name="Alpha"):
        status, body = self.call("POST", "/projects", {"name": name})
        self.assertEqual(status, 201, body)
        return body

    def task(self, project_id, title="write it", **fields):
        status, body = self.call("POST", f"/projects/{project_id}/tasks", dict(fields, title=title))
        self.assertEqual(status, 201, body)
        return body

    def go(self, task_id, to, expect=200):
        status, body = self.call("POST", f"/tasks/{task_id}/transition", {"to": to})
        self.assertEqual(status, expect, body)
        return body

    def block(self, task_id, blocker_id, expect=200):
        status, body = self.call("PUT", f"/tasks/{task_id}/blockers/{blocker_id}")
        self.assertEqual(status, expect, body)
        return body


class ProjectTests(ApiTest):
    def test_create_returns_the_whole_project(self):
        project = self.project("  Alpha  ")
        self.assertEqual(project["name"], "Alpha")
        self.assertIs(project["archived"], False)
        self.assertEqual(project["task_counts"], {"todo": 0, "doing": 0, "done": 0})
        self.assertIsInstance(project["id"], int)
        self.assertIn("created_at", project)

    def test_name_is_validated(self):
        for name in ("", "   ", "x" * 61, None, 7):
            self.assertEqual(self.call("POST", "/projects", {"name": name})[0], 422, name)
        self.assertEqual(self.call("POST", "/projects", {})[0], 422)
        self.assertEqual(self.call("POST", "/projects", {"name": "x" * 60})[0], 201)
        self.assertEqual(self.call("GET", "/projects")[1][0]["name"], "x" * 60)

    def test_name_is_unique_ignoring_case(self):
        self.project("Alpha")
        self.assertEqual(self.call("POST", "/projects", {"name": "alpha"})[0], 409)
        self.assertEqual(self.call("POST", "/projects", {"name": " ALPHA "})[0], 409)
        self.assertEqual(len(self.call("GET", "/projects")[1]), 1)

    def test_names_are_compared_case_folded(self):
        # the spec's own example: one name
        self.assertEqual(self.call("POST", "/projects", {"name": "Stra\u00dfe"})[0], 201)
        self.assertEqual(self.call("POST", "/projects", {"name": "STRASSE"})[0], 409)
        # a capital sigma lower-cases to a different letter at the end of a word
        self.assertEqual(self.call("POST", "/projects", {"name": "\u039f\u0394\u039f\u03a3"})[0], 201)
        self.assertEqual(self.call("POST", "/projects", {"name": "\u03bf\u03b4\u03bf\u03c3"})[0], 409)
        self.assertEqual(self.call("POST", "/projects", {"name": "\u03bf\u03b4\u03bf\u03c2"})[0], 409)
        self.assertEqual(len(self.call("GET", "/projects")[1]), 2)

    def test_an_archived_projects_name_is_still_taken(self):
        project = self.project("Alpha")
        self.call("POST", f"/projects/{project['id']}/archive")
        self.assertEqual(self.call("POST", "/projects", {"name": "alpha"})[0], 409)

    def test_list_is_in_creation_order_and_hides_archived(self):
        a, b, c = self.project("A"), self.project("B"), self.project("C")
        self.assertEqual(self.call("POST", f"/projects/{b['id']}/archive")[0], 200)
        self.assertEqual([p["name"] for p in self.call("GET", "/projects")[1]], ["A", "C"])
        status, everything = self.call("GET", "/projects?include_archived=true")
        self.assertEqual(status, 200)
        self.assertEqual([p["name"] for p in everything], ["A", "B", "C"])
        self.assertEqual([p["archived"] for p in everything], [False, True, False])
        self.assertEqual([p["name"] for p in self.call("GET", "/projects?include_archived=false")[1]], ["A", "C"])
        for value in ("", "1", "yes", "TRUE", "banana"):
            self.assertEqual(self.call("GET", f"/projects?include_archived={value}")[0], 422, value)

    def test_get_one_and_unknown(self):
        project = self.project()
        status, got = self.call("GET", f"/projects/{project['id']}")
        self.assertEqual((status, got), (200, project))
        self.assertEqual(self.call("GET", "/projects/999")[0], 404)
        self.assertEqual(self.call("GET", f"/projects/{10**30}")[0], 404)

    def test_task_counts_follow_the_tasks(self):
        project = self.project()
        first, second = self.task(project["id"]), self.task(project["id"])
        self.task(project["id"])
        self.go(first["id"], "doing")
        self.go(second["id"], "doing")
        self.go(second["id"], "done")
        counts = self.call("GET", f"/projects/{project['id']}")[1]["task_counts"]
        self.assertEqual(counts, {"todo": 1, "doing": 1, "done": 1})

    def test_archive_is_idempotent(self):
        project = self.project()
        for _ in range(2):
            status, body = self.call("POST", f"/projects/{project['id']}/archive")
            self.assertEqual(status, 200)
            self.assertIs(body["archived"], True)
        self.assertEqual(self.call("POST", "/projects/999/archive")[0], 404)

    def test_archived_project_takes_no_new_task_but_keeps_its_own_workable(self):
        project, other = self.project("A"), self.project("B")
        inside = self.task(project["id"])
        outside = self.task(other["id"])
        self.call("POST", f"/projects/{project['id']}/archive")
        self.assertEqual(self.call("POST", f"/projects/{project['id']}/tasks", {"title": "late"})[0], 409)
        self.assertEqual(self.call("POST", f"/tasks/{outside['id']}/move", {"project_id": project["id"]})[0], 409)
        self.assertEqual(self.call("GET", f"/tasks/{outside['id']}")[1]["project_id"], other["id"])
        # what is already inside can be read, changed, moved out and deleted
        self.assertEqual(self.call("PATCH", f"/tasks/{inside['id']}", {"title": "renamed"})[0], 200)
        self.assertEqual(self.call("POST", f"/tasks/{inside['id']}/move", {"project_id": project["id"]})[0], 200)
        self.go(inside["id"], "doing")
        status, moved = self.call("POST", f"/tasks/{inside['id']}/move", {"project_id": other["id"]})
        self.assertEqual((status, moved["project_id"]), (200, other["id"]))
        second = self.rows("SELECT COUNT(*) FROM tasks WHERE project_id = ?", (project["id"],))
        self.assertEqual(second[0][0], 0)

    def test_delete_removes_the_project_its_tasks_and_their_relations(self):
        doomed, kept = self.project("Doomed"), self.project("Kept")
        inside, tagged = self.task(doomed["id"]), self.task(doomed["id"], tags=["x"])
        outside = self.task(kept["id"])
        self.block(outside["id"], inside["id"])
        self.block(inside["id"], tagged["id"])
        self.assertEqual(self.call("DELETE", f"/projects/{doomed['id']}")[0], 204)
        self.assertEqual(self.call("GET", f"/projects/{doomed['id']}")[0], 404)
        self.assertEqual(self.call("GET", f"/tasks/{inside['id']}")[0], 404)
        self.assertEqual(self.call("GET", f"/tasks/{outside['id']}")[1]["blocked_by"], [])
        self.assertEqual(self.call("GET", "/tasks")[1]["total"], 1)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM tasks")[0][0], 1)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM blockers")[0][0], 0)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM task_tags")[0][0], 0)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM projects")[0][0], 1)
        self.assertEqual(self.call("DELETE", f"/projects/{doomed['id']}")[0], 404)
        # the task that was waiting can now finish
        self.go(outside["id"], "doing")
        self.go(outside["id"], "done")


class TaskTests(ApiTest):
    def test_create_returns_the_whole_task_with_defaults(self):
        project = self.project()
        task = self.task(project["id"], "  write it  ")
        self.assertEqual(task["title"], "write it")
        self.assertEqual(task["project_id"], project["id"])
        self.assertEqual((task["status"], task["priority"], task["tags"], task["blocked_by"]), ("todo", 3, [], []))
        self.assertIsNone(task["completed_at"])
        self.assertIn("created_at", task)
        self.assertEqual(self.call("GET", f"/tasks/{task['id']}"), (200, task))

    def test_create_validates_and_stores_nothing_when_invalid(self):
        project = self.project()
        bad = [
            {}, {"title": ""}, {"title": "  "}, {"title": "x" * 121}, {"title": 5},
            {"title": "t", "priority": 0}, {"title": "t", "priority": 6}, {"title": "t", "priority": "3"},
            {"title": "t", "priority": 2.5}, {"title": "t", "priority": True}, {"title": "t", "priority": None},
            {"title": "t", "tags": "a"}, {"title": "t", "tags": [1]}, {"title": "t", "tags": [""]},
            {"title": "t", "tags": ["x" * 21]}, {"title": "t", "tags": list("abcdef")}, {"title": "t", "tags": None},
        ]
        for body in bad:
            self.assertEqual(self.call("POST", f"/projects/{project['id']}/tasks", body)[0], 422, body)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM tasks")[0][0], 0)
        self.assertEqual(self.call("POST", "/projects/999/tasks", {"title": "t"})[0], 404)
        self.assertEqual(self.task(project["id"], "x" * 120, priority=5, tags=["x" * 20])["priority"], 5)

    def test_tags_are_trimmed_lowercased_and_deduplicated_in_order(self):
        project = self.project()
        task = self.task(project["id"], tags=[" Urgent ", "home", "URGENT", "Home", "b"])
        self.assertEqual(task["tags"], ["urgent", "home", "b"])
        self.assertEqual(self.call("GET", f"/tasks/{task['id']}")[1]["tags"], ["urgent", "home", "b"])

    def test_tag_length_is_measured_after_lower_casing(self):
        project = self.project()
        grows = "\u0130" * 20  # each becomes two characters when lower-cased
        self.assertEqual(self.call("POST", f"/projects/{project['id']}/tasks", {"title": "t", "tags": [grows]})[0], 422)
        task = self.task(project["id"], tags=["\u0130" * 10])
        self.assertEqual([len(tag) for tag in task["tags"]], [20])
        self.assertEqual(self.call("PATCH", f"/tasks/{task['id']}", {"tags": [grows]})[0], 422)
        self.assertEqual(self.rows("SELECT MAX(LENGTH(tag)) FROM task_tags")[0][0], 20)

    def test_patch_changes_only_what_is_sent(self):
        project = self.project()
        task = self.task(project["id"], "old", priority=2, tags=["a"])
        status, body = self.call("PATCH", f"/tasks/{task['id']}", {"title": "  new  "})
        self.assertEqual((status, body["title"], body["priority"], body["tags"]), (200, "new", 2, ["a"]))
        status, body = self.call("PATCH", f"/tasks/{task['id']}", {"priority": 5, "tags": []})
        self.assertEqual((status, body["title"], body["priority"], body["tags"]), (200, "new", 5, []))
        self.assertEqual(self.call("GET", f"/tasks/{task['id']}")[1], body)

    def test_patch_normalises_tags_like_create(self):
        project = self.project()
        task = self.task(project["id"])
        status, body = self.call("PATCH", f"/tasks/{task['id']}", {"tags": [" Urgent", "urgent", "Home"]})
        self.assertEqual((status, body["tags"]), (200, ["urgent", "home"]))
        listed = self.call("GET", "/tasks?tag=urgent")[1]
        self.assertEqual([t["id"] for t in listed["items"]], [task["id"]])
        self.assertEqual(self.rows("SELECT tag FROM task_tags ORDER BY position"), [("urgent",), ("home",)])

    def test_patch_rejects_other_fields_empty_bodies_and_bad_values(self):
        project = self.project()
        task = self.task(project["id"], "keep", priority=2, tags=["a"])
        bad = [{}, {"status": "done"}, {"project_id": 1}, {"title": "x", "status": "done"}, {"title": ""},
               {"priority": 9}, {"tags": ["x" * 21]}, {"title": "fine", "priority": 0}, {"title": None}]
        for body in bad:
            self.assertEqual(self.call("PATCH", f"/tasks/{task['id']}", body)[0], 422, body)
        self.assertEqual(self.call("GET", f"/tasks/{task['id']}")[1], task)
        self.assertEqual(self.call("PATCH", "/tasks/999", {"title": "x"})[0], 404)

    def test_delete_removes_the_task_and_frees_what_waited_on_it(self):
        project = self.project()
        blocker, waiting = self.task(project["id"], tags=["x"]), self.task(project["id"])
        self.block(waiting["id"], blocker["id"])
        self.block(blocker["id"], self.task(project["id"])["id"])
        self.assertEqual(self.call("DELETE", f"/tasks/{blocker['id']}")[0], 204)
        self.assertEqual(self.call("GET", f"/tasks/{blocker['id']}")[0], 404)
        self.assertEqual(self.call("DELETE", f"/tasks/{blocker['id']}")[0], 404)
        self.assertEqual(self.call("GET", f"/tasks/{waiting['id']}")[1]["blocked_by"], [])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM blockers")[0][0], 0)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM task_tags")[0][0], 0)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM tasks WHERE id = ?", (blocker["id"],))[0][0], 0)
        self.go(waiting["id"], "doing")
        self.go(waiting["id"], "done")

    def test_move(self):
        a, b = self.project("A"), self.project("B")
        task = self.task(a["id"], tags=["x"])
        status, moved = self.call("POST", f"/tasks/{task['id']}/move", {"project_id": b["id"]})
        self.assertEqual(status, 200)
        self.assertEqual(moved, dict(task, project_id=b["id"]))
        self.assertEqual(self.call("GET", f"/projects/{a['id']}")[1]["task_counts"]["todo"], 0)
        self.assertEqual(self.call("GET", f"/projects/{b['id']}")[1]["task_counts"]["todo"], 1)
        self.assertEqual(self.call("POST", f"/tasks/{task['id']}/move", {"project_id": b["id"]})[0], 200)
        self.assertEqual(self.call("POST", f"/tasks/{task['id']}/move", {"project_id": 999})[0], 404)
        self.assertEqual(self.call("POST", "/tasks/999/move", {"project_id": b["id"]})[0], 404)
        for body in ({}, {"project_id": "1"}, {"project_id": None}, {"project_id": 1.5}, {"project_id": True}):
            self.assertEqual(self.call("POST", f"/tasks/{task['id']}/move", body)[0], 422, body)
        self.assertEqual(self.call("GET", f"/tasks/{task['id']}")[1]["project_id"], b["id"])


class ListTests(ApiTest):
    def test_sorted_by_priority_then_id(self):
        project = self.project()
        made = [self.task(project["id"], f"t{i}", priority=p)["id"] for i, p in enumerate([3, 5, 1, 5, 3])]
        status, listed = self.call("GET", "/tasks")
        self.assertEqual(status, 200)
        self.assertEqual([t["id"] for t in listed["items"]], [made[1], made[3], made[0], made[4], made[2]])
        self.assertEqual(listed["total"], 5)

    def test_filters_combine(self):
        a, b = self.project("A"), self.project("B")
        one = self.task(a["id"], tags=["red", "big"])
        two = self.task(a["id"], tags=["red"])
        three = self.task(b["id"], tags=["red"])
        self.go(two["id"], "doing")

        def ids(query):
            status, body = self.call("GET", "/tasks" + query)
            self.assertEqual(status, 200, query)
            self.assertEqual(body["total"], len(body["items"]), query)
            return sorted(t["id"] for t in body["items"])

        self.assertEqual(ids(f"?project_id={a['id']}"), [one["id"], two["id"]])
        self.assertEqual(ids("?status=todo"), [one["id"], three["id"]])
        self.assertEqual(ids("?tag=red"), [one["id"], two["id"], three["id"]])
        self.assertEqual(ids("?tag=%20RED%20"), [one["id"], two["id"], three["id"]])
        self.assertEqual(ids("?tag=big"), [one["id"]])
        self.assertEqual(ids("?tag=re"), [])
        self.assertEqual(ids(f"?project_id={a['id']}&status=doing&tag=red"), [two["id"]])
        self.assertEqual(ids(f"?project_id={b['id']}&status=doing"), [])
        self.assertEqual(ids("?project_id=999"), [])
        self.assertEqual(ids(f"?project_id={10**30}"), [])
        self.assertEqual(ids("?status=done"), [])

    def test_paging_and_total(self):
        project, other = self.project("A"), self.project("B")
        made = [self.task(project["id"], f"t{i}")["id"] for i in range(5)]
        self.task(other["id"])
        query = f"/tasks?project_id={project['id']}"
        page = self.call("GET", query + "&limit=2")[1]
        self.assertEqual(([t["id"] for t in page["items"]], page["total"]), (made[:2], 5))
        page = self.call("GET", query + "&limit=2&offset=2")[1]
        self.assertEqual(([t["id"] for t in page["items"]], page["total"]), (made[2:4], 5))
        page = self.call("GET", query + "&limit=2&offset=4")[1]
        self.assertEqual(([t["id"] for t in page["items"]], page["total"]), (made[4:], 5))
        page = self.call("GET", query + "&offset=50")[1]
        self.assertEqual((page["items"], page["total"]), ([], 5))
        self.assertEqual(self.call("GET", "/tasks?limit=1")[1]["total"], 6)

    def test_default_limit_is_twenty_and_maximum_a_hundred(self):
        project = self.project()
        for i in range(21):
            self.task(project["id"], f"t{i}")
        page = self.call("GET", "/tasks")[1]
        self.assertEqual((len(page["items"]), page["total"]), (20, 21))
        self.assertEqual(len(self.call("GET", "/tasks?limit=100")[1]["items"]), 21)

    def test_bad_query_values_are_422(self):
        for query in ("?limit=0", "?limit=101", "?limit=x", "?limit=-1", "?limit=", "?offset=-1", "?offset=x",
                      "?status=open", "?status=", "?project_id=abc", "?project_id=1.5",
                      "?limit=5%0A", "?offset=0%0A", "?project_id=1%0A"):
            self.assertEqual(self.call("GET", "/tasks" + query)[0], 422, query)


class WorkflowTests(ApiTest):
    def test_allowed_moves_and_completed_at(self):
        task = self.task(self.project()["id"])
        self.assertIsNone(self.go(task["id"], "doing")["completed_at"])
        done = self.go(task["id"], "done")
        self.assertEqual(done["status"], "done")
        self.assertIsInstance(done["completed_at"], str)
        reopened = self.go(task["id"], "doing")
        self.assertEqual((reopened["status"], reopened["completed_at"]), ("doing", None))
        self.assertIsNone(self.call("GET", f"/tasks/{task['id']}")[1]["completed_at"])
        self.assertEqual(self.rows("SELECT completed_at FROM tasks")[0][0], None)
        back = self.go(task["id"], "todo")
        self.assertEqual((back["status"], back["completed_at"]), ("todo", None))

    def test_other_moves_are_409_and_change_nothing(self):
        task = self.task(self.project()["id"])
        for status, refused in (("todo", ("todo", "done")), ("doing", ("doing",)), ("done", ("done", "todo"))):
            if status != "todo":
                self.go(task["id"], status)
            before = self.call("GET", f"/tasks/{task['id']}")[1]
            for to in refused:
                self.go(task["id"], to, expect=409)
            self.assertEqual(self.call("GET", f"/tasks/{task['id']}")[1], before)

    def test_bad_requests(self):
        task = self.task(self.project()["id"])
        for body in ({}, {"to": "finished"}, {"to": None}, {"to": 1}, {"to": ["done"]}):
            self.assertEqual(self.call("POST", f"/tasks/{task['id']}/transition", body)[0], 422, body)
        self.assertEqual(self.call("POST", "/tasks/999/transition", {"to": "doing"})[0], 404)


class BlockingTests(ApiTest):
    def setUp(self):
        super().setUp()
        self.p = self.project()["id"]

    def test_put_is_idempotent_and_lists_ascending(self):
        a, b, c = (self.task(self.p)["id"] for _ in range(3))
        self.assertEqual(self.block(a, c)["blocked_by"], [c])
        self.assertEqual(self.block(a, b)["blocked_by"], [b, c])
        self.assertEqual(self.block(a, b)["blocked_by"], [b, c])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM blockers")[0][0], 2)
        self.block(a, 999, expect=404)
        self.block(999, a, expect=404)

    def test_blockers_may_be_in_another_project(self):
        other = self.project("Other")["id"]
        a, b = self.task(self.p)["id"], self.task(other)["id"]
        self.assertEqual(self.block(a, b)["blocked_by"], [b])

    def test_no_self_blocking_and_no_cycles_of_any_length(self):
        a, b, c, d = (self.task(self.p)["id"] for _ in range(4))
        self.block(a, a, expect=409)
        self.block(a, b)
        self.block(b, a, expect=409)
        self.block(b, c)
        self.block(c, a, expect=409)
        self.block(c, d)
        self.block(d, a, expect=409)
        self.block(d, b, expect=409)
        self.assertEqual(self.rows("SELECT task_id, blocker_id FROM blockers ORDER BY 1"), [(a, b), (b, c), (c, d)])
        self.block(a, d)  # a second path to d is not a cycle

    def test_remove(self):
        a, b = self.task(self.p)["id"], self.task(self.p)["id"]
        self.block(a, b)
        self.assertEqual(self.call("DELETE", f"/tasks/{a}/blockers/{b}")[0], 204)
        self.assertEqual(self.call("GET", f"/tasks/{a}")[1]["blocked_by"], [])
        self.assertEqual(self.call("DELETE", f"/tasks/{a}/blockers/{b}")[0], 404)
        self.assertEqual(self.call("DELETE", f"/tasks/999/blockers/{b}")[0], 404)

    def test_a_task_cannot_finish_before_what_it_waits_on(self):
        a, b = self.task(self.p)["id"], self.task(self.p)["id"]
        self.block(a, b)
        self.go(a, "doing")
        self.go(a, "done", expect=409)
        self.assertEqual(self.call("GET", f"/tasks/{a}")[1]["status"], "doing")
        self.go(b, "doing")
        self.go(a, "done", expect=409)
        self.go(b, "done")
        self.go(a, "done")
        # re-opening the blocker leaves the finished task alone
        self.go(b, "doing")
        self.assertEqual(self.call("GET", f"/tasks/{a}")[1]["status"], "done")

    def test_removing_the_relation_unblocks(self):
        a, b = self.task(self.p)["id"], self.task(self.p)["id"]
        self.block(a, b)
        self.go(a, "doing")
        self.call("DELETE", f"/tasks/{a}/blockers/{b}")
        self.go(a, "done")


class ProtocolTests(ApiTest):
    def test_invalid_json_is_400_and_a_non_object_422(self):
        project = self.project()
        task = self.task(project["id"])
        targets = [("POST", "/projects"), ("POST", f"/projects/{project['id']}/tasks"), ("PATCH", f"/tasks/{task['id']}"),
                   ("POST", f"/tasks/{task['id']}/transition"), ("POST", f"/tasks/{task['id']}/move")]
        for method, path in targets:
            self.assertEqual(self.call(method, path, raw=b"{nope")[0], 400, path)
            self.assertEqual(self.call(method, path)[0], 400, path)
            for raw in (b"[]", b'"x"', b"3", b"null"):
                self.assertEqual(self.call(method, path, raw=raw)[0], 422, (path, raw))

    def test_nan_and_infinity_are_not_json(self):
        project = self.project()
        for constant in (b"NaN", b"Infinity", b"-Infinity"):
            self.assertEqual(self.call("POST", "/projects", raw=b'{"name": "x", "extra": ' + constant + b"}")[0], 400)
            body = b'{"title": "t", "priority": ' + constant + b"}"
            self.assertEqual(self.call("POST", f"/projects/{project['id']}/tasks", raw=body)[0], 400)
        self.assertEqual(len(self.call("GET", "/projects")[1]), 1)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM tasks")[0][0], 0)

    def test_integers_of_any_length_are_only_out_of_range(self):
        project = self.project()
        task = self.task(project["id"])
        huge = "9" * 5000
        self.assertEqual(self.call("GET", f"/tasks/{huge}")[0], 404)
        self.assertEqual(self.call("GET", f"/projects/{huge}")[0], 404)
        self.assertEqual(self.call("PUT", f"/tasks/{task['id']}/blockers/{huge}")[0], 404)
        self.assertEqual(self.call("DELETE", f"/tasks/{task['id']}/blockers/{huge}")[0], 404)
        self.assertEqual(self.call("GET", f"/tasks?limit={huge}")[0], 422)
        self.assertEqual(self.call("GET", f"/tasks?offset={huge}")[1], {"items": [], "total": 1})
        self.assertEqual(self.call("GET", f"/tasks?project_id={huge}")[1], {"items": [], "total": 0})
        self.assertEqual(self.call("GET", f"/tasks?project_id=-{huge}")[1], {"items": [], "total": 0})
        self.assertEqual(self.call("GET", f"/tasks?limit={'0' * 5000}5")[1]["total"], 1)
        raw = lambda text: text.encode("ascii")  # noqa: E731
        self.assertEqual(self.call("POST", f"/projects/{project['id']}/tasks", raw=raw('{"title": "t", "priority": %s}' % huge))[0], 422)
        self.assertEqual(self.call("POST", f"/tasks/{task['id']}/move", raw=raw('{"project_id": %s}' % huge))[0], 404)
        self.assertEqual(self.call("POST", f"/tasks/{task['id']}/move", raw=raw('{"project_id": -%s}' % huge))[0], 404)

    def test_text_that_is_not_unicode_is_400(self):
        project = self.project()
        lone = b'"\\ud800"'
        self.assertEqual(self.call("POST", "/projects", raw=b'{"name": ' + lone + b"}")[0], 400)
        for body in (b'{"title": ' + lone + b"}", b'{"title": "t", "tags": [' + lone + b"]}"):
            self.assertEqual(self.call("POST", f"/projects/{project['id']}/tasks", raw=body)[0], 400, body)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM tasks")[0][0], 0)

    def test_unknown_paths_are_404_and_unsupported_methods_405(self):
        project = self.project()
        task = self.task(project["id"])
        for path in ("/", "/project", "/tasks/abc", "/tasks/1/blockers", "/projects/1/archive/x", "/tasks/"):
            self.assertEqual(self.call("GET", path)[0], 404, path)
        refused = [("DELETE", "/projects"), ("PUT", f"/projects/{project['id']}"), ("GET", f"/projects/{project['id']}/archive"),
                   ("GET", f"/projects/{project['id']}/tasks"), ("POST", "/tasks"), ("PUT", f"/tasks/{task['id']}"),
                   ("GET", f"/tasks/{task['id']}/transition"), ("GET", f"/tasks/{task['id']}/move"),
                   ("POST", f"/tasks/{task['id']}/blockers/{task['id']}")]
        for method, path in refused:
            self.assertEqual(self.call(method, path)[0], 405, (method, path))
        # a method the server has never heard of takes the same two answers
        self.assertEqual(self.call("FOO", "/projects")[0], 405)
        self.assertEqual(self.call("FOO", "/nowhere")[0], 404)


class PersistenceTests(ApiTest):
    def test_everything_survives_a_restart(self):
        project = self.project("Alpha")
        archived = self.project("Old")
        self.call("POST", f"/projects/{archived['id']}/archive")
        blocker = self.task(project["id"], "first", priority=4, tags=["a", "b"])
        waiting = self.task(project["id"], "second")
        self.block(waiting["id"], blocker["id"])
        self.go(blocker["id"], "doing")
        done = self.go(blocker["id"], "done")
        before = (self.call("GET", "/projects?include_archived=true")[1], self.call("GET", "/tasks")[1])
        self.stop()
        self.start()
        after = (self.call("GET", "/projects?include_archived=true")[1], self.call("GET", "/tasks")[1])
        self.assertEqual(after, before)
        self.assertEqual(self.call("GET", f"/tasks/{blocker['id']}")[1], done)
        self.assertEqual(self.call("GET", f"/tasks/{waiting['id']}")[1]["blocked_by"], [blocker["id"]])


if __name__ == "__main__":
    unittest.main()
