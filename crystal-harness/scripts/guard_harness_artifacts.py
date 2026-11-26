"""Artifact-ownership policy for the crystal-harness plugin.

Reads a PreToolUse hook event on stdin and enforces the ownership table in the
harness-protocol skill. The design of the harness assumes two boundaries hold:

- The generator never authors a verdict (qa.md / verdict.json / screenshots),
  and never rewrites the orchestrator's run state (state.json, handoff.md,
  journal.md, config.json, spec.md) or the cost ledger (ledger.jsonl). A generator that writes its own verdict or
  its own handoff is self-grading, which destroys the whole design.
- The evaluator never edits what it grades. Its writes are confined to its own
  round directories under .harness/sprints/ and .harness/final/ (where
  contract.md review blocks, qa.md, verdict.json and screenshots live) and the
  Playwright scratch area .harness/artifacts/. It may not write the
  generator's notes — build-notes.md, or the legacy report.md of a run started
  before 0.16.0, guarded alike — which are the generator's testimony, nor
  codex-review.md, which is an input it reads, not an artifact it authors —
  nor anything outside .harness/.

codex-review.md belongs to neither of them. The orchestrator commissions it from
a different vendor's model before the evaluator is spawned. A generator that can
write it can manufacture its own second opinion; an evaluator that can write it
can edit the evidence it is about to cite.

Prompt instructions state these rules too; this hook is what makes them
guarantees instead of requests. Fail closed: an event the policy cannot read is
blocked, because a guard that waves through what it could not inspect is worse
than no guard.
"""

import json
import os
import re
import sys

# `lenses/` holds the per-lens verdicts of a parallel evaluation and the
# reproduction results — verdicts in every sense that matters.
PROTECTED_LEAVES = ("qa.md", "verdict.json", "screenshots", "lenses")
ORCHESTRATOR_LEAVES = (
    "state.json", "handoff.md", "journal.md", "config.json", "spec.md", "ledger.jsonl",
    "split.json",  # the ACTIVE split plan of a team build: it is what bounds each builder
    # The project's learned rules and the issue log they are drawn from. A
    # generator that can edit them can delete the rule that would catch it.
    "rules.json", "issues.jsonl",
)
# A team build runs several generators at once as agent-team teammates. Hooks see
# a teammate under the NAME the lead gave it, not its agent type, so a builder is
# recognised by this prefix — and scripts/team_build.py's gate hook guarantees
# that only a harness-generator in the active split plan can be given such a name.
BUILDER_PREFIX = "builder-"
# One builder running any of these would stage, discard or rewrite files the
# other builders are still writing. They commit through team_build.py instead.
BUILDER_FORBIDDEN_GIT = re.compile(
    r"\bgit\s+(?:-C\s+\S+\s+)?(add|commit|stash|reset|checkout|restore|clean|rebase|merge|switch|pull|cherry-pick|revert|rm|mv|apply|am)\b"
)
GUARDED_ROLES = ("harness-generator", "harness-evaluator", "harness-investigator")


def role_of(agent_type):
    """The harness role an `agent_type` names, or "" for anything else.

    Claude Code hands a plugin's agent to hooks under its namespaced name —
    `crystal-harness:harness-generator` — not the bare `name` in the agent's
    frontmatter. Comparing the raw value against the bare names matched nothing,
    which let every write through with no symptom: the policy was a no-op on any
    installed copy of the plugin (measured on Claude Code 2.1.329). Only the
    last segment is compared, so the bare form keeps working too.
    """
    if not isinstance(agent_type, str):
        return ""
    leaf = agent_type.rsplit(":", 1)[-1]
    return leaf if leaf in GUARDED_ROLES else ""
CODEX_REVIEW_LEAF = "codex-review.md"
# Written by the orchestrating command with scripts/test_changes.py, before the
# evaluator is spawned: what the round did to the project's tests. Like the
# codex review it is evidence neither agent may author — the generator would be
# reporting on its own test deletions, the evaluator editing what it must weigh.
TEST_CHANGES_LEAF = "test-changes.json"
# The project rules this round's diff triggered, written by scripts/rules.py.
RULES_TO_CHECK_LEAF = "rules-to-check.json"
COMMISSIONED_LEAVES = (CODEX_REVIEW_LEAF, TEST_CHANGES_LEAF, RULES_TO_CHECK_LEAF)
# The generator's notes. Until 0.16.0 they were report.md, which Claude Code's
# Write tool refuses to any subagent (it rejects /^(REPORT|SUMMARY|FINDINGS|
# ANALYSIS).*\.md$/i before hooks run). A round directory from an older run can
# still hold the legacy name, so both are guarded alike: the generator may
# write either, the evaluator reads them, nobody else writes them.
NOTES = "build-notes.md"
LEGACY_NOTES = "report.md"
# In a round directory the evaluator reads these and never writes them: the
# generator's testimony (its notes, a team build's split plan and per-builder
# reports), the commissioned evidence, and an investigator's diagnosis.
EVALUATOR_READ_ONLY_LEAVES = (NOTES, LEGACY_NOTES, "split.json", "reports", "diagnosis") + COMMISSIONED_LEAVES
# .harness/captures/ holds an agent's final response, kept verbatim by a hook,
# from which the orchestrating command places a file the agent could not write
# (scripts/returned_files.py). An agent that could write there could put a file
# in another agent's mouth, so none may.
CAPTURES_LEAF = "captures"
# The diagnose workflow's working directory inside a round directory.
DIAGNOSIS_LEAF = "diagnosis"


def builder_of(agent_type):
    """The builder name if `agent_type` is a team-build teammate's name, else ""."""
    if isinstance(agent_type, str) and agent_type.startswith(BUILDER_PREFIX) and len(agent_type) > len(BUILDER_PREFIX):
        return agent_type[len(BUILDER_PREFIX):]
    return ""


def builder_owned(real_cwd, builder):
    """[(kind, path)] the active split plan gives this builder, or None if there is no usable plan."""
    try:
        with open(os.path.join(real_cwd, ".harness", "split.json"), "r", encoding="utf-8") as f:
            plan = json.load(f)
        for entry in plan["builders"]:
            if entry.get("name") == builder:
                owned = []
                for item in entry.get("owns", []):
                    text = str(item).strip().replace("\\", "/")
                    kind = "file"
                    if text.endswith("/**"):
                        kind, text = "dir", text[:-3]
                    elif text.endswith("/"):
                        kind, text = "dir", text[:-1]
                    owned.append((kind, "/".join(p for p in text.split("/") if p not in ("", ".")).casefold()))
                return owned
    except Exception:  # noqa: BLE001 - no plan, unreadable plan, unknown builder: all mean "owns nothing"
        return None
    return None


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
    """.harness/{sprints,final}/NN/{qa.md,verdict.json,screenshots/...,lenses/...}"""
    return (
        len(parts) >= 4
        and parts[0] == ".harness"
        and parts[1] in ("sprints", "final")
        and parts[3] in PROTECTED_LEAVES
    )


def is_commissioned(parts):
    """.harness/{sprints,final}/NN/{codex-review.md,test-changes.json}"""
    return (
        len(parts) == 4
        and parts[0] == ".harness"
        and parts[1] in ("sprints", "final")
        and parts[3] in COMMISSIONED_LEAVES
    )


def is_capture(parts):
    """.harness/captures/..."""
    return len(parts) >= 3 and parts[0] == ".harness" and parts[1] == CAPTURES_LEAF


def is_orchestrator_file(parts):
    """.harness/{state.json,handoff.md,journal.md,config.json,spec.md,ledger.jsonl}"""
    return len(parts) == 2 and parts[0] == ".harness" and parts[1] in ORCHESTRATOR_LEAVES


def evaluator_may_write(parts):
    """The evaluator's writable surface, per the ownership table.

    - .harness/artifacts/... — Playwright scratch output.
    - .harness/{sprints,final}/NN/... — its round artifacts, including the
      review block it appends to contract.md, but never the generator's notes
      (build-notes.md, or the legacy report.md), and never codex-review.md,
      which is an independent review it is supposed to weigh, not edit.
    """
    if not parts or parts[0] != ".harness":
        return False
    if len(parts) >= 3 and parts[1] == "artifacts":
        return True
    if len(parts) >= 4 and parts[1] in ("sprints", "final"):
        return parts[3] not in EVALUATOR_READ_ONLY_LEAVES
    return False


def is_diagnosis(parts):
    """.harness/{sprints,final}/NN/diagnosis/..."""
    return (
        len(parts) >= 5
        and parts[0] == ".harness"
        and parts[1] in ("sprints", "final")
        and parts[3] == DIAGNOSIS_LEAF
    )


def main():
    event = load_event()

    agent = role_of(event.get("agent_type"))
    builder = "" if agent else builder_of(event.get("agent_type"))
    if builder:
        agent = "harness-generator"  # a builder is a generator, with a narrower lane
    if not agent:
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
        # "lenses/" alone could be the application's own directory, so it only
        # counts alongside the harness directory.
        if "verdict.json" in lowered or "qa.md" in lowered or (".harness" in lowered and "lenses/" in lowered):
            deny(
                "harness-generator may not touch verdict artifacts through the "
                "shell. Only harness-evaluator produces verdicts; read them with "
                "Read if you are revising."
            )
        for leaf in COMMISSIONED_LEAVES:
            if leaf in lowered:
                deny(
                    f"harness-generator may not touch {leaf} through the shell. The "
                    "orchestrating command commissions it as independent evidence "
                    "about your diff; read it with Read if you need it."
                )
        if ".harness" in lowered and f"{CAPTURES_LEAF}/" in lowered:
            deny(
                "harness-generator may not touch .harness/captures/ through the shell. It holds "
                "agents' final responses, kept by a hook; nothing an agent writes belongs there."
            )
        for leaf in ("state.json", "handoff.md", "journal.md", "ledger.jsonl"):
            if leaf in lowered:
                deny(
                    f"harness-generator may not touch {leaf} through the shell. "
                    "The orchestrating command owns the run state; read it with "
                    "Read if you need it."
                )
        if builder:
            if "split.json" in lowered:
                deny(
                    f"{BUILDER_PREFIX}{builder} may not touch split.json through the shell. "
                    "The split plan is what bounds every builder; read it with Read."
                )
            if isinstance(command, str) and BUILDER_FORBIDDEN_GIT.search(command):
                deny(
                    f"{BUILDER_PREFIX}{builder} may not run that git command. Other builders are "
                    "writing in this working tree right now, and it would stage, discard or "
                    "rewrite their files. Commit your own paths with: python3 "
                    '"${CLAUDE_PLUGIN_ROOT}/scripts/team_build.py" commit --builder '
                    f'{builder} -m "<message>". Read-only git (status, diff, log, show) is fine.'
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
                "produces verdicts. Report what you built in build-notes.md; the verdict is "
                "not yours to write."
            )
        if is_commissioned(parts):
            deny(
                f"harness-generator may not write {rel}. It is independent evidence "
                "about your own diff, commissioned by the orchestrating command. Writing "
                "it yourself would make that evidence your own. Read it if you "
                "are revising."
            )
        if is_diagnosis(parts) or (len(parts) == 4 and parts[0] == ".harness" and parts[3] == DIAGNOSIS_LEAF):
            deny(
                f"harness-generator may not write {rel}. A diagnosis is what the investigators "
                "concluded about an issue you could not clear; read it, do not author it."
            )
        if is_orchestrator_file(parts):
            deny(
                f"harness-generator may not write {rel}. The orchestrating command "
                "owns the run state (state.json, handoff.md, journal.md, config.json, "
                "spec.md) and a hook owns ledger.jsonl. Report what you did in build-notes.md and let the caller record it."
            )
        if is_capture(parts):
            deny(
                f"harness-generator may not write {rel}. .harness/captures/ holds agents' final "
                "responses as a hook kept them. If a Write of yours was refused by a rule you did "
                "not expect, hand the file back in your final response instead (see your agent "
                "definition)."
            )

    if builder:
        if parts and parts[0] == ".harness":
            # reports/builder-<name>.md, never reports/<name>.md: a builder named
            # report-ui would be refused that name by Claude Code itself.
            own_report = (
                len(parts) == 5
                and parts[1] in ("sprints", "final")
                and parts[3] == "reports"
                and parts[4] == f"{BUILDER_PREFIX}{builder}.md".casefold()
            )
            if not own_report:
                deny(
                    f"{BUILDER_PREFIX}{builder} may not write {rel}. Inside .harness/ a builder "
                    f"writes one file: its own report, <round dir>/reports/{BUILDER_PREFIX}{builder}.md."
                )
            allow()
        owned = builder_owned(real_cwd, builder)
        if owned is None:
            deny(
                f"{BUILDER_PREFIX}{builder} may not write {rel}: there is no active split plan "
                "naming this builder (.harness/split.json), so it owns nothing. Tell the lead."
            )
        target_path = "/".join(parts)
        if not any(
            target_path == path if kind == "file" else (target_path == path or target_path.startswith(path + "/"))
            for kind, path in owned
        ):
            deny(
                f"{BUILDER_PREFIX}{builder} may not write {rel}: the split plan does not give you "
                "that path. If the change is needed, message the builder who owns it (the plan "
                "is in .harness/split.json) and ask for it; do not work around this."
            )

    if agent == "harness-investigator" and not is_diagnosis(parts):
        deny(
            f"harness-investigator may not write {rel}. An investigator reads and runs; the "
            "only files it writes are its findings under <round dir>/diagnosis/. It never "
            "edits what it is diagnosing — the fix belongs to the generator."
        )

    if agent == "harness-evaluator" and not evaluator_may_write(parts):
        deny(
            f"harness-evaluator may not write {rel}. The evaluator writes only its "
            "round artifacts under .harness/sprints/NN/ or .harness/final/NN/ "
            "(qa.md, verdict.json, screenshots, lenses/, the contract review block) and "
            ".harness/artifacts/. It does not edit what it grades and does not "
            "write the generator's notes (build-notes.md, or the legacy report.md), codex-review.md, "
            "test-changes.json, or the run state. Record defects as blocking issues in qa.md instead."
        )

    allow()


if __name__ == "__main__":
    main()
