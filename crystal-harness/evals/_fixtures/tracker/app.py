"""Tracker API: a JSON HTTP API for projects and the tasks inside them.

Standard library only. Everything lives in a SQLite file (default ./tracker.db
next to this file), so it survives a restart of the server.

Run:  python3 app.py
Env:  TRACKER_HOST (default 127.0.0.1), TRACKER_PORT (default 8765),
      TRACKER_DB (default tracker.db beside this file)
"""

import json
import os
import re
import sqlite3
import sys
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tracker.db")

NAME_MAX = 60
TITLE_MAX = 120
TAG_MAX = 20
TAGS_MAX = 5
PRIORITY_MIN, PRIORITY_MAX, PRIORITY_DEFAULT = 1, 5, 3
LIMIT_MAX, LIMIT_DEFAULT = 100, 20
SQLITE_MAX_INT = 2**63 - 1

STATUSES = ("todo", "doing", "done")
# status -> the statuses a task may move to from it
TRANSITIONS = {"todo": ("doing",), "doing": ("done", "todo"), "done": ("doing",)}

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS projects (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL,
        name_key   TEXT NOT NULL UNIQUE,
        archived   INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id   INTEGER NOT NULL,
        title        TEXT NOT NULL,
        status       TEXT NOT NULL DEFAULT 'todo',
        priority     INTEGER NOT NULL,
        completed_at TEXT,
        created_at   TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS task_tags (
        task_id  INTEGER NOT NULL,
        position INTEGER NOT NULL,
        tag      TEXT NOT NULL,
        PRIMARY KEY (task_id, position)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS blockers (
        task_id    INTEGER NOT NULL,
        blocker_id INTEGER NOT NULL,
        PRIMARY KEY (task_id, blocker_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS tasks_project ON tasks (project_id)",
    "CREATE INDEX IF NOT EXISTS task_tags_tag ON task_tags (tag)",
)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Errors the HTTP layer turns into a status
# --------------------------------------------------------------------------

class ApiError(Exception):
    status = 500


class BadRequest(ApiError):
    status = 400


class NotFound(ApiError):
    status = 404


class Conflict(ApiError):
    status = 409


class Invalid(ApiError):
    status = 422


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def require_object(payload):
    if not isinstance(payload, dict):
        raise Invalid("request body must be a JSON object")
    return payload


def is_integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def validate_text(value, field, maximum):
    if not isinstance(value, str):
        raise Invalid(f"{field} is required and must be a string")
    value = value.strip()
    if not 1 <= len(value) <= maximum:
        raise Invalid(f"{field} must be 1-{maximum} characters after trimming")
    return value


def validate_priority(value):
    if not is_integer(value) or not PRIORITY_MIN <= value <= PRIORITY_MAX:
        raise Invalid(f"priority must be an integer from {PRIORITY_MIN} to {PRIORITY_MAX}")
    return value


def validate_tags(value):
    """Check a tags array against the limits; return its entries trimmed."""
    if not isinstance(value, list) or len(value) > TAGS_MAX:
        raise Invalid(f"tags must be an array of at most {TAGS_MAX} strings")
    tags = []
    for tag in value:
        if not isinstance(tag, str):
            raise Invalid("every tag must be a string")
        tag = tag.strip()
        # the limit is on the form a tag is held in, and lower-casing can lengthen a string
        if not 1 <= len(tag.lower()) <= TAG_MAX:
            raise Invalid(f"every tag must be 1-{TAG_MAX} characters after trimming and lower-casing")
        tags.append(tag)
    return tags


def normalise_tags(tags):
    """Lower-case, and drop a tag that repeats an earlier one."""
    result = []
    for tag in tags:
        tag = tag.lower()
        if tag not in result:
            result.append(tag)
    return result


# --------------------------------------------------------------------------
# Datastore
# --------------------------------------------------------------------------

class Store:
    """SQLite-backed projects and tasks. One short-lived connection per
    operation, so the threaded server never shares one between threads; every
    write runs in an immediate transaction, so two requests cannot interleave
    a check with the write that depends on it."""

    def __init__(self, path):
        self.path = path
        with self._transaction(write=True) as conn:
            for statement in SCHEMA:
                conn.execute(statement)

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _transaction(self, write=False):
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()

    # -- rows to JSON ------------------------------------------------------

    def _project(self, conn, row):
        counts = dict.fromkeys(STATUSES, 0)
        for count in conn.execute(
            "SELECT status, COUNT(*) AS n FROM tasks WHERE project_id = ? GROUP BY status", (row["id"],)
        ):
            counts[count["status"]] = count["n"]
        return {
            "id": row["id"],
            "name": row["name"],
            "archived": bool(row["archived"]),
            "created_at": row["created_at"],
            "task_counts": counts,
        }

    def _tags(self, conn, task_id):
        rows = conn.execute("SELECT tag FROM task_tags WHERE task_id = ? ORDER BY position", (task_id,))
        return [r["tag"] for r in rows]

    def _blocked_by(self, conn, task_id):
        rows = conn.execute("SELECT blocker_id FROM blockers WHERE task_id = ? ORDER BY blocker_id", (task_id,))
        return [r["blocker_id"] for r in rows]

    def _task(self, conn, row):
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "title": row["title"],
            "status": row["status"],
            "priority": row["priority"],
            "tags": self._tags(conn, row["id"]),
            "blocked_by": self._blocked_by(conn, row["id"]),
            "completed_at": row["completed_at"],
            "created_at": row["created_at"],
        }

    # -- lookups -----------------------------------------------------------

    def _require_project(self, conn, project_id):
        row = None
        if 0 < project_id <= SQLITE_MAX_INT:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise NotFound("project not found")
        return row

    def _require_task(self, conn, task_id):
        row = None
        if 0 < task_id <= SQLITE_MAX_INT:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise NotFound("task not found")
        return row

    def _depends_on(self, conn, start, target):
        """True when `start` waits on `target`, directly or through other tasks."""
        seen, stack = set(), [start]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            blockers = self._blocked_by(conn, current)
            if target in blockers:
                return True
            stack.extend(blockers)
        return False

    def _set_tags(self, conn, task_id, tags):
        conn.execute("DELETE FROM task_tags WHERE task_id = ?", (task_id,))
        conn.executemany(
            "INSERT INTO task_tags (task_id, position, tag) VALUES (?, ?, ?)",
            [(task_id, position, tag) for position, tag in enumerate(tags)],
        )

    # -- projects ----------------------------------------------------------

    def create_project(self, name):
        with self._transaction(write=True) as conn:
            key = name.lower()
            if conn.execute("SELECT 1 FROM projects WHERE name_key = ?", (key,)).fetchone():
                raise Conflict("a project with that name already exists")
            cur = conn.execute(
                "INSERT INTO projects (name, name_key, created_at) VALUES (?, ?, ?)", (name, key, now())
            )
            return self._project(conn, self._require_project(conn, cur.lastrowid))

    def list_projects(self, include_archived):
        with self._transaction() as conn:
            sql = "SELECT * FROM projects"
            if not include_archived:
                sql += " WHERE archived = 0"
            return [self._project(conn, row) for row in conn.execute(sql + " ORDER BY id").fetchall()]

    def get_project(self, project_id):
        with self._transaction() as conn:
            return self._project(conn, self._require_project(conn, project_id))

    def archive_project(self, project_id):
        with self._transaction(write=True) as conn:
            self._require_project(conn, project_id)
            conn.execute("UPDATE projects SET archived = 1 WHERE id = ?", (project_id,))
            return self._project(conn, self._require_project(conn, project_id))

    def delete_project(self, project_id):
        with self._transaction(write=True) as conn:
            self._require_project(conn, project_id)
            its_tasks = "SELECT id FROM tasks WHERE project_id = ?"
            conn.execute(
                f"DELETE FROM blockers WHERE task_id IN ({its_tasks}) OR blocker_id IN ({its_tasks})",
                (project_id, project_id),
            )
            conn.execute(f"DELETE FROM task_tags WHERE task_id IN ({its_tasks})", (project_id,))
            conn.execute("DELETE FROM tasks WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    # -- tasks -------------------------------------------------------------

    def create_task(self, project_id, title, priority, tags):
        with self._transaction(write=True) as conn:
            project = self._require_project(conn, project_id)
            if project["archived"]:
                raise Conflict("the project is archived")
            cur = conn.execute(
                "INSERT INTO tasks (project_id, title, priority, created_at) VALUES (?, ?, ?, ?)",
                (project_id, title, priority, now()),
            )
            self._set_tags(conn, cur.lastrowid, tags)
            return self._task(conn, self._require_task(conn, cur.lastrowid))

    def get_task(self, task_id):
        with self._transaction() as conn:
            return self._task(conn, self._require_task(conn, task_id))

    def list_tasks(self, project_id, status, tag, limit, offset):
        where, params = [], []
        if project_id is not None:
            where.append("project_id = ?")
            params.append(project_id)
        if status is not None:
            where.append("status = ?")
            params.append(status)
        if tag is not None:
            where.append("EXISTS (SELECT 1 FROM task_tags WHERE task_id = tasks.id AND tag = ?)")
            params.append(tag)
        clause = " WHERE " + " AND ".join(where) if where else ""
        with self._transaction() as conn:
            rows = conn.execute(
                "SELECT * FROM tasks" + clause + " ORDER BY priority DESC, id LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM tasks" + clause, params).fetchone()[0]
            return {"items": [self._task(conn, row) for row in rows], "total": total}

    def update_task(self, task_id, changes):
        with self._transaction(write=True) as conn:
            self._require_task(conn, task_id)
            for column in ("title", "priority"):
                if column in changes:
                    conn.execute(f"UPDATE tasks SET {column} = ? WHERE id = ?", (changes[column], task_id))
            if "tags" in changes:
                self._set_tags(conn, task_id, changes["tags"])
            return self._task(conn, self._require_task(conn, task_id))

    def delete_task(self, task_id):
        with self._transaction(write=True) as conn:
            self._require_task(conn, task_id)
            conn.execute("DELETE FROM blockers WHERE task_id = ? OR blocker_id = ?", (task_id, task_id))
            conn.execute("DELETE FROM task_tags WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    def move_task(self, task_id, project_id):
        with self._transaction(write=True) as conn:
            task = self._require_task(conn, task_id)
            project = self._require_project(conn, project_id)
            if task["project_id"] != project_id:
                if project["archived"]:
                    raise Conflict("the target project is archived")
                conn.execute("UPDATE tasks SET project_id = ? WHERE id = ?", (project_id, task_id))
            return self._task(conn, self._require_task(conn, task_id))

    # -- workflow ----------------------------------------------------------

    def transition_task(self, task_id, to):
        with self._transaction(write=True) as conn:
            task = self._require_task(conn, task_id)
            if to not in TRANSITIONS[task["status"]]:
                raise Conflict(f"a task cannot go from {task['status']} to {to}")
            if to == "done":
                for blocker_id in self._blocked_by(conn, task_id):
                    blocker = conn.execute("SELECT status FROM tasks WHERE id = ?", (blocker_id,)).fetchone()
                    if blocker is None or blocker["status"] != "done":
                        raise Conflict(f"the task waits on task {blocker_id}, which is not done")
            completed_at = now() if to == "done" else None
            conn.execute(
                "UPDATE tasks SET status = ?, completed_at = ? WHERE id = ?", (to, completed_at, task_id)
            )
            return self._task(conn, self._require_task(conn, task_id))

    # -- blocking ----------------------------------------------------------

    def add_blocker(self, task_id, blocker_id):
        with self._transaction(write=True) as conn:
            self._require_task(conn, task_id)
            self._require_task(conn, blocker_id)
            if task_id == blocker_id:
                raise Conflict("a task cannot wait on itself")
            if self._depends_on(conn, blocker_id, task_id):
                raise Conflict("that would make a cycle of blocking relations")
            conn.execute(
                "INSERT OR IGNORE INTO blockers (task_id, blocker_id) VALUES (?, ?)", (task_id, blocker_id)
            )
            return self._task(conn, self._require_task(conn, task_id))

    def remove_blocker(self, task_id, blocker_id):
        with self._transaction(write=True) as conn:
            self._require_task(conn, task_id)
            removed = conn.execute(
                "DELETE FROM blockers WHERE task_id = ? AND blocker_id = ?", (task_id, min(blocker_id, SQLITE_MAX_INT))
            ).rowcount
            if not removed:
                raise NotFound("the task is not waiting on that blocker")


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

ROUTES = (
    (re.compile(r"^/projects$", re.ASCII), "projects"),
    (re.compile(r"^/projects/(\d+)$", re.ASCII), "project"),
    (re.compile(r"^/projects/(\d+)/archive$", re.ASCII), "archive"),
    (re.compile(r"^/projects/(\d+)/tasks$", re.ASCII), "project_tasks"),
    (re.compile(r"^/tasks$", re.ASCII), "tasks"),
    (re.compile(r"^/tasks/(\d+)$", re.ASCII), "task"),
    (re.compile(r"^/tasks/(\d+)/transition$", re.ASCII), "transition"),
    (re.compile(r"^/tasks/(\d+)/move$", re.ASCII), "move"),
    (re.compile(r"^/tasks/(\d+)/blockers/(\d+)$", re.ASCII), "blocker"),
)
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
UNSIGNED = re.compile(r"^\d+$", re.ASCII)
SIGNED = re.compile(r"^-?\d+$", re.ASCII)


class TrackerHandler(BaseHTTPRequestHandler):
    server_version = "TrackerAPI/1.0"

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
        if body and self.command != "HEAD":
            self.wfile.write(body)

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

    def _json_object(self):
        try:
            payload = json.loads(self._raw.decode("utf-8"))
            # an escaped lone surrogate parses, but is not text that can be stored or sent back
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
        except (UnicodeError, ValueError):
            raise BadRequest("request body is not valid JSON")
        return require_object(payload)

    def _query(self):
        """The last value given for each query parameter."""
        values = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        return {name: given[-1] for name, given in values.items()}

    def _handle(self):
        """Dispatch to _<method>_<resource>: 404 for a path the API does not
        have, 405 for one it has without a handler for this method."""
        try:
            self._raw = self._read_body()
            path = urlsplit(self.path).path
            for pattern, kind in ROUTES:
                match = pattern.match(path)
                if match:
                    break
            else:
                raise NotFound("not found")
            handler = getattr(self, f"_{self.command.lower()}_{kind}", None)
            if handler is None:
                allowed = ", ".join(m for m in METHODS if hasattr(self, f"_{m.lower()}_{kind}"))
                return self._send(405, {"error": "method not allowed"}, {"Allow": allowed})
            handler(*(int(group) for group in match.groups()))
        except ApiError as exc:
            self._send(exc.status, {"error": str(exc)})
        except Exception as exc:  # a bug, not a client error: say so instead of dropping the connection
            self.log_error("unhandled error on %s %s\n%s", self.command, self.path, traceback.format_exc())
            self._send(500, {"error": f"internal error: {type(exc).__name__}"})

    def __getattr__(self, name):
        # http.server looks up do_<METHOD> and answers 501 in HTML when there is none;
        # answering for every method keeps an unknown one on the 404/405 path above.
        if name.startswith("do_"):
            return self._handle
        raise AttributeError(name)

    # -- projects ----------------------------------------------------------

    def _get_projects(self):
        include_archived = self._query().get("include_archived", "false")
        if include_archived not in ("true", "false"):
            raise Invalid("include_archived must be true or false")
        self._send(200, self.store.list_projects(include_archived == "true"))

    def _post_projects(self):
        payload = self._json_object()
        name = validate_text(payload.get("name"), "name", NAME_MAX)
        self._send(201, self.store.create_project(name))

    def _get_project(self, project_id):
        self._send(200, self.store.get_project(project_id))

    def _delete_project(self, project_id):
        self.store.delete_project(project_id)
        self._send(204)

    def _post_archive(self, project_id):
        self._send(200, self.store.archive_project(project_id))

    # -- tasks -------------------------------------------------------------

    def _post_project_tasks(self, project_id):
        payload = self._json_object()
        title = validate_text(payload.get("title"), "title", TITLE_MAX)
        priority = validate_priority(payload.get("priority", PRIORITY_DEFAULT))
        tags = normalise_tags(validate_tags(payload.get("tags", [])))
        self._send(201, self.store.create_task(project_id, title, priority, tags))

    def _get_tasks(self):
        query = self._query()

        project_id = query.get("project_id")
        if project_id is not None:
            if not SIGNED.match(project_id):
                raise Invalid("project_id must be an integer")
            project_id = max(min(int(project_id), SQLITE_MAX_INT), -1)

        status = query.get("status")
        if status is not None and status not in STATUSES:
            raise Invalid(f"status must be one of {', '.join(STATUSES)}")

        tag = query.get("tag")
        if tag is not None:
            tag = tag.strip().lower()

        limit = query.get("limit", str(LIMIT_DEFAULT))
        if not UNSIGNED.match(limit) or not 1 <= int(limit) <= LIMIT_MAX:
            raise Invalid(f"limit must be an integer from 1 to {LIMIT_MAX}")
        offset = query.get("offset", "0")
        if not UNSIGNED.match(offset):
            raise Invalid("offset must be an integer, 0 or more")

        self._send(200, self.store.list_tasks(project_id, status, tag, int(limit), min(int(offset), SQLITE_MAX_INT)))

    def _get_task(self, task_id):
        self._send(200, self.store.get_task(task_id))

    def _patch_task(self, task_id):
        payload = self._json_object()
        unknown = sorted(set(payload) - {"title", "priority", "tags"})
        if unknown:
            raise Invalid(f"cannot change: {', '.join(unknown)}")
        if not payload:
            raise Invalid("give at least one of title, priority, tags")
        changes = {}
        if "title" in payload:
            changes["title"] = validate_text(payload["title"], "title", TITLE_MAX)
        if "priority" in payload:
            changes["priority"] = validate_priority(payload["priority"])
        if "tags" in payload:
            changes["tags"] = normalise_tags(validate_tags(payload["tags"]))
        self._send(200, self.store.update_task(task_id, changes))

    def _delete_task(self, task_id):
        self.store.delete_task(task_id)
        self._send(204)

    def _post_move(self, task_id):
        project_id = self._json_object().get("project_id")
        if not is_integer(project_id):
            raise Invalid("project_id is required and must be an integer")
        self._send(200, self.store.move_task(task_id, project_id))

    # -- workflow and blocking ---------------------------------------------

    def _post_transition(self, task_id):
        to = self._json_object().get("to")
        if to not in STATUSES:
            raise Invalid(f"to must be one of {', '.join(STATUSES)}")
        self._send(200, self.store.transition_task(task_id, to))

    def _put_blocker(self, task_id, blocker_id):
        self._send(200, self.store.add_blocker(task_id, blocker_id))

    def _delete_blocker(self, task_id, blocker_id):
        self.store.remove_blocker(task_id, blocker_id)
        self._send(204)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def make_server(host=DEFAULT_HOST, port=DEFAULT_PORT, db_path=DEFAULT_DB, quiet=False):
    server = ThreadingHTTPServer((host, port), TrackerHandler)
    server.daemon_threads = True
    server.store = Store(db_path)
    server.quiet = quiet
    return server


def main():
    host = os.environ.get("TRACKER_HOST", DEFAULT_HOST)
    port = int(os.environ.get("TRACKER_PORT", DEFAULT_PORT))
    db_path = os.environ.get("TRACKER_DB", DEFAULT_DB)
    server = make_server(host, port, db_path)
    bound_host, bound_port = server.server_address[:2]
    print(f"Tracker API listening on http://{bound_host}:{bound_port} (db: {db_path})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    sys.exit(main())
