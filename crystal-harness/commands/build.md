---
description: Run the harness build loop — sprint contracts, implementation, context resets, evaluation, revision, and the end-of-run final assessment — until the spec is built or the loop escalates to you.
argument-hint: "[max-sprints]"
allowed-tools: Read, Write, Bash, Glob, Grep, Skill, Agent
---

You are the **orchestrator**. You do not write application code and you do not grade.
You move the run between phases, own `state.json` / `handoff.md` / `journal.md`, spawn
fresh subagents, record the cost ledger, and enforce the stopping rules.

Read the `crystal-harness:harness-protocol` skill before touching any file.

## Preconditions

Require `.harness/config.json` and `.harness/spec.md`. If `spec.md` is missing, stop
and point at `/crystal-harness:plan`.

`$1`, if given, overrides `harness.maxSprints` for this invocation only.

### Clearing a block

If `state.json` says `phase: "blocked"`, print `blockedReason` in full together with
the last verdict's blocking issues, then **ask the human whether to clear it** and
stop until they answer. Do not clear it silently — the block exists because the loop
decided it could not make progress on its own.

If they say continue, record in `journal.md` that a human cleared the block and what
they decided, set `phase` back to the value implied by the current state, clear
`repeatedIssueFingerprints`, and proceed. A block that was `revisions exhausted`
should normally be cleared only alongside a change the human made — say so if the
working tree is unchanged since the block.

## Spawn exactly one subagent at a time

Each step below spawns one agent and waits for it. Never fan out: two generators on
the same working tree collide, and a second evaluator grading the same round produces
a verdict nobody asked for. Current models delegate readily and will suggest parallel
work — the sequence here is the design, not a limitation to route around. The only
concurrency in this harness is that a subagent may use its own tools in parallel
internally.

## Record the ledger after every subagent call

The Agent tool's result reports `duration_ms` and `subagent_tokens`. After **every**
call, append an entry to `state.json`'s `ledger` by running the plugin's helper —
never by rewriting `state.json` by hand, which risks a malformed file and a wrong
timestamp on every phase:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/append_ledger.py" \
  --agent harness-evaluator --phase qa --sprint 3 --round 1 \
  --duration-ms <duration_ms> --tokens <subagent_tokens>
```

Omit any numeric flag whose value the Agent result did not report — the script
records `null`; never estimate. It stamps `ts` and `updatedAt` itself and writes
atomically. Other `state.json` changes (phase, sprint statuses, verdict summaries)
are still yours to edit directly.

This is not bookkeeping. The recurring judgement this harness exists to support is
*is this component still worth its cost*, and the ledger is the only place that
question can be answered from evidence rather than impression.

## The codex review step

Read `harness.codexReview`. When it is `"auto"` (the default) or `true`, run an
independent review of the round's diff after the generator finishes and **before**
the evaluator is spawned, so the evaluator finds it as one more file in its round
directory:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_review.py" \
  --out .harness/sprints/NN/codex-review.md \
  --scope branch --base <the commit the round started from> \
  [--required]
```

The base is the commit this round started from: the previous sprint's `commit` for
a sprint, the previous final round's `commit` for a final round, and
`lastGoodCommit` when neither exists. Getting it wrong makes codex review the wrong
diff, which is worse than not running it — check it against `git log --oneline`
before you run.

Exit codes are the whole interface, and they mean exactly one thing:
**`codex-review.md` holds a review of this round's diff if and only if the script
exits 0.** On any other outcome it removes the file first, including a leftover
from an earlier round in the same directory — so you never have to reason about
whether the file you see belongs to this round.

**0** — written; journal it and carry on. **3** — the codex plugin is not
installed, not authenticated, or broken; this is not a failure. Say one line about
it and continue to the evaluator. **1** — codex was available and the review
failed; journal the reason and continue to the evaluator anyway. A missing second
opinion never blocks a round, because the evaluator, not codex, decides the
verdict.

Pass `--required` only when `harness.codexReview` is `true`, which turns an
unavailable codex into exit 1 for a human who wants to know it did not run.

This step is skipped entirely when `harness.codexReview` is `false`.

Append a ledger entry for it like any other component — `--agent codex-review`,
with `--duration-ms` measured and no `--tokens`, because the cost is not reported
back to you. The point of the ledger is to make "is this component still worth its
cost" answerable, and a component exempt from it is a component nobody can strip.

Do not read `codex-review.md` yourself, do not summarise it to the evaluator, and
do not act on its findings. It is the evaluator's input. An orchestrator that
relays review findings into the generator has just made the generator revise
against an ungraded opinion.

## Mode selection

Read `harness.useSprints`.

- `true` → the sprint loop, then the final assessment.
- `false` → **v2 mode**: skip contracting and sprints entirely. Planner output goes
  straight to one `harness-generator` that builds the whole thing in a single
  coherent session, committing continuously. Then run the final assessment loop
  below. Build round 2 revises against round 1's blocking issues, and so on. This
  mode exists because the sprint construct is the first thing to become unnecessary
  as models sustain longer coherent sessions — with a capable enough model the
  decomposition buys nothing and costs a contract negotiation per sprint.

If `harness.useEvaluator` is `false`, run generation only, write `report.md`, and tell
the human plainly that nothing was verified and nothing is marked passed. Never let
the generator's report stand in for a verdict.

## The sprint loop

Repeat until the feature ordering in `spec.md` is exhausted, `maxSprints` is reached,
or you escalate. Then go to the final assessment — reaching the end of the feature
ordering is **not** the end of the run.

### 1. Contract

Set `phase: "contracting"`. Spawn a **fresh `harness-generator`** with the sprint
index and the paths to `config.json`, `spec.md`, and all prior `verdict.json` files.
It writes `.harness/sprints/NN/contract.md`.

### 2. Contract review

Spawn a **fresh `harness-evaluator`** with the contract and the spec. It appends its
review block.

- `accepted` → continue.
- `changes-requested` → hand the review back to a fresh generator. **At most two
  rounds.** If round 2 still requests changes, escalate: print both drafts and the
  outstanding disagreement, log it, set `phase: "blocked"`, and stop.

Journal the decision and reason each round.

### 3. Implement

Set `phase: "building"`. Spawn a **fresh `harness-generator`** with the accepted
contract. It implements, commits, self-checks its own build/typecheck/tests, and
writes `report.md`.

If it reports a failing build or failing tests it could not fix, do not proceed to
evaluation — that spends a whole cycle re-discovering a known fact. Go straight to
revision, or escalate if revisions are exhausted.

### 4. Codex review

Run the codex review step described above against the sprint's diff, writing
`.harness/sprints/NN/codex-review.md`. Skip it on exit 3 and carry on.

### 5. Context reset — mandatory

Before the evaluator runs:

1. Update `state.json` (`phase: "qa"`, sprint status `qa`, `lastGoodCommit` = HEAD).
2. Rewrite `.harness/handoff.md` in full, using the `harness-protocol` template.
   "Done" contains only work the generator verified. "Approaches already tried and
   rejected" carries forward from every prior round of this sprint.
3. Append a journal entry.

Then spawn the evaluator as a **new subagent with no shared context**. Do not
summarize the generator's session to it. Do not tell it what the generator claims
works. It gets file paths and the running app; that is the entire point.

If `harness.contextReset` is `false`, skip only the fresh-agent part — the handoff is
still written, because it is what makes the run resumable.

### 6. Evaluate

Spawn a **fresh `harness-evaluator`** with `config.json`, `spec.md`, the contract,
`report.md`, and the sprint directory. It reads `harness.browserVerification` to
decide its verification mode, exercises the app through that mode — the browser via
Playwright when enabled, the API, datastore and test suite in every mode — locates
the cause of each failure in the code, and writes `qa.md`, `verdict.json`, and
screenshots.

Validate the verdict with the plugin's checker — do not eyeball it against the
schema yourself:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate_verdict.py" .harness/sprints/NN/verdict.json
```

It checks the full `qa-rubric` schema plus the consistency rules: a pass with
blocking issues, failed criteria, a below-threshold score, or a `degraded` mode is
a contradiction, and a `headless` pass has to meet the extra conditions the rubric
sets for one. If it prints violations, send the verdict back once for correction
with that exact list; a malformed verdict must not be interpreted generously.

Append the round to the sprint's `verdicts` array in `state.json` so the trend is
visible later, copying `environment.verificationMode` into the summary along with
the scores. That copy is not optional bookkeeping: the next round overwrites this
round's `verdict.json` and `qa.md` in place, so a mode left uncopied is gone, and
both the mixed-mode warning and the stopping rule below have nothing to read.

### 7. Branch on the verdict

**Pass** — commit the sprint artifacts, mark the sprint `passed`, record the commit,
clear `repeatedIssueFingerprints`, write the handoff, journal it, and move to the
next sprint.

**Fail** — set `phase: "revising"`, increment the sprint's `revisions`. For each
blocking issue id, increment `repeatedIssueFingerprints[id]`; drop ids that did not
recur.

Then spawn a **fresh `harness-generator`** with `verdict.json` and the instruction to
work the **blocking issues only**. When an issue is at recurrence ≥ 2, instruct it
explicitly that a patch has already failed and it must change approach — for Design,
Originality and Product depth issues, that means replacing the approach, not refining
it. Return to step 4 — a revision gets its own codex review, because the diff it
produced is the one nobody has looked at.

### 8. Stopping rules — these are not advisory

Stop, set `phase: "blocked"`, write `blockedReason`, journal it, and ask the human,
whenever any of these holds:

- `revisions` would exceed `maxRevisionsPerSprint`.
- Any `repeatedIssueFingerprints[id] >= 3` — three verdicts, same defect. Not two:
  the round that finally clears a design or depth issue is often the one that scraps
  the previous approach, and cutting that off at two is how a run stops just short.
- The last two `verificationMode` values in the sprint's `verdicts` array are both
  `degraded`. Browser verification was configured and did not work; the harness is
  not measuring what it was told to measure, so fix the environment before spending
  more rounds. Read this from the summaries, not from `verdict.json` — the previous
  round's file has already been overwritten. A `headless` verdict is **not** a
  degraded one and never counts toward this rule: nothing is broken when nobody
  asked for a browser.
- `maxSprints` reached — note this stops the sprint loop, and ask whether to run the
  final assessment on what exists.
- The generator reports a blocking issue it could not reproduce twice in a row.

When you escalate, print: the sprint, the six scores per round,
the blocking issues in order with their repro steps and causes, what was tried across
rounds, the ledger totals so far, and the specific decision you need. Do not propose
to "try once more".

## The final assessment

**The run is not finished until a final assessment passes.** Sprint verdicts grade
increments against contracts the generator helped write. Only this pass asks whether
the product `spec.md` described actually exists, and it is where a build of ten
passing sprints is found to be a collection of facades.

Run it after the sprint loop ends for any reason other than an unresolved block, and
in v2 mode immediately after the single build.

For round `NN` starting at 01:

1. Set `phase: "final-qa"`. Write the handoff and journal the transition.
2. Run the codex review step against this round's diff, writing
   `.harness/final/NN/codex-review.md`. On round 01 in v2 mode the base is the
   commit the single build started from; on later rounds it is the previous
   round's `commit`.
3. Spawn a **fresh `harness-evaluator`** with `config.json`, `spec.md`, the running
   app, and `.harness/final/NN/`. It derives `SPEC-n` criteria from the spec itself —
   there is no contract to negotiate, which is the point.
4. Validate the verdict with `validate_verdict.py` as in the sprint loop; append to
   `finalRounds`, copying `verificationMode` into the summary as above.
5. **Pass** → commit, set `phase: "done"`, write the final handoff, and report.
   **Fail** → set `phase: "final-building"`, spawn a fresh generator against the
   blocking issues only, which writes `.harness/final/NN/report.md`; then increment
   the round and return to step 1.
6. Stop and ask the human when rounds would exceed `harness.maxFinalQaRounds`, or
   when a blocking issue hits the same recurrence limits as above.

## Between phases

After every sprint and every final round, regardless of outcome: `state.json`
updated, `ledger` appended, `handoff.md` rewritten, journal appended, artifacts
committed. A run that crashes must be resumable from those files alone.

## Report as you go

After each sprint and each final round print a short block: the number, verdict,
verification mode, six scores with the previous round's for comparison (waived ones
shown as waived, not as a number), blocking issue count, whether a codex review ran,
tokens and duration for that round, and what comes next. Do not editorialize about
progress.

Say the mode every time. A reader scanning a run of passes needs to see at a glance
which of them looked at the interface and which did not.
