# Baseline

What the suite reported for the plugin's defaults, and — for the Tracker cases —
for one cheaper evaluator next to them. One run per case throughout, so these are
observations, not rates.

| | Notes cases (8) | Tracker cases (9) |
| --- | --- | --- |
| Evaluator as pinned: `claude-opus-5-5`, effort `high` | 6/6 detected, 0/2 false alarms | 7/7 detected, 0/2 false alarms |
| Evaluator forced to `claude-sonnet-5-5`, effort `high` | not run | 7/7 detected, 0/2 false alarms |

**The harder cases did not open any headroom.** Both evaluators found every seeded
defect in both apps. What the Tracker runs did show is in "What the Tracker runs
showed" below, and it is not what they were built to show.

## Sonnet 5.5 as the evaluator — 2026-11-22

The question: on what this suite measures, does the evaluator do as well on
`claude-sonnet-5-5` as on the pinned `claude-opus-5-5`, both at effort `high`?
All seventeen cases, three runs each on Sonnet, one run each on Opus as the
reference on the same fixture.

### Decided before the run

- **Detection holds** if every seeded case is detected in at least two of its
  three Sonnet runs, and no more than two of the 39 seeded runs are misses.
  A case missed in two or three of three is a kind of defect Sonnet does not
  reliably find, whatever the total.
- **False alarms hold** if at most one of the twelve clean Sonnet runs fails a
  sound app. Every failing clean run is read first: one that cites a real defect
  in the fixture is not a false alarm — it is reported as such, and the fixture
  is fixed afterwards, not during the pass.
- A run that ends without a verdict is invalid and in neither count; it is
  reported, not silently re-run.
- The Opus pass is one run per case. It is there to show the cases behave on the
  current fixture, not to estimate Opus's own miss rate.
- Whatever comes out speaks for defect detection through an API on two small
  apps. It says nothing about an interface, a long build, or the judgement
  dimensions, and it does not change the pin.

## Tracker cases — 2026-11-21

| | |
| --- | --- |
| Plugin | crystal-harness 0.15.0 |
| Claude Code | 2.1.330 |
| Evaluator | single evaluator (`parallelEvaluation: false`), headless; model as in each column, effort `high` |
| Session relaying each request | `claude-sonnet-5-5` |
| Commands | `python3 evals/run.py --case '<glob>' --model claude-sonnet-5-5`, plus `--evaluator-model claude-sonnet-5-5` for the second column |

| case | Opus 5.5: outcome | s | USD | Sonnet 5.5: outcome | s | USD | measured in |
| --- | --- | --- | --- | --- | --- | --- | --- |
| seeded-tracker-reopen-keeps-completed-at | detected | 334 | 1.71 | detected | 118 | 0.45 | round 1 |
| seeded-tracker-move-into-archived-project | detected | 280 | 1.31 | detected | 136 | 0.52 | round 1 |
| seeded-tracker-deleted-blocker-still-blocks | detected | 312 | 1.44 | detected | 166 | 0.57 | round 1 |
| seeded-tracker-indirect-cycle-accepted | detected | 311 | 1.58 | detected | 144 | 0.49 | round 1 |
| seeded-tracker-total-counts-the-page | detected | 364 | 1.62 | detected | 144 | 0.49 | round 1 |
| seeded-tracker-patch-tags-not-normalised | detected | 280 | 1.32 | detected | 168 | 0.54 | round 1 |
| seeded-tracker-tag-length-before-lower-casing | detected | 314 | 1.42 | detected | 134 | 0.50 | round 2 |
| clean-tracker-full-suite | passed | 389 | 1.84 | passed | 179 | 0.55 | round 3 |
| clean-tracker-decoys | passed | 529 | 2.40 | passed | 198 | 0.66 | round 3 |

An assessment of the Tracker costs about $1.30–2.40 and five to nine minutes on
Opus 5.5, and about $0.45–0.70 and two to three minutes on Sonnet 5.5: roughly a
third of the cost and half the time. (Notes, on Opus 5.5: about $0.80 and three
minutes.) All of it together — a trial run, three rounds, two evaluators — was
$29.36 at list price.

### Why three rounds

The fixture changed between them, because the evaluators kept being right about
it.

- **Round 1** ran the six designed defects and the two clean cases. Both
  evaluators found all six. Both also failed both clean cases — correctly. The app
  written to be sound checked a tag's length before lower-casing it, and took any
  value of `include_archived` as `false` where the spec's own status-code rule
  says 422. Its author and its 35 tests had missed both.
- **Round 2**, after fixing those: the tag-length defect, now seeded as its own
  case, was found by both. Each evaluator passed one clean case and failed the
  other, again correctly, on a new defect each: `NaN` and `Infinity` accepted as
  JSON (Opus), an integer of more than 4300 digits reaching `int()` and becoming a
  500 (Sonnet).
- **Round 3**, after fixing those: both clean cases passed on both evaluators.

So the six designed seeded cases were measured on a base app that still had the
defects fixed later. That does not change what they show — each verdict named the
seeded defect among its blocking issues, next to the others — but a re-run on the
current fixture is the first thing to do before comparing anything with these
rows.

### What the Tracker runs showed

**Multi-step defects that contradict a stated rule are not hard for these models
at this effort.** The six were designed to need a sequence, a second resource or
enough data, in an app too large to try everything once, behind a spec that
states rules rather than probes. Detection was 6/6 on both evaluators, in two to
six minutes.

**The suite cannot tell Opus 5.5 from Sonnet 5.5 as the evaluator.** That was the
check this pass was run for: if only the cheaper evaluator had missed something,
the suite would have been shown to discriminate. It did not. The one place the
two differed is thin: in round 1, with the tag-length defect present but unseeded
in all eight runs, Opus reported it as blocking in six and Sonnet in four; seeded
as its own case, both found it. Two in eight, one run each, is not a finding.

**No decoy drew a false alarm.** Across the three rounds the clean cases ran
twelve times. Six of those failed; every one of the six cited a real defect that
was then fixed, and none cited the cascading deletes, the archive check inside
the `UPDATE`, or the `CASE` without `ELSE`. Read as a false-alarm count on the
fixture as it now stands: 0 of 4.

**Whether a small defect blocks the round varies from run to run.** The
`include_archived` defect was mentioned in all sixteen round-1 verdicts, as
blocking in three of Opus's eight and five of Sonnet's eight, as a non-blocking
note in the rest. The 4300-digit integer was blocking in one Sonnet run and a
note in the next. Detection was stable; the severity call was not. This suite
does not measure that — it is why `include_archived` is not a seeded case — and
it is the kind of variance that decides whether a real round passes.

**The useful cases came from the evaluator, not from the author.** Five real
defects were found in code believed sound. A seeded mutation is limited to what
its author can imagine going wrong; the evaluator is not.

### What follows from it

- **An evaluator on a cheaper model is now the first change worth testing.** On
  everything this suite can measure, Sonnet 5.5 matched Opus 5.5 at about a third
  of the cost. That is nine cases run once, on one kind of product, and says
  nothing about the judgement dimensions, an interface, or a long build — so it
  is a reason to run `--runs 3` on all seventeen cases with
  `--evaluator-model`, not a reason to change the pin.
- **`parallelEvaluation` still cannot be justified from this suite.** A single
  evaluator finds everything in it.
- **Headroom will not come from harder single defects in an API.** It would have
  to come from what the suite does not cover — an interface, a codebase of many
  files, the severity call itself — or from defects a real build's evaluator
  missed and a later round caught.

## Notes cases — 2026-11-20

| | |
| --- | --- |
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

These eight have not been re-run since their graders were tightened in 0.15.0
(a pattern can no longer pair a word inside `blockingIssues` with one in a later
key). The change can only turn a "detected" into a "missed", never the reverse.

## How to read it

**The suite has no headroom at these settings, on either app.** Every case came
out right, so it cannot show that a change makes the evaluator *better* — there
is nothing left to gain on it. What it can show is a change making the evaluator
*worse*. That is the use it is fit for: a floor under cost-saving changes.

- Lowering the evaluator's effort, moving it to a cheaper model, or trimming its
  prompt and the rubric are each worth trying against this floor. If detection
  stays at 13/13 and false alarms at 0/4 over several runs, the saving is real on
  this kind of defect.
- Before reading a false-alarm count, read the issues. A fail on a sound app and
  a fail on an unsound one score the same, and for two rounds every "false alarm"
  here was the second kind.

## Conditions this was taken under

- Run as root in a container. There the sandbox makes every Bash call end with a
  "Read-only file system" line and exit code 1; the case prompt tells the
  evaluator so. On an ordinary machine that note is moot, and the numbers should
  be re-taken there before being compared with later ones.
- One run per case. The same command with `--runs 3` is the minimum before
  comparing two configurations.
- The Tracker rows come from three rounds on three states of the fixture, as
  described above. Only the two clean rows and the tag-length row were measured on
  a base app without the defects found along the way.
- Before round 1, one trial run (the three-task cycle, Sonnet 5.5) was made
  against a first draft of the Tracker spec that spelled that probe out. It found
  the defect in two minutes, and the spec was rewritten to state rules instead —
  once, before any measured run. No case was added, dropped or changed because of
  how a measured run came out, with two exceptions that are both stated above:
  the tag-length case was added because the evaluator found that defect, and the
  `include_archived` one was left out because its correct verdict is arguable.
- An earlier Notes run on 2026-11-20 had four of eight runs end without a
  verdict: the session relaying the request followed the plugin's session-start
  note ("use status first") instead of the request. That note was reworded and
  the case prompt made explicit; the Notes baseline is the run after that fix.
  The four runs that did reach a verdict in the earlier run agreed with it (three
  seeded defects detected, one clean app passed).
