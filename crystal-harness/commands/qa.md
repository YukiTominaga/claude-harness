---
description: Run the evaluator standalone against the current state of the app — a sprint's contract, or the whole spec — and write a verdict.
argument-hint: "[sprint-number | final]"
allowed-tools: Read, Write, Bash, Glob, Grep, Skill, Agent
---

Run a standalone evaluation. This does not advance the build loop; it produces a
verdict for the current state of the working tree.

Target, from `$1`:

- a number → sprint QA for that sprint, graded against its `contract.md`
- `final` → a **final assessment**, graded against `spec.md` as a whole, written to
  the next round directory under `.harness/final/`
- omitted → `state.json`'s `currentSprint`, else the highest-numbered directory
  under `.harness/sprints/`

## Procedure

1. Read `.harness/config.json`, `.harness/spec.md`, and — for sprint QA — the
   sprint's `contract.md`.
   - No contract for that sprint? Say so and grade against the spec instead, deriving
     `SPEC-n` criteria. State clearly that criteria were derived, not agreed.
2. Write `.harness/handoff.md` before spawning. Even a standalone QA is a phase
   boundary; the handoff is what makes an interrupted run resumable.
3. Spawn a **fresh `harness-evaluator`** with the file paths and the target
   directory. Give it no summary of what the code does. It reads
   `harness.browserVerification` itself and picks its verification mode from it —
   do not tell it which mode to use, and do not override the config for one run
   without saying so in the journal.
4. Read the returned `verdict.json`, validate it with `validate_verdict.py` —
   never by eye — append a journal entry, append the round to `state.json`
   (`sprints[].verdicts` or `finalRounds`) **including its
   `environment.verificationMode`**, and **append a `ledger` entry** with the
   evaluator's `duration_ms` and `subagent_tokens` from the Agent result.
   The summary is the only per-round history: the next round overwrites this
   round's `verdict.json` in place.

This command does not commission a codex review; that belongs to the build loop,
which knows which diff the round produced. If a `codex-review.md` is already in the
target directory the evaluator will read it as usual.

Do not change `phase` and do not mark anything `passed` here — a standalone QA is
evidence, not a loop transition. If it passes and the human wants that recorded, they
run `/crystal-harness:build`, which owns run state.

If the app cannot be started, report that as the verdict with the literal command and
output. Do not debug the application.

## Report

The verification mode first. Then the overall verdict; the six scores against the
thresholds that applied, with the previous round's for comparison and waived
dimensions named as waived; the pass / fail / not_verified counts, with browser-only
gaps counted separately; whether the API, persistence and test suite were verified;
and every blocking issue with its reproduction steps, cause, and screenshot path.

If the evaluator ran `degraded`, say so before anything else — browser verification
was asked for and not delivered, and nothing else in the report means what it
usually means.
