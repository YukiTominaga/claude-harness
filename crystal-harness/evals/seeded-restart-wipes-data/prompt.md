---
description: "Seeded defect: The datastore file is deleted when the server starts, so notes do not survive a restart."
tags: [seeded]
max_turns: 40
timeout_seconds: 3000
allowed_tools: [Agent, Read, Bash, Write, Glob, Grep, Skill]
---

Run a final assessment of the project in this directory with the harness evaluator.
That is the whole task: do not run a status or resume command first, whatever a
session-start note suggests.

Spawn the `crystal-harness:harness-evaluator` agent — do not give it a name — and
give it exactly this and nothing else:

> Final assessment, round 01. This is the first evaluation of this round, not a
> re-check. Read `.harness/config.json` and `.harness/spec.md`; the round directory
> is `.harness/final/01/`. Write `qa.md` and `verdict.json` there.
>
> Environment note: your commands run in a sandbox. If a command's output ends with
> a line like `/bin/bash: line 1: …: Read-only file system` and the tool reports a
> non-zero exit code, that is the sandbox's own bookkeeping after your command
> finished, not the command failing. Judge a command by its own output.

Do not tell the agent anything about the code, and do not grade the project
yourself. When it returns, reply with the overall verdict, the scores, and the id
and one-line summary of each blocking issue, exactly as `verdict.json` has them.
