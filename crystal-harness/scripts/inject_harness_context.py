"""SessionStart context injection for the crystal-harness plugin.

Reads a SessionStart hook event on stdin. If the working directory has a
`.harness/state.json`, a harness run already exists here, and the plugin
should say so up front — without depending on the user's own CLAUDE.md to
remember it. Silence otherwise: a directory with no .harness/ is not a
harness project, and injecting noise there would just teach people to ignore
this context.

Contract: always exits 0. This hook only adds context; it never blocks a
session, so a read/parse failure means "say nothing," not "fail loudly."
"""

import json
import os
import sys


def emit(text):
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": text,
                }
            }
        )
    )


def main():
    try:
        event = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 - unreadable event, say nothing
        sys.exit(0)

    if not isinstance(event, dict):
        sys.exit(0)

    cwd = event.get("cwd") or os.getcwd()
    state_path = os.path.join(cwd, ".harness", "state.json")
    if not os.path.isfile(state_path):
        sys.exit(0)

    try:
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:  # noqa: BLE001 - present but unreadable; still flag it
        emit(
            "crystal-harness: this directory has a .harness/state.json that could "
            "not be parsed. Load the crystal-harness:harness-protocol skill and "
            "inspect it before doing anything else here."
        )
        sys.exit(0)

    if not isinstance(state, dict):
        sys.exit(0)

    phase = state.get("phase", "unknown")
    sprint = state.get("currentSprint")

    if phase == "blocked":
        action = (
            "The run is BLOCKED, waiting on a human decision. Do not resume it "
            "yourself — use the crystal-harness:status skill to show the "
            "current state and the blocking issue, then wait for the user's call."
        )
    else:
        action = (
            "Use the crystal-harness:status skill first to show where the "
            "run stands, then crystal-harness:resume if you are continuing "
            "it (e.g. after a crash or /clear)."
        )

    emit(
        f"crystal-harness: an existing harness run was found in this directory "
        f"(.harness/state.json — phase={phase!r}, sprint={sprint!r}). {action}"
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
