"""Notes API: a tiny JSON HTTP API for short text notes.

Standard library only. Notes live in a SQLite file (default ./notes.db next to
this file), so they survive a restart of the server.

Run:  python3 app.py
Env:  NOTES_HOST (default 127.0.0.1), NOTES_PORT (default 8765),
      NOTES_DB (default notes.db beside this file)
"""

import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "notes.db")

TITLE_MAX = 100
SQLITE_MAX_INT = 2**63 - 1

NOTES_PATH = "/notes"
NOTE_PATH = re.compile(r"^/notes/(\d+)$", re.ASCII)

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    body       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
)
"""


# --------------------------------------------------------------------------
# Datastore
# --------------------------------------------------------------------------

class NoteStore:
    """SQLite-backed notes. One short-lived connection per operation, so the
    threaded server never shares a connection between threads."""

    def __init__(self, path):
        self.path = path
        self._run(SCHEMA)

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _run(self, sql, params=()):
        """Execute one statement in its own transaction; return (rows, rowcount)."""
        conn = self._connect()
        try:
            with conn:  # commits on success, rolls back on error
                cur = conn.execute(sql, params)
                return cur.fetchall(), cur.rowcount
        finally:
            conn.close()

    @staticmethod
    def _to_dict(row):
        return {
            "id": row["id"],
            "title": row["title"],
            "body": row["body"],
            "created_at": row["created_at"],
        }

    def create(self, title, body):
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn = self._connect()
        try:
            with conn:
                cur = conn.execute(
                    "INSERT INTO notes (title, body, created_at) VALUES (?, ?, ?)",
                    (title, body, created_at),
                )
                note_id = cur.lastrowid
        finally:
            conn.close()
        return {"id": note_id, "title": title, "body": body, "created_at": created_at}

    def list(self):
        rows, _ = self._run("SELECT id, title, body, created_at FROM notes ORDER BY id")
        return [self._to_dict(r) for r in rows]

    def get(self, note_id):
        if note_id > SQLITE_MAX_INT:
            return None
        rows, _ = self._run(
            "SELECT id, title, body, created_at FROM notes WHERE id = ?", (note_id,)
        )
        return self._to_dict(rows[0]) if rows else None

    def delete(self, note_id):
        """Permanently remove a note. Return True if it existed."""
        if note_id > SQLITE_MAX_INT:
            return False
        _, rowcount = self._run("DELETE FROM notes WHERE id = ?", (note_id,))
        return rowcount > 0


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

class ValidationError(Exception):
    pass


def validate_new_note(payload):
    """Return (title, body) from a decoded JSON payload or raise ValidationError."""
    if not isinstance(payload, dict):
        raise ValidationError("request body must be a JSON object")

    title = payload.get("title")
    if not isinstance(title, str):
        raise ValidationError("title is required and must be a string")
    title = title.strip()
    if not 1 <= len(title) <= TITLE_MAX:
        raise ValidationError(f"title must be 1-{TITLE_MAX} characters after trimming")

    body = payload.get("body", "")
    if body is None:
        body = ""
    if not isinstance(body, str):
        raise ValidationError("body must be a string")

    return title, body


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

class BadRequest(Exception):
    pass


METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


class NotesHandler(BaseHTTPRequestHandler):
    server_version = "NotesAPI/1.0"

    # -- plumbing ----------------------------------------------------------

    @property
    def store(self):
        return self.server.store

    def log_message(self, fmt, *args):
        if not getattr(self.server, "quiet", False):
            super().log_message(fmt, *args)

    def _send(self, status, payload=None, headers=None):
        body = b""
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        if status != 204:
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _error(self, status, message, headers=None):
        self._send(status, {"error": message}, headers)

    def _route(self):
        """Return ('collection', None) | ('item', id) | (None, None)."""
        path = urlsplit(self.path).path
        if path == NOTES_PATH:
            return "collection", None
        match = NOTE_PATH.match(path)
        if match:
            return "item", int(match.group(1))
        return None, None

    def _read_body(self):
        """Read the whole request body so the connection is never left with
        unread bytes, whatever response we end up sending."""
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length) if raw_length is not None else 0
        except ValueError:
            raise BadRequest("invalid Content-Length header")
        if length < 0:
            raise BadRequest("invalid Content-Length header")
        return self.rfile.read(length) if length else b""

    @staticmethod
    def _parse_json(raw):
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise BadRequest("request body is not valid JSON")

    def _handle(self):
        """Dispatch to _<method>_<resource>; 404 for unknown paths, 405 for a
        known path without a handler for this method."""
        try:
            raw = self._read_body()
        except BadRequest as exc:
            return self._error(400, str(exc))
        kind, note_id = self._route()
        if kind is None:
            return self._error(404, "not found")
        handler = getattr(self, f"_{self.command.lower()}_{kind}", None)
        if handler is None:
            allowed = ", ".join(
                m for m in METHODS if hasattr(self, f"_{m.lower()}_{kind}")
            )
            return self._error(405, "method not allowed", {"Allow": allowed})
        handler(note_id, raw)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _handle

    # -- resources ---------------------------------------------------------

    def _get_collection(self, _note_id, _raw):
        self._send(200, self.store.list())

    def _post_collection(self, _note_id, raw):
        try:
            payload = self._parse_json(raw)
        except BadRequest as exc:
            return self._error(400, str(exc))
        try:
            title, body = validate_new_note(payload)
        except ValidationError as exc:
            return self._error(422, str(exc))
        self._send(201, self.store.create(title, body))

    def _get_item(self, note_id, _raw):
        note = self.store.get(note_id)
        if note is None:
            return self._error(404, "note not found")
        self._send(200, note)

    def _delete_item(self, note_id, _raw):
        if not self.store.delete(note_id):
            return self._error(404, "note not found")
        self._send(204)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def make_server(host=DEFAULT_HOST, port=DEFAULT_PORT, db_path=DEFAULT_DB, quiet=False):
    server = ThreadingHTTPServer((host, port), NotesHandler)
    server.daemon_threads = True
    server.store = NoteStore(db_path)
    server.quiet = quiet
    return server


def main():
    host = os.environ.get("NOTES_HOST", DEFAULT_HOST)
    port = int(os.environ.get("NOTES_PORT", DEFAULT_PORT))
    db_path = os.environ.get("NOTES_DB", DEFAULT_DB)
    server = make_server(host, port, db_path)
    bound_host, bound_port = server.server_address[:2]
    print(f"Notes API listening on http://{bound_host}:{bound_port} (db: {db_path})",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    sys.exit(main())
