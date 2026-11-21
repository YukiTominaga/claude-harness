# Baseline

What the suite reported for the plugin's defaults. One run per case, so these are
eight observations, not rates.

| | |
| --- | --- |
| Date | 2026-11-20 |
| Plugin | crystal-harness 0.14.0 |
| Claude Code | 2.1.329 |
| Evaluator | `claude-opus-5-5`, effort `high` — as pinned in `agents/harness-evaluator.md`, single evaluator (`parallelEvaluation: false`), headless |
| Session relaying each request | `claude-sonnet-5-5` |
| Command | `python3 evals/run.py --runs 1 --model claude-sonnet-5-5` |

**Seeded defects detected: 6/6. False alarms on clean apps: 0/2. Invalid runs: 0.**

| case | outcome | seconds | est. USD |
| --- | --- | --- | --- |
| seeded-delete-not-committed | detected | 152 | 0.79 |
| seeded-delete-unknown-returns-204 | detected | 186 | 0.89 |
| seeded-list-newest-first | detected | 158 | 0.80 |
| seeded-restart-wipes-data | detected | 169 | 0.83 |
| seeded-invalid-json-returns-422 | detected | 138 | 0.79 |
| seeded-body-discarded | detected | 140 | 0.75 |
| clean-full-suite | passed | 176 | 0.89 |
| clean-second-implementation | passed | 156 | 0.84 |

Estimated cost $6.57 at list price, 21 minutes of wall time, about $0.80 and two
and a half to three minutes per assessment.

## How to read it

**The suite has no headroom at these settings.** Every case came out right, so it
cannot show that a change makes the evaluator *better* — there is nothing left to
gain on it. What it can show is a change making the evaluator *worse*. That is the
use it is fit for today: a floor under cost-saving changes.

- Lowering the evaluator's effort, moving it to a cheaper model, or trimming its
  prompt and the rubric are each worth trying against this floor. If detection
  stays at 6/6 and false alarms at 0/2 over several runs, the saving is real on
  this kind of defect.
- Turning on `parallelEvaluation` cannot be justified from this suite: a single
  evaluator already finds everything here. The argument for it needs cases a
  single evaluator misses.

To make the suite discriminate upward, add harder cases — defects that need two
steps to expose, that sit behind a UI, that only appear under a particular order
of operations — and take them from defects a real run missed. A case is hard
enough to be worth adding when you can say why it is hard before you run it.

## Conditions this was taken under

- Run as root in a container. There the sandbox makes every Bash call end with a
  "Read-only file system" line and exit code 1; the case prompt tells the
  evaluator so. On an ordinary machine that note is moot, and the numbers should
  be re-taken there before being compared with later ones.
- One run per case. The same command with `--runs 3` is the minimum before
  comparing two configurations.
- An earlier run on the same day had four of eight runs end without a verdict:
  the session relaying the request followed the plugin's session-start note
  ("use status first") instead of the request. That note was reworded and the
  case prompt made explicit; this baseline is the run after that fix. The four
  runs that did reach a verdict in the earlier run agreed with this one (three
  seeded defects detected, one clean app passed).
