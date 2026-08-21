"""Artifact-ownership policy for the crystal-harness plugin.

Reads a PreToolUse hook event on stdin and enforces the ownership table in the
harness-protocol skill. The design of the harness assumes two boundaries hold:

- The generator never authors a verdict (qa.md / verdict.json / screenshots),
  and never rewrites the orchestrator's run state (state.json, handoff.md,
  journal.md, config.json, spec.md). A generator that writes its own verdict or
  its own handoff is self-grading, which destroys the whole design.
- The evaluator never edits what it grades. Its writes are confined to its own
  round directories under .harness/sprints/ and .harness/final/ (where
  contract.md review blocks, qa.md, verdict.json and screenshots live) and the
  Playwright scratch area .harness/artifacts/. It may not write report.md —
  that file is the generator's testimony — nor anything outside .harness/.

Prompt instructions state these rules too; this hook is what makes them
guarantees instead of requests. Fail closed: an event the policy cannot read is
blocked, because a guard that waves through what it could not inspect is worse
than no guard.
"""

import json
import os
import sys

PROTECTED_LEAVES = ("qa.md", "verdict.json", "screenshots")
ORCHESTRATOR_LEAVES = ("state.json", "handoff.md", "journal.md", "config.json", "spec.md")


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
    """.harness/{sprints,final}/NN/{qa.md,verdict.json,screenshots/...}"""
    return (
        len(parts) >= 4
        and parts[0] == ".harness"
        and parts[1] in ("sprints", "final")
        and parts[3] in PROTECTED_LEAVES
    )


def is_orchestrator_file(parts):
    """.harness/{state.json,handoff.md,journal.md,config.json,spec.md}"""
    return len(parts) == 2 and parts[0] == ".harness" and parts[1] in ORCHESTRATOR_LEAVES


def evaluator_may_write(parts):
    """The evaluator's writable surface, per the ownership table.

    - .harness/artifacts/... — Playwright scratch output.
    - .harness/{sprints,final}/NN/... — its round artifacts, including the
      review block it appends to contract.md, but never report.md, which is
      the generator's completion report.
    """
    if not parts or parts[0] != ".harness":
        return False
    if len(parts) >= 3 and parts[1] == "artifacts":
        return True
    if len(parts) >= 4 and parts[1] in ("sprints", "final"):
        return parts[3] != "report.md"
    return False


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
    # reason to name a verdict artifact or an orchestrator-owned run file in a
    # shell command at all — it reads them with Read. The evaluator's Bash is
    # deliberately not policed; it runs the project's own build, test and dev
    # commands, and any heuristic there would break the run more often than it
    # would catch anything.
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
        for leaf in ("state.json", "handoff.md", "journal.md"):
            if leaf in lowered:
                deny(
                    f"harness-generator may not touch {leaf} through the shell. "
                    "The orchestrating command owns the run state; read it with "
                    "Read if you need it."
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

    if agent == "harness-generator":
        if is_verdict_artifact(parts):
            deny(
                f"harness-generator may not write {rel}. Only harness-evaluator "
                "produces verdicts. Report what you built in report.md; the verdict is "
                "not yours to write."
            )
        if is_orchestrator_file(parts):
            deny(
                f"harness-generator may not write {rel}. The orchestrating command "
                "owns the run state (state.json, handoff.md, journal.md, config.json, "
                "spec.md). Report what you did in report.md and let the caller record it."
            )

    if agent == "harness-evaluator" and not evaluator_may_write(parts):
        deny(
            f"harness-evaluator may not write {rel}. The evaluator writes only its "
            "round artifacts under .harness/sprints/NN/ or .harness/final/NN/ "
            "(qa.md, verdict.json, screenshots, the contract review block) and "
            ".harness/artifacts/. It does not edit what it grades and does not "
            "write report.md or the run state. Record defects as blocking issues "
            "in qa.md instead."
        )

    allow()


if __name__ == "__main__":
    main()
