---
description: Run the harness build loop — sprint contracts, implementation, context resets, evaluation, revision, and the end-of-run final assessment — until the spec is built or the loop escalates to you.
argument-hint: "[max-sprints]"
allowed-tools: Read, Write, Bash, Glob, Grep, Skill, Agent, Workflow
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

## One builder at a time, unless a split plan says otherwise

Each build, contract and revision step below spawns one agent and waits for it.
Never fan those out on your own: two generators on the same working tree collide.
Current models delegate readily and will suggest parallel work — the sequence here
is the design, not a limitation to route around.

The one exception is a **team build** (`harness.teamBuild: true`): the first build
of a round may be done by several generators at once, under a split plan that a
script validates and a hook enforces — see "Team build" below. Contract steps and
revisions are never split.

Evaluation is different, because evaluators do not write source. When
`harness.parallelEvaluation` is `true`, a QA round is graded by one evaluator per
lens, run by the plugin's `evaluate` workflow — see "Parallel evaluation" below.
When it is `false` (the default) a round has exactly one evaluator, and a second
one grading the same round would produce a verdict nobody asked for.

## The ledger records itself — keep `state.json` ahead of it

You do not append ledger entries for agents. A `SubagentStop` hook sums each
agent's token usage from its transcript and appends to `.harness/ledger.jsonl`
when the agent finishes (see `harness-protocol`). Two things are still yours:

- **Set `phase`, `currentSprint` and `currentRound` in `state.json` before you
  spawn an agent, never after it returns.** The hook stamps the entry with whatever
  `state.json` says at the moment the agent stops. An entry stamped with the
  previous phase is attributed to the wrong round for good.
- **Never copy `subagent_tokens` from an Agent tool result** into the journal, a
  report block, or anything else. It is the size of the agent's final request, not
  its run. When you need a round's cost, run

  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py" report
  ```

  and quote its numbers.

This is not bookkeeping. The recurring judgement this harness exists to support is
*is this component still worth its cost*, and the ledger is the only place that
question can be answered from evidence rather than impression.

## The budget

`harness.maxRunTokens` and `harness.maxRunCostUsd` cap what the run may spend on
agents. Before **every** spawn — an agent or the `evaluate` workflow — run

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py" budget
```

Exit 0: carry on. Exit 3 (a cap is reached) or exit 1 with `BUDGET NOT
ENFORCEABLE` (a cost cap is set but there are no rates to price tokens by): stop,
set `phase: "blocked"` with the printed lines as `blockedReason`, journal it, and
ask the human. Do not finish "just this round" first.

A `PreToolUse` hook enforces the same check: once a cap is reached it denies
starting any harness agent or the `evaluate` workflow. If you see that denial you
skipped the check above; do what it says. Only the human raising or removing the
cap in `config.json` lets the run continue — never edit the cap yourself.

## A file an agent handed back

An agent's `Write` can be refused by a rule outside this plugin. One such rule is
known and designed around: Claude Code refuses a subagent's write to any `.md`
file whose name starts with `report`, `summary`, `findings` or `analysis` — the
reason the generator's notes are `build-notes.md` ("The generator's notes" below).
The agents are told never to route around a refusal. Instead the agent ends its
final response with a line `Write rejected: <path> — <message>` and the file's
content between `<!-- crystal-harness:begin <name> -->` and
`<!-- crystal-harness:end <name> -->`, and stops. By the time you see that
response, a `SubagentStop` hook has kept it, verbatim, under `.harness/captures/`.

When a generator's, a builder's or an evaluator's final response carries such a
block, do this before anything else in the round:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/returned_files.py" place --round-dir <round dir> --agent-id <id>
```

`<id>` is the agent id the Agent tool result gave you; for a builder, pass
`--agent builder-<name>` instead. With neither, `place` takes the one capture
waiting and refuses when there is more than one. It writes each block byte for
byte into the round directory — and only a file that agent's role owns:
`build-notes.md` for a generator, `reports/builder-<name>.md` for that builder,
`qa.md` and `verdict.json` for an evaluator. It appends where the content came
from to `journal.md` — the agent, each file's size and sha256, the rejection the
agent quoted — and moves the capture to `.harness/captures/placed/`, where it
stays as the record. That journal entry is the provenance; do not write another.

- **Exit 0** — placed. Carry on with the round exactly as if the agent had written
  the file. In the round's report block, name the file and quote the rejection:
  a rule outside the plugin refusing a harness file is something the human needs
  to hear, because the plugin should stop asking for that name.
- **Exit 1** — nothing was written, and it printed why: no capture, a malformed
  block, a file that role does not own. Stop: set `phase: "blocked"` with the
  printed lines as `blockedReason`, journal it, and ask the human. Do not send the
  agent back to try another way.

**Never write, copy or summarise that content yourself** — not with `Write`, not
with `Bash`, not by retyping it from the agent's response, and not by repairing a
malformed block. The generator's notes are the generator's testimony; `qa.md` and
`verdict.json` are the evaluator's verdict. A copy you made is your version of
their words, and the next agent would be grading, or acting on, your paraphrase.
The script is the only thing that moves that content.

**There is no human approval before placing, deliberately.** The script decides
nothing: it copies bytes the agent wrote into the one file that agent was already
supposed to write, and refuses everything else. It is also what the refusing rule
asks for — return the content as text and let the parent keep it. Stopping for
the human every time would stall an unattended run on a step with no decision in
it. The human is told, in the journal and the round's report block, and is asked
only when the mechanical path fails.

## The generator's notes

The generator's notes are `build-notes.md` in the round directory. A plugin
update can arrive in the middle of a run, so a round directory begun before
0.16.0 may hold the legacy `report.md` instead. Do not guess which one to hand on:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/returned_files.py" notes-path <round dir>
```

prints `build-notes.md` when it exists, otherwise the legacy `report.md`, and exits
1 when there is neither. When both exist, the legacy file is ignored — it is older.

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

It is the one component you record by hand, because it is not an agent and fires
no hook — measure its wall time and run

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py" append --agent codex-review --duration-ms <ms>
```

It carries no token count, because that cost is not reported back to you. The
point of the ledger is to make "is this component still worth its
cost" answerable, and a component exempt from it is a component nobody can strip.

Do not read `codex-review.md` yourself, do not summarise it to the evaluator, and
do not act on its findings. It is the evaluator's input. An orchestrator that
relays review findings into the generator has just made the generator revise
against an ungraded opinion.

## The test-changes step

The evaluator leans on the project's test suite, and the generator wrote it. So
before any evaluator is spawned, in every round and in both evaluation modes,
record what the round did to the tests:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/test_changes.py" \
  --base <the commit the round started from> \
  --out .harness/sprints/NN/test-changes.json
```

The base is the same commit you gave the codex review. Exit 0 means the report was
written — whether or not it says `weakened`; journal a weakened report in one line
and carry on, because judging it is the evaluator's job, not yours. Exit 1 means
git could not produce the diff: the script has removed any earlier report, so say
one line about it and continue without one.

Like `codex-review.md`, this file is evidence about the generator's diff that
neither agent may write, and you do not summarise it to anyone. Its consequence is
enforced where it matters: whenever the file exists, validate the round's verdict
with `--test-changes` (below), which rejects a pass carried from an earlier round
on the strength of a suite this round weakened.

## Project rules

`.harness/rules.json` holds checks this project's evaluators have learned to make —
each from a defect that came back, each approved by the human through
`/crystal-harness:rules`. Two mechanical steps keep that memory working, in every
round and in both evaluation modes:

- **Before the evaluator**, after the test-changes step and with the same base:

  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/rules.py" match \
    --base <the commit the round started from> \
    --out .harness/sprints/NN/rules-to-check.json
  ```

  It writes the rules whose trigger this round's diff hits — usually none. Exit 1
  means it could not read the diff or the rules file: it has removed any earlier
  list; say one line and continue without one. Whenever the file exists, add
  `--rules <that file>` to the `validate_verdict.py` call, which rejects a verdict
  that does not account for every rule on the list.
- **After a verdict validates**, pass or fail:

  ```
  python3 "${CLAUDE_PLUGIN_ROOT}/scripts/rules.py" record .harness/sprints/NN/verdict.json
  ```

  The next round overwrites that verdict; this appends its issues to
  `.harness/issues.jsonl`, which is what `/crystal-harness:rules` later reads.

You never write a rule, the list, or the log yourself. When the run ends — done or
blocked — and `rules.py candidates` has something to show, say so in one line and
point at `/crystal-harness:rules`; proposing rules is a separate, human-approved step.

## Diagnosing a recurring issue

When `harness.diagnoseRecurringIssues` is `true` and a blocking issue's count in
`repeatedIssueFingerprints` has just reached **2** — the generator fixed it once and
it came back — do not spawn the next generator on a guess. Run the plugin's
`diagnose` workflow first, once per such issue, one issue at a time:

```json
{
  "roundDir": ".harness/final/02",
  "issueId": "B-api-1",
  "verdictPath": ".harness/final/02/verdict.json",
  "commit": "<git rev-parse HEAD>",
  "scratchDir": "<a directory outside the project, e.g. from mktemp -d>"
}
```

Start it by name (`crystal-harness:diagnose`) with the Workflow tool and wait for it.
One `harness-investigator` reproduces the issue and records what it sees; three
argue different kinds of cause without seeing each other; three more try to break
those arguments; one runs the deciding experiments and writes
`<round dir>/diagnosis/<issue id>/diagnosis.md`. Investigators cannot edit source —
the guard holds them to that directory.

Then spawn the revising generator as usual and add one line to its brief: the path
of the diagnosis. Do not summarise it. Journal the root cause and the confidence the
workflow returned.

- If the workflow returns `not_reproduced`, treat it as one failure to reproduce
  under the stopping rule below and pass that to the generator instead of a
  diagnosis.
- If it returns `incomplete`, or `diagnosis.md` does not exist, journal that and go
  on without one. A missing diagnosis never blocks the round.
- Diagnose an issue once. If it reaches a third recurrence the stopping rule ends
  the loop; a second diagnosis of the same issue is not a way around that.

It costs eight agents per issue. That is the price of not spending a third revision
— and then the human's attention — on the same wrong guess.

## Parallel evaluation

When `harness.parallelEvaluation` is `true`, the "evaluate" step of a sprint round
and of a final round is this procedure instead of a single evaluator. Everything
before it (context reset, codex review, test changes) and after it (validating the
verdict, summarising it into `state.json`, branching) is unchanged.

1. **Clear the lens directory**: `rm -rf <round dir>/lenses`. A lens file left from
   the previous round in the same directory must not be there to be read as this
   one's. (The merge also checks every file's round and commit, so this is the
   belt, not the braces.)
2. **Start the plugin's `evaluate` workflow** with the Workflow tool, by name
   (`crystal-harness:evaluate`), passing `args` as a JSON object:

   ```json
   {
     "roundDir": ".harness/final/02",
     "phase": "final",
     "sprint": null,
     "round": 2,
     "commit": "<git rev-parse HEAD>",
     "browser": false,
     "reproduce": true,
     "recheck": { "previousCommit": "<commit the previous round graded>",
                  "previousRoundDir": ".harness/final/01" }
   }
   ```

   - `phase` is `"sprint"` or `"final"`; `sprint` is the sprint index, or `null`.
   - `round` is the number the verdict will carry — the same value you pass to
     the merge in step 4.
   - `browser` is `harness.browserVerification`; `reproduce` is
     `harness.reproduceBlockingIssues` (default `true`).
   - `recheck` is `null` on a first evaluation. On a re-check give
     `previousCommit`, and `previousRoundDir` only in a final assessment — in a
     sprint the previous verdict is still in the round directory.

   The workflow runs the `code` lens alongside `tests` → `api` → (`screen` when
   the browser is enabled), each a fresh `harness-evaluator`, then has one more
   fresh evaluator per blocking issue try to reproduce it from its steps alone.
   The lenses that run the application go one after another because they share
   its ports and datastore; do not ask for more parallelism than that.
3. **Wait for the workflow to complete.** It runs in the background and you are
   notified; do nothing else to the round meanwhile. Its result is a summary, not a
   verdict — do not act on it.
4. **Merge**:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/merge_verdicts.py" <round dir> --round <n>
   ```

   Exit 0: `verdict.json` and `qa.md` are written. Exit 2: nothing was written, and
   it printed why — a lens is missing, malformed, self-contradictory or stale.
   Relaunch the workflow **once** with `resumeFromRunId` and the same args, so the
   lenses that finished return their cached results and only the missing one runs
   again, then merge again. A second exit 2 is an escalation: set
   `phase: "blocked"` with the printed reasons. Never write or patch a lens file or
   `verdict.json` yourself, and never treat a round that did not merge as a fail.
5. Continue with validation exactly as for a single evaluator.

Each lens and each reproduction is a ledger entry of its own, so `ledger.py report`
shows what this mode costs next to what it found. That comparison — against a run
with `parallelEvaluation: false` — is the evidence for keeping it on.

## Team build

When `harness.teamBuild` is `true`, the **first build** of a round — step 3
"Implement" of a sprint, or the single build of `useSprints: false` — is this
procedure. Revisions after a failed QA round are not: those stay with one
generator, because they work a short list of blocking issues.

A team build needs agent teams, which are experimental and off by default, and an
interactive session. Check first:

```
echo "${CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS:-0}"
```

If that does not print `1`, say one line — team build is configured but agent
teams are not enabled, so this round builds with a single generator — journal it,
and do the normal build step. Never treat that as an error.

1. **Split.** Set `phase: "building"` (and `currentRound` as the build step says).
   Spawn a fresh `harness-generator` **without a `name`**, in the **splitting**
   phase, with `config.json`, `spec.md`, the contract if there is one, and the
   round directory. It writes `<round dir>/split.json` and no code. The round
   directory is `.harness/sprints/NN` in a sprint and `.harness/final/01` for the
   single build of `useSprints: false`.
2. **Validate**:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/team_build.py" validate <round dir>/split.json
   ```

   Violations go back once to a fresh generator in the splitting phase with the
   exact list. If the second plan is still invalid, or the plan has a single
   builder, do the normal single-generator build instead and journal why. A plan
   with one builder is a legitimate answer: it means the work has no seam.
3. **Activate**: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/team_build.py" activate <round dir>/split.json`.
   This installs `.harness/split.json`, which is what the guard reads. From here
   until step 7 no agent other than the builders may be running.
4. **Spawn the builders.** For each builder in the plan, one Agent call with
   `name: "builder-<name>"` and the `harness-generator` agent type — the name is
   what makes it a teammate, and a hook refuses any other name for a generator.
   Give each the same brief:
   - it is `builder-<name>`, building in the round directory `<round dir>`;
   - its `scope` and `owns`, verbatim from the plan;
   - every pinned interface, verbatim;
   - the other builders' names and scopes, so it knows whom to ask;
   - the commit command with the script's real path:
     `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/team_build.py" commit --builder <name> -m "…"`;
   - that it follows the `team-build` skill's "Building as `builder-<name>`".

   Give no builder a summary of another's progress, and do not build anything
   yourself while they work.
5. **Wait until every builder has reported done.** Builders message each other
   about interfaces; that is the point of a team. Step in only if one asks you to
   settle a disagreement about a pinned interface — decide, tell every builder it
   touches, and journal the decision. A builder that says its report was refused
   has handed it back: place it as "A file an agent handed back" says, with
   `--agent builder-<name>`, before the check below.
6. **Check what they left**:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/team_build.py" check
   ```

   Exit 0: clean. Exit 2: each printed line names the builder who can fix it —
   send that builder its lines verbatim, wait, and check again. After **two**
   rounds of that, stop sending: journal what is still outstanding and go on; the
   evaluator will grade what exists. Lines addressed to `nobody` are a path with
   no owner — ask the builder whose paths are nearest to remove or claim it.
7. **Stand the team down.** Ask each builder to shut down and wait until all have.
   Then, in this order:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/team_build.py" report
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/team_build.py" deactivate
   ```

   `report` joins the builders' own reports (`reports/builder-<name>.md`) into
   `<round dir>/build-notes.md`, which is what the evaluator reads. Do not write or
   edit that file yourself.
8. Run the project's `commands.build` and `commands.test` once and note the
   literal outcome in the journal — the builders tested their own parts, and this
   is the first time the whole has been run. Then continue with the round as
   usual (codex review, test changes, context reset, evaluation). A red build or
   suite here goes to the evaluator like any other state of the tree; do not send
   the builders back in.

Builders are teammates, so they are not reused: a later round's build, if it is a
team build, starts from a new split plan and new builders.

## Mode selection

Read `harness.useSprints`.

- `true` → the sprint loop, then the final assessment.
- `false` → **v2 mode**: skip contracting and sprints entirely. Planner output goes
  straight to one `harness-generator` that builds the whole thing in a single
  coherent session, committing continuously — or, when `harness.teamBuild` is
  `true`, to a team build ("Team build" above), whose `build-notes.md` lands in
  `.harness/final/01/`. Then run the final assessment loop
  below. Build round 2 revises against round 1's blocking issues, and so on. For
  the single build set `phase: "building"` with `currentSprint: null` and
  `currentRound: null` before spawning — it precedes the first round. This
  mode exists because the sprint construct is the first thing to become unnecessary
  as models sustain longer coherent sessions — with a capable enough model the
  decomposition buys nothing and costs a contract negotiation per sprint.

If `harness.useEvaluator` is `false`, run generation only — the generator writes
`build-notes.md` — and tell the human plainly that nothing was verified and nothing
is marked passed. Never let the generator's notes stand in for a verdict.

## The sprint loop

Repeat until the feature ordering in `spec.md` is exhausted, `maxSprints` is reached,
or you escalate. Then go to the final assessment — reaching the end of the feature
ordering is **not** the end of the run.

### 1. Contract

Set `phase: "contracting"`, `currentSprint` to this sprint and `currentRound: null`.
Spawn a **fresh `harness-generator`** with the sprint
index and the paths to `config.json`, `spec.md`, and the previous sprint's
`verdict.json` (its non-blocking issues are the ones a new sprint may pick up;
older verdicts are already summarised in `state.json`). It writes
`.harness/sprints/NN/contract.md`.

Check the contract's shape before anyone reviews it:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate_contract.py" .harness/sprints/NN/contract.md
```

It enforces the criterion cap (`harness.maxAcceptanceCriteria`, default 20), 3–7
scope items and unique ids. If it prints violations, send the contract back once to
a fresh generator in the contract-revision phase with that exact list and the
instruction to move trailing scope items to "Out of scope" rather than compress
criteria. If the second attempt still fails, escalate. Never spend an evaluator on
a contract that fails this check.

### 2. Contract review

Spawn a **fresh `harness-evaluator`** with the contract and the spec. It appends its
review block.

- `accepted` → continue.
- `accepted-with-amendments` → continue. The amendments in the review block are
  part of the contract; the building generator and the QA evaluator both read them.
- `changes-requested` → spawn a fresh generator in the **contract-revision** phase
  with only `contract.md` — no prior verdicts or handoff, and `spec.md` only when a
  `[blocking]` item is about spec coverage. It edits what the
  `[blocking]` items name and appends `## Revision n changes`. Re-run
  `validate_contract.py`, then spawn a fresh evaluator for round 2, telling it to
  review only the listed changes and the round-1 blocking items. **At most two
  rounds.** If round 2 still requests changes, escalate: print both drafts and the
  outstanding disagreement, log it, set `phase: "blocked"`, and stop.

Run `validate_contract.py` again after every review round too — an amendment must
not take the contract past the cap. Journal the decision and reason each round, and
set the sprint's `contractRounds`.

### 3. Implement

Set `phase: "building"` and `currentRound: 1`. If `harness.teamBuild` is `true`, run
"Team build" above for this sprint — the contract's pinned interfaces are the
starting point for the split plan's — and continue from the next step. Otherwise
spawn a **fresh `harness-generator`**
with the accepted contract. It implements, commits, self-checks its own build/typecheck/tests, and
writes `build-notes.md` — or, if a rule outside the plugin refused that write, hands
it back; place it then ("A file an agent handed back").

If it reports a failing build or failing tests it could not fix, do not proceed to
evaluation — that spends a whole cycle re-discovering a known fact. Go straight to
revision, or escalate if revisions are exhausted.

### 4. Codex review and test changes

Run the codex review step described above against the sprint's diff, writing
`.harness/sprints/NN/codex-review.md`. Skip it on exit 3 and carry on. Then run the
test-changes step against the same base, writing
`.harness/sprints/NN/test-changes.json`, and the `rules.py match` step of "Project
rules", writing `.harness/sprints/NN/rules-to-check.json`.

### 5. Context reset — mandatory

Before the evaluator runs:

1. Note the current `lastGoodCommit` — on a revision round it is the commit the
   previous QA round graded, and step 6 needs it. Then update `state.json`
   (`phase: "qa"`, sprint status `qa`, `lastGoodCommit` = HEAD).
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

If `harness.parallelEvaluation` is `true`, run "Parallel evaluation" above for this
round and skip to validating the verdict. Otherwise:

Spawn a **fresh `harness-evaluator`** with `config.json`, `spec.md`, the contract,
the generator's notes (the path `returned_files.py notes-path` prints — see "The
generator's notes"), and the sprint directory. It reads `harness.browserVerification` to
decide its verification mode, exercises the app through that mode — the browser via
Playwright when enabled, the API, datastore and test suite in every mode — locates
the cause of each failure in the code, and writes `qa.md`, `verdict.json`, and
screenshots.

On a revision round, tell it this is a **re-check**, and give it the commit the
previous round graded (noted in step 5). The previous `verdict.json` is still in
the sprint directory until the evaluator overwrites it; the evaluator reads it
first. It re-verifies failed and diff-affected criteria, runs the full test suite
as the regression check, and carries the rest — see its "Re-check rounds" section.
This is a pointer to files, not a summary: do not tell it what the generator claims
to have fixed.

If the evaluator handed `qa.md` or `verdict.json` back instead of writing it, place
it first ("A file an agent handed back"). Then validate the verdict with the
plugin's checker — do not eyeball it against the schema yourself:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/validate_verdict.py" .harness/sprints/NN/verdict.json \
  --test-changes .harness/sprints/NN/test-changes.json
```

Leave `--test-changes` off only when the test-changes step wrote no file, and add
`--rules .harness/sprints/NN/rules-to-check.json` whenever that file exists. The
script checks the full `qa-rubric` schema plus the consistency rules: a pass with
blocking issues, failed criteria, a below-threshold score, or a `degraded` mode is
a contradiction; a `headless` pass has to meet the extra conditions the rubric
sets for one; and when the round weakened its tests, a pass carried from an
earlier round is rejected. If it prints violations, send the verdict back once
for correction with that exact list; a malformed verdict must not be interpreted
generously. In parallel evaluation there is no single evaluator to send it back
to: relaunch the workflow once with the violation list added to its args as
`"correction": "<the exact list>"`, merge again, and escalate if it is still
rejected.

Append the round to the sprint's `verdicts` array in `state.json` so the trend is
visible later, copying `environment.verificationMode` into the summary along with
the scores. That copy is not optional bookkeeping: the next round overwrites this
round's `verdict.json` and `qa.md` in place, so a mode left uncopied is gone, and
both the mixed-mode warning and the stopping rule below have nothing to read.

### 7. Branch on the verdict

**Pass** — commit the sprint artifacts, mark the sprint `passed`, record the commit,
clear `repeatedIssueFingerprints`, write the handoff, journal it, and move to the
next sprint.

**Fail** — set `phase: "revising"`, increment the sprint's `revisions`, and set
`currentRound` to `revisions + 1`. For each
blocking issue id, increment `repeatedIssueFingerprints[id]`; drop ids that did not
recur.

If an issue's count has just reached 2 and `harness.diagnoseRecurringIssues` is
`true`, run "Diagnosing a recurring issue" above before the next step.

Then spawn a **fresh `harness-generator`** with `verdict.json` and the instruction to
work the **blocking issues only**. Give it the file, not your reading of it — in
particular do not drop an issue marked `verification: "not_reproduced"`; whether a
defect is real is not yours to decide. When an issue is at recurrence ≥ 2, instruct it
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
- The generator reports a blocking issue it could not reproduce twice in a row —
  or once, when the verdict already marked that issue `not_reproduced`. Two
  independent failures to reproduce mean the report, not the code, needs a human.
- `ledger.py budget` exits 3 or 1 (see "The budget").

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

1. Set `phase: "final-qa"` and `currentRound` to `NN`. Write the handoff and journal
   the transition.
2. Run the codex review step against this round's diff, writing
   `.harness/final/NN/codex-review.md`. On round 01 in v2 mode the base is the
   commit the single build started from; on later rounds it is the previous
   round's `commit`. Then run the test-changes step against the same base,
   writing `.harness/final/NN/test-changes.json`, and `rules.py match`, writing
   `.harness/final/NN/rules-to-check.json`.
3. If `harness.parallelEvaluation` is `true`, run "Parallel evaluation" above for
   `.harness/final/NN/` and go to step 4. Otherwise spawn a **fresh
   `harness-evaluator`** with `config.json`, `spec.md`, the running
   app, and `.harness/final/NN/`. On round 01 it derives `SPEC-n` criteria from the
   spec itself — there is no contract to negotiate, which is the point. On later
   rounds, tell it this is a **re-check** and give it the previous round's
   `.harness/final/NN/verdict.json` and `commit`: it reuses those `SPEC-n` ids,
   re-verifies failed and diff-affected criteria, and runs the full test suite as
   the regression check.
4. Validate the verdict with `validate_verdict.py` as in the sprint loop, with
   `--test-changes` and `--rules` when those files exist, then run `rules.py
   record` on it; append to
   `finalRounds`, copying `verificationMode` into the summary as above.
5. **Pass** → commit, set `phase: "done"`, write the final handoff, and report.
   **Fail** → set `phase: "final-building"` (leave `currentRound` at `NN` — the fix
   is written into this round's directory), run "Diagnosing a recurring issue" if
   it applies, then spawn a fresh generator against the
   blocking issues only, which writes `.harness/final/NN/build-notes.md`; then increment
   the round and return to step 1.
6. Stop and ask the human when rounds would exceed `harness.maxFinalQaRounds`, or
   when a blocking issue hits the same recurrence limits as above.

## Between phases

After every sprint and every final round, regardless of outcome: `state.json`
updated, `handoff.md` rewritten, journal appended, artifacts committed —
`.harness/ledger.jsonl` among them, since the hook has been appending to it. A run that crashes must be resumable from those files alone.

## Report as you go

After each sprint and each final round print a short block: the number, verdict,
verification mode, six scores with the previous round's for comparison (waived ones
shown as waived, not as a number), blocking issue count (and how many of them were independently reproduced, when
parallel evaluation ran), whether a codex review ran, whether the round weakened
its tests,
tokens and duration for that round as `ledger.py report` gives them, and what comes
next. Do not editorialize about
progress.

Say the mode every time. A reader scanning a run of passes needs to see at a glance
which of them looked at the interface and which did not.
