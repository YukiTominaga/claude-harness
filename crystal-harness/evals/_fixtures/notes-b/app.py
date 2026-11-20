#!/usr/bin/env python3
"""Notes API: a tiny JSON service that stores short text notes in SQLite.

    python3 app.py            # listens on 127.0.0.1:8765, data in notes.db

    POST   /notes        {"title": str 1-100 chars trimmed, "body"?: str} -> 201 Note
    GET    /notes        -> 200 [Note, ...] in ascending id order
    GET    /notes/{id}   -> 200 Note | 404
    DELETE /notes/{id}   -> 204 | 404

Environment (both optional, used by the tests):
    NOTES_PORT  port to listen on (default 8765; 0 picks a free port)
    NOTES_DB    SQLite file (default: notes.db next to this file)

Every 4xx/5xx response is JSON {"error": "<message>"}. Python standard library only.
"""

import json
import os
import re
import sqlite3
import sys
import traceback
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "notes.db")

TITLE_MAX = 100
MAX_ID = 2**63 - 1  # largest id SQLite can hold; anything above is simply "no such note"
MAX_BODY_BYTES = 1024 * 1024

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body  TEXT NOT NULL DEFAULT ''
)
"""


class ApiError(Exception):
    """An error that maps straight onto a JSON {"error": ...} response."""

    def __init__(self, status, message, headers=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.headers = headers or {}


# --- storage -----------------------------------------------------------------


def init_db(db_path):
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute(SCHEMA)


def _connect(db_path):
    return closing(sqlite3.connect(db_path, timeout=10))


def _note(row):
    return {"id": row[0], "title": row[1], "body": row[2]}


def insert_note(db_path, title, body):
    with _connect(db_path) as conn, conn:
        cur = conn.execute("INSERT INTO notes (title, body) VALUES (?, ?)", (title, body))
        return {"id": cur.lastrowid, "title": title, "body": body}


def list_notes(db_path):
    with _connect(db_path) as conn:
        return [_note(r) for r in conn.execute("SELECT id, title, body FROM notes ORDER BY id")]


def find_note(db_path, note_id):
    with _connect(db_path) as conn:
        row = conn.execute("SELECT id, title, body FROM notes WHERE id = ?", (note_id,)).fetchone()
    return _note(row) if row else None


def delete_note(db_path, note_id):
    with _connect(db_path) as conn, conn:
        return conn.execute("DELETE FROM notes WHERE id = ?", (note_id,)).rowcount > 0


# --- validation --------------------------------------------------------------


def parse_json(raw):
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):  # includes bad UTF-8 and an empty body
        raise ApiError(400, "request body is not valid JSON") from None


def validate_new_note(payload):
    """Return (title, body) for a valid POST /notes payload, else raise a 422."""
    if not isinstance(payload, dict):
        raise ApiError(422, "request body must be a JSON object with a title")
    if "title" not in payload:
        raise ApiError(422, "title is required")
    title = payload["title"]
    if not isinstance(title, str):
        raise ApiError(422, "title must be a string")
    title = title.strip()
    if not 1 <= len(title) <= TITLE_MAX:
        raise ApiError(422, f"title must be 1-{TITLE_MAX} characters after trimming whitespace")
    body = payload.get("body", "")
    if not isinstance(body, str):
        raise ApiError(422, "body must be a string")
    for name, text in (("title", title), ("body", body)):
        try:
            text.encode("utf-8")  # rejects lone surrogates such as "\ud800"
        except UnicodeEncodeError:
            raise ApiError(422, f"{name} contains characters that cannot be stored") from None
    return title, body


def parse_note_id(segment):
    """A decimal-integer id, or ApiError 404 (so /notes/abc is just 'no such note')."""
    text = unquote(segment)
    if not re.fullmatch(r"[0-9]+", text) or int(text) > MAX_ID:
        raise ApiError(404, "note not found")
    return int(text)


# --- HTTP --------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "NotesAPI/1.0"
    timeout = 60  # drop idle keep-alive connections

    # Every method goes through one dispatcher so nothing answers with the
    # standard library's HTML error page.
    def _dispatch(self):
        try:
            raw = self._read_body()
            status, payload, headers = self._route(raw)
            self._send(status, payload, headers)
        except ApiError as err:
            self._send(err.status, {"error": err.message}, err.headers)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception:
            self.log_error("unhandled error:\n%s", traceback.format_exc())
            self._send(500, {"error": "internal server error"})

    do_GET = do_POST = do_DELETE = do_PUT = do_PATCH = do_HEAD = do_OPTIONS = _dispatch

    def _route(self, raw):
        db = self.server.db_path
        segments = self.path.split("?", 1)[0].split("#", 1)[0].split("/")

        if segments == ["", "notes"]:
            if self.command == "GET":
                return 200, list_notes(db), None
            if self.command == "POST":
                title, body = validate_new_note(parse_json(raw))
                return 201, insert_note(db, title, body), None
            raise ApiError(405, "method not allowed", {"Allow": "GET, POST"})

        if len(segments) == 3 and segments[0] == "" and segments[1] == "notes":
            if self.command not in ("GET", "DELETE"):
                raise ApiError(405, "method not allowed", {"Allow": "GET, DELETE"})
            note_id = parse_note_id(segments[2])
            if self.command == "GET":
                note = find_note(db, note_id)
                if note is None:
                    raise ApiError(404, "note not found")
                return 200, note, None
            if not delete_note(db, note_id):
                raise ApiError(404, "note not found")
            return 204, None, None

        raise ApiError(404, "not found")

    def _read_body(self):
        encoding = self.headers.get("Transfer-Encoding", "").strip().lower()
        if encoding:
            if encoding != "chunked":
                self.close_connection = True
                raise ApiError(501, "unsupported Transfer-Encoding")
            return self._read_chunked()
        length = self.headers.get("Content-Length")
        if length is None:
            return b""
        if not re.fullmatch(r"[0-9]+", length.strip()):
            self.close_connection = True
            raise ApiError(400, "invalid Content-Length header")
        size = int(length)
        if size > MAX_BODY_BYTES:
            self.close_connection = True
            raise ApiError(413, "request body too large")
        data = self.rfile.read(size)
        if len(data) < size:
            self.close_connection = True
            raise ApiError(400, "request body is shorter than Content-Length")
        return data

    def _read_chunked(self):
        data = bytearray()
        try:
            while True:
                size = int(self.rfile.readline(65537).split(b";", 1)[0].strip(), 16)
                if size == 0:
                    while self.rfile.readline(65537) not in (b"\r\n", b"\n", b""):
                        pass  # discard trailers
                    return bytes(data)
                if len(data) + size > MAX_BODY_BYTES:
                    raise ApiError(413, "request body too large")
                data += self.rfile.read(size)
                self.rfile.readline(65537)  # the CRLF after each chunk
        except ValueError:
            self.close_connection = True
            raise ApiError(400, "malformed chunked request body") from None
        except ApiError:
            self.close_connection = True
            raise

    def _send(self, status, payload=None, headers=None):
        data = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        if status != 204:
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if data and self.command != "HEAD":
            self.wfile.write(data)

    def send_error(self, code, message=None, explain=None):
        # Errors raised by the standard library itself (malformed request line,
        # oversized headers, unknown method, ...) get the same JSON shape.
        self.log_error("code %d, message %s", code, message)
        self.close_connection = True
        text = message or self.responses.get(code, ("error",))[0]
        self._send(code, {"error": text}, {"Connection": "close"})


def make_server(host, port, db_path):
    init_db(db_path)
    server = ThreadingHTTPServer((host, port), Handler)
    server.db_path = db_path
    return server


def main():
    raw_port = os.environ.get("NOTES_PORT") or str(DEFAULT_PORT)
    try:
        port = int(raw_port)
    except ValueError:
        sys.exit(f"error: NOTES_PORT must be an integer, got {raw_port!r}")
    db_path = os.environ.get("NOTES_DB") or DEFAULT_DB
    server = make_server(HOST, port, db_path)
    print(f"notes api listening on http://{HOST}:{server.server_address[1]} (db: {db_path})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
