---
name: harness-protocol
description: The file-based contract every harness agent reads and writes — .harness/ layout, state.json and verdict.json schemas, the handoff.md template, and the journal. Use whenever reading or writing anything under .harness/, at any phase boundary, and before any context reset or resume.
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
├── state.json           # machine-readable run state
├── handoff.md           # rolling context-reset handoff artifact
├── journal.md           # append-only log of decisions and events
├── artifacts/           # Playwright MCP scratch output (screenshots land here first)
└── sprints/
    └── 01/
        ├── contract.md      # generator proposes, evaluator accepts
        ├── report.md        # generator's completion report + self-check
        ├── qa.md            # evaluator verdict, human-readable
        ├── verdict.json     # evaluator verdict, machine-readable
        └── screenshots/     # evidence referenced by qa.md
```

Sprint directories are zero-padded two-digit (`01`, `02`, …). In `useSprints: false`
mode there is exactly one directory, `01`, and it holds the single end-of-run
evaluation.

## Ownership

| Path | Written by | Read by |
| --- | --- | --- |
| `config.json` | `/harness-init`, the human | everyone |
| `spec.md` | planner | generator, evaluator |
| `sprints/NN/contract.md` | generator (proposal), evaluator (accept/reject block appended) | both |
| `sprints/NN/report.md` | generator | evaluator |
| `sprints/NN/qa.md`, `verdict.json`, `screenshots/` | **evaluator only** | generator (read-only, when revising) |
| `state.json`, `handoff.md`, `journal.md` | the orchestrating command | everyone |

The generator writing its own `verdict.json` is the single failure that destroys the
whole design, so it is also blocked by a `PreToolUse` hook, not just by instruction.

## `state.json`

JSON Schema (draft 2020-12):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "harness state",
  "type": "object",
  "required": ["schemaVersion", "phase", "currentSprint", "sprints", "consecutiveFailures", "lastGoodCommit", "updatedAt"],
  "additionalProperties": false,
  "properties": {
    "schemaVersion": { "const": 1 },
    "phase": {
      "enum": ["init", "planning", "contracting", "building", "qa", "revising", "done", "blocked"]
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
          "status": {
            "enum": ["contracting", "contracted", "building", "qa", "revising", "passed", "failed", "abandoned"]
          },
          "revisions": { "type": "integer", "minimum": 0 },
          "contractRounds": { "type": "integer", "minimum": 0 },
          "lastVerdict": { "enum": ["pass", "fail", null] },
          "commit": { "type": ["string", "null"] }
        }
      }
    },
    "consecutiveFailures": { "type": "integer", "minimum": 0 },
    "repeatedIssueFingerprints": {
      "type": "object",
      "description": "blocking-issue id -> number of consecutive verdicts it has appeared in. Used to detect no-progress loops.",
      "additionalProperties": { "type": "integer", "minimum": 1 }
    },
    "lastGoodCommit": { "type": ["string", "null"] },
    "blockedReason": { "type": ["string", "null"] },
    "updatedAt": { "type": "string", "format": "date-time" }
  }
}
```

`phase: "blocked"` means the loop stopped and is waiting for a human. It is not an
error state to be cleared automatically — only a human decision moves it.

## `verdict.json`

Owned by the evaluator. Schema is defined in the `qa-rubric` skill, which also holds
the thresholds. Summary of the shape:

```json
{
  "schemaVersion": 1,
  "sprint": 1,
  "overall": "pass",
  "scores": { "functionality": 4, "design": 3, "originality": 3, "craft": 3 },
  "criteria": [
    { "id": "AC-1", "text": "...", "result": "pass", "evidence": "…", "screenshot": "…" }
  ],
  "blockingIssues": [],
  "nonBlockingIssues": [],
  "environment": { "playwrightAvailable": true, "appUrl": "http://localhost:5173", "degraded": false },
  "evaluatedAt": "2026-08-09T12:00:00Z"
}
```

## `handoff.md` — the load-bearing artifact

`handoff.md` must be sufficient for a **completely fresh agent with zero prior
context** to resume the run. Write it at every phase boundary, before any context
reset, without exception. Overwrite it in place; the history lives in `journal.md`.

A handoff whose `Written at` state does not match `state.json` (different phase, or
different sprint) is a **hard error**: stop and tell the human. Do not guess. A stale
handoff is worse than no handoff, because it reads as authoritative.

Fixed template — use these headings verbatim:

```markdown
# Handoff

Written at: <ISO-8601 timestamp>
Phase: <phase from state.json>  Sprint: <index or ->
Last good commit: <sha or ->

## Current goal
<One paragraph. What the run as a whole is trying to produce, and what this
sprint is trying to produce. No history.>

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

## Files that matter
<Path — why it matters. Only files the next agent must read. Not a directory
listing.>

## Next action
<Exactly one imperative sentence. Not a list. If the next action is "ask the
human", say what the question is.>
```

Rules that make the template work:

- **"Done" means verified.** Written-but-untested code goes in "In progress", not
  "Done". This is the specific line that stops a resumed agent from believing the
  run is further along than it is.
- **"Next action" is one action.** A list invites the fresh agent to pick the easy
  item. One sentence forces a decision at write time, while context still exists.
- **"Decisions already made" is not optional.** Its absence is the reason resumed
  agents rebuild things a different way and break what worked.

## `journal.md`

Append-only. Never rewrite prior entries. One entry per event that a human would
want to reconstruct later: phase transitions, contract accept/reject with the
reason, verdicts, revisions, escalations, and configuration changes.

```markdown
## 2026-08-09T12:34:56Z — sprint 01 — verdict: fail
2 blocking issues. Top: "Rectangle fill tool only places tiles at the drag start
and end points instead of filling the region." Revision 1 of 3 starting.
```

Escalations must be logged with the reason before control returns to the human.

## Reading order for a fresh agent

1. `.harness/state.json` — where am I.
2. `.harness/handoff.md` — what do I do next. Cross-check phase/sprint against
   `state.json`; mismatch is a hard error.
3. `.harness/config.json` — how do I run this project.
4. `.harness/spec.md` — what is being built.
5. `.harness/sprints/NN/contract.md`, then `qa.md` if revising.

Do not read `journal.md` to reconstruct state. It is for humans; `state.json` and
`handoff.md` are the machine truth.
