"""Smoke tests for the Notes API: the happy path of creating and reading a note."""

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


class NotesSmokeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = app.make_server(port=0, db_path=os.path.join(self.tmp.name, "notes.db"), quiet=True)
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

    def test_create_returns_the_note(self):
        status, note = self.call("POST", "/notes", {"title": "hello"})
        self.assertEqual(status, 201)
        self.assertEqual(note["title"], "hello")
        self.assertIsInstance(note["id"], int)

    def test_created_note_can_be_read(self):
        _, note = self.call("POST", "/notes", {"title": "hello"})
        status, got = self.call("GET", f"/notes/{note['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(got["title"], "hello")

    def test_empty_title_is_rejected(self):
        status, _ = self.call("POST", "/notes", {"title": "   "})
        self.assertEqual(status, 422)

    def test_delete_of_a_note_returns_204(self):
        _, note = self.call("POST", "/notes", {"title": "bye"})
        status, _ = self.call("DELETE", f"/notes/{note['id']}")
        self.assertEqual(status, 204)


if __name__ == "__main__":
    unittest.main()
