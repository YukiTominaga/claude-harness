---
description: Run the planner on a product idea and produce .harness/spec.md, then wait for your approval.
argument-hint: "<one-line product idea>"
allowed-tools: Read, Write, Bash, Glob, Grep, Skill, Agent(harness-planner)
---

Produce the product specification for this harness run.

Idea: `$ARGUMENTS`

Read the `crystal-harness:harness-protocol` skill. Require `.harness/config.json` to
exist — if it does not, stop and tell the human to run
`/crystal-harness:init` first. Do not initialize on their behalf; init needs
their confirmation of the detected commands.

## Procedure

1. If `$ARGUMENTS` is empty, ask for the idea and stop.
2. Set `state.json` `phase: "planning"`.
3. Spawn the **`harness-planner`** subagent with: the idea verbatim, the path to
   `.harness/config.json`, the target directory, and the instruction to write
   `.harness/spec.md`. Give it nothing else — the planner's whole value is that it
   reasons from the idea and the domain, not from your framing of it.
4. When it returns, read `.harness/spec.md` yourself. Check for the failure modes
   the planner is prone to:
   - implementation detail leaking in (file names, component trees, library
     choices, route shapes) — if present, say so in your summary; it will cascade.
   - a "Feature ordering" item that is not traceable to a described surface and
     behaviour.
   - an invented AI feature in "Where AI adds real value" that the product does not
     need.
5. Append a journal entry. Rewrite `.harness/handoff.md` with `phase: planning`
   complete and "Next action" = run `/crystal-harness:build`.
6. Set `state.json` `phase: "contracting"`, `currentSprint: 1`.

## Then stop

Show the human:

- the one-liner and the surfaces list
- the full prioritized feature ordering
- the non-goals
- every open question with the assumption the planner made
- anything you flagged in step 4

Then **wait**. Do not start building. `/crystal-harness:build` is a separate,
deliberate step, because the spec is the one artifact where a wrong assumption is
cheap to fix now and expensive to fix after four sprints are built on it.
