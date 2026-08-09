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
# Contract: reads the PreToolUse hook event on stdin. Exits 0 — printing a
# permissionDecision object — when the policy was evaluated. Exits 2, which blocks
# the call, when it could not be evaluated at all. A guard that cannot run must not
# pretend the policy is satisfied.
#
# This wrapper exists only to turn a missing interpreter into a loud block instead
# of a silent no-op. The policy itself lives in guard_harness_artifacts.py.

set -u

if ! command -v python3 >/dev/null 2>&1; then
  echo "crystal-harness guard: python3 not found, so artifact ownership cannot be" \
       "enforced. Blocking this call rather than allowing an unchecked one." \
       "Install python3, or disable the crystal-harness plugin." >&2
  exit 2
fi

exec python3 "$(dirname "$0")/guard_harness_artifacts.py"
