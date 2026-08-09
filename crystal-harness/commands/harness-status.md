---
description: Print the current harness phase, sprint table, latest verdict summary, and open blocking issues.
allowed-tools: Read, Glob, Grep, Bash
---

Report the state of this harness run. Read-only: change nothing, spawn nothing.

Read `.harness/state.json`, `.harness/config.json`, `.harness/handoff.md`, and every
`.harness/sprints/*/verdict.json`. If `.harness/` does not exist, say so and point
at `/crystal-harness:harness-init`.

Print exactly this, in this order:

## Run

Phase, current sprint, `useSprints` / `useEvaluator` / `usePlanner` / 
`contextResetPolicy`, `lastGoodCommit` (with its subject line from
`git log -1 --format=%s`), and whether the working tree is clean.

If `phase` is `blocked`, print `blockedReason` first, in full, before anything else.

## Sprints

| # | title | status | rev | verdict | F | D | O | C | commit |

One row per sprint from `state.json`, joined with each `verdict.json`. Use `-` for
missing values. Mark any score below its threshold so it is visible at a glance.

## Latest verdict

From the highest-numbered `verdict.json`: overall, the criterion counts
(pass / fail / not_verified), and `environment.degraded` — if degraded, say so
prominently with the reason, because a degraded verdict measured much less than it
appears to.

## Open blocking issues

Every issue in the latest verdict's `blockingIssues`, in order, with id, summary,
and screenshot path. If any id also appears in `state.json`'s
`repeatedIssueFingerprints` with a count ≥ 2, flag it as recurring — that is the
condition that stops the loop.

## Next action

The "Next action" line from `handoff.md`, verbatim, plus the command that performs
it. If `handoff.md`'s phase/sprint disagrees with `state.json`, say the handoff is
stale and that `/crystal-harness:harness-resume` will refuse to continue until it is
resolved.

Add no commentary about progress or quality.
