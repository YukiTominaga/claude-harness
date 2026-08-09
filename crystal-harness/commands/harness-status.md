---
description: Print the current harness phase, sprint and final-round tables with score trends, the cost ledger, and open blocking issues.
allowed-tools: Read, Glob, Grep, Bash
---

Report the state of this harness run. Read-only: change nothing, spawn nothing.

Read `.harness/state.json`, `.harness/config.json`, `.harness/handoff.md`, and every
`verdict.json` under `.harness/sprints/` and `.harness/final/`. If `.harness/` does
not exist, say so and point at `/crystal-harness:harness-init`.

Print exactly this, in this order.

## Run

Phase, current sprint or final round, `useSprints` / `useEvaluator` / `contextReset`,
`lastGoodCommit` (with its subject from `git log -1 --format=%s`), and whether the
working tree is clean.

If `phase` is `blocked`, print `blockedReason` in full, first, before anything else.

## Rounds

One table for sprints and one for final rounds, **one row per QA round** rather than
per sprint — the scores across rounds are the trend, so they have to be visible side
by side:

| sprint/round | status | PD | Fn | Ds | Or | Cr | CQ | blocking | commit |

Mark any score below its threshold (PD/Fn/Ds/Or ≥ 4, Cr/CQ ≥ 3). Say in one line
whether the sequence is improving, plateauing, or regressing — that is the signal for
whether another round is worth its cost.

If there are no final rounds yet, say so plainly: **the run is not finished until a
final assessment passes**, and reaching the end of the feature ordering is not the
same thing.

## Cost

Aggregate `state.json`'s `ledger`:

| agent | calls | tokens | wall time |
| harness-planner | | | |
| harness-generator | | | |
| harness-evaluator | | | |
| **total** | | | |

Then one line naming the evaluator's share of total tokens. If
`harness.costPerMTokUsd` is set, add an estimated-USD column and label it estimated.
If the ledger is empty, say so — the strip decisions in the README are not answerable
without it.

## Open blocking issues

From the latest verdict: `overall`, the criterion counts (pass / fail /
not_verified), and — if `environment.degraded` is true — say so prominently with the
reason, because a degraded verdict measured far less than it appears to. If
`apiVerified` or `persistenceVerified` is false and the project has a backend, say
persistence was not independently confirmed.

Then every issue in `blockingIssues`, in order, with id, summary, `cause`, and
screenshot path. Flag any id whose `repeatedIssueFingerprints` count is ≥ 2 — one
more recurrence stops the loop.

## Next action

The "Next action" line from `handoff.md`, verbatim, plus the command that performs it.
If `handoff.md`'s phase/sprint disagrees with `state.json`, say the handoff is stale
and that `/crystal-harness:harness-resume` will refuse to continue until it is
resolved.

Add no commentary about progress or quality.
