#!/usr/bin/env bash
# PreToolUse guard for the crystal-harness plugin.
#
# Prevents exactly two failures, both of which silently destroy the separation of
# generation from evaluation:
#
#   1. harness-generator writing its own verdict (.harness/sprints/*/qa.md,
#      verdict.json, screenshots/). If the generator can write the verdict, the
#      harness is self-grading and every pass is meaningless.
#   2. harness-evaluator editing application source. If the evaluator can fix what
#      it grades, it becomes the author of the thing it is judging.
#
# Any other agent, and any other path, is allowed through untouched.
#
# Contract: reads the PreToolUse hook event on stdin, exits 0 always, and prints a
# permissionDecision JSON object only when denying.

set -u

payload=$(cat)

if ! command -v python3 >/dev/null 2>&1; then
  echo "crystal-harness guard: python3 not found; artifact-ownership guard is NOT active." >&2
  exit 0
fi

python3 - "$payload" <<'PY'
import json, os, sys

def allow():
    sys.exit(0)

def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)

try:
    event = json.loads(sys.argv[1])
except (IndexError, ValueError) as exc:
    print(f"crystal-harness guard: unparseable hook payload ({exc}); allowing.", file=sys.stderr)
    allow()

agent = event.get("agent_type") or ""
if agent not in ("harness-generator", "harness-evaluator"):
    allow()

tool_input = event.get("tool_input") or {}
target = (
    tool_input.get("file_path")
    or tool_input.get("notebook_path")
    or tool_input.get("path")
    or ""
)
if not target:
    allow()

cwd = event.get("cwd") or os.getcwd()
abs_target = os.path.normpath(os.path.join(cwd, target)) if not os.path.isabs(target) else os.path.normpath(target)
rel = os.path.relpath(abs_target, cwd)
parts = rel.split(os.sep)

in_harness = parts[0] == ".harness"
is_verdict_artifact = (
    in_harness
    and len(parts) >= 4
    and parts[1] == "sprints"
    and (parts[3] in ("qa.md", "verdict.json") or parts[3] == "screenshots")
)

if agent == "harness-generator" and is_verdict_artifact:
    deny(
        f"harness-generator may not write {rel}. Only harness-evaluator produces "
        "verdicts. Report what you built in report.md; the verdict is not yours to "
        "write."
    )

if agent == "harness-evaluator" and not in_harness:
    deny(
        f"harness-evaluator may not write {rel}. The evaluator does not edit what it "
        "grades. Record the defect as a blocking issue in qa.md instead."
    )

allow()
PY
