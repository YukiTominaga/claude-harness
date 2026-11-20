---
description: Turn defects that came back into project rules — list the candidates from the issue log, draft a rule for each the human wants, and store only the ones they approve.
allowed-tools: Read, Write, Bash, Glob, Grep
---

Every evaluator starts a round knowing nothing about the rounds before it. A project
rule is how a kind of defect that was missed once stops being missable: a concrete
check, with a trigger that can be read from a diff, that later evaluators are handed
whenever a round's diff hits the trigger.

You propose. The human decides. Nothing is stored without their yes.

## 1. Show what has come back

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/rules.py" candidates
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/rules.py" list
```

`candidates` reads `.harness/issues.jsonl`, the log of every issue every validated
verdict of this project has raised. It lists an issue id that appeared in two or more
rounds, and a source file that two or more distinct issues were traced to. If it
says there are none, say so and stop — one occurrence is an anecdote, and a rule
written from an anecdote is how a checklist fills with noise.

## 2. Draft a rule for each candidate worth one

For each candidate, read the cause it records and the code it names, then decide
whether a rule would have caught it. Not every candidate deserves one: a defect that
needed one specific fix and cannot recur is not a rule. Say which you are skipping
and why.

A rule is:

```json
{
  "title": "Writes must be committed",
  "check": "For every handler in this diff that changes the datastore, perform the write, then read the row from a second connection. A 2xx with no row is a failure.",
  "paths": ["app/**"],
  "keywords": ["conn.execute"],
  "origin": ["B-api-1"]
}
```

- **`check` is something an evaluator can do and observe**, in the product, with a
  result that is either there or not. "Be careful with transactions" is not a check.
- **The trigger has to be readable from a diff.** `paths` are globs over changed
  files; `keywords` are text in added lines; at least one is required, and neither
  may match everything. A rule that fires on every round stops being read. Prefer
  the narrowest trigger that still covers where the defect could reappear.
- **`origin`** lists the issue ids it came from, so a later reader can see why it
  exists.
- One rule per kind of defect. If two candidates share a cause, write one rule.
- Check `list` first: do not propose what an existing rule already covers.

## 3. Ask, then store only what was approved

Show every drafted rule in full and ask the human which to keep, change or drop.
Wait for the answer. Then write the approved ones to a file as a JSON array and run:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/rules.py" add --file <that file>
```

It validates each rule and appends it to `.harness/rules.json`; if it rejects one,
nothing is stored — fix exactly what it names and ask again if the fix changes the
rule's meaning. Journal which rules were added and from which issues, and commit
`.harness/rules.json`.

Never edit `.harness/rules.json` or `.harness/issues.jsonl` by hand, and never add a
rule the human did not approve — a rule binds every later round of this project.
Removing a rule is the human's edit to make.
