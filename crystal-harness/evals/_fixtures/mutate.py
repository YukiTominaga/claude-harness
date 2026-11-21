#!/usr/bin/env python3
"""Rewrite a fixture's app.py: seed one known defect, or apply a decoy.

A mutation is one or more exact text replacements. If the text one expects is
not there exactly once — the base app drifted — the script exits non-zero
instead of silently producing a clean app that an eval case would then score as
"defect missed".

DEFECTS change what the app does, in one way each. DECOYS do not: each rewrites
a piece of the tracker so that it reads like one of the defects — a delete that
no longer mentions the dependent rows, a check that is no longer in the Python —
while behaving exactly as before. They exist to tempt a false alarm.
scripts/test_eval_fixtures.py holds both to that: a defect must show in a probe,
a decoy must not.

Usage: mutate.py <mutation> [<mutation> ...] <path to app.py>
"""

import sys

NOTES_DEFECTS = {
    # A write that reports success and is rolled back: the connection is closed
    # without a commit.
    "delete-not-committed": (
        '''        _, rowcount = self._run("DELETE FROM notes WHERE id = ?", (note_id,))
        return rowcount > 0''',
        '''        conn = self._connect()
        try:
            rowcount = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,)).rowcount
        finally:
            conn.close()
        return rowcount > 0''',
    ),
    # An error path that answers like the happy path.
    "delete-unknown-returns-204": (
        '''        if not self.store.delete(note_id):
            return self._error(404, "note not found")
        self._send(204)''',
        '''        self.store.delete(note_id)
        self._send(204)''',
    ),
    # Correct data in the wrong order.
    "list-newest-first": (
        '''FROM notes ORDER BY id")''',
        '''FROM notes ORDER BY id DESC")''',
    ),
    # Works until the server is restarted.
    "restart-wipes-data": (
        '''        self.path = path
        self._run(SCHEMA)''',
        '''        self.path = path
        if os.path.exists(path):
            os.remove(path)
        self._run(SCHEMA)''',
    ),
    # The stated edge case answers with the wrong status.
    "invalid-json-returns-422": (
        '''            payload = self._parse_json(raw)
        except BadRequest as exc:
            return self._error(400, str(exc))''',
        '''            payload = self._parse_json(raw)
        except BadRequest as exc:
            return self._error(422, str(exc))''',
    ),
    # A field is accepted, validated, and thrown away.
    "body-discarded": (
        '''        self._send(201, self.store.create(title, body))''',
        '''        self._send(201, self.store.create(title, ""))''',
    ),
}

# The tracker's defects are harder on purpose. None shows on the first request to
# an endpoint: each needs a particular sequence, a second resource, or enough
# data — and each is an omission, so the code that is left reads as plausible.
TRACKER_DEFECTS = {
    # Order of operations: only visible after done -> doing, and only in one field.
    "reopen-keeps-completed-at": (
        '''            completed_at = now() if to == "done" else None''',
        '''            completed_at = now() if to == "done" else task["completed_at"]''',
    ),
    # Two features meeting: the archive rule is enforced on create, not on move.
    "move-into-archived-project": (
        '''            project = self._require_project(conn, project_id)
            if project["archived"]:
                raise Conflict("the target project is archived")
            conn.execute("UPDATE tasks SET project_id = ? WHERE id = ?", (project_id, task_id))''',
        '''            self._require_project(conn, project_id)
            conn.execute("UPDATE tasks SET project_id = ? WHERE id = ?", (project_id, task_id))''',
    ),
    # Four steps: block, delete the blocker, then try to finish what was waiting.
    "deleted-blocker-still-blocks": (
        '''            conn.execute("DELETE FROM blockers WHERE task_id = ? OR blocker_id = ?", (task_id, task_id))''',
        '''            conn.execute("DELETE FROM blockers WHERE task_id = ?", (task_id,))''',
    ),
    # Needs three tasks: a two-task cycle is still refused.
    "indirect-cycle-accepted": (
        '''        """True when `start` waits on `target`, directly or through other tasks."""
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
        return False''',
        '''        """True when `start` waits on `target`."""
        return target in self._blocked_by(conn, start)''',
    ),
    # Needs more matches than the page holds: with everything on one page it is right.
    "total-counts-the-page": (
        '''            total = conn.execute("SELECT COUNT(*) FROM tasks" + clause, params).fetchone()[0]
            return {"items": [self._task(conn, row) for row in rows], "total": total}''',
        '''            return {"items": [self._task(conn, row) for row in rows], "total": len(rows)}''',
    ),
    # A second path to the same field: create normalises tags, PATCH only validates them.
    "patch-tags-not-normalised": (
        '''            changes["tags"] = normalise_tags(validate_tags(payload["tags"]))''',
        '''            changes["tags"] = validate_tags(payload["tags"])''',
    ),
}

TRACKER_DECOYS = {
    # The deletes stop naming tags, blockers and tasks: foreign keys cascade instead.
    "decoy-cascading-deletes": [
        (
            '''        project_id   INTEGER NOT NULL,
        title        TEXT NOT NULL,''',
            '''        project_id   INTEGER NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
        title        TEXT NOT NULL,''',
        ),
        (
            '''        task_id  INTEGER NOT NULL,
        position INTEGER NOT NULL,''',
            '''        task_id  INTEGER NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
        position INTEGER NOT NULL,''',
        ),
        (
            '''        task_id    INTEGER NOT NULL,
        blocker_id INTEGER NOT NULL,
        PRIMARY KEY (task_id, blocker_id)''',
            '''        task_id    INTEGER NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
        blocker_id INTEGER NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
        PRIMARY KEY (task_id, blocker_id)''',
        ),
        (
            '''        conn.row_factory = sqlite3.Row
        return conn''',
            '''        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn''',
        ),
        (
            '''            self._require_project(conn, project_id)
            its_tasks = "SELECT id FROM tasks WHERE project_id = ?"
            conn.execute(
                f"DELETE FROM blockers WHERE task_id IN ({its_tasks}) OR blocker_id IN ({its_tasks})",
                (project_id, project_id),
            )
            conn.execute(f"DELETE FROM task_tags WHERE task_id IN ({its_tasks})", (project_id,))
            conn.execute("DELETE FROM tasks WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))''',
            '''            self._require_project(conn, project_id)
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))''',
        ),
        (
            '''            self._require_task(conn, task_id)
            conn.execute("DELETE FROM blockers WHERE task_id = ? OR blocker_id = ?", (task_id, task_id))
            conn.execute("DELETE FROM task_tags WHERE task_id = ?", (task_id,))
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))''',
            '''            self._require_task(conn, task_id)
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))''',
        ),
    ],
    # The archive rule on a move leaves the Python and goes into the UPDATE.
    "decoy-move-check-in-sql": [
        (
            '''            project = self._require_project(conn, project_id)
            if project["archived"]:
                raise Conflict("the target project is archived")
            conn.execute("UPDATE tasks SET project_id = ? WHERE id = ?", (project_id, task_id))''',
            '''            self._require_project(conn, project_id)
            moved = conn.execute(
                "UPDATE tasks SET project_id = ?1 WHERE id = ?2"
                " AND NOT EXISTS (SELECT 1 FROM projects WHERE id = ?1 AND archived = 1)",
                (project_id, task_id),
            ).rowcount
            if not moved:
                raise Conflict("the target project is archived")''',
        ),
    ],
    # A CASE with no ELSE: it yields NULL, which is what leaving `done` needs.
    "decoy-completed-at-case": [
        (
            '''            completed_at = now() if to == "done" else None
            conn.execute(
                "UPDATE tasks SET status = ?, completed_at = ? WHERE id = ?", (to, completed_at, task_id)
            )''',
            '''            conn.execute(
                "UPDATE tasks SET status = ?1, completed_at = CASE WHEN ?1 = 'done' THEN ?2 END WHERE id = ?3",
                (to, now(), task_id),
            )''',
        ),
    ],
}

MUTATIONS = {**NOTES_DEFECTS, **TRACKER_DEFECTS, **TRACKER_DECOYS}


def main():
    names, path = sys.argv[1:-1], sys.argv[-1]
    if not names or any(name not in MUTATIONS for name in names):
        print(f"usage: mutate.py <{'|'.join(MUTATIONS)}> [...] <app.py>", file=sys.stderr)
        return 2
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    for name in names:
        replacements = MUTATIONS[name]
        if isinstance(replacements, tuple):
            replacements = [replacements]
        for old, new in replacements:
            if source.count(old) != 1:
                print(f"mutate: expected exactly one occurrence of the target text for {name}, "
                      f"found {source.count(old)} — the base app changed", file=sys.stderr)
                return 1
            source = source.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(source)
    return 0


if __name__ == "__main__":
    sys.exit(main())
