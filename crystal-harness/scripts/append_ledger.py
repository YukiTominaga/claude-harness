#!/usr/bin/env python3
"""Append one ledger entry to .harness/state.json — deterministically.

The orchestrator must record a ledger entry after every subagent call. Having
the model rewrite the whole of state.json for each entry risks a malformed or
truncated file at every phase, and models routinely get "now" wrong. This
script does the mechanical part: it stamps the timestamp itself, appends the
entry, refreshes updatedAt, and writes atomically (temp file + rename in the
same directory), so a crash mid-write can never leave a half-written state.

Usage:
    python3 append_ledger.py --agent harness-evaluator --phase qa \
        --sprint 3 --round 1 --duration-ms 372000 --tokens 41200 \
        [--note "…"] [--state .harness/state.json]

Numeric flags left out are recorded as null — never estimated. Exits 0 and
prints the appended entry on success; exits 1 with the reason if state.json is
missing or not the shape the harness-protocol schema requires. A broken
state.json is a fact the orchestrator must surface, not one to paper over here.
"""

import argparse
import datetime
import json
import os
import sys
import tempfile

AGENTS = ("harness-planner", "harness-generator", "harness-evaluator")


def fail(message):
    print(f"append_ledger: {message}", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True, choices=AGENTS)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--sprint", type=int, default=None)
    parser.add_argument("--round", type=int, default=None)
    parser.add_argument("--duration-ms", type=int, default=None)
    parser.add_argument("--tokens", type=int, default=None)
    parser.add_argument("--note", default=None)
    parser.add_argument("--state", default=os.path.join(".harness", "state.json"))
    args = parser.parse_args()

    if not os.path.isfile(args.state):
        fail(f"{args.state} does not exist")

    try:
        with open(args.state, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception as exc:  # noqa: BLE001
        fail(f"could not parse {args.state}: {exc}")

    if not isinstance(state, dict) or not isinstance(state.get("ledger"), list):
        fail(f"{args.state} is not a state object with a ledger array — inspect it before appending")

    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = {
        "ts": now,
        "agent": args.agent,
        "phase": args.phase,
        "sprint": args.sprint,
        "round": args.round,
        "durationMs": args.duration_ms,
        "tokens": args.tokens,
    }
    if args.note is not None:
        entry["note"] = args.note

    state["ledger"].append(entry)
    state["updatedAt"] = now

    state_dir = os.path.dirname(os.path.abspath(args.state))
    fd, tmp_path = tempfile.mkstemp(dir=state_dir, prefix=".state-", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp_path, args.state)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    print(json.dumps(entry, ensure_ascii=False))


if __name__ == "__main__":
    main()
