#!/usr/bin/env python3
"""Regression tests for scripts/team_build.py.

A team build puts several generators on one working tree at once. What keeps
them from overwriting each other is the split plan and the checks around it: if
the validator starts accepting overlapping ownership, if `commit` starts
sweeping up another builder's files, or if the gate lets a generator start
under a name the guard cannot recognise, the build still completes — with one
builder's work silently replaced by another's, or with an unguarded agent.

No framework — run it directly:

    python3 crystal-harness/scripts/test_team_build.py

Exits 0 when every case passes, 1 otherwise.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "team_build.py")

FAILURES = []
COUNT = 0


def check(name, condition, detail=""):
    global COUNT
    COUNT += 1
    if not condition:
        FAILURES.append(name)
    print(f"{'PASS' if condition else 'FAIL'}  {name}{'' if condition else '  <- ' + str(detail)[:500]}")


def run(root, *args, stdin=None):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=root)
    return subprocess.run(["python3", SCRIPT, *args], capture_output=True, text=True, cwd=root, input=stdin, env=env)


def git(root, *args):
    return subprocess.run(["git", "-C", root, *args], check=True, capture_output=True, text=True).stdout


def write(root, path, content="x\n"):
    full = os.path.join(root, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)


PLAN = {
    "interfaces": ["POST /notes {title} -> 201 {id, title}"],
    "builders": [
        {"name": "api", "scope": "the HTTP API", "owns": ["app.py", "tests/api/**"]},
        {"name": "cli", "scope": "the command-line client", "owns": ["cli/**", "tests/cli/"]},
    ],
}


def new_project(plan=PLAN, max_builders=None, round_dir=".harness/final/01"):
    root = tempfile.mkdtemp(prefix="team-test-")
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    harness = {} if max_builders is None else {"maxBuilders": max_builders}
    write(root, ".harness/config.json", json.dumps({"harness": harness}))
    write(root, ".harness/state.json", "{}")
    write(root, "README.md", "# x\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    split = os.path.join(root, round_dir, "split.json")
    write(root, os.path.join(round_dir, "split.json"), json.dumps(plan))
    return root, split


def validates(name, plan, expect_ok, needle=None, **project):
    root, split = new_project(plan, **project)
    try:
        proc = run(root, "validate", split)
        ok = (proc.returncode == 0) is expect_ok and (needle is None or needle in proc.stdout)
        check(name, ok, proc.stdout + proc.stderr)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def with_builders(*builders, interfaces=("GET /x",)):
    return {"interfaces": list(interfaces), "builders": [dict(b) for b in builders]}


def b(name, *owns, scope="does a thing"):
    return {"name": name, "scope": scope, "owns": list(owns)}


def gate(root, **tool_input):
    event = {"hook_event_name": "PreToolUse", "cwd": root, "tool_name": "Agent", "tool_input": tool_input}
    proc = run(root, "gate", stdin=json.dumps(event))
    decision = json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"] if proc.stdout.strip() else "allow"
    return proc, decision


def main():
    # ---- validate
    validates("a two-builder plan with disjoint paths is valid", PLAN, True, "2 builder(s)")
    validates("one builder needs no pinned interfaces", with_builders(b("all", "src/**"), interfaces=()), True)
    validates("the same file owned twice", with_builders(b("a", "app.py"), b("c", "app.py")), False, "overlap")
    validates("a file inside another builder's directory", with_builders(b("a", "src/**"), b("c", "src/api/routes.py")), False, "overlap")
    validates("a directory nested in another's", with_builders(b("a", "src/**"), b("c", "src/api/**")), False, "overlap")
    validates("overlap that differs only by case", with_builders(b("a", "Src/**"), b("c", "src/app.py")), False, "overlap")
    validates("sibling directories with a common name prefix do not overlap",
              with_builders(b("a", "src/api/**"), b("c", "src/api-client/**")), True)
    validates("a file and a same-named-prefix directory do not overlap",
              with_builders(b("a", "app.py"), b("c", "app/**")), True)
    validates("wildcards other than dir/** are refused", with_builders(b("a", "src/*.py"), b("c", "cli/**")), False, "no other wildcards")
    validates("owning the whole project is refused", with_builders(b("a", "**"), b("c", "cli/**")), False, "no other wildcards")
    validates("owning ./ is refused", with_builders(b("a", "./"), b("c", "cli/**")), False, "whole project")
    validates("an absolute path is refused", with_builders(b("a", "/etc/passwd"), b("c", "cli/**")), False, "relative")
    validates("a path with .. is refused", with_builders(b("a", "../other/**"), b("c", "cli/**")), False, "`..`")
    validates("owning part of .harness is refused", with_builders(b("a", ".harness/**"), b("c", "cli/**")), False, ".harness")
    validates("owning .git is refused", with_builders(b("a", ".git/hooks/**"), b("c", "cli/**")), False, ".git")
    validates("more builders than harness.maxBuilders",
              with_builders(b("a", "a/**"), b("c", "c/**"), b("d", "d/**"), b("e", "e/**")), False, "maxBuilders is 3")
    validates("the configured limit is honoured", with_builders(b("a", "a/**"), b("c", "c/**"), b("d", "d/**")), False,
              "maxBuilders is 2", max_builders=2)
    validates("two builders with nothing pinned between them", with_builders(b("a", "a/**"), b("c", "c/**"), interfaces=()), False, "interfaces")
    validates("a duplicate builder name", with_builders(b("a", "a/**"), b("a", "c/**")), False, "used twice")
    validates("a builder name the gate could not match", with_builders(b("API Team", "a/**"), b("c", "c/**")), False, "name")
    validates("a builder with no scope", with_builders({"name": "a", "owns": ["a/**"]}, b("c", "c/**")), False, "scope")
    validates("a builder that owns nothing", with_builders(b("a"), b("c", "c/**")), False, "owns")
    validates("no builders at all", {"interfaces": [], "builders": []}, False, "non-empty")

    root, split = new_project()
    try:
        write(root, ".harness/final/01/split.json", "{ not json")
        proc = run(root, "validate", split)
        check("an unparseable plan is invalid", proc.returncode == 1 and "could not read or parse" in proc.stdout, proc.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # ---- activate / commit / check / report / deactivate
    root, split = new_project()
    try:
        proc = run(root, "commit", "--builder", "api", "-m", "x")
        check("commit without an active plan exits 1", proc.returncode == 1, proc.stderr)
        proc = run(root, "check")
        check("check without an active plan exits 1", proc.returncode == 1, proc.stderr)

        base = git(root, "rev-parse", "HEAD").strip()
        proc = run(root, "activate", split)
        active = json.load(open(os.path.join(root, ".harness", "split.json")))
        check("activate installs the plan with its round directory and base commit",
              proc.returncode == 0 and active["roundDir"] == ".harness/final/01" and active["base"] == base
              and os.path.isdir(os.path.join(root, ".harness/final/01/reports")), proc.stdout + proc.stderr)

        write(root, "app.py", "print('api')\n")
        write(root, "tests/api/test_notes.py", "def test_x(): pass\n")
        write(root, "cli/main.py", "print('cli')\n")          # the other builder, mid-work
        write(root, "notes.txt", "scratch\n")                 # owned by nobody
        proc = run(root, "commit", "--builder", "api", "-m", "feat: api")
        committed = git(root, "show", "--name-only", "--format=", "HEAD").split()
        check("commit takes exactly the builder's own paths",
              proc.returncode == 0 and sorted(committed) == ["app.py", "tests/api/test_notes.py"], (proc.stdout, committed))
        status = git(root, "status", "--porcelain", "--untracked-files=all")
        check("the other builder's file is left untouched and unstaged",
              "?? cli/main.py" in status and "?? notes.txt" in status, status)

        proc = run(root, "commit", "--builder", "api", "-m", "again")
        check("a second commit with nothing new is a no-op, not an error",
              proc.returncode == 0 and "nothing to commit" in proc.stdout, proc.stdout)
        proc = run(root, "commit", "--builder", "ghost", "-m", "x")
        check("an unknown builder cannot commit", proc.returncode == 1 and "not a builder" in proc.stderr, proc.stderr)
        proc = run(root, "commit", "--builder", "cli", "-m", "   ")
        check("an empty commit message is refused", proc.returncode == 1, proc.stderr)

        proc = run(root, "check")
        check("check reports uncommitted work to the builder who owns it",
              proc.returncode == 2 and "builder-cli: uncommitted work in cli/main.py" in proc.stdout, proc.stdout)
        check("check reports a path nobody owns", "nobody: notes.txt" in proc.stdout, proc.stdout)
        check("check reports each missing report",
              "builder-api: no report" in proc.stdout and "builder-cli: no report" in proc.stdout, proc.stdout)

        run(root, "commit", "--builder", "cli", "-m", "feat: cli")
        os.remove(os.path.join(root, "notes.txt"))
        write(root, ".harness/final/01/reports/api.md", "## What is complete\nThe API.\n")
        write(root, ".harness/final/01/reports/cli.md", "## What is complete\nThe client.\n")
        proc = run(root, "check")
        check("check is clean once everything is committed, owned and reported", proc.returncode == 0 and "clean" in proc.stdout, proc.stdout)

        write(root, "README.md", "# changed by someone\n")
        git(root, "add", "README.md")
        git(root, "commit", "-q", "-m", "docs")
        proc = run(root, "check")
        check("a committed change to an unowned path is a violation",
              proc.returncode == 2 and "README.md was committed but no builder owns it" in proc.stdout, proc.stdout)

        proc = run(root, "report")
        text = open(os.path.join(root, ".harness/final/01/report.md")).read()
        check("report joins every builder's report under its name, with the pinned interfaces",
              proc.returncode == 0 and "## Builder `api`" in text and "The client." in text and "POST /notes" in text, text[:300])

        # ---- gate
        gen, ev = "crystal-harness:harness-generator", "crystal-harness:harness-evaluator"
        check("gate: an unnamed generator is allowed", gate(root, subagent_type=gen)[1] == "allow")
        check("gate: a builder of the active plan is allowed", gate(root, subagent_type=gen, name="builder-api")[1] == "allow")
        check("gate: the bare agent type works the same", gate(root, subagent_type="harness-generator", name="builder-cli")[1] == "allow")
        check("gate: a generator under any other name is denied", gate(root, subagent_type=gen, name="backend")[1] == "deny")
        check("gate: a builder name that is not in the plan is denied", gate(root, subagent_type=gen, name="builder-ghost")[1] == "deny")
        check("gate: a named evaluator is denied", gate(root, subagent_type=ev, name="qa")[1] == "deny")
        check("gate: an unnamed evaluator is allowed", gate(root, subagent_type=ev)[1] == "allow")
        check("gate: another agent type may not take a builder name", gate(root, subagent_type="general-purpose", name="builder-api")[1] == "deny")
        check("gate: unrelated named agents are none of its business", gate(root, subagent_type="Explore", name="scout")[1] == "allow")
        check("gate: a named planner is allowed", gate(root, subagent_type="crystal-harness:harness-planner", name="planner")[1] == "allow")
        proc = run(root, "gate", stdin="not json")
        check("gate: fails closed on an event it cannot read", proc.returncode == 2, proc)
        proc = run(root, "gate", stdin=json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}}))
        check("gate: other tools pass", proc.returncode == 0 and not proc.stdout.strip())

        proc = run(root, "deactivate")
        check("deactivate removes the active plan", proc.returncode == 0 and not os.path.exists(os.path.join(root, ".harness/split.json")))
        check("gate: with no active plan a builder cannot start", gate(root, subagent_type=gen, name="builder-api")[1] == "deny")
    finally:
        shutil.rmtree(root, ignore_errors=True)

    root, split = new_project(with_builders(b("a", "src/**"), b("c", "src/api/**")))
    try:
        proc = run(root, "activate", split)
        check("activate refuses an invalid plan and installs nothing",
              proc.returncode == 1 and not os.path.exists(os.path.join(root, ".harness/split.json")), proc.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    root, _ = new_project()
    try:
        write(root, "elsewhere/split.json", json.dumps(PLAN))
        proc = run(root, "activate", os.path.join(root, "elsewhere/split.json"))
        check("activate refuses a plan that is not in a round directory", proc.returncode == 1, proc.stderr)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} failing case(s): {', '.join(FAILURES)}")
        return 1
    print(f"all {COUNT} team-build cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
