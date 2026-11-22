# Baseline

What the suite reported for the plugin's defaults, and for one cheaper evaluator
next to them. The newest pass is first; it is the only one with more than one run
per case, and its counts are still counts, not rates.

Seeded defects detected, and clean runs that failed, on 2026-11-22:

| | Notes: seeded | Notes: clean | Tracker: seeded | Tracker: clean |
| --- | --- | --- | --- | --- |
| Evaluator as pinned: `claude-opus-5-5`, effort `high`, 1 run per case | 6/6 | 0/2 failed | 7/7 | 1/2 failed |
| Evaluator forced to `claude-sonnet-5-5`, effort `high`, 3 runs per case | 18/18 | 0/6 failed | 20/21 | 2/6 failed |

**On what this suite measures, Sonnet 5.5 did the evaluator's job as well as
Opus 5.5, at a third to two-fifths of the cost.** Every clean run that failed, on either model,
cited a real defect in the fixture and none cited a decoy. The one seeded run not
counted as detected never got the app running. The detail, and what the result
does not cover, is in the next section.

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

### What came out

| | |
| --- | --- |
| Plugin | crystal-harness 0.15.0 |
| Claude Code | 2.1.330 |
| Evaluator | single evaluator (`parallelEvaluation: false`), headless, effort `high` |
| Session relaying each request | `claude-sonnet-5-5` |
| Commands | `python3 evals/run.py --model claude-sonnet-5-5 --runs 3 --evaluator-model claude-sonnet-5-5`, then the same with `--runs 1` and no `--evaluator-model` |

| case | Sonnet 5.5, three runs | s (mean) | USD (mean) | Opus 5.5, one run | s | USD |
| --- | --- | --- | --- | --- | --- | --- |
| seeded-delete-not-committed | 3/3 detected | 95 | 0.32 | detected | 159 | 0.79 |
| seeded-delete-unknown-returns-204 | 3/3 detected | 88 | 0.34 | detected | 167 | 0.85 |
| seeded-list-newest-first | 3/3 detected | 94 | 0.31 | detected | 152 | 0.78 |
| seeded-restart-wipes-data | 3/3 detected | 96 | 0.35 | detected | 147 | 0.75 |
| seeded-invalid-json-returns-422 | 3/3 detected | 80 | 0.32 | detected | 113 | 0.63 |
| seeded-body-discarded | 3/3 detected | 91 | 0.34 | detected | 136 | 0.72 |
| clean-full-suite | 3/3 passed | 78 | 0.32 | passed | 181 | 1.05 |
| clean-second-implementation | 3/3 passed | 82 | 0.31 | passed | 148 | 0.82 |
| seeded-tracker-reopen-keeps-completed-at | 3/3 detected | 159 | 0.54 | detected | 325 | 1.60 |
| seeded-tracker-move-into-archived-project | **2/3 detected** | 118 | 0.44 | detected | 355 | 1.54 |
| seeded-tracker-deleted-blocker-still-blocks | 3/3 detected | 151 | 0.53 | detected | 332 | 1.55 |
| seeded-tracker-indirect-cycle-accepted | 3/3 detected | 132 | 0.47 | detected | 280 | 1.41 |
| seeded-tracker-total-counts-the-page | 3/3 detected | 140 | 0.51 | detected | 261 | 1.32 |
| seeded-tracker-patch-tags-not-normalised | 3/3 detected | 170 | 0.61 | detected | 312 | 1.55 |
| seeded-tracker-tag-length-before-lower-casing | 3/3 detected | 164 | 0.57 | detected | 320 | 1.49 |
| clean-tracker-full-suite | **2/3 passed** | 185 | 0.57 | **failed** | 403 | 1.88 |
| clean-tracker-decoys | **2/3 passed** | 186 | 0.57 | passed | 403 | 1.76 |

No run ended without a verdict. The Sonnet pass was 51 runs, $22.23 and 105
minutes; the Opus pass 17 runs, $20.51 and 70 minutes; $42.74 together at list
price.

| per assessment | Sonnet 5.5 | Opus 5.5 |
| --- | --- | --- |
| Notes | $0.33, 88 s | $0.80, 150 s |
| Tracker | $0.53, 156 s | $1.57, 332 s |

### Against what was decided

**Detection holds.** 38 of 39 seeded runs detected; one miss, where two were
allowed; no case below two of three. No seeded defect was passed: the miss failed
its round too.

**False alarms hold, on the reading decided beforehand and not on the raw count.**
Two of twelve clean Sonnet runs failed, which is one more than the limit. Read,
neither is a false alarm: both cite behaviour that reproduces on the fixture and
contradicts its spec, and Opus's own run of one of the two cases failed on the
same thing. Whoever prefers the raw count should read this criterion as not met —
and should then read the pinned evaluator's one-in-four the same way.

The three runs that were not right, and the one Opus run:

- **`seeded-tracker-move-into-archived-project`, Sonnet run 2 — the miss.** The
  evaluator reported that every write it tried from Bash came back `Read-only
  file system`, did not start the server, marked ten of eleven criteria
  `not_verified` and failed the round for that. It had seen the defect while
  reading — "`Store.move_task` calls `_require_project` but never checks
  `archived`" — and, as its instructions say, did not grade what it had not
  driven. Its evaluator ran for 88 seconds. The restriction is real — the sandbox
  mounts the project directory read-only and gives each command its own `/tmp`
  and network — and every other run met it too: the other 50 Sonnet runs and all
  17 Opus runs drove the app anyway, from a copy in a writable directory, with
  the database path overridden, or in-process, start to stop inside one command.
- **`clean-tracker-full-suite`, Sonnet run 2.** Two blocking issues. A number in
  the query string followed by a newline was taken as a number — `limit=5%0A`
  answered 200, and `offset=0%0A` answered 500 — because the validating patterns
  ended in `$`. And `ΟΔΟΣ` and `οδοσ` were both accepted as project names:
  `str.lower()` turns a capital sigma into `ς` at the end of a word and `σ`
  elsewhere, so the two got different keys.
- **`clean-tracker-decoys`, Sonnet run 2.** The sigma again, as its one blocking
  issue. Nothing about the three decoys.
- **`clean-tracker-full-suite`, the Opus run.** The sigma, as its one blocking
  issue.

### What it showed

**Nothing here separates the two models on finding a seeded defect.** 38 of 39
against 13 of 13, and the one miss was not a defect looked for and not found.

**The one thing that differed is how the cheaper model met an awkward
environment.** Every run here has to get round a read-only project directory
(see "Conditions"). Two of 51 Sonnet verdicts carry a blocking issue that is
about that rather than about the app — the miss above, and one run that detected
its defect and also blocked on not having started `python3 app.py` on its real
port. None of the 17 Opus verdicts does. Two in 51 against none in 17 is not a
rate; it is the place to look first.

**The app written to be sound was still not sound, for the third time.** The sigma
came from the fix for an earlier finding (`casefold()` replaced by `lower()` so
that `ß` and `ss` would stay apart). Both models found it. In the clean Tracker
runs the sigma was reported in two of Sonnet's six and in both of Opus's two —
blocking in three of those four, a note in one. Two further Sonnet runs noted the
neighbouring `Straße`/`STRASSE` question and did not block on it.

**The severity call still varies, on both models.** Same defect, same fixture:
blocking in one Opus run, a note in the other.

**The decoys have now drawn nothing in the ten runs that carried them**: four in
this pass, six in the three earlier rounds.

### After the pass

The two defects are fixed in the fixture, as decided: names are compared
case-folded, and the spec now says so and gives `Straße`/`STRASSE` as one name,
which settles the question the app kept being marked on; the patterns end in
`\Z`. Both are in the fixture's own tests and in `scripts/test_eval_fixtures.py`.
**Nothing has been measured on the fixture as it now stands.**

### What follows from it

- **The evidence this suite can give for a Sonnet 5.5 evaluator is in, and it is
  favourable**: the same detection, a third to two-fifths of the cost and about half the time
  per assessment.
- **It is evidence about one part of the evaluator's work.** Finding a planted
  defect through an API is the part these models find easy. The evaluator also
  judges an interface, holds a long build's context and decides what blocks, and
  none of that is measured here. Changing the pin on this alone would be
  deciding the unmeasured part by the measured one.
- **The cheapest next evidence is a real build.** Run one with the evaluator on
  Sonnet 5.5 and read its verdicts against what the build then turned out to
  need. Separately, re-running this pass on an ordinary machine would show
  whether the environment-induced blocks go away.
- **A clean case measures the fixture at least as much as the evaluator.** Three
  passes, three sets of real defects. A clean count from this suite should
  always be read with the issues next to it.

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
seeded defect among its blocking issues, next to the others. The 2026-11-22 pass
above re-ran all of them on one state of the fixture; compare with those rows,
not these.

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
  `--evaluator-model`, not a reason to change the pin. (Done on 2026-11-22; see
  above.)
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

These rows are from before the graders were tightened in 0.15.0 (a pattern can no
longer pair a word inside `blockingIssues` with one in a later key). The
2026-11-22 pass re-ran all eight with the tightened graders: 6/6 and 0/2 on
Opus 5.5 again, 18/18 and 0/6 on Sonnet 5.5.

## How to read it

**The suite has no headroom at these settings, on either app.** Every seeded
defect was found by the pinned evaluator, so it cannot show that a change makes
the evaluator *better* — there is nothing left to gain on it. What it can show is a change making the evaluator
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
  evaluator so. Whether an ordinary machine behaves the same has not been
  checked, and the numbers should be re-taken there before being compared with
  later ones.
- The evaluator's Bash commands also see the project directory read-only, and
  each has its own `/tmp` and network, so `python3 app.py` cannot simply be
  started in place and probed from the next command. The case prompt does not
  say so. Every evaluator has to find a way round — a copy of the app in a
  writable directory, the database path overridden, or server and probes inside
  one command — and all 17 Opus runs and 50 of 51 Sonnet runs of 2026-11-22 did.
- One run per case, except the Sonnet pass of 2026-11-22, which is three. Three
  runs can show a case that fails most of the time; they cannot put a number on
  one that fails one time in ten.
- The 2026-11-21 Tracker rows come from three rounds on three states of the
  fixture, as described above. Only the two clean rows and the tag-length row were measured on
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
