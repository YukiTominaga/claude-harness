#!/usr/bin/env python3
"""Regression tests for scripts/returned_files.py.

When a rule outside this plugin refuses an agent's Write, the agent hands the
file back in its final response and the orchestrator puts it in place with
this script. What has to hold is that nothing in between touches the content:
the hook keeps the response as the agent wrote it, `place` writes each block
byte for byte, only into the files that agent's role owns, and refuses —
writing nothing — whenever it cannot do exactly that. A lenient `place` would
let one agent's response stand in for another's file, or a verdict arrive from
the generator.

No framework — run it directly:

    python3 crystal-harness/scripts/test_returned_files.py

Exits 0 when every case passes, 1 otherwise.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "returned_files.py")

FAILURES = []
COUNT = 0

GEN = "crystal-harness:harness-generator"
EV = "crystal-harness:harness-evaluator"

# Deliberately awkward: non-ASCII, trailing spaces, a blank line at the end,
# a fenced block, and a line that mentions a marker without being one.
NOTES = (
    "# Sprint 03 report — build\n"
    "\n"
    "## What is complete\n"
    "- S-1 ノート一覧 (commit abc1234)   \n"
    "```\n$ npm test\n12 passed\n```\n"
    "Mentions <!-- crystal-harness:end build-notes.md --> inline, which is not a marker.\n"
    "\n"
)


def check(name, condition, detail=""):
    global COUNT
    COUNT += 1
    if not condition:
        FAILURES.append(name)
    print(f"{'PASS' if condition else 'FAIL'}  {name}{'' if condition else '  <- ' + str(detail)[:600]}")


def block(name, content):
    return f"<!-- crystal-harness:begin {name} -->\n{content}<!-- crystal-harness:end {name} -->\n"


def response(*blocks, rejected=".harness/sprints/03/build-notes.md"):
    head = "Commits: abc1234 feat: notes list.\nSelf-check: npm test — 12 passed.\n"
    if rejected:
        head += f"Write rejected: {rejected} — Some rule you have never heard of.\n"
    return head + "".join(blocks)


def new_project(state=True):
    root = tempfile.mkdtemp(prefix="returned-test-")
    os.makedirs(os.path.join(root, ".harness", "sprints", "03"))
    os.makedirs(os.path.join(root, ".harness", "final", "01"))
    if state:
        with open(os.path.join(root, ".harness", "state.json"), "w", encoding="utf-8") as f:
            f.write("{}")
    return root


def run(root, *args, stdin=None):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=root)
    return subprocess.run(["python3", SCRIPT, *args], capture_output=True, text=True, cwd=root, input=stdin, env=env)


def capture(root, agent_type, message, agent_id="a1", **extra):
    event = {"hook_event_name": "SubagentStop", "cwd": root, "agent_type": agent_type, "agent_id": agent_id,
             "agent_transcript_path": "/nowhere/agent.jsonl", "last_assistant_message": message}
    event.update(extra)
    return run(root, "capture", stdin=json.dumps(event))


def captures(root):
    path = os.path.join(root, ".harness", "captures")
    return sorted(f for f in os.listdir(path) if f.endswith(".json")) if os.path.isdir(path) else []


def read(root, rel):
    with open(os.path.join(root, rel), "r", encoding="utf-8", newline="") as f:
        return f.read()


def exists(root, rel):
    return os.path.exists(os.path.join(root, rel))


def main():
    # ---- capture: the SubagentStop hook
    root = new_project()
    try:
        message = response(block("build-notes.md", NOTES))
        proc = capture(root, GEN, message)
        saved = json.load(open(os.path.join(root, ".harness", "captures", "a1.json"), encoding="utf-8"))
        check("capture keeps a generator's final response verbatim when it hands a file back",
              proc.returncode == 0 and saved["message"] == message and saved["agentType"] == GEN and saved["agentId"] == "a1",
              (proc.returncode, proc.stderr, saved.get("agentType")))
        check("capture prints nothing", proc.stdout == "" and proc.stderr == "", (proc.stdout, proc.stderr))
        capture(root, EV, response(block("qa.md", "# QA\n")), agent_id="e1")
        capture(root, "builder-api", response(block("reports/builder-api.md", "## What is complete\n")), agent_id="b1")
        check("capture keeps an evaluator's and a builder's too", captures(root) == ["a1.json", "b1.json", "e1.json"], captures(root))
        capture(root, GEN, "Commits: abc. Self-check: ok.\n", agent_id="plain")
        check("a final response with no block is not kept", "plain.json" not in captures(root), captures(root))
        capture(root, "crystal-harness:harness-planner", response(block("build-notes.md", NOTES)), agent_id="p1")
        capture(root, "general-purpose", response(block("build-notes.md", NOTES)), agent_id="g1")
        capture(root, "crystal-harness:harness-investigator", response(block("build-notes.md", NOTES)), agent_id="i1")
        check("an agent with no file to hand back is not kept",
              not {"p1.json", "g1.json", "i1.json"} & set(captures(root)), captures(root))
        capture(root, GEN, response(block("build-notes.md", NOTES)), agent_id="../../escape")
        check("a hostile agent id cannot place the capture outside captures/",
              not exists(root, "escape.json") and not exists(root, ".harness/escape.json")
              and any("escape" in c for c in captures(root)), captures(root))
        proc = capture(root, GEN, None, agent_id="nomsg")
        check("an event without last_assistant_message is not kept, and does not fail",
              proc.returncode == 0 and "nomsg.json" not in captures(root), proc)
        proc = run(root, "capture", stdin="not json")
        check("capture exits 0 on an event it cannot read", proc.returncode == 0 and proc.stdout == "", proc)
        proc = run(root, "capture", stdin=json.dumps({"hook_event_name": "Stop", "agent_type": GEN, "agent_id": "s1",
                                                       "last_assistant_message": message}))
        check("capture ignores other hook events", proc.returncode == 0 and "s1.json" not in captures(root))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    root = new_project(state=False)
    try:
        capture(root, GEN, response(block("build-notes.md", NOTES)))
        check("capture writes nothing outside a harness run", not exists(root, ".harness/captures"))
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # ---- place: the generator's notes
    root = new_project()
    try:
        with open(os.path.join(root, ".harness", "journal.md"), "w", encoding="utf-8") as f:
            f.write("## earlier entry\n")
        capture(root, GEN, response(block("build-notes.md", NOTES)), agent_id="a1")
        proc = run(root, "place", "--round-dir", ".harness/sprints/03", "--agent-id", "a1")
        placed = read(root, ".harness/sprints/03/build-notes.md") if exists(root, ".harness/sprints/03/build-notes.md") else None
        check("place writes the notes byte for byte", proc.returncode == 0 and placed == NOTES, (proc.stdout, proc.stderr, placed))
        journal = read(root, ".harness/journal.md")
        digest = hashlib.sha256(NOTES.encode("utf-8")).hexdigest()
        check("place journals where the file came from",
              journal.startswith("## earlier entry\n") and "a1" in journal and GEN in journal
              and ".harness/sprints/03/build-notes.md" in journal and digest in journal
              and str(len(NOTES.encode("utf-8"))) in journal, journal)
        check("the journal quotes the rejection the agent reported",
              "Write rejected: .harness/sprints/03/build-notes.md — Some rule you have never heard of." in journal, journal)
        check("the capture is kept as provenance, out of the way of the next place",
              captures(root) == [] and exists(root, ".harness/captures/placed/a1.json"), captures(root))
        check("place never writes the legacy name", not exists(root, ".harness/sprints/03/report.md"))
        proc = run(root, "place", "--round-dir", ".harness/sprints/03")
        check("a capture cannot be placed twice", proc.returncode == 1 and "no capture" in proc.stdout.lower(), proc.stdout)

        # A revision round: last round's notes are still in the directory.
        capture(root, GEN, response(block("build-notes.md", "# Sprint 03 report — revision 1\n")), agent_id="a2")
        proc = run(root, "place", "--round-dir", ".harness/sprints/03")
        check("a revision's returned notes replace the previous round's",
              proc.returncode == 0 and read(root, ".harness/sprints/03/build-notes.md") == "# Sprint 03 report — revision 1\n", proc.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # ---- place: only what the agent's role owns, and all or nothing
    def refused(name, agent_type, message, round_dir=".harness/sprints/03", needle=None, untouched=()):
        root = new_project()
        try:
            capture(root, agent_type, message, agent_id="x1")
            proc = run(root, "place", "--round-dir", round_dir)
            written = [rel for rel in (".harness/sprints/03/build-notes.md", ".harness/sprints/03/qa.md",
                                       ".harness/sprints/03/verdict.json", ".harness/journal.md", *untouched) if exists(root, rel)]
            ok = proc.returncode == 1 and not written and (needle is None or needle in proc.stdout)
            check(name, ok and captures(root) == ["x1.json"], (proc.returncode, proc.stdout, proc.stderr, written, captures(root)))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    refused("the generator cannot hand back a verdict — nothing is placed, not even its notes", GEN,
            response(block("build-notes.md", NOTES), block("verdict.json", '{"verdict": "pass"}\n')), needle="verdict.json")
    refused("the evaluator cannot hand back the generator's notes", EV, response(block("build-notes.md", NOTES)), needle="build-notes.md")
    refused("nobody hands back the legacy name", GEN, response(block("report.md", NOTES)), needle="report.md")
    refused("a block with no end marker", GEN, response("<!-- crystal-harness:begin build-notes.md -->\n" + NOTES), needle="end marker")
    refused("the same file twice", GEN, response(block("build-notes.md", NOTES), block("build-notes.md", "# other\n")), needle="twice")
    refused("an empty block", GEN, response(block("build-notes.md", "")), needle="empty")
    refused("a block nested in another", GEN,
            response("<!-- crystal-harness:begin build-notes.md -->\n# a\n" + block("build-notes.md", "# b\n")), needle="inside")
    refused("a round directory that is not one", GEN, response(block("build-notes.md", NOTES)), round_dir=".harness/elsewhere",
            needle="round directory")
    refused("a round directory outside the project", GEN, response(block("build-notes.md", NOTES)), round_dir="../sprints/03",
            needle="round directory")

    # ---- place: the evaluator's two files, and a builder's report
    root = new_project()
    try:
        verdict = '{\n  "verdict": "fail"\n}\n'
        capture(root, EV, response(block("qa.md", "# QA — sprint 03\n"), block("verdict.json", verdict), rejected=None), agent_id="e1")
        proc = run(root, "place", "--round-dir", ".harness/sprints/03")
        check("the evaluator's qa.md and verdict.json are both placed",
              proc.returncode == 0 and read(root, ".harness/sprints/03/qa.md") == "# QA — sprint 03\n"
              and read(root, ".harness/sprints/03/verdict.json") == verdict, proc.stdout + proc.stderr)

        capture(root, "builder-api", response(block("reports/builder-api.md", "## API\n")), agent_id="b1")
        capture(root, "builder-cli", response(block("reports/builder-api.md", "## not mine\n")), agent_id="b2")
        proc = run(root, "place", "--round-dir", ".harness/final/01")
        check("with two captures waiting, place will not guess", proc.returncode == 1 and "b1" in proc.stdout and "b2" in proc.stdout, proc.stdout)
        proc = run(root, "place", "--round-dir", ".harness/final/01", "--agent", "builder-api")
        check("a builder's report is placed under reports/",
              proc.returncode == 0 and read(root, ".harness/final/01/reports/builder-api.md") == "## API\n", proc.stdout + proc.stderr)
        proc = run(root, "place", "--round-dir", ".harness/final/01", "--agent-id", "b2")
        check("a builder cannot hand back another builder's report",
              proc.returncode == 1 and read(root, ".harness/final/01/reports/builder-api.md") == "## API\n", proc.stdout)
        proc = run(root, "place", "--round-dir", ".harness/final/01", "--agent-id", "nobody")
        check("an agent id with no capture is refused", proc.returncode == 1, proc.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    # ---- notes-path: build-notes.md, else the legacy report.md
    root = new_project()
    try:
        rd = os.path.join(".harness", "sprints", "03")
        proc = run(root, "notes-path", rd)
        check("notes-path with neither file exits 1", proc.returncode == 1 and proc.stdout == "", proc)
        with open(os.path.join(root, rd, "report.md"), "w", encoding="utf-8") as f:
            f.write("# legacy\n")
        proc = run(root, "notes-path", rd)
        check("a round from before 0.16.0 falls back to the legacy report.md",
              proc.returncode == 0 and proc.stdout.strip() == os.path.join(rd, "report.md"), proc.stdout)
        with open(os.path.join(root, rd, "build-notes.md"), "w", encoding="utf-8") as f:
            f.write("# new\n")
        proc = run(root, "notes-path", rd)
        check("when both exist, build-notes.md is the one and the legacy file is ignored",
              proc.returncode == 0 and proc.stdout.strip() == os.path.join(rd, "build-notes.md"), proc.stdout)
        os.remove(os.path.join(root, rd, "report.md"))
        proc = run(root, "notes-path", rd)
        check("build-notes.md alone", proc.returncode == 0 and proc.stdout.strip() == os.path.join(rd, "build-notes.md"), proc.stdout)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} failing case(s): {', '.join(FAILURES)}")
        return 1
    print(f"all {COUNT} returned-file cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
