"""End-to-end tests for the Notes API.

Most tests run the real HTTP server in a background thread against a temporary
SQLite file and talk to it over a socket. The restart tests launch the real
`python3 app.py` entrypoint as a subprocess.
"""

import http.client
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import app  # noqa: E402


class Client:
    """Minimal HTTP client; one connection per request."""

    def __init__(self, host, port):
        self.host, self.port = host, port

    def request(self, method, path, body=None, raw=None, headers=None):
        """Send a request. `body` is JSON-encoded; `raw` is sent as-is (bytes)."""
        hdrs = dict(headers or {})
        data = raw
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        conn = http.client.HTTPConnection(self.host, self.port, timeout=10)
        try:
            conn.request(method, path, body=data, headers=hdrs)
            resp = conn.getresponse()
            payload = resp.read()
            return resp.status, resp, payload
        finally:
            conn.close()

    def json(self, method, path, body=None, raw=None, headers=None):
        status, resp, payload = self.request(method, path, body, raw, headers)
        return status, (json.loads(payload) if payload else None)


class ServerTestCase(unittest.TestCase):
    """Fresh server + fresh database per test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "notes.db")
        self.server = app.make_server("127.0.0.1", 0, self.db_path, quiet=True)
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        self.thread.start()
        host, port = self.server.server_address[:2]
        self.client = Client(host, port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tmp.cleanup()

    def db_rows(self, sql="SELECT id, title, body FROM notes ORDER BY id"):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()

    def create(self, title="a note", body=None):
        payload = {"title": title}
        if body is not None:
            payload["body"] = body
        status, note = self.client.json("POST", "/notes", payload)
        self.assertEqual(status, 201, note)
        return note


class CreateNoteTests(ServerTestCase):
    def test_create_returns_201_and_the_note(self):
        status, note = self.client.json(
            "POST", "/notes", {"title": "Groceries", "body": "milk, eggs"}
        )
        self.assertEqual(status, 201)
        self.assertEqual(note["title"], "Groceries")
        self.assertEqual(note["body"], "milk, eggs")
        self.assertIsInstance(note["id"], int)
        self.assertTrue(note["created_at"])

    def test_response_is_json_content_type(self):
        _, resp, _ = self.client.request("POST", "/notes", {"title": "x"})
        self.assertTrue(resp.getheader("Content-Type").startswith("application/json"))

    def test_body_is_optional_and_defaults_to_empty_string(self):
        note = self.create("no body")
        self.assertEqual(note["body"], "")
        self.assertEqual(self.db_rows(), [(note["id"], "no body", "")])

    def test_null_body_is_treated_as_empty(self):
        status, note = self.client.json("POST", "/notes", {"title": "t", "body": None})
        self.assertEqual(status, 201)
        self.assertEqual(note["body"], "")

    def test_title_is_trimmed_before_storing(self):
        note = self.create("   padded   ")
        self.assertEqual(note["title"], "padded")
        self.assertEqual(self.db_rows()[0][1], "padded")

    def test_title_length_boundaries(self):
        self.assertEqual(self.create("x" * 100)["title"], "x" * 100)
        # 100 characters plus surrounding whitespace is still valid after trimming
        self.assertEqual(self.create("  " + "y" * 100 + "  ")["title"], "y" * 100)
        status, _ = self.client.json("POST", "/notes", {"title": "z" * 101})
        self.assertEqual(status, 422)
        self.assertEqual(len(self.db_rows()), 2)

    def test_title_counts_characters_not_bytes(self):
        self.assertEqual(len(self.create("é" * 100)["title"]), 100)

    def test_unicode_round_trips(self):
        note = self.create("日本語のメモ", "naïve café ☕")
        status, fetched = self.client.json("GET", f"/notes/{note['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(fetched["title"], "日本語のメモ")
        self.assertEqual(fetched["body"], "naïve café ☕")

    def test_invalid_titles_return_422_and_store_nothing(self):
        bad_payloads = [
            {},
            {"body": "only a body"},
            {"title": ""},
            {"title": "   \t\n "},
            {"title": "z" * 101},
            {"title": None},
            {"title": 5},
            {"title": ["a"]},
        ]
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                status, err = self.client.json("POST", "/notes", payload)
                self.assertEqual(status, 422)
                self.assertIn("error", err)
        self.assertEqual(self.db_rows(), [])
        self.assertEqual(self.client.json("GET", "/notes"), (200, []))

    def test_non_string_body_returns_422_and_stores_nothing(self):
        for body in (5, ["a"], {"a": 1}, True):
            with self.subTest(body=body):
                status, _ = self.client.json("POST", "/notes", {"title": "t", "body": body})
                self.assertEqual(status, 422)
        self.assertEqual(self.db_rows(), [])

    def test_json_that_is_not_an_object_returns_422(self):
        for raw in (b"[]", b'"title"', b"42", b"null", b"true"):
            with self.subTest(raw=raw):
                status, _ = self.client.json("POST", "/notes", raw=raw)
                self.assertEqual(status, 422)
        self.assertEqual(self.db_rows(), [])

    def test_invalid_json_returns_400_and_stores_nothing(self):
        bad_bodies = [
            b"{not json",
            b'{"title": "unterminated',
            b"",
            b"title=hello",
            b"\xff\xfe\x00",  # not valid UTF-8
        ]
        for raw in bad_bodies:
            with self.subTest(raw=raw):
                status, err = self.client.json("POST", "/notes", raw=raw)
                self.assertEqual(status, 400)
                self.assertIn("error", err)
        self.assertEqual(self.db_rows(), [])

    def test_invalid_json_is_400_even_when_it_would_also_fail_validation(self):
        status, _ = self.client.json("POST", "/notes", raw=b'{"title": ')
        self.assertEqual(status, 400)

    def test_post_to_unknown_path_with_body_is_404(self):
        status, _ = self.client.json("POST", "/nope", {"title": "t"})
        self.assertEqual(status, 404)


class ReadNoteTests(ServerTestCase):
    def test_list_is_empty_on_fresh_database(self):
        self.assertEqual(self.client.json("GET", "/notes"), (200, []))

    def test_list_returns_all_notes_in_creation_order(self):
        created = [self.create(f"note {i}", f"body {i}") for i in range(5)]
        status, listed = self.client.json("GET", "/notes")
        self.assertEqual(status, 200)
        self.assertEqual(listed, created)
        self.assertEqual([n["title"] for n in listed], [f"note {i}" for i in range(5)])

    def test_ids_are_unique_and_increasing(self):
        ids = [self.create(f"n{i}")["id"] for i in range(4)]
        self.assertEqual(ids, sorted(set(ids)))

    def test_get_one_returns_the_note(self):
        note = self.create("findable", "here")
        self.create("another")
        status, fetched = self.client.json("GET", f"/notes/{note['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(fetched, note)

    def test_get_unknown_id_is_404(self):
        self.create("exists")
        status, err = self.client.json("GET", "/notes/9999")
        self.assertEqual(status, 404)
        self.assertIn("error", err)

    def test_get_malformed_or_out_of_range_id_is_404(self):
        for suffix in ("abc", "0", "-1", "1.5", "1/2", "9" * 40, "%20"):
            with self.subTest(id=suffix):
                status, _ = self.client.json("GET", f"/notes/{suffix}")
                self.assertEqual(status, 404)

    def test_unknown_paths_are_404(self):
        for path in ("/", "/note", "/notes/", "/other/1"):
            with self.subTest(path=path):
                status, _ = self.client.json("GET", path)
                self.assertEqual(status, 404)

    def test_query_string_is_ignored(self):
        note = self.create("q")
        status, listed = self.client.json("GET", "/notes?x=1")
        self.assertEqual((status, listed), (200, [note]))
        status, fetched = self.client.json("GET", f"/notes/{note['id']}?x=1")
        self.assertEqual((status, fetched), (200, note))

    def test_unsupported_methods_return_405_with_allow_header(self):
        note = self.create("m")
        for method, path in (("PUT", "/notes"), ("PATCH", f"/notes/{note['id']}"),
                             ("POST", f"/notes/{note['id']}")):
            with self.subTest(method=method, path=path):
                status, resp, _ = self.client.request(method, path, {"title": "x"})
                self.assertEqual(status, 405)
                self.assertTrue(resp.getheader("Allow"))
        # nothing was changed by any of those
        self.assertEqual(self.client.json("GET", "/notes"), (200, [note]))


class DeleteNoteTests(ServerTestCase):
    def test_delete_returns_204_with_no_body(self):
        note = self.create("doomed")
        status, resp, payload = self.client.request("DELETE", f"/notes/{note['id']}")
        self.assertEqual(status, 204)
        self.assertEqual(payload, b"")

    def test_deleted_note_is_gone_from_get_list_and_datastore(self):
        keep_before = self.create("before")
        doomed = self.create("doomed", "bye")
        keep_after = self.create("after")
        self.assertEqual(self.client.request("DELETE", f"/notes/{doomed['id']}")[0], 204)

        status, err = self.client.json("GET", f"/notes/{doomed['id']}")
        self.assertEqual(status, 404)
        self.assertIn("error", err)
        self.assertEqual(self.client.json("GET", "/notes"), (200, [keep_before, keep_after]))
        # the row is physically gone, not flagged
        self.assertEqual(
            self.db_rows(f"SELECT COUNT(*) FROM notes WHERE id = {doomed['id']}"), [(0,)]
        )
        self.assertEqual(
            self.db_rows(), [(keep_before["id"], "before", ""), (keep_after["id"], "after", "")]
        )

    def test_other_notes_are_untouched(self):
        a, b = self.create("a", "1"), self.create("b", "2")
        self.client.request("DELETE", f"/notes/{a['id']}")
        self.assertEqual(self.client.json("GET", f"/notes/{b['id']}"), (200, b))

    def test_delete_unknown_id_is_404_and_changes_nothing(self):
        note = self.create("stays")
        status, err = self.client.json("DELETE", "/notes/9999")
        self.assertEqual(status, 404)
        self.assertIn("error", err)
        self.assertEqual(self.client.json("GET", "/notes"), (200, [note]))

    def test_delete_twice_is_404_the_second_time(self):
        note = self.create("once")
        self.assertEqual(self.client.request("DELETE", f"/notes/{note['id']}")[0], 204)
        self.assertEqual(self.client.request("DELETE", f"/notes/{note['id']}")[0], 404)

    def test_delete_malformed_or_out_of_range_id_is_404(self):
        note = self.create("safe")
        for suffix in ("abc", "0", "-1", "9" * 40):
            with self.subTest(id=suffix):
                self.assertEqual(self.client.request("DELETE", f"/notes/{suffix}")[0], 404)
        self.assertEqual(self.client.json("GET", "/notes"), (200, [note]))

    def test_delete_on_collection_is_405_and_deletes_nothing(self):
        note = self.create("safe")
        status, resp, _ = self.client.request("DELETE", "/notes")
        self.assertEqual(status, 405)
        self.assertIn("POST", resp.getheader("Allow"))
        self.assertEqual(self.client.json("GET", "/notes"), (200, [note]))

    def test_item_allow_header_lists_get_and_delete(self):
        note = self.create("m")
        _, resp, _ = self.client.request("PUT", f"/notes/{note['id']}", {"title": "x"})
        self.assertEqual(sorted(resp.getheader("Allow").split(", ")), ["DELETE", "GET"])

    def test_delete_with_a_request_body_still_works(self):
        note = self.create("body on delete")
        status, _, _ = self.client.request("DELETE", f"/notes/{note['id']}", raw=b"ignored")
        self.assertEqual(status, 204)
        self.assertEqual(self.db_rows(), [])

    def test_ids_are_never_reused_after_delete(self):
        first = self.create("first")
        last = self.create("last")
        self.client.request("DELETE", f"/notes/{last['id']}")
        again = self.create("again")
        self.assertGreater(again["id"], last["id"])
        self.assertEqual(self.client.json("GET", f"/notes/{last['id']}")[0], 404)
        self.assertEqual(self.client.json("GET", "/notes")[1], [first, again])

    def test_deleting_everything_leaves_an_empty_list(self):
        notes = [self.create(f"n{i}") for i in range(3)]
        for n in notes:
            self.assertEqual(self.client.request("DELETE", f"/notes/{n['id']}")[0], 204)
        self.assertEqual(self.client.json("GET", "/notes"), (200, []))
        self.assertEqual(self.db_rows(), [])


class RestartProcess:
    """Run the real `python3 app.py` against a database file."""

    def __init__(self, db_path):
        self.db_path = db_path
        self.proc = None
        self.client = None

    def start(self):
        env = dict(os.environ, NOTES_PORT="0", NOTES_DB=self.db_path)
        self.proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "app.py")],
            cwd=tempfile.gettempdir(), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        line = self.proc.stdout.readline()  # "Notes API listening on http://H:P ..."
        if "listening on http://" not in line:
            self.stop()
            raise AssertionError(f"server did not start: {line!r}")
        host_port = line.split("http://", 1)[1].split()[0]
        host, port = host_port.rsplit(":", 1)
        self.client = Client(host, int(port))
        return self.client

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
        if self.proc:
            self.proc.wait(timeout=10)
            self.proc.stdout.close()
        self.proc = None


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "notes.db")
        self.proc = RestartProcess(self.db_path)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.proc.stop)

    def test_notes_survive_a_server_restart(self):
        client = self.proc.start()
        first = client.json("POST", "/notes", {"title": "one", "body": "1"})[1]
        second = client.json("POST", "/notes", {"title": "two"})[1]
        self.proc.stop()

        client = self.proc.start()
        status, listed = client.json("GET", "/notes")
        self.assertEqual(status, 200)
        self.assertEqual(listed, [first, second])
        self.assertEqual(client.json("GET", f"/notes/{first['id']}"), (200, first))

    def test_a_deleted_note_stays_deleted_after_restart(self):
        client = self.proc.start()
        keep = client.json("POST", "/notes", {"title": "keep"})[1]
        doomed = client.json("POST", "/notes", {"title": "doomed"})[1]
        self.assertEqual(client.request("DELETE", f"/notes/{doomed['id']}")[0], 204)
        self.proc.stop()

        client = self.proc.start()
        self.assertEqual(client.json("GET", f"/notes/{doomed['id']}")[0], 404)
        self.assertEqual(client.json("GET", "/notes"), (200, [keep]))
        # an id freed by delete is not handed out again after a restart
        new = client.json("POST", "/notes", {"title": "new"})[1]
        self.assertGreater(new["id"], doomed["id"])

    def test_ids_continue_after_restart(self):
        client = self.proc.start()
        first = client.json("POST", "/notes", {"title": "one"})[1]
        self.proc.stop()
        client = self.proc.start()
        second = client.json("POST", "/notes", {"title": "two"})[1]
        self.assertGreater(second["id"], first["id"])

    def test_default_port_and_database_location(self):
        # With no NOTES_* overrides the server binds 127.0.0.1:8765 and uses the
        # notes.db beside app.py. Only check the constants; do not touch the
        # real database file from a test.
        self.assertEqual(app.DEFAULT_HOST, "127.0.0.1")
        self.assertEqual(app.DEFAULT_PORT, 8765)
        self.assertEqual(app.DEFAULT_DB, os.path.join(ROOT, "notes.db"))


if __name__ == "__main__":
    unittest.main()
