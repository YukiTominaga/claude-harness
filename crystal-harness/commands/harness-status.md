---
description: Print the current harness phase, sprint and final-round tables, score trends, the cost ledger, and open blocking issues.
allowed-tools: Read, Glob, Grep, Bash
---

Report the state of this harness run. Read-only: change nothing, spawn nothing.

Read `.harness/state.json`, `.harness/config.json`, `.harness/handoff.md`, and every
`verdict.json` under `.harness/sprints/` and `.harness/final/`. If `.harness/` does
not exist, say so and point at `/crystal-harness:harness-init`.

Print exactly this, in this order:

## Run

Phase, current sprint, `useSprints` / `useEvaluator` / `usePlanner` /
`contextResetPolicy`, `lastGoodCommit` (with its subject from
`git log -1 --format=%s`), and whether the working tree is clean.

If `phase` is `blocked`, print `blockedReason` in full, first, before anything else.

## Sprints

| # | title | status | rev | verdict | PD | Fn | Ds | Or | Cr | CQ | wtd | commit |

One row per sprint, joined with its latest `verdict.json`. `-` for missing values.
Mark any score below its threshold (PD/Fn/Ds/Or ≥ 4, Cr/CQ ≥ 3) so it is visible at a
glance.

## Final assessment

| round | status | verdict | PD | Fn | Ds | Or | Cr | CQ | wtd | blocking |

If there are no final rounds yet, say so plainly: **the run is not finished until a
final assessment passes**, and reaching the end of the feature ordering is not the
same thing.

## Score trend

For the current sprint or final sequence, the `weightedScore` per round in order, so
it is visible whether rounds are improving, plateauing, or regressing. Say which of
the three it is; that is the signal for whether another round is worth its cost.

## Cost

Aggregate `state.json`'s `ledger` and print:

| agent | calls | tokens | wall time |
| harness-planner | | | |
| harness-generator | | | |
| harness-evaluator | | | |
| **total** | | | |

Then one line naming the evaluator's share of total tokens. If
`harness.costPerMTokUsd` is set in `config.json`, add an estimated-USD column and
label it estimated. If the ledger is empty, say so — the strip decisions in the README
are not answerable without it.

## Latest verdict

Overall, criterion counts (pass / fail / not_verified), `environment.degraded`, and
`apiVerified` / `persistenceVerified`. If degraded, say so prominently with the
reason — a degraded verdict measured far less than it appears to. If either
verification flag is false and the project has a backend, say that persistence was
not independently confirmed.

## Open blocking issues

Every issue in the latest verdict's `blockingIssues`, in order, with id, summary,
`cause`, and screenshot path. Flag any id whose `repeatedIssueFingerprints` count is
≥ 2, and say whether `approachChanges` for it is 0 — that pair is the condition that
stops the loop.

## Next action

The "Next action" line from `handoff.md`, verbatim, plus the command that performs it.
If `handoff.md`'s phase/sprint disagrees with `state.json`, say the handoff is stale
and that `/crystal-harness:harness-resume` will refuse to continue until it is
resolved.

Add no commentary about progress or quality.
