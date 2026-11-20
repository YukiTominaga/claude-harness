#!/usr/bin/env python3
"""The cost ledger: .harness/ledger.jsonl — written by code, never by a model.

The recurring judgement this harness exists to support is "is this component
still worth its cost", and the ledger is the only evidence for it. Three things
made the previous design (the orchestrator appending `subagent_tokens` to
state.json after every Agent call) unable to carry that weight:

- `subagent_tokens` in an Agent tool result is the size of the subagent's FINAL
  API request, not the total across its run. Measured on Claude Code 2.1.329: a
  two-request subagent reported 4,810 where its transcript sums to 9,422. For a
  long generator session the gap is orders of magnitude.
- Agent-team teammates report no token numbers to the lead at all, and a workflow
  reports one aggregate, so the orchestrator has nothing to copy for either.
- An entry the model must remember to append is an entry that goes missing, and
  parallel agents finishing together would race on state.json.

So the ledger is now recorded by a `SubagentStop` hook, which fires for plain
subagents, workflow agents and in-process teammates alike, and which is handed
`agent_transcript_path`. The transcript carries the usage of every API request
the agent made; this script sums it.

Subcommands:

    ledger.py hook      SubagentStop hook entry point (event JSON on stdin)
    ledger.py append    record a component that is not an agent (codex-review)
    ledger.py report    aggregate the ledger; --json for machines
    ledger.py budget    compare the run's total with harness.maxRunTokens /
                        harness.maxRunCostUsd; exit 3 when a cap is reached
    ledger.py gate      PreToolUse hook on Agent|Workflow: deny spawning a
                        harness agent once a cap is reached

The file is JSON Lines and append-only. An agent that stops more than once (a
teammate going idle repeatedly, a subagent continued with SendMessage) writes a
new cumulative snapshot each time, so the LAST line for an `agentId` supersedes
the earlier ones — `report` applies that rule; do not sum the raw file.

Contract of `hook`: it always exits 0 and prints nothing. Exit 2 on SubagentStop
would stop the agent from stopping, and a bookkeeping failure must never do
that. A failure is instead made visible in the data: the entry is written with
`tokens: null` and a `note`, and `report` counts such entries.
"""

import argparse
import datetime
import json
import os
import sys
import time

try:
    import fcntl
except ImportError:  # Windows: appends are still single write() calls
    fcntl = None

ROLES = ("harness-planner", "harness-generator", "harness-evaluator", "harness-investigator")
# Components with a cost that are not agents and so produce no SubagentStop.
EXTERNAL = ("codex-review",)
TOKEN_FIELDS = (
    ("input", "input_tokens"),
    ("output", "output_tokens"),
    ("cacheWrite", "cache_creation_input_tokens"),
    ("cacheRead", "cache_read_input_tokens"),
)
LEDGER_NAME = "ledger.jsonl"
# Claude Code writes an agent's last response to its transcript asynchronously —
# measured about 100 ms AFTER the SubagentStop hook starts. Summing at once
# drops the final request from every entry. The hook therefore waits, up to this
# cap, for the final message to appear. Overridable so the tests need not wait.
SETTLE_CAP_S = float(os.environ.get("CRYSTAL_HARNESS_LEDGER_SETTLE_MS", "3000")) / 1000
SETTLE_POLL_S = 0.05
SETTLE_QUIET_S = 1.0


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def role_of(agent_type):
    """Map a hook `agent_type` to a harness role, or "other".

    A plugin agent arrives namespaced — `crystal-harness:harness-evaluator` —
    so only the last segment is compared. A workflow agent given no agentType
    arrives as `workflow-subagent`, and a teammate arrives under the NAME the
    lead gave it rather than its definition's type; both are "other" here —
    except a `builder-<x>` teammate, which is a generator by construction.
    """
    leaf = (agent_type or "").rsplit(":", 1)[-1]
    if leaf in ROLES:
        return leaf
    # A team-build builder is a generator teammate; scripts/team_build.py's gate
    # guarantees only a harness-generator can carry this name.
    if (agent_type or "").startswith("builder-") and len(agent_type) > len("builder-"):
        return "harness-generator"
    return "other"


def harness_dir(project_dir):
    return os.path.join(project_dir, ".harness")


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_position(project_dir):
    """(phase, sprint, round) from state.json, each None when unavailable."""
    try:
        state = read_json(os.path.join(harness_dir(project_dir), "state.json"))
    except Exception:  # noqa: BLE001 - an unreadable state must not lose the entry
        return None, None, None
    if not isinstance(state, dict):
        return None, None, None

    def int_or_none(value):
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    phase = state.get("phase") if isinstance(state.get("phase"), str) else None
    return phase, int_or_none(state.get("currentSprint")), int_or_none(state.get("currentRound"))


def parse_ts(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def summarize_transcript(path):
    """Sum API usage across every request recorded in an agent transcript.

    One API response can be written as several lines (one per content block)
    that share a `message.id` and repeat its usage, so usage is taken once per
    id — the per-field maximum, which also absorbs a partial count on an early
    line. Returns a dict, or raises if the file cannot be read at all.
    """
    per_message = {}
    models = []
    first_ts = last_ts = None
    last_text = None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue  # a torn final line while the file is still being written
            if not isinstance(record, dict):
                continue
            ts = parse_ts(record.get("timestamp"))
            if ts is not None:
                first_ts = ts if first_ts is None or ts < first_ts else first_ts
                last_ts = ts if last_ts is None or ts > last_ts else last_ts
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                        last_text = block["text"]
            model = message.get("model")
            if isinstance(model, str) and model not in models and not model.startswith("<"):
                models.append(model)
            key = message.get("id") or record.get("uuid") or len(per_message)
            seen = per_message.setdefault(key, {})
            for _name, field in TOKEN_FIELDS:
                value = usage.get(field)
                if isinstance(value, int) and not isinstance(value, bool):
                    seen[field] = max(seen.get(field, 0), value)

    tokens = {name: sum(m.get(field, 0) for m in per_message.values()) for name, field in TOKEN_FIELDS}
    duration_ms = None
    if first_ts is not None and last_ts is not None:
        duration_ms = int((last_ts - first_ts).total_seconds() * 1000)
    return {
        "tokens": tokens,
        "requests": len(per_message),
        "models": models,
        "durationMs": duration_ms,
        "lastText": last_text,
    }


def summarize_when_settled(path, final_message):
    """Summarize a transcript once the agent's final response has reached it.

    `final_message` is the hook event's `last_assistant_message`. The transcript
    is complete when its last assistant text is that message. If the event gave
    no message, or the two never match, fall back to the file having stopped
    growing. Returns (summary, confirmed); raises what `summarize_transcript`
    raises if the file is still unreadable when the cap is reached.

    Waiting here delays nothing but this hook: the write it waits for is not
    blocked by the hook, which is how it lands while the hook is still running.
    """
    want = final_message.strip() if isinstance(final_message, str) and final_message.strip() else None
    deadline = time.monotonic() + SETTLE_CAP_S
    last_size, quiet_since = None, time.monotonic()
    while True:
        error = None
        try:
            summary = summarize_transcript(path)
        except Exception as exc:  # noqa: BLE001 - may simply not be written yet
            summary, error = None, exc
        if summary is not None and want is not None and (summary["lastText"] or "").strip() == want:
            return summary, True
        now = time.monotonic()
        try:
            size = os.path.getsize(path)
        except OSError:
            size = None
        if size != last_size:
            last_size, quiet_since = size, now
        settled = summary is not None and now - quiet_since >= SETTLE_QUIET_S
        if now >= deadline or settled:
            if summary is None:
                raise error
            return summary, want is None
        time.sleep(SETTLE_POLL_S)


def agent_kind(transcript_path):
    """subagent | workflow | teammate — best effort, from where the transcript lives.

    Workflow agents are stored under `subagents/workflows/<run>/`. A teammate has
    a sidecar `agent-<id>.meta.json` naming `taskKind: in_process_teammate`. Both
    are observed layout, not a documented contract, so anything unrecognised is a
    plain subagent rather than an error.
    """
    if not isinstance(transcript_path, str) or not transcript_path:
        return "subagent"
    normalized = transcript_path.replace("\\", "/")
    if "/subagents/workflows/" in normalized:
        return "workflow"
    meta_path = transcript_path[: -len(".jsonl")] + ".meta.json" if transcript_path.endswith(".jsonl") else None
    if meta_path and os.path.isfile(meta_path):
        try:
            meta = read_json(meta_path)
            if isinstance(meta, dict) and "teammate" in str(meta.get("taskKind", "")):
                return "teammate"
        except Exception:  # noqa: BLE001
            pass
    return "subagent"


def append_entry(project_dir, entry):
    """Append one JSON line. A single O_APPEND write, under a lock where available."""
    path = os.path.join(harness_dir(project_dir), LEDGER_NAME)
    data = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, data)
    finally:
        os.close(fd)


# ---------------------------------------------------------------- hook


def cmd_hook(_args):
    try:
        event = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return 0
    if not isinstance(event, dict) or event.get("hook_event_name") != "SubagentStop":
        return 0

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()
    if not os.path.isfile(os.path.join(harness_dir(project_dir), "state.json")):
        return 0  # not a harness run; say nothing, write nothing

    agent_type = event.get("agent_type")
    agent_id = event.get("agent_id")
    # Claude Code also fires SubagentStop for internal helpers with an empty type
    # and no transcript on disk. They are not components anyone can strip.
    if not isinstance(agent_type, str) or not agent_type or not isinstance(agent_id, str) or not agent_id:
        return 0

    transcript_path = event.get("agent_transcript_path")
    phase, sprint, round_ = run_position(project_dir)
    entry = {
        "ts": now_iso(),
        "agent": role_of(agent_type),
        "agentType": agent_type,
        "agentId": agent_id,
        "kind": agent_kind(transcript_path),
        "phase": phase,
        "sprint": sprint,
        "round": round_,
        "durationMs": None,
        "requests": None,
        "tokens": None,
        "models": [],
        "source": "transcript",
    }
    try:
        summary, confirmed = summarize_when_settled(transcript_path, event.get("last_assistant_message"))
        summary.pop("lastText", None)
        if summary["requests"] == 0:
            entry["note"] = "transcript held no API usage records"
        else:
            entry.update(summary)
            if not confirmed:
                entry["note"] = "final response not confirmed in the transcript; its request may be missing"
    except Exception as exc:  # noqa: BLE001 - recorded, never raised
        entry["note"] = f"transcript unreadable: {type(exc).__name__}"

    try:
        append_entry(project_dir, entry)
    except Exception:  # noqa: BLE001 - nowhere left to record it
        pass
    return 0


# ---------------------------------------------------------------- append


def cmd_append(args):
    project_dir = args.project_dir
    if not os.path.isfile(os.path.join(harness_dir(project_dir), "state.json")):
        print(f"ledger: {harness_dir(project_dir)}/state.json does not exist", file=sys.stderr)
        return 1
    phase, sprint, round_ = run_position(project_dir)
    entry = {
        "ts": now_iso(),
        "agent": args.agent,
        "agentType": None,
        "agentId": None,
        "kind": "external",
        "phase": args.phase if args.phase is not None else phase,
        "sprint": args.sprint if args.sprint is not None else sprint,
        "round": args.round if args.round is not None else round_,
        "durationMs": args.duration_ms,
        "requests": None,
        "tokens": None,
        "models": [],
        "source": "manual",
    }
    if args.note:
        entry["note"] = args.note
    append_entry(project_dir, entry)
    print(json.dumps(entry, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- report


def load_entries(project_dir):
    """(effective entries, unreadable line count). Last snapshot per agentId wins."""
    path = os.path.join(harness_dir(project_dir), LEDGER_NAME)
    ordered, by_id, unreadable = [], {}, 0
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    unreadable += 1
                    continue
                if not isinstance(entry, dict) or not isinstance(entry.get("agent"), str):
                    unreadable += 1
                    continue
                agent_id = entry.get("agentId")
                if isinstance(agent_id, str) and agent_id:
                    if agent_id in by_id:
                        ordered[by_id[agent_id]] = entry
                    else:
                        by_id[agent_id] = len(ordered)
                        ordered.append(entry)
                else:
                    ordered.append(entry)
    return ordered, unreadable


def load_legacy(project_dir):
    """Entries from a schemaVersion 2 state.json `ledger` array, if any.

    Their `tokens` is the final-request figure the Agent tool reported, so they
    are counted for calls and wall time but kept out of every token total.
    """
    try:
        state = read_json(os.path.join(harness_dir(project_dir), "state.json"))
    except Exception:  # noqa: BLE001
        return []
    legacy = state.get("ledger") if isinstance(state, dict) else None
    return [e for e in legacy if isinstance(e, dict)] if isinstance(legacy, list) else []


def load_rates(project_dir):
    """harness.costPerMTokUsd: a number (blended, per total token) or a
    per-category object {input, output, cacheWrite, cacheRead}. None if unset."""
    try:
        config = read_json(os.path.join(harness_dir(project_dir), "config.json"))
        value = config["harness"]["costPerMTokUsd"]
    except Exception:  # noqa: BLE001
        return None

    def is_number(x):
        return isinstance(x, (int, float)) and not isinstance(x, bool) and x >= 0

    if is_number(value):
        return {"blended": float(value)}
    if isinstance(value, dict) and all(is_number(value.get(name)) for name, _ in TOKEN_FIELDS):
        return {name: float(value[name]) for name, _ in TOKEN_FIELDS}
    return None


def cost_of(tokens, rates):
    if rates is None or tokens is None:
        return None
    if "blended" in rates:
        return sum(tokens.values()) * rates["blended"] / 1_000_000
    return sum(tokens[name] * rates[name] for name, _ in TOKEN_FIELDS) / 1_000_000


def empty_bucket():
    return {
        "calls": 0,
        "durationMs": 0,
        "tokens": {name: 0 for name, _ in TOKEN_FIELDS},
        "callsWithoutTokens": 0,
    }


def add_to(bucket, entry, count_tokens=True):
    bucket["calls"] += 1
    duration = entry.get("durationMs")
    if isinstance(duration, int) and not isinstance(duration, bool):
        bucket["durationMs"] += duration
    tokens = entry.get("tokens")
    if count_tokens and isinstance(tokens, dict):
        for name, _ in TOKEN_FIELDS:
            value = tokens.get(name)
            if isinstance(value, int) and not isinstance(value, bool):
                bucket["tokens"][name] += value
    elif entry.get("agent") not in EXTERNAL:
        bucket["callsWithoutTokens"] += 1


def finish(bucket, rates):
    bucket["totalTokens"] = sum(bucket["tokens"].values())
    bucket["estimatedUsd"] = cost_of(bucket["tokens"], rates)
    return bucket


def round_label(entry):
    """The row an entry belongs to in the per-round table."""
    phase = entry.get("phase") or "unknown"
    sprint, round_ = entry.get("sprint"), entry.get("round")
    if str(phase).startswith("final"):
        return f"final round {round_}" if round_ is not None else "final"
    if sprint is not None:
        return f"sprint {sprint} round {round_}" if round_ is not None else f"sprint {sprint}"
    return str(phase)  # planning, or the single build of useSprints: false


def build_report(project_dir):
    entries, unreadable = load_entries(project_dir)
    legacy = load_legacy(project_dir)
    rates = load_rates(project_dir)

    by_agent, by_round = {}, {}
    total = empty_bucket()
    for entry in entries:
        add_to(by_agent.setdefault(entry["agent"], empty_bucket()), entry)
        add_to(total, entry)
        add_to(by_round.setdefault(round_label(entry), empty_bucket()), entry)
    for entry in legacy:
        agent = entry.get("agent") if isinstance(entry.get("agent"), str) else "other"
        add_to(by_agent.setdefault(agent, empty_bucket()), entry, count_tokens=False)
        add_to(total, entry, count_tokens=False)

    order = list(ROLES) + list(EXTERNAL) + ["other"]
    agents = sorted(by_agent, key=lambda a: (order.index(a) if a in order else len(order), a))
    report = {
        "byAgent": {a: finish(by_agent[a], rates) for a in agents},
        "byRound": {k: finish(v, rates) for k, v in by_round.items()},
        "total": finish(total, rates),
        "evaluatorTokenShare": None,
        "rates": rates,
        "entries": len(entries),
        "legacyEntries": len(legacy),
        "unreadableLines": unreadable,
    }
    if report["total"]["totalTokens"] > 0 and "harness-evaluator" in by_agent:
        report["evaluatorTokenShare"] = round(
            by_agent["harness-evaluator"]["totalTokens"] / report["total"]["totalTokens"], 4
        )
    return report


def fmt_duration(ms):
    seconds = int(round(ms / 1000))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def fmt_tokens(n):
    return f"{n:,}"


def render(report):
    with_usd = report["rates"] is not None
    lines = []

    def table(title, first_column, rows):
        header = [first_column, "calls", "input", "cache write", "cache read", "output", "total tokens", "wall time"]
        if with_usd:
            header.append("est. USD")
        lines.append(f"### {title}")
        lines.append("")
        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join(["---"] * len(header)) + " |")
        for name, b in rows:
            external = name in EXTERNAL
            t = b["tokens"]
            cells = [name, str(b["calls"])]
            cells += ["—"] * 5 if external else [
                fmt_tokens(t["input"]), fmt_tokens(t["cacheWrite"]), fmt_tokens(t["cacheRead"]),
                fmt_tokens(t["output"]), fmt_tokens(b["totalTokens"]),
            ]
            cells.append(fmt_duration(b["durationMs"]))
            if with_usd:
                cells.append("—" if external or b["estimatedUsd"] is None else f"{b['estimatedUsd']:.2f}")
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")

    if report["entries"] == 0 and report["legacyEntries"] == 0:
        return "The ledger is empty — no agent has finished in this run yet.\n"

    table("By agent", "agent", list(report["byAgent"].items()) + [("**total**", report["total"])])
    if report["byRound"]:
        table("By round", "round", list(report["byRound"].items()))

    share = report["evaluatorTokenShare"]
    if share is not None:
        lines.append(f"Evaluator share of total tokens: {share * 100:.1f}%.")
    if with_usd:
        kind = "one blended rate applied to every token" if "blended" in report["rates"] else "per-category rates"
        lines.append(f"USD is estimated from harness.costPerMTokUsd ({kind}); it is not a bill.")
    missing = report["total"]["callsWithoutTokens"]
    if missing:
        lines.append(
            f"{missing} call(s) have no token data and are missing from every token total — "
            "the transcript could not be read, or the entry predates the transcript-based ledger."
        )
    if report["legacyEntries"]:
        lines.append(
            f"{report['legacyEntries']} entry(ies) come from a schemaVersion 2 state.json. Their token "
            "figure was the agent's final request only, so they count toward calls and wall time but not tokens."
        )
    if report["unreadableLines"]:
        lines.append(f"{report['unreadableLines']} line(s) of ledger.jsonl could not be parsed and were skipped.")
    lines.append(
        "Token totals cover agents (subagents, workflow agents, teammates). The orchestrating "
        "session's own usage is not in the ledger."
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- budget

HARNESS_WORKFLOWS = ("evaluate", "diagnose")


def load_caps(project_dir):
    """(maxRunTokens, maxRunCostUsd) from config.json; None where unset or invalid."""
    try:
        harness = read_json(os.path.join(harness_dir(project_dir), "config.json"))["harness"]
    except Exception:  # noqa: BLE001
        return None, None

    def positive(value, integer=False):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            return None
        return int(value) if integer else float(value)

    return positive(harness.get("maxRunTokens"), integer=True), positive(harness.get("maxRunCostUsd"))


def budget_status(project_dir):
    """Where the run stands against its caps.

    `exceeded` lists the caps reached. `problems` lists caps that cannot be
    enforced — a cost cap with no rates to price tokens by. A cap somebody set
    that silently does nothing is worse than no cap, so a problem stops the run
    the same way an exceeded cap does.
    """
    report = build_report(project_dir)
    max_tokens, max_usd = load_caps(project_dir)
    tokens, usd = report["total"]["totalTokens"], report["total"]["estimatedUsd"]
    exceeded, problems = [], []
    if max_tokens is not None and tokens >= max_tokens:
        exceeded.append(f"{fmt_tokens(tokens)} tokens used, cap harness.maxRunTokens is {fmt_tokens(max_tokens)}")
    if max_usd is not None:
        if report["rates"] is None:
            problems.append(
                "harness.maxRunCostUsd is set but harness.costPerMTokUsd is not, so the run's cost "
                "cannot be computed — set the rates, or cap tokens with harness.maxRunTokens instead"
            )
        elif usd is not None and usd >= max_usd:
            exceeded.append(f"estimated ${usd:.2f} spent, cap harness.maxRunCostUsd is ${max_usd:.2f}")
    return {
        "tokens": tokens,
        "estimatedUsd": usd,
        "maxRunTokens": max_tokens,
        "maxRunCostUsd": max_usd,
        "exceeded": exceeded,
        "problems": problems,
    }


def cmd_budget(args):
    if not os.path.isdir(harness_dir(args.project_dir)):
        print(f"ledger: {harness_dir(args.project_dir)} does not exist", file=sys.stderr)
        return 1
    status = budget_status(args.project_dir)
    if args.json:
        print(json.dumps(status, indent=2, ensure_ascii=False))
    else:
        if status["maxRunTokens"] is None and status["maxRunCostUsd"] is None:
            print(f"No budget cap is set. {fmt_tokens(status['tokens'])} tokens used so far.")
        if status["maxRunTokens"] is not None:
            share = status["tokens"] / status["maxRunTokens"] * 100
            print(f"Tokens: {fmt_tokens(status['tokens'])} of {fmt_tokens(status['maxRunTokens'])} ({share:.0f}%).")
        if status["maxRunCostUsd"] is not None and status["estimatedUsd"] is not None:
            share = status["estimatedUsd"] / status["maxRunCostUsd"] * 100
            print(f"Estimated cost: ${status['estimatedUsd']:.2f} of ${status['maxRunCostUsd']:.2f} ({share:.0f}%).")
        for line in status["exceeded"]:
            print(f"BUDGET REACHED: {line}.")
        for line in status["problems"]:
            print(f"BUDGET NOT ENFORCEABLE: {line}.")
    if status["exceeded"]:
        return 3
    return 1 if status["problems"] else 0


def gated_target(event):
    """The harness component a PreToolUse event is about to start, or None."""
    tool = event.get("tool_name")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    if tool == "Agent":
        role = role_of(tool_input.get("subagent_type"))
        return role if role != "other" else None
    if tool == "Workflow":
        name = tool_input.get("name")
        if isinstance(name, str) and ":" in name:
            plugin, leaf = name.rsplit(":", 1)
            if plugin.startswith("crystal-harness") and leaf in HARNESS_WORKFLOWS:
                return f"workflow {leaf}"
    return None


def cmd_gate(_args):
    """Deny starting a harness agent or workflow once the run is over budget.

    The stopping rules are stated to the orchestrator in prose; this makes the
    budget one a guarantee. It fails open: a cost control that cannot evaluate
    must not stop work the way an ownership guard must, so any error allows.
    """
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict) or event.get("hook_event_name") != "PreToolUse":
            return 0
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()
        if not os.path.isfile(os.path.join(harness_dir(project_dir), "state.json")):
            return 0
        target = gated_target(event)
        if target is None:
            return 0
        status = budget_status(project_dir)
        reasons = status["exceeded"] + status["problems"]
        if not reasons:
            return 0
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"crystal-harness budget: not starting {target} — " + "; ".join(reasons) + ". "
                    'Set phase to "blocked" with this as blockedReason and ask the human. '
                    "Only a human raising or removing the cap in .harness/config.json lets the run continue."
                ),
            }
        }))
    except Exception:  # noqa: BLE001 - fail open
        return 0
    return 0


def cmd_report(args):
    if not os.path.isdir(harness_dir(args.project_dir)):
        print(f"ledger: {harness_dir(args.project_dir)} does not exist", file=sys.stderr)
        return 1
    report = build_report(args.project_dir)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        sys.stdout.write(render(report))
    return 0


def main():
    parser = argparse.ArgumentParser(description="crystal-harness cost ledger")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("hook", help="SubagentStop hook entry point; reads the event on stdin")

    p_append = sub.add_parser("append", help="record a non-agent component")
    p_append.add_argument("--agent", required=True, choices=EXTERNAL)
    p_append.add_argument("--duration-ms", type=int, default=None)
    p_append.add_argument("--phase", default=None, help="defaults to state.json's phase")
    p_append.add_argument("--sprint", type=int, default=None, help="defaults to state.json's currentSprint")
    p_append.add_argument("--round", type=int, default=None, help="defaults to state.json's currentRound")
    p_append.add_argument("--note", default=None)
    p_append.add_argument("--project-dir", default=os.getcwd())

    p_report = sub.add_parser("report", help="aggregate the ledger")
    p_report.add_argument("--json", action="store_true")
    p_report.add_argument("--project-dir", default=os.getcwd())

    p_budget = sub.add_parser("budget", help="compare the run's total with its caps; exit 3 when one is reached")
    p_budget.add_argument("--json", action="store_true")
    p_budget.add_argument("--project-dir", default=os.getcwd())

    sub.add_parser("gate", help="PreToolUse hook on Agent|Workflow; reads the event on stdin")

    args = parser.parse_args()
    commands = {"hook": cmd_hook, "append": cmd_append, "report": cmd_report, "budget": cmd_budget, "gate": cmd_gate}
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
