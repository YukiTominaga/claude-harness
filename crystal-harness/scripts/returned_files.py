#!/usr/bin/env python3
"""Files an agent could not write, handed back in its final response.

Claude Code can refuse a subagent's `Write` for reasons outside this plugin. The
case that has been met: its Write tool rejects a subagent's write to any file
whose basename matches /^(REPORT|SUMMARY|FINDINGS|ANALYSIS).*\\.md$/i, with
"Subagents should return findings as text, not write report files. Include this
content in your final response instead." It is checked before permission rules
and PreToolUse hooks, so no setting lets the write through (Claude Code
2.1.332). That is why the generator's notes are `build-notes.md` and no longer
`report.md`.

A rule nobody has met yet can do the same to another file. The agents are told
never to route around a rejection — not through Bash, not under another name.
Instead the agent ends its final response with the file's content between two
marker lines, and stops:

    <!-- crystal-harness:begin build-notes.md -->
    # Sprint 03 report — build
    ...
    <!-- crystal-harness:end build-notes.md -->

This script puts that content where it belongs without a model retyping it:

    returned_files.py capture
        SubagentStop hook. When a harness agent's final response carries a
        block, keep the response verbatim in .harness/captures/<agent id>.json.
    returned_files.py place --round-dir <dir> [--agent-id <id> | --agent <type or name>]
        Write each block of one capture into the round directory, byte for byte,
        only if every block is a file that agent's role owns; journal where it
        came from; move the capture to .harness/captures/placed/.
    returned_files.py notes-path <round dir>
        The generator's notes for a round: build-notes.md, or — only when that is
        absent — the legacy report.md of a run started before 0.16.0.

The content is the agent's: the generator's notes are its testimony, qa.md and
verdict.json the evaluator's verdict. A copy the orchestrating model made would
be its own words. So `capture` takes the text from the hook event, not from a
model, and `place` either writes every block exactly or writes nothing.

Contract of `capture`: it always exits 0 and prints nothing — exit 2 on
SubagentStop would keep the agent from stopping. A response it could not keep
surfaces later, as `place` finding no capture.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys

NOTES = "build-notes.md"
# The generator's notes before 0.16.0. Claude Code refuses a subagent's Write to
# it, so nothing writes it any more; a round directory from an older run may
# still have one, and it is read only when build-notes.md is absent.
LEGACY_NOTES = "report.md"
BUILDER_PREFIX = "builder-"
GENERATOR, EVALUATOR = "harness-generator", "harness-evaluator"

BEGIN = re.compile(r"^<!-- crystal-harness:begin (\S+) -->$")
END = re.compile(r"^<!-- crystal-harness:end (\S+) -->$")
REJECTED = "Write rejected:"


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def placeable(agent_type):
    """The round-directory-relative files an agent of this type may hand back.

    Exactly the files that role writes and the guard lets it write: a generator
    cannot hand back a verdict, an evaluator cannot hand back the generator's
    notes, a builder cannot hand back another builder's report.
    """
    if not isinstance(agent_type, str):
        return ()
    if agent_type.startswith(BUILDER_PREFIX) and len(agent_type) > len(BUILDER_PREFIX):
        return (f"reports/{agent_type}.md",)
    leaf = agent_type.rsplit(":", 1)[-1]
    if leaf == GENERATOR:
        return (NOTES,)
    if leaf == EVALUATOR:
        return ("qa.md", "verdict.json")
    return ()


def notes_path(round_dir):
    """The generator's notes in `round_dir`: build-notes.md, else the legacy report.md, else None.

    When both exist the legacy file is ignored: build-notes.md was written by a
    later round than anything under the old name could have been.
    """
    for name in (NOTES, LEGACY_NOTES):
        path = os.path.join(round_dir, name)
        if os.path.isfile(path):
            return path
    return None


def strip_eol(line):
    return line.rstrip("\r\n").rstrip(" \t")


def extract(text):
    """([(name, content)], [rejection line]) from a final response; raises ValueError.

    A marker is a whole line. The content is every line between the two markers,
    exactly as they stand, line endings included.
    """
    lines = text.splitlines(keepends=True)
    blocks, rejections, i = [], [], 0
    while i < len(lines):
        line = strip_eol(lines[i])
        begin = BEGIN.match(line)
        if begin is None:
            if END.match(line):
                raise ValueError(f"line {i + 1}: an end marker with no begin marker before it")
            if line.startswith(REJECTED):
                rejections.append(line)
            i += 1
            continue
        name = begin.group(1)
        j = i + 1
        while j < len(lines):
            inner = strip_eol(lines[j])
            if BEGIN.match(inner):
                raise ValueError(f"line {j + 1}: a begin marker inside the block for {name}")
            end = END.match(inner)
            if end and end.group(1) == name:
                break
            j += 1
        if j == len(lines):
            raise ValueError(f"the block for {name} has no end marker")
        blocks.append((name, "".join(lines[i + 1:j])))
        i = j + 1
    return blocks, rejections


def safe_id(agent_id):
    cleaned = re.sub(r"[^A-Za-z0-9_.@-]", "_", agent_id).lstrip(".")
    return cleaned[:120] or "_"


def captures_dir(project_dir):
    return os.path.join(project_dir, ".harness", "captures")


# ---------------------------------------------------------------- capture


def cmd_capture(_args):
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict) or event.get("hook_event_name") != "SubagentStop":
            return 0
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or os.getcwd()
        if not os.path.isfile(os.path.join(project_dir, ".harness", "state.json")):
            return 0  # not a harness run
        agent_type, agent_id = event.get("agent_type"), event.get("agent_id")
        message = event.get("last_assistant_message")
        if not placeable(agent_type) or not isinstance(agent_id, str) or not agent_id:
            return 0
        if not isinstance(message, str) or not any(BEGIN.match(strip_eol(l)) for l in message.splitlines()):
            return 0
        directory = captures_dir(project_dir)
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"{safe_id(agent_id)}.json")
        record = {
            "agentId": agent_id,
            "agentType": agent_type,
            "capturedAt": now_iso(),
            "transcriptPath": event.get("agent_transcript_path"),
            "message": message,
        }
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001 - a hook on SubagentStop must never fail the stop
        pass
    return 0


# ---------------------------------------------------------------- place


def fail(lines):
    for line in lines:
        print(f"place: {line}")
    print("place: nothing was written.")
    return 1


def load_captures(project_dir):
    directory = captures_dir(project_dir)
    found = []
    if os.path.isdir(directory):
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(directory, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    record = json.load(f)
                if isinstance(record, dict) and isinstance(record.get("message"), str):
                    found.append((path, record))
            except Exception:  # noqa: BLE001 - an unreadable capture is reported by absence
                continue
    return found


def choose(found, agent_id, agent):
    """(path, record) or a list of reasons."""
    if agent_id is not None:
        found = [c for c in found if c[1].get("agentId") == agent_id or os.path.basename(c[0]) == f"{safe_id(agent_id)}.json"]
    if agent is not None:
        found = [c for c in found if agent in (c[1].get("agentType"), str(c[1].get("agentType", "")).rsplit(":", 1)[-1])]
    if len(found) == 1:
        return found[0]
    if not found:
        return ["no capture waiting to be placed"
                + (f" for agent id {agent_id}" if agent_id else "") + (f" for {agent}" if agent else "")
                + ". The hook keeps a final response only when it carries a begin marker; without one there is "
                  "nothing to place mechanically."]
    return ["more than one capture is waiting; say which with --agent-id or --agent:"] + [
        f"  {c[1].get('agentId')}  {c[1].get('agentType')}  captured {c[1].get('capturedAt')}" for c in found
    ]


def round_dir_of(project_dir, round_dir):
    """The project-relative round directory, or None if it is not .harness/{sprints,final}/NN."""
    full = os.path.realpath(round_dir if os.path.isabs(round_dir) else os.path.join(project_dir, round_dir))
    rel = os.path.relpath(full, project_dir)
    parts = rel.split(os.sep)
    if len(parts) == 3 and parts[0] == ".harness" and parts[1] in ("sprints", "final") and parts[2] not in ("", ".", ".."):
        return "/".join(parts)
    return None


def cmd_place(args):
    project_dir = os.path.realpath(args.project_dir)
    rel_round = round_dir_of(project_dir, args.round_dir)
    if rel_round is None:
        return fail([f"{args.round_dir} is not a round directory (.harness/sprints/NN or .harness/final/NN) of this project"])
    chosen = choose(load_captures(project_dir), args.agent_id, args.agent)
    if isinstance(chosen, list):
        return fail(chosen)
    capture_path, record = chosen
    agent_type = record.get("agentType")
    allowed = placeable(agent_type)
    try:
        blocks, rejections = extract(record["message"])
    except ValueError as exc:
        return fail([f"the final response of {agent_type} ({record.get('agentId')}): {exc}"])

    problems, seen = [], set()
    if not blocks:
        problems.append("the final response has no complete block to place")
    for name, content in blocks:
        if name in seen:
            problems.append(f"{name} is handed back twice")
        seen.add(name)
        if name not in allowed:
            problems.append(
                f"{agent_type} may not hand back {name} — it may hand back only "
                f"{', '.join(allowed) or 'nothing'}" + (f" ({LEGACY_NOTES} is the legacy name, which nothing writes)" if name == LEGACY_NOTES else "")
            )
        if not content.strip():
            problems.append(f"the block for {name} is empty")
    if problems:
        return fail(problems)

    written = []
    for name, content in blocks:
        target = os.path.join(project_dir, rel_round, *name.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        data = content.encode("utf-8")
        with open(target, "wb") as f:
            f.write(data)
        written.append((f"{rel_round}/{name}", len(data), hashlib.sha256(data).hexdigest()))

    placed_dir = os.path.join(captures_dir(project_dir), "placed")
    os.makedirs(placed_dir, exist_ok=True)
    kept = os.path.join(placed_dir, os.path.basename(capture_path))
    if os.path.exists(kept):
        stem = os.path.basename(capture_path)[: -len(".json")]
        kept = os.path.join(placed_dir, f"{stem}-{now_iso().replace(':', '')}.json")
    os.replace(capture_path, kept)

    entry = [
        "",
        f"## {now_iso()} — returned file placed",
        f"`{agent_type}` (agent {record.get('agentId')}) could not write its file and handed it back in its final "
        "response. Placed byte for byte by returned_files.py, not retyped:",
    ]
    entry += [f"- `{path}` — {size} bytes, sha256 {digest}" for path, size, digest in written]
    entry += [f"The agent said: {line}" for line in rejections] or ["The agent quoted no `Write rejected:` line."]
    entry.append(f"Its full final response is kept at `{os.path.relpath(kept, project_dir)}`.")
    with open(os.path.join(project_dir, ".harness", "journal.md"), "a", encoding="utf-8") as f:
        f.write("\n".join(entry) + "\n")
    print("\n".join(entry[1:]))
    return 0


# ---------------------------------------------------------------- notes-path


def cmd_notes_path(args):
    path = notes_path(args.round_dir)
    if path is None:
        print(f"notes-path: neither {NOTES} nor the legacy {LEGACY_NOTES} is in {args.round_dir}", file=sys.stderr)
        return 1
    print(path)
    return 0


def main():
    parser = argparse.ArgumentParser(description="crystal-harness: files handed back in a final response")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("capture")
    p = sub.add_parser("place")
    p.add_argument("--round-dir", required=True)
    p.add_argument("--agent-id")
    p.add_argument("--agent", help="agent type (with or without the plugin prefix) or teammate name, e.g. builder-api")
    p.add_argument("--project-dir", default=os.getcwd())
    p = sub.add_parser("notes-path")
    p.add_argument("round_dir")
    args = parser.parse_args()
    return {"capture": cmd_capture, "place": cmd_place, "notes-path": cmd_notes_path}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
