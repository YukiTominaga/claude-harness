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
├── config.json          # harness configuration, written by /harness-init
├── spec.md              # planner output: the product specification
├── state.json           # machine-readable run state, including the cost ledger
├── handoff.md           # rolling context-reset handoff artifact
├── journal.md           # append-only log of decisions and events
├── artifacts/           # Playwright MCP scratch output (gitignored)
├── sprints/
│   └── 01/
│       ├── contract.md      # generator proposes, evaluator accepts
│       ├── report.md        # generator's completion report + self-check
│       ├── qa.md            # evaluator verdict, human-readable
│       ├── verdict.json     # evaluator verdict, machine-readable
│       └── screenshots/
└── final/
    └── 01/                  # one directory per end-of-run QA round
        ├── qa.md
        ├── verdict.json
        ├── report.md        # generator's report for this round's fixes
        └── screenshots/
```

Sprint and final-round directories are zero-padded two-digit. In `useSprints: false`
mode `sprints/` stays empty: the run is planner → one long build → `final/01`,
`final/02`, … one directory per build-and-QA round.

**Every run ends with a passing `final/NN`, or it is not finished.** Sprint verdicts
grade increments against contracts the generator helped write. Only the final
assessment asks whether the product `spec.md` described actually exists.

## Ownership

| Path | Written by | Read by |
| --- | --- | --- |
| `config.json` | `/harness-init`, the human | everyone |
| `spec.md` | planner | generator, evaluator |
| `sprints/NN/contract.md` | generator (proposal), evaluator (review block) | both |
| `sprints/NN/report.md`, `final/NN/report.md` | generator | evaluator |
| `*/qa.md`, `*/verdict.json`, `*/screenshots/` | **evaluator only** | generator (read-only) |
| `state.json`, `handoff.md`, `journal.md` | the orchestrating command | everyone |

The generator writing its own verdict is the single failure that destroys the whole
design, so it is also blocked by a `PreToolUse` hook covering both `sprints/NN/` and
`final/NN/`, not just by instruction.

## `state.json`

JSON Schema (draft 2020-12):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "harness state",
  "type": "object",
  "required": ["schemaVersion", "phase", "currentSprint", "sprints", "finalRounds", "consecutiveFailures", "lastGoodCommit", "ledger", "updatedAt"],
  "additionalProperties": false,
  "properties": {
    "schemaVersion": { "const": 2 },
    "phase": {
      "enum": ["init", "planning", "contracting", "building", "qa", "revising", "final-building", "final-qa", "done", "blocked"]
    },
    "currentSprint": { "type": ["integer", "null"], "minimum": 1 },
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
          "verdicts": {
            "type": "array",
            "description": "one entry per QA round, oldest first — the trend a human needs to decide whether another round is worth it",
            "items": {
              "type": "object",
              "required": ["round", "overall"],
              "additionalProperties": false,
              "properties": {
                "round": { "type": "integer", "minimum": 0 },
                "overall": { "enum": ["pass", "fail"] },
                "weightedScore": { "type": ["number", "null"] },
                "blockingCount": { "type": "integer", "minimum": 0 }
              }
            }
          },
          "commit": { "type": ["string", "null"] }
        }
      }
    },
    "finalRounds": {
      "type": "array",
      "description": "end-of-run assessment rounds; same shape as a sprint's verdicts",
      "items": {
        "type": "object",
        "required": ["round", "status"],
        "additionalProperties": false,
        "properties": {
          "round": { "type": "integer", "minimum": 1 },
          "status": { "enum": ["building", "qa", "passed", "failed"] },
          "overall": { "enum": ["pass", "fail", null] },
          "weightedScore": { "type": ["number", "null"] },
          "blockingCount": { "type": ["integer", "null"], "minimum": 0 },
          "commit": { "type": ["string", "null"] }
        }
      }
    },
    "consecutiveFailures": { "type": "integer", "minimum": 0 },
    "repeatedIssueFingerprints": {
      "type": "object",
      "description": "blocking-issue id -> number of consecutive verdicts it has appeared in",
      "additionalProperties": { "type": "integer", "minimum": 1 }
    },
    "approachChanges": {
      "type": "object",
      "description": "blocking-issue id -> number of times the generator reported a materially different approach for it. Distinguishes 'stuck' from 'still trying something new'.",
      "additionalProperties": { "type": "integer", "minimum": 0 }
    },
    "ledger": { "$ref": "#/$defs/ledger" },
    "lastGoodCommit": { "type": ["string", "null"] },
    "blockedReason": { "type": ["string", "null"] },
    "updatedAt": { "type": "string", "format": "date-time" }
  },
  "$defs": {
    "ledger": {
      "type": "array",
      "description": "append-only, one entry per subagent invocation. This is the evidence for whether a component is still worth its cost.",
      "items": {
        "type": "object",
        "required": ["ts", "agent", "phase", "durationMs", "tokens"],
        "additionalProperties": false,
        "properties": {
          "ts": { "type": "string", "format": "date-time" },
          "agent": { "enum": ["harness-planner", "harness-generator", "harness-evaluator"] },
          "phase": { "type": "string", "description": "the phase value at the time of the call" },
          "sprint": { "type": ["integer", "null"] },
          "round": { "type": ["integer", "null"] },
          "durationMs": { "type": ["integer", "null"], "minimum": 0 },
          "tokens": { "type": ["integer", "null"], "minimum": 0, "description": "subagent_tokens as reported by the Agent tool result" },
          "note": { "type": "string" }
        }
      }
    }
  }
}
```

`phase: "blocked"` means the loop stopped and is waiting for a human. Only a human
decision moves it — `/harness-build` asks before clearing it.

### The ledger is not optional

After **every** subagent call, append a ledger entry using the `durationMs` and
`subagent_tokens` the Agent tool reports in its result. If a value is unavailable,
write `null` rather than omitting the entry or estimating.

This exists for one reason. The most important recurring judgement in this harness
is *is this component still worth its cost*, and that question cannot be answered
from prose. The ledger is what makes "the evaluator found nothing in the last four
sprints and cost 38% of the run" a fact instead of an impression.

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
changes. Include the ledger delta (tokens and duration) for the phase.

```markdown
## 2026-08-09T12:34:56Z — sprint 01 — verdict: fail (weighted 2.8)
2 blocking issues. Top: "Rectangle fill tool only places tiles at the drag start
and end points instead of filling the region" (cause: fillRectangle not called on
mouseUp, LevelEditor.tsx:414). Revision 1 of 5 starting.
Evaluator: 41.2k tokens, 6m12s.
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
