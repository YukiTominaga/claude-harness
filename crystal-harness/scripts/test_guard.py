#!/usr/bin/env python3
"""Regression tests for the artifact-ownership guard.

The guard is executable policy: if it silently stops denying, the harness keeps
running and every verdict becomes self-awarded without any visible symptom. That
failure is invisible by construction, so the policy needs a test that fails loudly.

No framework — run it directly:

    python3 crystal-harness/scripts/test_guard.py

Exits 0 when every case matches, 1 otherwise.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

GUARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guard-harness-artifacts.sh")

DENY, ALLOW, BLOCK = "deny", "allow", "block"


def run(event, cwd):
    """Return the guard's decision: 'deny', 'allow', or 'block' (exit 2)."""
    proc = subprocess.run(
        ["bash", GUARD],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if proc.returncode == 2:
        return BLOCK
    if proc.returncode != 0:
        raise AssertionError(f"guard exited {proc.returncode}: {proc.stderr}")
    if not proc.stdout.strip():
        return ALLOW
    return json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"]


def write(agent, path, cwd):
    return {"agent_type": agent, "cwd": cwd, "tool_name": "Write", "tool_input": {"file_path": path}}


def bash(agent, command, cwd):
    return {"agent_type": agent, "cwd": cwd, "tool_name": "Bash", "tool_input": {"command": command}}


def cases(root):
    gen, ev = "harness-generator", "harness-evaluator"
    return [
        # The generator may not author a verdict, in either directory tree.
        ("gen -> sprints verdict.json", write(gen, ".harness/sprints/01/verdict.json", root), DENY),
        ("gen -> sprints qa.md (absolute)", write(gen, f"{root}/.harness/sprints/02/qa.md", root), DENY),
        ("gen -> sprints screenshots", write(gen, ".harness/sprints/01/screenshots/x.png", root), DENY),
        ("gen -> final verdict.json", write(gen, ".harness/final/01/verdict.json", root), DENY),
        ("gen -> final qa.md", write(gen, ".harness/final/02/qa.md", root), DENY),
        # Case-insensitive filesystems resolve these to the same file.
        ("gen -> .HARNESS/.../VERDICT.JSON", write(gen, ".HARNESS/Sprints/01/VERDICT.JSON", root), DENY),
        # Shell is the obvious way around a path check, for the one agent with no
        # legitimate reason to name a verdict artifact at all.
        ("gen -> bash redirect into verdict", bash(gen, "echo x > .harness/sprints/01/verdict.json", root), DENY),
        # What the generator legitimately does.
        ("gen -> sprints report.md", write(gen, ".harness/sprints/01/report.md", root), ALLOW),
        ("gen -> final report.md", write(gen, ".harness/final/01/report.md", root), ALLOW),
        ("gen -> application source", write(gen, "src/App.tsx", root), ALLOW),
        ("gen -> bash npm test", bash(gen, "npm test", root), ALLOW),
        # The evaluator may not edit what it grades — including via traversal or a
        # symlink planted inside .harness/.
        ("eval -> application source", write(ev, "src/App.tsx", root), DENY),
        ("eval -> ../ traversal escape", write(ev, ".harness/../src/App.tsx", root), DENY),
        ("eval -> symlink escape", write(ev, ".harness/escape/App.tsx", root), DENY),
        # What the evaluator legitimately does.
        ("eval -> final verdict.json", write(ev, ".harness/final/01/verdict.json", root), ALLOW),
        ("eval -> sprints qa.md", write(ev, ".harness/sprints/01/qa.md", root), ALLOW),
        ("eval -> bash dev server", bash(ev, "npm run dev", root), ALLOW),
        ("eval -> bash sqlite3 read", bash(ev, 'sqlite3 app.db "select count(*) from notes"', root), ALLOW),
        # Agents outside the harness are none of the guard's business.
        ("unrelated agent -> verdict.json", {"cwd": root, "tool_name": "Write", "tool_input": {"file_path": ".harness/sprints/01/verdict.json"}}, ALLOW),
        # Fail closed: an unevaluatable policy must not read as a satisfied one.
        ("malformed payload", "MALFORMED", BLOCK),
        ("payload is a JSON array", [1, 2, 3], BLOCK),
    ]


def main():
    root = tempfile.mkdtemp(prefix="guard-test-")
    try:
        os.makedirs(os.path.join(root, ".harness"))
        os.makedirs(os.path.join(root, "src"))
        os.symlink(os.path.join(root, "src"), os.path.join(root, ".harness", "escape"))

        failures = []
        for name, event, expected in cases(root):
            if event == "MALFORMED":
                proc = subprocess.run(["bash", GUARD], input="not json", capture_output=True, text=True, cwd=root)
                got = BLOCK if proc.returncode == 2 else ALLOW
            else:
                got = run(event, root)
            ok = got == expected
            if not ok:
                failures.append(name)
            print(f"{'PASS' if ok else 'FAIL'}  {name:<38} want={expected:<6} got={got}")

        print()
        if failures:
            print(f"{len(failures)} failing case(s): {', '.join(failures)}")
            return 1
        print("all guard cases pass")
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
