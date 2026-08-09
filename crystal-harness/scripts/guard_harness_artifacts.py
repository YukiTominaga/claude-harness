"""Artifact-ownership policy for the crystal-harness plugin.

Reads a PreToolUse hook event on stdin. See guard-harness-artifacts.sh for the
contract and the rationale.
"""

import json
import os
import sys

PROTECTED_LEAVES = ("qa.md", "verdict.json", "screenshots")


def allow():
    sys.exit(0)


def deny(reason):
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    sys.exit(0)


def block(message):
    """Exit 2: the policy could not be evaluated, so the call must not proceed."""
    print(f"crystal-harness guard: {message}", file=sys.stderr)
    sys.exit(2)


def load_event():
    # Fail closed. An unreadable event means the policy was not evaluated, and a
    # guard that waves through what it could not inspect is worse than no guard,
    # because the whole design assumes it is holding.
    try:
        event = json.load(sys.stdin)
    except Exception as exc:  # noqa: BLE001 - any failure here must block, loudly
        block(f"could not parse the PreToolUse event ({exc}). Blocking rather than allowing an unchecked edit.")
    if not isinstance(event, dict):
        block("PreToolUse event was not a JSON object. Blocking rather than allowing an unchecked edit.")
    return event


def project_relative(target, real_cwd):
    """Repo-relative path components of `target`, case-folded.

    realpath, not normpath: a symlink planted inside .harness/ that points at
    src/ would otherwise satisfy a purely textual "is under .harness" check.
    Case-folded because on APFS and NTFS `.HARNESS/.../VERDICT.JSON` and
    `.harness/.../verdict.json` are the same file.
    """
    abs_target = target if os.path.isabs(target) else os.path.join(real_cwd, target)
    parent = os.path.realpath(os.path.dirname(abs_target) or real_cwd)
    resolved = os.path.join(parent, os.path.basename(abs_target))
    rel = os.path.relpath(resolved, real_cwd)
    return rel, [part.casefold() for part in rel.split(os.sep)]


def is_verdict_artifact(parts):
    return (
        len(parts) >= 4
        and parts[0] == ".harness"
        and parts[1] == "sprints"
        and parts[3] in PROTECTED_LEAVES
    )


def main():
    event = load_event()

    agent = event.get("agent_type") or ""
    if agent not in ("harness-generator", "harness-evaluator"):
        allow()

    tool = event.get("tool_name") or ""
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}

    real_cwd = os.path.realpath(event.get("cwd") or os.getcwd())

    # Shell writes cannot be checked by resolving a path, and sniffing redirections
    # is both leaky and prone to blocking legitimate work. One narrow case is worth
    # covering because it has no false positives: the generator has no legitimate
    # reason to name a verdict artifact in a shell command at all — it reads them
    # with Read. The evaluator's Bash is deliberately not policed; it runs the
    # project's own build, test and dev commands, and any heuristic there would
    # break the run more often than it would catch anything.
    if tool == "Bash":
        if agent != "harness-generator":
            allow()
        command = tool_input.get("command")
        lowered = command.casefold() if isinstance(command, str) else ""
        if "verdict.json" in lowered or "qa.md" in lowered:
            deny(
                "harness-generator may not touch verdict artifacts through the "
                "shell. Only harness-evaluator produces verdicts; read them with "
                "Read if you are revising."
            )
        allow()

    target = (
        tool_input.get("file_path")
        or tool_input.get("notebook_path")
        or tool_input.get("path")
        or ""
    )
    if not isinstance(target, str) or not target:
        allow()

    rel, parts = project_relative(target, real_cwd)
    in_harness = bool(parts) and parts[0] == ".harness"

    if agent == "harness-generator" and is_verdict_artifact(parts):
        deny(
            f"harness-generator may not write {rel}. Only harness-evaluator "
            "produces verdicts. Report what you built in report.md; the verdict is "
            "not yours to write."
        )

    if agent == "harness-evaluator" and not in_harness:
        deny(
            f"harness-evaluator may not write {rel}. The evaluator does not edit "
            "what it grades. Record the defect as a blocking issue in qa.md instead."
        )

    allow()


if __name__ == "__main__":
    main()
