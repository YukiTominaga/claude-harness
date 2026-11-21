"""Tests for the notes API (app.py), exercised over real HTTP.

Each server is a real `python3 app.py` subprocess on a free port (NOTES_PORT=0,
the port is read from its startup line) with a temporary NOTES_DB. Nothing here
touches port 8765 or ./notes.db.
"""

import contextlib
import http.client
import json
import os
import queue
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "app.py")
APP = os.path.abspath(APP)


def rows(db_path, sql):
    """Read straight from the SQLite file, the way the API's clients never do."""
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        return conn.execute(sql).fetchall()


class Server:
    """A running app.py with its own database file."""

    def __init__(self, db_path, app=APP, port="0", extra_env=None):
        env = dict(os.environ, NOTES_PORT=port)
        env.pop("NOTES_DB", None)
        if db_path is not None:
            env["NOTES_DB"] = db_path
        env.update(extra_env or {})
        self._stderr = tempfile.TemporaryFile()
        self.proc = subprocess.Popen(
            [sys.executable, app], env=env, stdout=subprocess.PIPE, stderr=self._stderr
        )
        line = self._first_line()
        match = re.search(r"http://127\.0\.0\.1:(\d+)", line)
        if not match:
            self.stop()
            raise AssertionError(f"app.py did not report a port; first line: {line!r}")
        self.port = int(match.group(1))

    def _first_line(self):
        lines = queue.Queue()
        threading.Thread(
            target=lambda: lines.put(self.proc.stdout.readline().decode()), daemon=True
        ).start()
        try:
            return lines.get(timeout=15)
        except queue.Empty:
            self.stop()
            raise AssertionError("app.py printed nothing within 15 seconds") from None

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc.stdout.close()
        self._stderr.close()

    def connection(self):
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)

    def request(self, method, path, body=None, headers=None, conn=None):
        """Return (status, headers, raw bytes). `body` is JSON-encoded unless bytes."""
        if body is not None and not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body).encode("utf-8")
        own = conn is None
        conn = conn or self.connection()
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            return resp.status, resp, resp.read()
        finally:
            if own:
                conn.close()

    def json(self, method, path, body=None, **kwargs):
        status, resp, raw = self.request(method, path, body, **kwargs)
        return status, (json.loads(raw) if raw else None)


class ApiTestCase(unittest.TestCase):
    """One server and one empty database per test."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="notes-api-test-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.db_path = os.path.join(self.tmp, "notes.db")
        self.server = Server(self.db_path)
        self.addCleanup(self.server.stop)

    def create(self, title="a note", **extra):
        status, note = self.server.json("POST", "/notes", {"title": title, **extra})
        self.assertEqual(status, 201, note)
        return note

    def assert_error(self, status, payload, expected):
        self.assertEqual(status, expected, payload)
        self.assertIsInstance(payload, dict)
        self.assertEqual(list(payload), ["error"])
        self.assertIsInstance(payload["error"], str)
        self.assertTrue(payload["error"].strip())

    def assert_nothing_stored(self):
        self.assertEqual(self.server.json("GET", "/notes"), (200, []))
        self.assertEqual(rows(self.db_path, "SELECT id FROM notes"), [])


class CreateTests(ApiTestCase):
    def test_create_returns_201_with_the_note(self):
        status, resp, raw = self.server.request("POST", "/notes", {"title": "Groceries", "body": "milk"})
        self.assertEqual(status, 201)
        self.assertEqual(resp.getheader("Content-Type"), "application/json")
        note = json.loads(raw)
        self.assertEqual(set(note), {"id", "title", "body"})
        self.assertIsInstance(note["id"], int)
        self.assertGreater(note["id"], 0)
        self.assertEqual((note["title"], note["body"]), ("Groceries", "milk"))

    def test_omitted_body_is_empty_string(self):
        note = self.create("no body")
        self.assertEqual(note["body"], "")
        self.assertEqual(self.server.json("GET", f"/notes/{note['id']}")[1]["body"], "")

    def test_title_is_trimmed(self):
        note = self.create("  \t padded \n ")
        self.assertEqual(note["title"], "padded")
        self.assertEqual(self.server.json("GET", f"/notes/{note['id']}")[1]["title"], "padded")

    def test_body_is_stored_as_given(self):
        note = self.create("t", body="  keep\nthis  ")
        self.assertEqual(self.server.json("GET", f"/notes/{note['id']}")[1]["body"], "  keep\nthis  ")

    def test_title_length_boundaries(self):
        self.assertEqual(self.create("x")["title"], "x")
        self.assertEqual(self.create("y" * 100)["title"], "y" * 100)
        # the limit applies after trimming
        self.assertEqual(self.create("  " + "z" * 100 + "  ")["title"], "z" * 100)
        status, payload = self.server.json("POST", "/notes", {"title": "y" * 101})
        self.assert_error(status, payload, 422)
        status, payload = self.server.json("POST", "/notes", {"title": " " + "y" * 101 + " "})
        self.assert_error(status, payload, 422)
        self.assertEqual(len(self.server.json("GET", "/notes")[1]), 3)

    def test_length_counts_characters_not_bytes(self):
        self.assertEqual(self.create("é" * 100)["title"], "é" * 100)
        self.assertEqual(self.create("\U0001F600" * 100)["title"], "\U0001F600" * 100)
        status, payload = self.server.json("POST", "/notes", {"title": "é" * 101})
        self.assert_error(status, payload, 422)

    def test_unicode_round_trip(self):
        note = self.create("日本語のメモ", body="naïve café \U0001F600")
        self.assertEqual(self.server.json("GET", f"/notes/{note['id']}")[1], note)
        self.assertEqual(note["title"], "日本語のメモ")

    def test_invalid_titles_are_422_and_store_nothing(self):
        bad_payloads = [
            {},
            {"body": "only a body"},
            {"title": ""},
            {"title": "   \t\n "},
            {"title": None},
            {"title": 5},
            {"title": True},
            {"title": ["a"]},
            {"title": {"a": 1}},
            {"title": "ok", "body": 5},
            {"title": "ok", "body": None},
            {"title": "ok", "body": ["x"]},
            {"title": "\ud800"},
            {"title": "ok", "body": "\udfff"},
        ]
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                status, resp = self.server.json("POST", "/notes", payload)
                self.assert_error(status, resp, 422)
        self.assert_nothing_stored()

    def test_valid_json_that_is_not_an_object_is_422(self):
        for raw in [b"[]", b'["title"]', b'"title"', b"42", b"null", b"true", b"[{\"title\": \"x\"}]"]:
            with self.subTest(raw=raw):
                status, resp = self.server.json("POST", "/notes", raw)
                self.assert_error(status, resp, 422)
        self.assert_nothing_stored()

    def test_invalid_json_is_400_and_stores_nothing(self):
        for raw in [b"", b"   ", b"not json", b'{"title": "x"', b"{'title': 'x'}", b'{"title": "x"} trailing',
                    b"\xff\xfe\x00", b'{"title": "\xff"}', b"[" * 100000]:
            with self.subTest(raw=raw[:30]):
                status, resp = self.server.json("POST", "/notes", raw)
                self.assert_error(status, resp, 400)
        status, resp = self.server.json("POST", "/notes")  # no body at all
        self.assert_error(status, resp, 400)
        self.assert_nothing_stored()

    def test_content_type_of_the_request_is_not_required(self):
        status, _, raw = self.server.request(
            "POST", "/notes", b'{"title": "curl default"}',
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(status, 201, raw)

    def test_chunked_request_body(self):
        body = b'{"title": "chunked"}'
        chunked = b"%x\r\n%s\r\n0\r\n\r\n" % (len(body), body)
        status, _, raw = self.server.request(
            "POST", "/notes", chunked, headers={"Transfer-Encoding": "chunked"}
        )
        self.assertEqual(status, 201, raw)
        self.assertEqual(json.loads(raw)["title"], "chunked")

    def test_oversized_body_is_413_json(self):
        # Declare a 2 MiB body but send none of it: the server must refuse on the header alone.
        status, payload = self.server.json("POST", "/notes", headers={"Content-Length": str(2 * 1024 * 1024)})
        self.assert_error(status, payload, 413)
        self.assert_nothing_stored()

    def test_invalid_content_length_is_400_json(self):
        status, payload = self.server.json("POST", "/notes", headers={"Content-Length": "abc"})
        self.assert_error(status, payload, 400)
        self.assert_nothing_stored()

    def test_ids_ascend_are_never_reused_and_survive_deleting_the_newest(self):
        first, second = self.create("one"), self.create("two")
        self.assertLess(first["id"], second["id"])
        self.assertEqual(self.server.request("DELETE", f"/notes/{second['id']}")[0], 204)
        third = self.create("three")
        self.assertGreater(third["id"], second["id"])

    def test_concurrent_creates_get_distinct_ids(self):
        ids, errors = [], []

        def worker(n):
            try:
                ids.append(self.create(f"note {n}")["id"])
            except Exception as exc:  # reported below
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(set(ids)), 20)
        self.assertEqual([n["id"] for n in self.server.json("GET", "/notes")[1]], sorted(ids))


class ReadTests(ApiTestCase):
    def test_list_is_empty_array_when_there_are_no_notes(self):
        status, resp, raw = self.server.request("GET", "/notes")
        self.assertEqual(status, 200)
        self.assertEqual(resp.getheader("Content-Type"), "application/json")
        self.assertEqual(json.loads(raw), [])

    def test_list_is_a_top_level_array_in_creation_order(self):
        created = [self.create(f"note {n}", body=f"body {n}") for n in range(5)]
        status, notes = self.server.json("GET", "/notes")
        self.assertEqual(status, 200)
        self.assertEqual(notes, created)
        self.assertEqual([n["id"] for n in notes], sorted(n["id"] for n in notes))

    def test_get_one(self):
        note = self.create("find me", body="here")
        status, resp, raw = self.server.request("GET", f"/notes/{note['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(resp.getheader("Content-Type"), "application/json")
        self.assertEqual(json.loads(raw), note)

    def test_unknown_id_is_404(self):
        self.create("exists")
        status, payload = self.server.json("GET", "/notes/9999")
        self.assert_error(status, payload, 404)

    def test_ids_that_are_not_decimal_integers_are_404(self):
        self.create("exists")
        for segment in ["abc", "1.5", "-1", "0", "1e2", "0x1", "%20", "1%20", "", "99999999999999999999999",
                        "%D9%A1", "%E0%A5%A7", "1/2", "1%2F2"]:
            with self.subTest(segment=segment):
                status, payload = self.server.json("GET", f"/notes/{segment}")
                self.assert_error(status, payload, 404)

    def test_query_string_is_ignored(self):
        note = self.create("q")
        self.assertEqual(self.server.json("GET", "/notes?limit=1")[1], [note])
        self.assertEqual(self.server.json("GET", f"/notes/{note['id']}?x=y")[1], note)


class DeleteTests(ApiTestCase):
    def test_delete_returns_204_with_empty_body_and_removes_the_note(self):
        keep, gone = self.create("keep"), self.create("gone")
        status, resp, raw = self.server.request("DELETE", f"/notes/{gone['id']}")
        self.assertEqual(status, 204)
        self.assertEqual(raw, b"")
        self.assert_error(*self.server.json("GET", f"/notes/{gone['id']}"), 404)
        self.assertEqual(self.server.json("GET", "/notes")[1], [keep])
        self.assertEqual(rows(self.db_path, "SELECT id FROM notes"), [(keep["id"],)])

    def test_deleting_twice_or_an_unknown_id_is_404(self):
        note = self.create("once")
        self.assertEqual(self.server.request("DELETE", f"/notes/{note['id']}")[0], 204)
        self.assert_error(*self.server.json("DELETE", f"/notes/{note['id']}"), 404)
        self.assert_error(*self.server.json("DELETE", "/notes/424242"), 404)

    def test_delete_with_a_bad_id_is_404(self):
        keep = self.create("keep")
        for segment in ["abc", "-1", "1.5", "99999999999999999999999"]:
            with self.subTest(segment=segment):
                self.assert_error(*self.server.json("DELETE", f"/notes/{segment}"), 404)
        self.assertEqual(self.server.json("GET", "/notes")[1], [keep])


class ErrorShapeTests(ApiTestCase):
    def test_every_error_is_json_with_an_error_message(self):
        note = self.create("x")
        cases = [
            ("GET", "/", None, 404),
            ("GET", "/nope", None, 404),
            ("GET", "/notes/", None, 404),
            ("GET", f"/notes/{note['id']}/extra", None, 404),
            ("GET", "/notes//1", None, 404),
            ("PUT", "/notes", {"title": "x"}, 405),
            ("DELETE", "/notes", None, 405),
            ("POST", f"/notes/{note['id']}", {"title": "x"}, 405),
            ("PUT", f"/notes/{note['id']}", {"title": "x"}, 405),
            ("PATCH", f"/notes/{note['id']}", {"title": "x"}, 405),
            ("TRACE", "/notes", None, 501),
        ]
        for method, path, body, expected in cases:
            with self.subTest(method=method, path=path):
                status, resp, raw = self.server.request(method, path, body)
                self.assertEqual(status, expected)
                self.assertEqual(resp.getheader("Content-Type"), "application/json")
                payload = json.loads(raw)
                self.assertTrue(payload["error"].strip())
        self.assertEqual(self.server.json("GET", "/notes")[1], [note])

    def test_malformed_request_line_gets_a_json_400(self):
        with socket.create_connection(("127.0.0.1", self.server.port), timeout=10) as sock:
            sock.sendall(b"GARBAGE\r\n\r\n")
            data = b""
            while chunk := sock.recv(4096):
                data += chunk
        head, _, body = data.partition(b"\r\n\r\n")
        self.assertTrue(head.startswith(b"HTTP/1.1 400"), head)
        self.assertIn(b"application/json", head)
        self.assertTrue(json.loads(body)["error"].strip())

    def test_connection_stays_usable_after_errors(self):
        conn = self.server.connection()
        self.addCleanup(conn.close)
        steps = [
            ("POST", "/notes", b"not json", 400),
            ("POST", "/notes", {"title": ""}, 422),
            ("POST", "/nowhere", {"title": "ignored body"}, 404),
            ("GET", "/notes/abc", None, 404),
            ("POST", "/notes", {"title": "after the errors"}, 201),
            ("GET", "/notes", None, 200),
        ]
        for method, path, body, expected in steps:
            status, _, _ = self.server.request(method, path, body, conn=conn)
            self.assertEqual(status, expected, (method, path))


class StorageTests(ApiTestCase):
    def test_schema_matches_the_pinned_table(self):
        columns = {r[1]: r for r in rows(self.db_path, "PRAGMA table_info(notes)")}
        sql = rows(self.db_path, "SELECT sql FROM sqlite_master WHERE name = 'notes'")[0][0]
        self.assertEqual(list(columns), ["id", "title", "body"])
        self.assertEqual(columns["id"][2:3] + columns["id"][5:6], ("INTEGER", 1))
        self.assertEqual((columns["title"][2], columns["title"][3]), ("TEXT", 1))
        self.assertEqual((columns["body"][2], columns["body"][3], columns["body"][4]), ("TEXT", 1, "''"))
        self.assertIn("AUTOINCREMENT", sql.upper())

    def test_writes_reach_the_database_file(self):
        note = self.create("  stored  ", body="in sqlite")
        self.assertEqual(
            rows(self.db_path, "SELECT id, title, body FROM notes"), [(note["id"], "stored", "in sqlite")]
        )

    def test_notes_persist_across_a_server_restart(self):
        first = self.create("before restart", body="b1")
        second = self.create("also before")
        self.assertEqual(self.server.request("DELETE", f"/notes/{second['id']}")[0], 204)
        self.server.stop()

        self.server = Server(self.db_path)
        self.addCleanup(self.server.stop)
        self.assertEqual(self.server.json("GET", "/notes")[1], [first])
        self.assertEqual(self.server.json("GET", f"/notes/{first['id']}")[1], first)
        self.assert_error(*self.server.json("GET", f"/notes/{second['id']}"), 404)
        third = self.create("after restart")
        self.assertGreater(third["id"], second["id"])  # ids are not reused across restarts either

    def test_two_servers_on_different_databases_are_independent(self):
        other_db = os.path.join(self.tmp, "other.db")
        other = Server(other_db)
        self.addCleanup(other.stop)
        self.create("only in the first")
        self.assertEqual(other.json("GET", "/notes"), (200, []))
        self.assertTrue(os.path.exists(other_db))

    def test_notes_port_is_honoured(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = Server(os.path.join(self.tmp, "port.db"), port=str(port))
        self.addCleanup(server.stop)
        self.assertEqual(server.port, port)
        self.assertEqual(server.json("GET", "/notes"), (200, []))

    def test_default_database_is_notes_db_next_to_app_py(self):
        # Run a copy of app.py so the project's own ./notes.db is never touched.
        copy_dir = os.path.join(self.tmp, "project")
        os.mkdir(copy_dir)
        app_copy = os.path.join(copy_dir, "app.py")
        shutil.copy(APP, app_copy)
        server = Server(None, app=app_copy)
        self.addCleanup(server.stop)
        note = self.create_on(server, "default location")
        self.assertTrue(os.path.exists(os.path.join(copy_dir, "notes.db")))
        self.assertEqual(
            rows(os.path.join(copy_dir, "notes.db"), "SELECT id, title FROM notes"),
            [(note["id"], "default location")],
        )

    @staticmethod
    def create_on(server, title):
        status, note = server.json("POST", "/notes", {"title": title})
        assert status == 201, note
        return note

    def test_invalid_notes_port_exits_with_a_message(self):
        result = subprocess.run(
            [sys.executable, APP], env=dict(os.environ, NOTES_PORT="not-a-port", NOTES_DB=self.db_path),
            capture_output=True, text=True, timeout=15,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("NOTES_PORT", result.stderr)


if __name__ == "__main__":
    unittest.main()
