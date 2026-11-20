#!/usr/bin/env python3
"""Regression tests for the cost ledger (scripts/ledger.py).

The ledger is the evidence for every "is this component still worth its cost"
decision, and it breaks invisibly: a hook that stops recording, a sum that
double-counts a streamed response, or a snapshot that is added instead of
superseded all produce a plausible-looking table. So the arithmetic and the
hook's contract are tested here.

No framework — run it directly:

    python3 crystal-harness/scripts/test_ledger.py

Exits 0 when every case passes, 1 otherwise.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

LEDGER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ledger.py")

FAILURES = []
COUNT = 0


def check(name, condition, detail=""):
    global COUNT
    COUNT += 1
    if not condition:
        FAILURES.append(name)
    print(f"{'PASS' if condition else 'FAIL'}  {name}{'' if condition else '  <- ' + str(detail)}")


def usage(inp, out, cache_write, cache_read):
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_creation_input_tokens": cache_write,
        "cache_read_input_tokens": cache_read,
    }


def assistant(message_id, ts, use, model="claude-opus-5-5", text=None):
    message = {"id": message_id, "model": model, "usage": use}
    if text is not None:
        message["content"] = [{"type": "text", "text": text}]
    return {"type": "assistant", "timestamp": ts, "message": message}


def write_transcript(path, records):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write((record if isinstance(record, str) else json.dumps(record)) + "\n")


def new_project(state=None, config=None):
    root = tempfile.mkdtemp(prefix="ledger-test-")
    os.makedirs(os.path.join(root, ".harness"))
    if state is not None:
        with open(os.path.join(root, ".harness", "state.json"), "w", encoding="utf-8") as f:
            f.write(state if isinstance(state, str) else json.dumps(state))
    if config is not None:
        with open(os.path.join(root, ".harness", "config.json"), "w", encoding="utf-8") as f:
            json.dump(config, f)
    return root


def hook_env(root, settle_ms):
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = root
    # 0 = read the transcript once and do not wait for it to settle.
    env["CRYSTAL_HARNESS_LEDGER_SETTLE_MS"] = str(settle_ms)
    return env


def run_hook(root, event, raw=None, settle_ms=0):
    return subprocess.run(
        ["python3", LEDGER, "hook"],
        input=raw if raw is not None else json.dumps(event),
        capture_output=True,
        text=True,
        env=hook_env(root, settle_ms),
        cwd=root,
    )


def stop_event(root, agent_type, agent_id, transcript):
    return {
        "hook_event_name": "SubagentStop",
        "cwd": root,
        "agent_type": agent_type,
        "agent_id": agent_id,
        "agent_transcript_path": transcript,
    }


def ledger_lines(root):
    path = os.path.join(root, ".harness", "ledger.jsonl")
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def report(root):
    proc = subprocess.run(
        ["python3", LEDGER, "report", "--json", "--project-dir", root], capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise AssertionError(f"report exited {proc.returncode}: {proc.stderr}")
    return json.loads(proc.stdout)


STATE = {"schemaVersion": 3, "phase": "final-qa", "currentSprint": None, "currentRound": 2}


def test_hook_sums_the_whole_run():
    root = new_project(STATE)
    try:
        transcript = os.path.join(root, "t", "subagents", "agent-a1.jsonl")
        write_transcript(transcript, [
            {"type": "user", "timestamp": "2026-11-20T04:00:00.000Z", "message": {"role": "user", "content": "go"}},
            assistant("msg_1", "2026-11-20T04:00:10.000Z", usage(2, 100, 4000, 0)),
            assistant("msg_2", "2026-11-20T04:01:30.500Z", usage(3, 250, 500, 4000)),
        ])
        proc = run_hook(root, stop_event(root, "crystal-harness:harness-evaluator", "a1", transcript))
        lines = ledger_lines(root)
        check("hook exits 0 and prints nothing", proc.returncode == 0 and proc.stdout == "", proc)
        check("hook writes exactly one entry", len(lines) == 1, lines)
        e = lines[0] if lines else {}
        check("namespaced agent_type resolves to its role", e.get("agent") == "harness-evaluator", e.get("agent"))
        check("raw agent_type is kept", e.get("agentType") == "crystal-harness:harness-evaluator")
        check(
            "tokens are summed across every request, not the last one",
            e.get("tokens") == {"input": 5, "output": 350, "cacheWrite": 4500, "cacheRead": 4000},
            e.get("tokens"),
        )
        check("request count", e.get("requests") == 2, e.get("requests"))
        check("duration spans first to last record", e.get("durationMs") == 90500, e.get("durationMs"))
        check("models seen are listed", e.get("models") == ["claude-opus-5-5"], e.get("models"))
        check(
            "phase, sprint and round come from state.json",
            (e.get("phase"), e.get("sprint"), e.get("round")) == ("final-qa", None, 2),
            (e.get("phase"), e.get("sprint"), e.get("round")),
        )
        check("plain subagent kind", e.get("kind") == "subagent", e.get("kind"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_streamed_response_is_counted_once():
    root = new_project(STATE)
    try:
        transcript = os.path.join(root, "t", "subagents", "agent-a2.jsonl")
        # One API response written as three lines (one per content block), the
        # first carrying a partial output count; then a torn final line.
        write_transcript(transcript, [
            assistant("msg_1", "2026-11-20T04:00:00.000Z", usage(2, 10, 1000, 300)),
            assistant("msg_1", "2026-11-20T04:00:01.000Z", usage(2, 80, 1000, 300)),
            assistant("msg_1", "2026-11-20T04:00:02.000Z", usage(2, 80, 1000, 300)),
            '{"type": "assistant", "timestamp": "2026-11-20T04:00:0',
        ])
        run_hook(root, stop_event(root, "harness-generator", "a2", transcript))
        e = (ledger_lines(root) or [{}])[0]
        check(
            "repeated message id is one request with the per-field maximum",
            e.get("requests") == 1 and e.get("tokens") == {"input": 2, "output": 80, "cacheWrite": 1000, "cacheRead": 300},
            e,
        )
        check("bare agent_type also resolves", e.get("agent") == "harness-generator", e.get("agent"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_kinds():
    root = new_project(STATE)
    try:
        wf = os.path.join(root, "t", "subagents", "workflows", "wf_1", "agent-w1.jsonl")
        write_transcript(wf, [assistant("m", "2026-11-20T04:00:00.000Z", usage(1, 1, 1, 1))])
        run_hook(root, stop_event(root, "workflow-subagent", "w1", wf))

        tm = os.path.join(root, "t", "subagents", "agent-tm1.jsonl")
        write_transcript(tm, [assistant("m", "2026-11-20T04:00:00.000Z", usage(1, 1, 1, 1))])
        with open(tm[: -len(".jsonl")] + ".meta.json", "w", encoding="utf-8") as f:
            json.dump({"agentType": "backend", "taskKind": "in_process_teammate"}, f)
        run_hook(root, stop_event(root, "backend", "tm1", tm))

        by_id = {e["agentId"]: e for e in ledger_lines(root)}
        check("workflow agent kind from transcript location", by_id.get("w1", {}).get("kind") == "workflow", by_id.get("w1"))
        check("default workflow agent is role 'other'", by_id.get("w1", {}).get("agent") == "other")
        check("teammate kind from the meta sidecar", by_id.get("tm1", {}).get("kind") == "teammate", by_id.get("tm1"))
        check("teammate named by the lead is role 'other'", by_id.get("tm1", {}).get("agent") == "other")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_hook_never_blocks_and_never_lies():
    root = new_project(STATE)
    try:
        missing = os.path.join(root, "t", "subagents", "agent-gone.jsonl")
        proc = run_hook(root, stop_event(root, "crystal-harness:harness-generator", "gone", missing))
        e = (ledger_lines(root) or [{}])[-1]
        check("unreadable transcript still exits 0", proc.returncode == 0, proc)
        check(
            "unreadable transcript is recorded as tokens null with a note, not as zero",
            e.get("agentId") == "gone" and e.get("tokens") is None and "unreadable" in e.get("note", ""),
            e,
        )

        empty = os.path.join(root, "t", "subagents", "agent-empty.jsonl")
        write_transcript(empty, [{"type": "user", "timestamp": "2026-11-20T04:00:00.000Z", "message": {"content": "x"}}])
        run_hook(root, stop_event(root, "crystal-harness:harness-generator", "empty", empty))
        e = ledger_lines(root)[-1]
        check("transcript with no usage records is null, not zero", e.get("tokens") is None and "note" in e, e)

        before = len(ledger_lines(root))
        proc = run_hook(root, None, raw="not json")
        check("malformed event exits 0 and writes nothing", proc.returncode == 0 and len(ledger_lines(root)) == before, proc)
        proc = run_hook(root, [1, 2, 3])
        check("non-object event exits 0 and writes nothing", proc.returncode == 0 and len(ledger_lines(root)) == before)

        t = os.path.join(root, "t", "subagents", "agent-x.jsonl")
        write_transcript(t, [assistant("m", "2026-11-20T04:00:00.000Z", usage(1, 1, 1, 1))])
        run_hook(root, stop_event(root, "", "internal", t))
        check("empty agent_type (internal helper) is skipped", len(ledger_lines(root)) == before)
        other = dict(stop_event(root, "harness-generator", "x", t), hook_event_name="PreToolUse")
        run_hook(root, other)
        check("events other than SubagentStop are ignored", len(ledger_lines(root)) == before)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_hook_outside_a_run_and_project_dir():
    bare = tempfile.mkdtemp(prefix="ledger-test-bare-")
    root = new_project(STATE)
    try:
        t = os.path.join(bare, "agent-a.jsonl")
        write_transcript(t, [assistant("m", "2026-11-20T04:00:00.000Z", usage(1, 1, 1, 1))])
        run_hook(bare, stop_event(bare, "harness-generator", "a", t))
        check("no .harness/state.json means no ledger is created", not os.path.exists(os.path.join(bare, ".harness")))

        # A worktree-isolated agent reports the worktree as cwd. The ledger
        # belongs to the project the session was started in.
        event = stop_event(os.path.join(root, "some", "worktree"), "harness-generator", "wt", t)
        run_hook(root, event)
        check("CLAUDE_PROJECT_DIR wins over the event's cwd", [e["agentId"] for e in ledger_lines(root)] == ["wt"])

        unreadable = new_project("{ not json")
        run_hook(unreadable, stop_event(unreadable, "harness-generator", "u", t))
        e = (ledger_lines(unreadable) or [{}])[0]
        check(
            "unparseable state.json still records the entry, with null position",
            e.get("tokens") is not None and (e.get("phase"), e.get("sprint"), e.get("round")) == (None, None, None),
            e,
        )
        shutil.rmtree(unreadable, ignore_errors=True)
    finally:
        shutil.rmtree(bare, ignore_errors=True)
        shutil.rmtree(root, ignore_errors=True)


def test_hook_waits_for_the_final_response():
    # Claude Code flushes an agent's last response to the transcript shortly
    # AFTER SubagentStop fires. A hook that sums at once loses that request from
    # every entry — which is what the first version of this hook did.
    root = new_project(STATE)
    try:
        first = assistant("m1", "2026-11-20T04:00:00.000Z", usage(2, 50, 3000, 0))
        final = assistant("m2", "2026-11-20T04:00:05.000Z", usage(2, 9, 0, 3000), text="DONE")

        late = os.path.join(root, "t", "subagents", "agent-late.jsonl")
        write_transcript(late, [first])
        event = dict(stop_event(root, "crystal-harness:harness-evaluator", "late", late), last_assistant_message="DONE")
        proc = subprocess.Popen(
            ["python3", LEDGER, "hook"], stdin=subprocess.PIPE, text=True, env=hook_env(root, 5000), cwd=root
        )
        proc.stdin.write(json.dumps(event))
        proc.stdin.close()
        time.sleep(0.3)
        with open(late, "a", encoding="utf-8") as f:
            f.write(json.dumps(final) + "\n")
        proc.wait(timeout=20)
        e = ledger_lines(root)[-1]
        check(
            "a final response that lands after the hook starts is still counted",
            e.get("requests") == 2 and e.get("tokens", {}).get("cacheRead") == 3000 and "note" not in e,
            e,
        )

        ready = os.path.join(root, "t", "subagents", "agent-ready.jsonl")
        write_transcript(ready, [first, final])
        event = dict(stop_event(root, "harness-evaluator", "ready", ready), last_assistant_message="  DONE\n")
        started = time.monotonic()
        run_hook(root, event, settle_ms=5000)
        e = ledger_lines(root)[-1]
        check(
            "a transcript that already ends with the final message is not waited on",
            e.get("requests") == 2 and "note" not in e and time.monotonic() - started < 2.5,
            (e, time.monotonic() - started),
        )

        never = os.path.join(root, "t", "subagents", "agent-never.jsonl")
        write_transcript(never, [first])
        event = dict(stop_event(root, "harness-evaluator", "never", never), last_assistant_message="DONE")
        proc = run_hook(root, event, settle_ms=300)
        e = ledger_lines(root)[-1]
        check(
            "a final response that never arrives is flagged, not silently dropped",
            proc.returncode == 0 and e.get("requests") == 1 and "not confirmed" in e.get("note", ""),
            e,
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_report_supersedes_snapshots():
    root = new_project(STATE, {"harness": {"costPerMTokUsd": None}})
    try:
        t = os.path.join(root, "t", "subagents", "agent-tm.jsonl")
        write_transcript(t, [assistant("m1", "2026-11-20T04:00:00.000Z", usage(1, 10, 100, 0))])
        run_hook(root, stop_event(root, "harness-generator", "tm", t))
        # The same agent works again and stops again: a cumulative snapshot.
        write_transcript(t, [
            assistant("m1", "2026-11-20T04:00:00.000Z", usage(1, 10, 100, 0)),
            assistant("m2", "2026-11-20T04:05:00.000Z", usage(1, 20, 0, 100)),
        ])
        run_hook(root, stop_event(root, "harness-generator", "tm", t))
        e2 = os.path.join(root, "t", "subagents", "agent-ev.jsonl")
        write_transcript(e2, [assistant("m1", "2026-11-20T04:10:00.000Z", usage(4, 6, 0, 90))])
        run_hook(root, stop_event(root, "crystal-harness:harness-evaluator", "ev", e2))

        check("the file keeps every snapshot (append-only)", len(ledger_lines(root)) == 3)
        r = report(root)
        gen = r["byAgent"].get("harness-generator", {})
        check("a re-stopped agent counts as one call", gen.get("calls") == 1, gen)
        check(
            "the later snapshot supersedes, it is not added",
            gen.get("tokens") == {"input": 2, "output": 30, "cacheWrite": 100, "cacheRead": 100},
            gen.get("tokens"),
        )
        check("total across agents", r["total"]["totalTokens"] == 232 + 100, r["total"])
        check("evaluator share of tokens", r["evaluatorTokenShare"] == round(100 / 332, 4), r["evaluatorTokenShare"])
        check("no rate configured means no USD", r["total"]["estimatedUsd"] is None and r["rates"] is None)
        check("rounds are keyed from the entries", list(r["byRound"]) == ["final round 2"], list(r["byRound"]))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_append_and_external_rows():
    root = new_project({"schemaVersion": 3, "phase": "qa", "currentSprint": 3, "currentRound": 1})
    try:
        proc = subprocess.run(
            ["python3", LEDGER, "append", "--agent", "codex-review", "--duration-ms", "42000", "--project-dir", root],
            capture_output=True, text=True,
        )
        e = (ledger_lines(root) or [{}])[0]
        check("append exits 0 and echoes the entry", proc.returncode == 0 and json.loads(proc.stdout) == e, proc)
        check(
            "append takes its position from state.json",
            (e.get("phase"), e.get("sprint"), e.get("round")) == ("qa", 3, 1) and e.get("tokens") is None,
            e,
        )
        proc = subprocess.run(
            ["python3", LEDGER, "append", "--agent", "harness-evaluator", "--project-dir", root],
            capture_output=True, text=True,
        )
        check("append refuses an agent role — those are recorded by the hook", proc.returncode != 0)
        subprocess.run(
            ["python3", LEDGER, "append", "--agent", "codex-review", "--duration-ms", "8000", "--project-dir", root],
            capture_output=True, text=True,
        )
        r = report(root)
        cr = r["byAgent"]["codex-review"]
        check("entries without an agentId each count", cr["calls"] == 2 and cr["durationMs"] == 50000, cr)
        check("an external component is not a call missing its tokens", r["total"]["callsWithoutTokens"] == 0, r["total"])
        check("sprint rounds are keyed by sprint and round", list(r["byRound"]) == ["sprint 3 round 1"], list(r["byRound"]))

        bare = tempfile.mkdtemp(prefix="ledger-test-bare-")
        proc = subprocess.run(
            ["python3", LEDGER, "append", "--agent", "codex-review", "--project-dir", bare], capture_output=True, text=True
        )
        check("append outside a run exits 1", proc.returncode == 1)
        shutil.rmtree(bare, ignore_errors=True)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_report_rates_legacy_and_damage():
    legacy_state = {
        "schemaVersion": 2,
        "phase": "qa",
        "currentSprint": 1,
        "ledger": [
            {"ts": "2026-08-09T00:00:00Z", "agent": "harness-generator", "phase": "building", "sprint": 1,
             "round": 1, "durationMs": 60000, "tokens": 41200},
            {"ts": "2026-08-09T00:10:00Z", "agent": "codex-review", "phase": "building", "sprint": 1,
             "round": 1, "durationMs": 5000, "tokens": None},
        ],
    }
    rates = {"input": 10, "output": 50, "cacheWrite": 12.5, "cacheRead": 1}
    root = new_project(legacy_state, {"harness": {"costPerMTokUsd": rates}})
    try:
        t = os.path.join(root, "t", "subagents", "agent-g.jsonl")
        write_transcript(t, [assistant("m", "2026-11-20T04:00:00.000Z", usage(1_000_000, 200_000, 400_000, 3_000_000))])
        run_hook(root, stop_event(root, "harness-generator", "g", t))
        with open(os.path.join(root, ".harness", "ledger.jsonl"), "a", encoding="utf-8") as f:
            f.write("{ torn line\n")
            f.write('["not", "an", "entry"]\n')

        r = report(root)
        gen = r["byAgent"]["harness-generator"]
        check("legacy state.json entries are counted as calls", gen["calls"] == 2 and r["legacyEntries"] == 2, gen)
        check("a legacy final-request token figure stays out of the totals", gen["totalTokens"] == 4_600_000, gen)
        check("the legacy call is reported as lacking token data", gen["callsWithoutTokens"] == 1, gen)
        check("legacy wall time is kept", gen["durationMs"] == 60000, gen)
        check(
            "per-category rates price each category separately",
            abs(gen["estimatedUsd"] - (10 + 10 + 5 + 3)) < 1e-9,
            gen["estimatedUsd"],
        )
        check("damaged lines are skipped and counted", r["unreadableLines"] == 2, r["unreadableLines"])

        with open(os.path.join(root, ".harness", "config.json"), "w", encoding="utf-8") as f:
            json.dump({"harness": {"costPerMTokUsd": 2}}, f)
        r = report(root)
        check("a single number is a blended rate over all tokens", abs(r["total"]["estimatedUsd"] - 9.2) < 1e-9, r["total"])
        with open(os.path.join(root, ".harness", "config.json"), "w", encoding="utf-8") as f:
            json.dump({"harness": {"costPerMTokUsd": {"input": 10}}}, f)
        check("an incomplete rate object prices nothing rather than guessing", report(root)["rates"] is None)

        proc = subprocess.run(["python3", LEDGER, "report", "--project-dir", root], capture_output=True, text=True)
        check(
            "the text report renders both tables and the caveats",
            proc.returncode == 0 and "### By agent" in proc.stdout and "### By round" in proc.stdout
            and "schemaVersion 2" in proc.stdout and "could not be parsed" in proc.stdout,
            proc.stdout,
        )
    finally:
        shutil.rmtree(root, ignore_errors=True)


def run_gate(root, event, raw=None):
    proc = subprocess.run(
        ["python3", LEDGER, "gate"],
        input=raw if raw is not None else json.dumps(event),
        capture_output=True, text=True, env=hook_env(root, 0), cwd=root,
    )
    decision = None
    if proc.stdout.strip():
        decision = json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"]
    return proc, decision


def spawn_event(root, tool, **tool_input):
    return {"hook_event_name": "PreToolUse", "cwd": root, "tool_name": tool, "tool_input": tool_input}


def run_budget(root):
    return subprocess.run(["python3", LEDGER, "budget", "--project-dir", root], capture_output=True, text=True)


def set_config(root, **harness):
    with open(os.path.join(root, ".harness", "config.json"), "w", encoding="utf-8") as f:
        json.dump({"harness": harness}, f)


def test_budget_and_gate():
    root = new_project(STATE, {"harness": {}})
    try:
        t = os.path.join(root, "t", "subagents", "agent-g.jsonl")
        write_transcript(t, [assistant("m", "2026-11-20T04:00:00.000Z", usage(100_000, 50_000, 0, 850_000))])
        run_hook(root, stop_event(root, "crystal-harness:harness-generator", "g", t))  # 1,000,000 tokens

        gen = spawn_event(root, "Agent", subagent_type="crystal-harness:harness-generator", prompt="build")
        wf = spawn_event(root, "Workflow", name="crystal-harness:evaluate")

        proc = run_budget(root)
        check("no cap: budget exits 0 and says so", proc.returncode == 0 and "No budget cap" in proc.stdout, proc.stdout)
        check("no cap: gate allows", run_gate(root, gen)[1] is None)

        set_config(root, maxRunTokens=2_000_000)
        proc = run_budget(root)
        check("under the token cap: exit 0 with the share", proc.returncode == 0 and "(50%)" in proc.stdout, proc.stdout)
        check("under the token cap: gate allows", run_gate(root, gen)[1] is None)

        set_config(root, maxRunTokens=1_000_000)
        proc = run_budget(root)
        check("at the token cap: budget exits 3", proc.returncode == 3 and "BUDGET REACHED" in proc.stdout, proc.stdout)
        proc, decision = run_gate(root, gen)
        check("at the token cap: gate denies a harness agent", decision == "deny" and proc.returncode == 0, proc.stdout)
        check("at the token cap: gate denies the evaluate workflow", run_gate(root, wf)[1] == "deny")
        check(
            "the bare role name is gated too",
            run_gate(root, spawn_event(root, "Agent", subagent_type="harness-evaluator"))[1] == "deny",
        )
        check(
            "an unrelated agent is never gated",
            run_gate(root, spawn_event(root, "Agent", subagent_type="Explore"))[1] is None,
        )
        check(
            "someone else's workflow is never gated",
            run_gate(root, spawn_event(root, "Workflow", name="evaluate"))[1] is None
            and run_gate(root, spawn_event(root, "Workflow", name="other-plugin:evaluate"))[1] is None,
        )
        check("other tools are never gated", run_gate(root, spawn_event(root, "Bash", command="npm test"))[1] is None)
        proc, decision = run_gate(root, None, raw="not json")
        check("gate fails open on a malformed event", proc.returncode == 0 and decision is None)

        rates = {"input": 10, "output": 50, "cacheWrite": 12.5, "cacheRead": 1}  # -> $4.35
        set_config(root, maxRunCostUsd=5, costPerMTokUsd=rates)
        proc = run_budget(root)
        check("under the cost cap: exit 0", proc.returncode == 0 and "$4.35 of $5.00" in proc.stdout, proc.stdout)
        set_config(root, maxRunCostUsd=4, costPerMTokUsd=rates)
        check("over the cost cap: budget exits 3 and gate denies", run_budget(root).returncode == 3 and run_gate(root, gen)[1] == "deny")

        set_config(root, maxRunCostUsd=4)
        proc = run_budget(root)
        check(
            "a cost cap with no rates is reported as unenforceable, not ignored",
            proc.returncode == 1 and "NOT ENFORCEABLE" in proc.stdout and run_gate(root, gen)[1] == "deny",
            proc.stdout,
        )
        set_config(root, maxRunTokens=0, maxRunCostUsd=-1)
        check("zero and negative caps are treated as unset", run_budget(root).returncode == 0)
    finally:
        shutil.rmtree(root, ignore_errors=True)

    bare = tempfile.mkdtemp(prefix="ledger-test-bare-")
    try:
        gen = spawn_event(bare, "Agent", subagent_type="crystal-harness:harness-generator")
        check("gate does nothing outside a harness run", run_gate(bare, gen)[1] is None)
    finally:
        shutil.rmtree(bare, ignore_errors=True)


def test_report_empty():
    root = new_project(STATE)
    try:
        proc = subprocess.run(["python3", LEDGER, "report", "--project-dir", root], capture_output=True, text=True)
        check("an empty ledger says so", proc.returncode == 0 and "empty" in proc.stdout, proc.stdout)
        bare = tempfile.mkdtemp(prefix="ledger-test-bare-")
        proc = subprocess.run(["python3", LEDGER, "report", "--project-dir", bare], capture_output=True, text=True)
        check("report without .harness exits 1", proc.returncode == 1)
        shutil.rmtree(bare, ignore_errors=True)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    for test in (
        test_hook_sums_the_whole_run,
        test_streamed_response_is_counted_once,
        test_kinds,
        test_hook_never_blocks_and_never_lies,
        test_hook_outside_a_run_and_project_dir,
        test_hook_waits_for_the_final_response,
        test_report_supersedes_snapshots,
        test_append_and_external_rows,
        test_report_rates_legacy_and_damage,
        test_budget_and_gate,
        test_report_empty,
    ):
        test()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} failing case(s): {', '.join(FAILURES)}")
        return 1
    print(f"all {COUNT} ledger cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
