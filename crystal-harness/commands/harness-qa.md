---
description: Run the evaluator standalone against the current state of the app and write a verdict.
argument-hint: "[sprint-number]"
allowed-tools: Read, Write, Bash, Glob, Grep, Skill, Agent
---

Run a standalone evaluation. This does not advance the build loop; it produces a
verdict for the current state of the working tree.

Sprint: `$1` if given, otherwise `state.json`'s `currentSprint`, otherwise the
highest-numbered directory under `.harness/sprints/`.

## Procedure

1. Read `.harness/config.json`, `.harness/spec.md`, and the sprint's `contract.md`.
   - No contract for that sprint? Say so, and grade against `spec.md`'s "Behaviour
     and states" and "Edge cases" sections instead, deriving criterion ids. State
     clearly in your report that criteria were derived, not agreed — an evaluation
     against criteria the generator never saw is a useful signal but not a sprint
     verdict.
2. Write `.harness/handoff.md` before spawning. Even a standalone QA is a phase
   boundary; the handoff is what makes an interrupted run resumable.
3. Spawn a **fresh `harness-evaluator`** with the file paths and the sprint
   directory. Give it no summary of what the code does.
4. Read the returned `verdict.json`, validate it against the `qa-rubric` schema,
   append a journal entry, and update the sprint's `lastVerdict` in `state.json`.

Do not change `phase` and do not mark a sprint `passed` here — a standalone QA is
evidence, not a loop transition. If it passes and the human wants that recorded,
they run `/crystal-harness:harness-build`, which owns sprint state.

If the app cannot be started, report that as the verdict with the literal command
and output. Do not debug the application.

## Report

Overall verdict, the four scores against their thresholds, the pass / fail /
not_verified counts, and every blocking issue with its reproduction steps and
screenshot path. If the evaluator ran degraded, say so first, before anything else.
