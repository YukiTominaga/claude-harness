#!/usr/bin/env python3
"""Seed one known defect into the notes-a fixture's app.py.

Each mutation is an exact text replacement. If the text it expects is not
there — the base app drifted — it exits non-zero instead of silently producing a
clean app that an eval case would then score as "defect missed".

Usage: mutate.py <mutation> <path to app.py>
"""

import sys

MUTATIONS = {
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


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in MUTATIONS:
        print(f"usage: mutate.py <{'|'.join(MUTATIONS)}> <app.py>", file=sys.stderr)
        return 2
    old, new = MUTATIONS[sys.argv[1]]
    with open(sys.argv[2], "r", encoding="utf-8") as f:
        source = f.read()
    if source.count(old) != 1:
        print(f"mutate: expected exactly one occurrence of the target text for {sys.argv[1]}, "
              f"found {source.count(old)} — the base app changed", file=sys.stderr)
        return 1
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write(source.replace(old, new))
    return 0


if __name__ == "__main__":
    sys.exit(main())
