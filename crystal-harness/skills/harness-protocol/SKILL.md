---
name: harness-protocol
description: The file-based contract every harness agent reads and writes — .harness/ layout, state.json and verdict.json schemas, the handoff.md template, the cost ledger, and the journal. Use whenever reading or writing anything under .harness/, at any phase boundary, and before any context reset or resume.
---

# Harness protocol

All communication between harness agents goes through files under `.harness/` in the
target project. **No agent may depend on having seen another agent's conversation.**
If a fact is not in a file, the next agent does not know it.

This exists because the harness resets context instead of compacting it. A compacted
conversation silently loses detail and the agent that inherits it cuts scope to fit.
A fresh agent reading complete files does not.

## Layout

```
.harness/
├── config.json          # harness configuration, written by /crystal-harness:init
├── spec.md              # planner output: the product specification
├── state.json           # machine-readable run state
├── ledger.jsonl         # cost ledger, appended by a hook — never by an agent
├── handoff.md           # rolling context-reset handoff artifact
├── journal.md           # append-only log of decisions and events
├── artifacts/           # Playwright MCP scratch output, browser mode only (gitignored)
├── sprints/
│   └── 01/
│       ├── contract.md      # generator proposes, evaluator accepts
│       ├── report.md        # generator's completion report + self-check
│       ├── codex-review.md  # independent review of the diff, orchestrator-owned
│       ├── test-changes.json # what the round did to the tests, orchestrator-owned
│       ├── lenses/          # parallel evaluation only: one verdict per lens
│       │   ├── api.json, api.md, tests.json, …
│       │   └── verify/      # one reproduction result per blocking issue
│       ├── qa.md            # the round's verdict, human-readable
│       ├── verdict.json     # the round's verdict, machine-readable
│       └── screenshots/
└── final/
    └── 01/                  # one directory per end-of-run QA round
        ├── qa.md
        ├── verdict.json
        ├── report.md        # generator's report for this round's fixes
        ├── codex-review.md
        ├── test-changes.json
        ├── lenses/
        └── screenshots/
```

`lenses/` exists only when `harness.parallelEvaluation` is `true`. In that mode each
lens evaluator writes its own pair of files there and
`scripts/merge_verdicts.py` — not an agent — produces the round's `verdict.json`
and `qa.md` from them. The `evaluation-lenses` skill defines the lens files.

`codex-review.md` is present only when the `codex` plugin is installed and
`harness.codexReview` is not `false`; `screenshots/` only in `browser` mode. Their
absence is normal and means what it says — nobody should infer a failure from it.

Sprint and final-round directories are zero-padded two-digit. In `useSprints: false`
mode `sprints/` stays empty: the run is planner → one long build → `final/01`,
`final/02`, … one directory per build-and-QA round.

**Every run ends with a passing `final/NN`, or it is not finished.** Sprint verdicts
grade increments against contracts the generator helped write. Only the final
assessment asks whether the product `spec.md` described actually exists.

## Ownership

| Path | Written by | Read by |
| --- | --- | --- |
| `config.json` | `/crystal-harness:init`, the human | everyone |
| `spec.md` | planner | generator, evaluator |
| `sprints/NN/contract.md` | generator (proposal), evaluator (review block) | both |
| `sprints/NN/report.md`, `final/NN/report.md` | generator | evaluator |
| `*/codex-review.md` | the orchestrating command (via `scripts/codex_review.py`) | evaluator (read-only) |
| `*/test-changes.json` | the orchestrating command (via `scripts/test_changes.py`) | evaluator (read-only), `validate_verdict.py` |
| `*/qa.md`, `*/verdict.json`, `*/screenshots/` | **evaluator only** — or, in parallel evaluation, `scripts/merge_verdicts.py` run by the orchestrating command | generator (read-only) |
| `*/lenses/` | **evaluator only**, one lens or one reproduction per agent | `merge_verdicts.py`; generator never |
| `state.json`, `handoff.md`, `journal.md` | the orchestrating command | everyone |
| `ledger.jsonl` | the `SubagentStop` hook, and `scripts/ledger.py append` for codex reviews | `/crystal-harness:status`, via `scripts/ledger.py report` |

The generator writing its own verdict is the single failure that destroys the whole
design, so this table is enforced by a `PreToolUse` hook, not just by instruction:
the generator is blocked from verdict artifacts in both `sprints/NN/` and
`final/NN/` and from the orchestrator-owned files (`state.json`, `handoff.md`,
`journal.md`, `config.json`, `spec.md`) and from `ledger.jsonl`; the evaluator is blocked from everything
except its round artifacts, the contract review block, and `.harness/artifacts/`.

`codex-review.md` and `test-changes.json` are blocked for **both** of them. Each is
evidence about the generator's diff, commissioned before the evaluator exists. A
generator that can write one manufactures its own second opinion, or its own report
on the tests it deleted; an evaluator that can write one edits the evidence it is
about to cite.

## `state.json`

JSON Schema (draft 2020-12):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "harness state",
  "type": "object",
  "required": ["schemaVersion", "phase", "currentSprint", "currentRound", "sprints", "finalRounds", "lastGoodCommit", "updatedAt"],
  "additionalProperties": false,
  "properties": {
    "schemaVersion": { "const": 3 },
    "phase": {
      "enum": ["init", "planning", "contracting", "building", "qa", "revising", "final-building", "final-qa", "done", "blocked"]
    },
    "currentSprint": { "type": ["integer", "null"], "minimum": 1 },
    "currentRound": {
      "type": ["integer", "null"],
      "minimum": 1,
      "description": "the round the next agent works in. In a sprint: that sprint's revisions + 1. In the final assessment: the NN of the final/NN directory the next agent writes into. null before any round exists (init, planning, contracting, and the single build of useSprints: false). Set it in the same edit as phase — the ledger hook stamps every entry with it."
    },
    "sprints": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["index", "status"],
        "additionalProperties": false,
        "properties": {
          "index": { "type": "integer", "minimum": 1 },
          "title": { "type": "string" },
          "status": { "enum": ["contracting", "contracted", "building", "qa", "revising", "passed", "failed", "abandoned"] },
          "revisions": { "type": "integer", "minimum": 0 },
          "contractRounds": { "type": "integer", "minimum": 0 },
          "verdicts": { "$ref": "#/$defs/verdictSummaries" },
          "commit": { "type": ["string", "null"] }
        }
      }
    },
    "finalRounds": { "$ref": "#/$defs/verdictSummaries" },
    "repeatedIssueFingerprints": {
      "type": "object",
      "description": "blocking-issue id -> number of consecutive verdicts it has appeared in",
      "additionalProperties": { "type": "integer", "minimum": 1 }
    },
    "ledger": {
      "type": "array",
      "description": "DEPRECATED, schemaVersion 2 only. A run started before 0.10.0 kept its ledger here. Never append to it and never delete it: scripts/ledger.py report still reads it, as calls and wall time only."
    },
    "lastGoodCommit": { "type": ["string", "null"] },
    "blockedReason": { "type": ["string", "null"] },
    "updatedAt": { "type": "string", "format": "date-time" }
  },
  "$defs": {
    "verdictSummaries": {
      "type": "array",
      "description": "one entry per QA round, oldest first. Used by sprints[].verdicts and by finalRounds — the six scores across rounds are the trend a human reads to decide whether another round is worth its cost. This array is the ONLY per-round history: each round overwrites its directory's verdict.json and qa.md, so anything not copied here is gone after the next round.",
      "items": {
        "type": "object",
        "required": ["round", "overall"],
        "additionalProperties": false,
        "properties": {
          "round": { "type": "integer", "minimum": 0 },
          "overall": { "enum": ["pass", "fail", null], "description": "null while the round is still building or in QA" },
          "verificationMode": { "enum": ["browser", "headless", "degraded", null], "description": "copied from that round's environment.verificationMode. Without it a score trend silently mixes modes, and the two-consecutive-degraded stopping rule has nothing to read." },
          "scores": { "type": ["object", "null"], "description": "the six dimension scores from that round's verdict.json" },
          "blockingCount": { "type": ["integer", "null"], "minimum": 0 },
          "commit": { "type": ["string", "null"] }
        }
      }
    }
  }
}
```

`phase: "blocked"` means the loop stopped and is waiting for a human. Only a human
decision moves it — `/crystal-harness:build` asks before clearing it.

A `state.json` with `schemaVersion: 2` belongs to a run started before 0.10.0. Keep
its `ledger` array where it is, set `schemaVersion` to 3 and add `currentRound` at
the next phase transition, and carry on.

## `ledger.jsonl` — recorded by code, not by you

The most important recurring judgement in this harness is *is this component still
worth its cost*, and that question cannot be answered from prose. The ledger is what
makes "the evaluator found nothing in the last four sprints and cost 38% of the
run" a fact instead of an impression.

Nobody appends agent entries by hand. A `SubagentStop` hook runs
`scripts/ledger.py hook` every time an agent finishes — a subagent, a workflow
agent or an agent-team teammate — sums the token usage of **every API request in
that agent's transcript**, and appends one JSON line:

```json
{"ts": "2026-11-20T04:59:57Z", "agent": "harness-generator",
 "agentType": "crystal-harness:harness-generator", "agentId": "a0eca8157df0ecc2a",
 "kind": "subagent", "phase": "building", "sprint": 2, "round": 1,
 "durationMs": 3650, "requests": 2,
 "tokens": {"input": 4, "output": 763, "cacheWrite": 13355, "cacheRead": 28874},
 "models": ["claude-opus-5-5"], "source": "transcript"}
```

Three rules follow from how it is produced:

- **Do not copy `subagent_tokens` from an Agent tool result anywhere.** It is the
  size of the agent's *final* request, not its run — a three-request agent that
  processed 64,685 tokens reports 21,689. The ledger is the only token figure to
  quote in the journal or to a human.
- **Do not sum `ledger.jsonl` yourself.** An agent that stops more than once writes
  a cumulative snapshot each time, so the last line per `agentId` supersedes the
  earlier ones. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py" report`
  (add `--json` for a machine-readable form) and print what it prints.
- **`phase`, `sprint` and `round` are read from `state.json` at the moment the agent
  stops.** So update `phase`, `currentSprint` and `currentRound` *before* spawning
  an agent, never after it returns — an entry stamped with the previous phase is
  attributed to the wrong round for good.

`agent` is the harness role when the agent's type names one, and `other` for
anything else that ran during the run (a workflow agent with no agent type, a
teammate, an Explore call) — those cost tokens too, and a ledger that dropped them
would understate the run.

A codex review is not an agent and fires no hook. Record it yourself, with the
wall time you measured:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py" append --agent codex-review --duration-ms <ms>
```

`append` takes the phase, sprint and round from `state.json` and refuses any agent
role, because those are the hook's to record.

If an entry has `"tokens": null`, the transcript could not be read; `report` counts
such calls and says so. That is a finding to pass on to the human, not a number to
estimate around. The orchestrating session's own usage is not in the ledger.

## `verdict.json`

Owned by the evaluator. Schema, thresholds and the six dimensions are defined in the
`qa-rubric` skill.

## `handoff.md` — the load-bearing artifact

`handoff.md` must be sufficient for a **completely fresh agent with zero prior
context** to resume the run. Write it at every phase boundary, before any context
reset, without exception. Overwrite it in place; the history lives in `journal.md`.

A handoff whose `Phase` or `Sprint` does not match `state.json` is a **hard error**:
stop and tell the human. A stale handoff is worse than no handoff, because it reads
as authoritative.

Fixed template — use these headings verbatim:

```markdown
# Handoff

Written at: <ISO-8601 timestamp>
Phase: <phase from state.json>  Sprint: <index or ->  Round: <n or ->
Last good commit: <sha or ->

## Current goal
<One paragraph. What the run as a whole is trying to produce, and what this
sprint or round is trying to produce. No history.>

## Done
<Bullets. Completed and verified work only. Each bullet names the commit or the
artifact that proves it. Work that is merely written but unverified does NOT
belong here.>

## In progress — exactly where it stopped
<The single unit of work that was open, the file and function it was in, what
had been changed, and what the next edit was going to be. If nothing was open,
write "Nothing in progress.">

## Known broken
<Bullets. Every thing currently not working, including things deliberately left
broken. Each with a reproduction. If nothing, write "Nothing known broken.">

## Decisions already made — do not relitigate
<Bullets: decision, and the one-line reason. These were settled. A fresh agent
re-opening them wastes the run. Include rejected alternatives.>

## Approaches already tried and rejected
<Per blocking issue id: what was attempted and why it did not clear the issue.
This is what stops the third revision from repeating the first.>

## Files that matter
<Path — why it matters. Only files the next agent must read.>

## Next action
<Exactly one imperative sentence. Not a list. If the next action is "ask the
human", say what the question is.>
```

Rules that make the template work:

- **"Done" means verified.** Written-but-untested code goes in "In progress". This
  is the line that stops a resumed agent from believing the run is further along
  than it is.
- **"Next action" is one action.** A list invites the fresh agent to pick the easy
  item.
- **"Decisions already made" is not optional.** Its absence is why resumed agents
  rebuild working things a different way.
- **"Approaches already tried" is what makes revision 3 different from revision 1.**

## `journal.md`

Append-only. Never rewrite prior entries. One entry per event a human would want to
reconstruct later: phase transitions, contract accept/reject with the reason,
verdicts with scores, revisions, escalations, human decisions, and configuration
changes. Include the round's tokens and duration, taken from `ledger.py report`.

```markdown
## 2026-08-09T12:34:56Z — sprint 01 — verdict: fail (weighted 2.8)
2 blocking issues. Top: "Rectangle fill tool only places tiles at the drag start
and end points instead of filling the region" (cause: fillRectangle not called on
mouseUp, LevelEditor.tsx:414). Revision 1 of 5 starting.
Evaluator: 1.84M tokens (1.71M cache read), 6m12s.
```

Escalations must be logged with the reason before control returns to the human.

## Reading order for a fresh agent

1. `.harness/state.json` — where am I.
2. `.harness/handoff.md` — what do I do next. Cross-check phase/sprint against
   `state.json`; mismatch is a hard error.
3. `.harness/config.json` — how do I run this project.
4. `.harness/spec.md` — what is being built.
5. The current `contract.md`, then `qa.md` / `verdict.json` if revising.

Do not read `journal.md` to reconstruct state. It is for humans; `state.json` and
`handoff.md` are the machine truth.
