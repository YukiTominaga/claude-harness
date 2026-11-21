"""Smoke tests for the Tracker API: the happy path of filing a task and starting it."""

import http.client
import json
import os
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import app  # noqa: E402


class TrackerSmokeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = app.make_server(port=0, db_path=os.path.join(self.tmp.name, "tracker.db"), quiet=True)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def call(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            data = json.dumps(body).encode("utf-8") if body is not None else None
            conn.request(method, path, body=data, headers={"Content-Type": "application/json"} if data else {})
            resp = conn.getresponse()
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
        finally:
            conn.close()

    def test_create_a_project(self):
        status, project = self.call("POST", "/projects", {"name": "Alpha"})
        self.assertEqual(status, 201)
        self.assertEqual(project["name"], "Alpha")
        self.assertEqual(self.call("GET", f"/projects/{project['id']}")[0], 200)

    def test_empty_project_name_is_rejected(self):
        self.assertEqual(self.call("POST", "/projects", {"name": "  "})[0], 422)

    def test_file_a_task_and_read_it(self):
        _, project = self.call("POST", "/projects", {"name": "Alpha"})
        status, task = self.call("POST", f"/projects/{project['id']}/tasks", {"title": "write it", "tags": ["home"]})
        self.assertEqual(status, 201)
        self.assertEqual((task["title"], task["status"], task["tags"]), ("write it", "todo", ["home"]))
        self.assertEqual(self.call("GET", f"/tasks/{task['id']}")[1]["title"], "write it")

    def test_start_a_task(self):
        _, project = self.call("POST", "/projects", {"name": "Alpha"})
        _, task = self.call("POST", f"/projects/{project['id']}/tasks", {"title": "write it"})
        status, started = self.call("POST", f"/tasks/{task['id']}/transition", {"to": "doing"})
        self.assertEqual((status, started["status"]), (200, "doing"))

    def test_list_tasks(self):
        _, project = self.call("POST", "/projects", {"name": "Alpha"})
        self.call("POST", f"/projects/{project['id']}/tasks", {"title": "one"})
        status, listed = self.call("GET", "/tasks")
        self.assertEqual(status, 200)
        self.assertEqual(len(listed["items"]), 1)

    def test_delete_a_task(self):
        _, project = self.call("POST", "/projects", {"name": "Alpha"})
        _, task = self.call("POST", f"/projects/{project['id']}/tasks", {"title": "one"})
        self.assertEqual(self.call("DELETE", f"/tasks/{task['id']}")[0], 204)


if __name__ == "__main__":
    unittest.main()
