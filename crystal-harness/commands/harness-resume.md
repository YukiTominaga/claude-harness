---
description: Reconstruct a harness run from .harness/state.json and handoff.md after a crash, /clear, or a new session, and continue.
allowed-tools: Read, Write, Bash, Glob, Grep, Skill, Agent
---

Resume this harness run. Assume you know nothing about it. Anything you think you
remember about this project is not evidence — the files are.

Read the `crystal-harness:harness-protocol` skill, then reconstruct in this order.

## 1. Reconstruct

1. `.harness/state.json` — phase, current sprint, sprint statuses, failure counters,
   `lastGoodCommit`.
2. `.harness/handoff.md` — the goal, what is done, what was in progress, known
   broken, settled decisions, next action.
3. `.harness/config.json` — how to run the project.
4. `.harness/spec.md` — what is being built.
5. The current sprint's `contract.md`, and `qa.md` / `verdict.json` if the phase is
   `revising`.

Do not read `journal.md` to reconstruct state. It is a human log and it contains
superseded decisions.

## 2. Consistency checks — a mismatch is a hard error

Stop and ask the human if any of these fail. Do not guess your way past one; a
resumed agent that guesses wrong rebuilds working code a different way.

- `handoff.md` is missing → hard error. The previous session did not reach a phase
  boundary cleanly. Report `state.json`'s phase, `git log -5`, and `git status`, and
  ask whether to roll back to `lastGoodCommit` or to treat the working tree as-is.
- `handoff.md`'s `Phase:` or `Sprint:` disagrees with `state.json` → **stale
  handoff**, hard error. Show both. A stale handoff reads as authoritative and is
  the worst input a fresh agent can get.
- `handoff.md`'s `Last good commit` is not an ancestor of `HEAD`, or does not exist
  → report it with `git log --oneline -10` and ask.
- `git status` shows uncommitted changes while the phase is `qa` or `passed` → say
  so; something was edited outside the loop.
- `phase: "blocked"` → print `blockedReason` and the last verdict's blocking issues,
  and stop. A block is cleared by a human decision, not by resuming.

## 3. Confirm before continuing

Print a reconstruction summary and stop for confirmation:

- phase, current sprint, and the sprint table with statuses
- the handoff's "Current goal", "In progress", "Known broken", and "Next action"
- revision count and `maxRevisionsPerSprint`, and any issue id already at 2
  recurrences
- `lastGoodCommit` and whether the working tree is clean

Ask: continue from "Next action", or roll back to `lastGoodCommit` first?

## 4. Continue

On confirmation, re-enter the loop at the reconstructed phase by following
`/crystal-harness:harness-build` from that point. Every subagent you spawn is fresh
and gets file paths — never a narrative reconstruction of what you just read.

Append a journal entry recording the resume, the phase resumed at, and the commit
the tree was at.
