---
description: Print the current harness phase, sprint and final-round tables with score trends, the cost ledger, and open blocking issues.
allowed-tools: Read, Glob, Grep, Bash
---

Report the state of this harness run. Read-only: change nothing, spawn nothing.

Read `.harness/state.json`, `.harness/config.json`, `.harness/handoff.md`, and every
`verdict.json` under `.harness/sprints/` and `.harness/final/`. If `.harness/` does
not exist, say so and point at `/crystal-harness:init`.

Print exactly this, in this order.

## Run

Phase, current sprint or final round, `useSprints` / `useEvaluator` /
`contextReset` / `browserVerification` / `codexReview`, `lastGoodCommit` (with its
subject from `git log -1 --format=%s`), and whether the working tree is clean.

If `browserVerification` is `false`, add one line: this run grades in headless
mode, so design, originality and craft are not assessed and browser-only criteria
are not checked. A reader scanning a column of passes has to be able to see what
those passes covered.

If `phase` is `blocked`, print `blockedReason` in full, first, before anything else.

## Rounds

One table for sprints and one for final rounds, **one row per QA round** rather than
per sprint — the scores across rounds are the trend, so they have to be visible side
by side:

| sprint/round | mode | PD | Fn | Ds | Or | Cr | CQ | blocking | commit |

`mode` is the round's `verificationMode` from its entry in `sprints[].verdicts` or
`finalRounds` — read it there, not from `verdict.json`, which only ever holds the
latest round. A summary written before this field existed has no mode; print `?`
rather than assuming one. Mark any score below a threshold that applied in that mode (PD/Fn/Ds/Or ≥ 4, Cr/CQ ≥ 3). Render a waived
dimension as `—`, never as a number and never as a zero: a `headless` row with
three dashes and a `browser` row with three fours are not comparable, and a reader
must not be able to mistake one for the other. Say in one line whether the sequence
is improving, plateauing, or regressing — that is the signal for whether another
round is worth its cost. If the modes differ across rows, say that too, because a
trend across mixed modes is not a trend.

If there are no final rounds yet, say so plainly: **the run is not finished until a
final assessment passes**, and reaching the end of the feature ordering is not the
same thing.

## Cost

Aggregate `state.json`'s `ledger`:

| agent | calls | tokens | wall time |
| harness-planner | | | |
| harness-generator | | | |
| harness-evaluator | | | |
| codex-review | | | |
| **total** | | | |

`codex-review` rows report wall time only; its token cost is not reported back to
the harness, so leave that cell `—` rather than guessing.

Then one line naming the evaluator's share of total tokens. If
`harness.costPerMTokUsd` is set, add an estimated-USD column and label it estimated.
If the ledger is empty, say so — the strip decisions in the README are not answerable
without it.

## Open blocking issues

From the latest verdict: `overall`, the verification mode, and the criterion counts
(pass / fail / not_verified, with browser-only gaps counted separately).

If the mode is `degraded`, say so prominently with the `degradedReason`: browser
verification was configured and did not happen, so the verdict measured far less
than it appears to, and two in a row stop the loop. If the mode is `headless`, say
plainly how many criteria went unchecked — that number, not the verdict, is what
tells the human whether to re-run with `browserVerification: true`.

If `apiVerified` or `persistenceVerified` is false and the project has a backend,
say persistence was not independently confirmed.

Then every issue in `blockingIssues`, in order, with id, summary, `cause`, and
screenshot path. Flag any id whose `repeatedIssueFingerprints` count is ≥ 2 — one
more recurrence stops the loop.

## Next action

The "Next action" line from `handoff.md`, verbatim, plus the command that performs it.
If `handoff.md`'s phase/sprint disagrees with `state.json`, say the handoff is stale
and that `/crystal-harness:resume` will refuse to continue until it is
resolved.

Add no commentary about progress or quality.
