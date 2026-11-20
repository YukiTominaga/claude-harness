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

GUARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guard_harness_artifacts.py")

DENY, ALLOW, BLOCK = "deny", "allow", "block"


def run(event, cwd):
    """Return the guard's decision: 'deny', 'allow', or 'block' (exit 2)."""
    proc = subprocess.run(
        ["python3", GUARD],
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
    # What Claude Code actually puts in `agent_type` for an installed plugin's
    # agent: the plugin-namespaced name. Every case below that uses the bare
    # name passed while the guard was a no-op in real runs, because the guard
    # compared the raw value against the bare names — so the namespaced form
    # is tested first and separately.
    ns_gen, ns_ev = "crystal-harness:harness-generator", "crystal-harness:harness-evaluator"
    return [
        ("namespaced gen -> final verdict.json", write(ns_gen, ".harness/final/01/verdict.json", root), DENY),
        ("namespaced gen -> state.json", write(ns_gen, ".harness/state.json", root), DENY),
        ("namespaced gen -> bash into verdict", bash(ns_gen, "echo x > .harness/final/01/verdict.json", root), DENY),
        ("namespaced gen -> application source", write(ns_gen, "src/App.tsx", root), ALLOW),
        ("namespaced eval -> application source", write(ns_ev, "src/App.tsx", root), DENY),
        ("namespaced eval -> final report.md", write(ns_ev, ".harness/final/01/report.md", root), DENY),
        ("namespaced eval -> final verdict.json", write(ns_ev, ".harness/final/01/verdict.json", root), ALLOW),
        # The planner has no row in the ownership table, namespaced or not.
        ("namespaced planner -> spec.md", write("crystal-harness:harness-planner", ".harness/spec.md", root), ALLOW),
        # A name that merely contains a role is not that role.
        ("lookalike agent -> verdict.json", write("not-harness-generator", ".harness/final/01/verdict.json", root), ALLOW),
        ("non-string agent_type -> verdict.json", write(7, ".harness/final/01/verdict.json", root), ALLOW),
        # The generator may not author a verdict, in either directory tree.
        ("gen -> sprints verdict.json", write(gen, ".harness/sprints/01/verdict.json", root), DENY),
        ("gen -> sprints qa.md (absolute)", write(gen, f"{root}/.harness/sprints/02/qa.md", root), DENY),
        ("gen -> sprints screenshots", write(gen, ".harness/sprints/01/screenshots/x.png", root), DENY),
        ("gen -> final verdict.json", write(gen, ".harness/final/01/verdict.json", root), DENY),
        ("gen -> final qa.md", write(gen, ".harness/final/02/qa.md", root), DENY),
        # Case-insensitive filesystems resolve these to the same file.
        ("gen -> .HARNESS/.../VERDICT.JSON", write(gen, ".HARNESS/Sprints/01/VERDICT.JSON", root), DENY),
        # The generator may not rewrite the orchestrator's run state either —
        # a self-serving handoff.md is self-grading with extra steps.
        ("gen -> state.json", write(gen, ".harness/state.json", root), DENY),
        ("gen -> handoff.md", write(gen, ".harness/handoff.md", root), DENY),
        ("gen -> journal.md", write(gen, ".harness/journal.md", root), DENY),
        ("gen -> spec.md", write(gen, ".harness/spec.md", root), DENY),
        ("gen -> config.json", write(gen, ".harness/config.json", root), DENY),
        # The cost ledger is written by a hook from transcripts. An agent that
        # can edit it can make itself look cheap.
        ("gen -> ledger.jsonl", write(gen, ".harness/ledger.jsonl", root), DENY),
        ("gen -> bash appending to ledger", bash(gen, "echo '{}' >> .harness/ledger.jsonl", root), DENY),
        # Shell is the obvious way around a path check, for the one agent with no
        # legitimate reason to name a verdict artifact at all.
        ("gen -> bash redirect into verdict", bash(gen, "echo x > .harness/sprints/01/verdict.json", root), DENY),
        ("gen -> bash redirect into handoff", bash(gen, "echo x >> .harness/handoff.md", root), DENY),
        ("gen -> bash naming state.json", bash(gen, "cat .harness/state.json", root), DENY),
        # codex-review.md is an independent review of the generator's own diff.
        # A generator that can write it can manufacture its own second opinion.
        ("gen -> sprints codex-review.md", write(gen, ".harness/sprints/01/codex-review.md", root), DENY),
        ("gen -> final codex-review.md", write(gen, ".harness/final/02/codex-review.md", root), DENY),
        ("gen -> bash redirect into codex-review", bash(gen, "echo x > .harness/final/01/codex-review.md", root), DENY),
        # test-changes.json reports what the round did to the tests. The generator
        # would be writing the report on its own test deletions.
        ("gen -> final test-changes.json", write(gen, ".harness/final/02/test-changes.json", root), DENY),
        ("gen -> bash redirect into test-changes", bash(gen, "echo '{}' > .harness/final/02/test-changes.json", root), DENY),
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
        # Inside .harness/ the evaluator still owns only its round artifacts:
        # not the run state, not the spec, not the generator's report.
        ("eval -> state.json", write(ev, ".harness/state.json", root), DENY),
        ("eval -> handoff.md", write(ev, ".harness/handoff.md", root), DENY),
        ("eval -> spec.md", write(ev, ".harness/spec.md", root), DENY),
        ("eval -> ledger.jsonl", write(ev, ".harness/ledger.jsonl", root), DENY),
        ("eval -> sprints report.md", write(ev, ".harness/sprints/01/report.md", root), DENY),
        ("eval -> final report.md", write(ev, ".harness/final/01/report.md", root), DENY),
        ("eval -> stray note in .harness", write(ev, ".harness/notes.md", root), DENY),
        # The evaluator weighs codex-review.md; editing it would be editing the
        # evidence it is about to cite.
        ("eval -> sprints codex-review.md", write(ev, ".harness/sprints/01/codex-review.md", root), DENY),
        ("eval -> final codex-review.md", write(ev, ".harness/final/01/codex-review.md", root), DENY),
        ("eval -> sprints test-changes.json", write(ev, ".harness/sprints/01/test-changes.json", root), DENY),
        # What the evaluator legitimately does.
        ("eval -> final verdict.json", write(ev, ".harness/final/01/verdict.json", root), ALLOW),
        ("eval -> sprints qa.md", write(ev, ".harness/sprints/01/qa.md", root), ALLOW),
        ("eval -> sprints screenshots", write(ev, ".harness/sprints/01/screenshots/fail.png", root), ALLOW),
        ("eval -> contract review block", write(ev, ".harness/sprints/01/contract.md", root), ALLOW),
        ("eval -> playwright artifacts", write(ev, ".harness/artifacts/snap.png", root), ALLOW),
        # Parallel evaluation: each lens writes its own files under lenses/.
        ("eval -> lens verdict", write(ev, ".harness/final/02/lenses/api.json", root), ALLOW),
        ("eval -> lens notes", write(ev, ".harness/sprints/01/lenses/code.md", root), ALLOW),
        ("eval -> reproduction result", write(ev, ".harness/final/02/lenses/verify/B-api-1.json", root), ALLOW),
        ("gen -> lens verdict", write(gen, ".harness/final/02/lenses/api.json", root), DENY),
        ("gen -> bash into lens verdict", bash(gen, "echo '{}' > .harness/final/02/lenses/api.json", root), DENY),
        ("gen -> bash in the app's own lenses dir", bash(gen, "ls src/lenses/ && npm test", root), ALLOW),
        ("gen -> app source named lenses", write(gen, "src/lenses/wide.ts", root), ALLOW),
        ("eval -> bash dev server", bash(ev, "npm run dev", root), ALLOW),
        ("eval -> bash sqlite3 read", bash(ev, 'sqlite3 app.db "select count(*) from notes"', root), ALLOW),
        ("eval -> bash reading codex-review", bash(ev, "cat .harness/sprints/01/codex-review.md", root), ALLOW),
        # ---- team build: builders are generator teammates, seen by NAME, each
        # confined to the paths the active split plan gives it.
        ("builder -> its own file", write("builder-api", "app.py", root), ALLOW),
        ("builder -> inside its own directory", write("builder-api", "tests/api/test_notes.py", root), ALLOW),
        ("builder -> its own directory, other case", write("builder-api", "Tests/API/x.py", root), ALLOW),
        ("builder -> another builder's file", write("builder-api", "cli/main.py", root), DENY),
        ("builder -> a path nobody owns", write("builder-api", "README.md", root), DENY),
        ("builder -> a sibling of its file", write("builder-api", "app.py.bak", root), DENY),
        ("builder -> ../ escape into another's dir", write("builder-api", "tests/api/../../cli/main.py", root), DENY),
        ("builder -> its own report", write("builder-api", ".harness/final/01/reports/api.md", root), ALLOW),
        ("builder -> another builder's report", write("builder-api", ".harness/final/01/reports/cli.md", root), DENY),
        ("builder -> the active split plan", write("builder-api", ".harness/split.json", root), DENY),
        ("builder -> the round's split plan", write("builder-api", ".harness/final/01/split.json", root), DENY),
        ("builder -> verdict.json", write("builder-api", ".harness/final/01/verdict.json", root), DENY),
        ("builder -> state.json", write("builder-api", ".harness/state.json", root), DENY),
        ("builder not in the plan owns nothing", write("builder-ghost", "app.py", root), DENY),
        ("builder -> bash npm test", bash("builder-cli", "npm test", root), ALLOW),
        ("builder -> bash git status and diff", bash("builder-cli", "git status --short && git diff -- cli/", root), ALLOW),
        ("builder -> bash git log", bash("builder-cli", "git log --oneline -5", root), ALLOW),
        ("builder -> bash git commit", bash("builder-cli", "git commit -am wip", root), DENY),
        ("builder -> bash git add", bash("builder-cli", "git add -A", root), DENY),
        ("builder -> bash git stash", bash("builder-cli", "git stash", root), DENY),
        ("builder -> bash git checkout .", bash("builder-cli", "git checkout -- .", root), DENY),
        ("builder -> bash git -C . reset", bash("builder-cli", "git -C . reset --hard", root), DENY),
        ("builder -> bash commit through the script", bash("builder-cli", 'python3 "/p/scripts/team_build.py" commit --builder cli -m "feat: cli"', root), ALLOW),
        ("builder -> bash naming split.json", bash("builder-cli", "cat .harness/split.json", root), DENY),
        ("builder -> bash into verdict", bash("builder-cli", "echo x > .harness/final/01/verdict.json", root), DENY),
        # The plain generator writes the round's proposed plan, never the active one.
        ("gen -> the round's split plan", write(gen, ".harness/final/01/split.json", root), ALLOW),
        ("gen -> the active split plan", write(gen, ".harness/split.json", root), DENY),
        ("namespaced gen -> git commit is its normal way to commit", bash(ns_gen, "git add -A && git commit -m feat", root), ALLOW),
        ("eval -> the active split plan", write(ev, ".harness/split.json", root), DENY),
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
        with open(os.path.join(root, ".harness", "split.json"), "w", encoding="utf-8") as f:
            json.dump({"builders": [
                {"name": "api", "scope": "the API", "owns": ["app.py", "tests/api/**"]},
                {"name": "cli", "scope": "the client", "owns": ["cli/**"]},
            ], "interfaces": ["GET /notes"], "roundDir": ".harness/final/01", "base": "x"}, f)
        os.symlink(os.path.join(root, "src"), os.path.join(root, ".harness", "escape"))

        failures = []
        for name, event, expected in cases(root):
            if event == "MALFORMED":
                proc = subprocess.run(["python3", GUARD], input="not json", capture_output=True, text=True, cwd=root)
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
        print(f"all {len(cases(root))} guard cases pass")
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
