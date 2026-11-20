# crystal-harness

English | [日本語](README.ja.md)

A Claude Code plugin that packages a multi-agent harness for long-running application
development. It separates the agent that builds from the agent that grades, replaces
"is this good?" with a thresholded rubric, resets context through files instead of
compacting it, makes each sprint an agreement rather than a guess, and never lets a
run finish without an independent assessment of the whole product.

Modeled on Anthropic's
[Harness Design for Long-Running Application Development](https://www.anthropic.com/engineering/harness-design-long-running-apps).

## The failure modes it addresses

| Failure | What it looks like | What the harness does |
| --- | --- | --- |
| **Loss of coherence / context anxiety** | As the window fills, the agent cuts scope and wraps up prematurely. | Context **reset**, not compaction. At every phase boundary the run writes `handoff.md` and a *fresh* agent picks it up. Nothing depends on conversation history. |
| **Self-evaluation leniency** | Asked to grade its own output, an agent confidently praises mediocre work. | Generation and evaluation are different agents with different prompts, different tools, and no shared context. A hook makes the boundary structural, not advisory. |
| **Poor QA judgment** | It finds a real issue, talks itself into deciding it isn't a big deal, and approves. It tests superficially and misses edges. | Six thresholded dimensions with behavioral anchors, 20 calibration examples, and explicit anti-sycophancy rules — a criterion not exercised is `not_verified`, never `pass`. |
| **Display-only depth** | Every surface renders; nothing can be manipulated. | **Product depth** is its own graded dimension with a threshold of 4. A control that opens a menu whose selection does nothing scores 2. |
| **Under-scoping** | A one-line prompt produces a thin three-feature app. | A planner writes a scope-complete spec before any code exists — ambitious on scope, deliberately silent on implementation. |
| **Passing sprints, failing product** | Ten sprints pass; the app doesn't hold together. | A **final assessment** graded against `spec.md` with criteria nobody negotiated. The run is not finished until it passes. |
| **A grader with the author's priors** | Generation and evaluation are separate agents, but still the same model family reading a diff that family wrote. | An optional independent review of each diff by a non-Claude model (the `codex` plugin), recorded as evidence the evaluator must confirm against the code — never as a gate. |
| **QA too slow to run** | Browser verification dominates the cost of a round, so it gets skipped informally and nobody records that it was. | Browser verification is a config flag with **three recorded modes**. A round that skipped it says so in the verdict, and a round that wanted it and did not get it can never pass. |
| **Tests that vouch for themselves** | The evaluator leans on the project's test suite, and the generator wrote it. A failing test deleted or skipped never shows up as a red suite. | A script reports what each round did to the tests before the evaluator runs. If the suite was weakened, no earlier pass may be carried on its strength, and the verdict validator enforces that. |
| **A run with no ceiling** | Rounds keep going because each one looks like it might be the last. | Optional token and cost caps, checked from the ledger. When one is reached the loop stops and asks, and a hook refuses to start another harness agent until a human raises it. |
| **The same defect, again** | Every evaluator starts a round knowing nothing about the rounds before it, so a kind of defect it missed once it can miss again. | An issue log that outlives the verdicts, and **project rules** drawn from it: concrete checks with a trigger readable from a diff, approved by a human, handed to the evaluator whenever a round's diff hits the trigger. The validator rejects a verdict that leaves one out. |
| **A fix that was a guess** | A blocking issue comes back after it was "fixed", and the next attempt is a smaller version of the last. | Optionally, a returning issue is **diagnosed** before anyone touches the code again: evidence, three competing hypotheses argued apart, a refutation of each, then the experiments that decide. |

## Install

```bash
git clone <this repo>
claude
```

Then, inside Claude Code:

```
/plugin marketplace add YukiTominaga/claude-harness
/plugin install crystal-harness@crystal-harness
```

For local development against an uncommitted checkout, add the marketplace from the local
path instead:

```
/plugin marketplace add /absolute/path/to/claude-harness
/plugin install crystal-harness@crystal-harness
```

Restart Claude Code. Or, for a throwaway trial without installing:

```bash
claude --plugin-dir /absolute/path/to/claude-harness/crystal-harness
```

Verify — the inventory should show 4 agents, 1 MCP server, 3 hooks, and 12 skills (the
seven commands are counted as skills alongside the five reference skills), plus the
`evaluate` and `diagnose` workflows:

```bash
claude plugin details crystal-harness
```

Requires `python3` (the ownership hook and the helper scripts) and `node`/`npx`
(Playwright MCP, fetched on first use — only needed when you turn browser
verification on).

Optional: install [`openai/codex-plugin-cc`](https://github.com/openai/codex-plugin-cc)
and each round's diff also gets an independent review from a non-Claude model.

```
/plugin marketplace add openai/codex-plugin-cc
/plugin install codex@openai-codex
/codex:setup
```

The harness detects it by finding its `codex-companion.mjs` and asking it whether
it is ready — installed but unauthenticated counts as absent, because it cannot
review anything. Nothing breaks without it; see "Independent review" below.

### Updating

```bash
claude plugin marketplace update crystal-harness
claude plugin update crystal-harness@crystal-harness
claude plugin list --json | grep -A1 crystal-harness   # confirm "enabled": true
```

`plugin update` has been seen once (Claude Code 2.1.226) to install the new version
and leave it **disabled**. The symptom is every `/crystal-harness:*` command coming
back `Unknown command` in the next session. If `enabled` is false, run
`claude plugin enable crystal-harness`. Then restart.

## Quickstart

```
/crystal-harness:init
/crystal-harness:plan a pomodoro timer with session history
/crystal-harness:build
```

`/crystal-harness:init` shows you the detected config and waits. `/crystal-harness:plan`
shows you the spec and waits. `/crystal-harness:build` then runs the loop — sprints, then
the final assessment — and only stops when it needs a decision from you.

At any point:

```
/crystal-harness:status                # where is the run, and what has it cost
/crystal-harness:qa [n|final]          # grade the current tree, standalone
/crystal-harness:resume                # after a crash, /clear, or a new session
/crystal-harness:rules                 # turn defects that came back into approved project rules
```

> Plugin commands are namespaced: the real invocation is
> `/crystal-harness:init`, not `/init`.

## The `.harness/` artifact contract

Every agent-to-agent handoff is a file. No agent may depend on having seen another
agent's conversation.

```
.harness/
├── config.json          # harness configuration
├── spec.md              # planner output: the product specification
├── state.json           # run state
├── ledger.jsonl         # cost ledger, appended by a hook from agent transcripts
├── issues.jsonl         # every issue every validated verdict raised
├── rules.json           # project rules the human approved
├── handoff.md           # rolling context-reset handoff artifact
├── journal.md           # append-only human-readable log
├── artifacts/           # Playwright scratch output, browser mode only (gitignored)
├── sprints/01/
│   ├── contract.md      # generator proposes, evaluator accepts
│   ├── report.md        # generator's completion report + self-check
│   ├── codex-review.md  # independent review of the diff (when codex is installed)
│   ├── test-changes.json # what the round did to the tests, from a script
│   ├── rules-to-check.json # the project rules this round's diff triggers
│   ├── diagnosis/       # diagnose workflow only: evidence, hypotheses, the diagnosis
│   ├── lenses/          # parallel evaluation only: one verdict per lens
│   ├── qa.md            # the round's verdict, human-readable
│   ├── verdict.json     # the round's verdict, machine-readable
│   └── screenshots/
└── final/01/            # the end-of-run assessment, one directory per round
    ├── qa.md
    ├── verdict.json
    ├── report.md
    ├── codex-review.md
    ├── test-changes.json
    ├── lenses/
    └── screenshots/
```

Full definitions, both JSON Schemas, and the `handoff.md` template live in the
`crystal-harness:harness-protocol` skill.

`handoff.md` is the load-bearing artifact. It must be sufficient for a completely
fresh agent with zero prior context to continue: current goal, what is done *and
verified*, exactly where work stopped, known-broken things, decisions not to be
relitigated, **approaches already tried and rejected**, the files that matter, and
**one** next action. A handoff whose phase disagrees with `state.json` is a hard error
— `/crystal-harness:resume` refuses to continue until a human resolves it.

### The cost ledger

`.harness/ledger.jsonl` is an append-only record of what every agent cost: the
agent, phase, sprint and round, wall time, and tokens split into input, cache
write, cache read and output.

No model writes it. A `SubagentStop` hook runs `scripts/ledger.py` each time an
agent finishes — a subagent, a workflow agent or an agent-team teammate — and sums
the usage of **every API request in that agent's transcript**. That is a
deliberate change from recording the `subagent_tokens` figure the Agent tool
returns, which turned out to be the size of the agent's *final* request rather
than its run: measured on Claude Code 2.1.329, an agent that processed 64,685
tokens over three requests reported 21,689. For a long generator session the gap is
orders of magnitude, and the earlier ledger understated every run by it. (The
hook also has to wait a moment: Claude Code writes an agent's last response to the
transcript about 100 ms after `SubagentStop` fires, so the hook holds until that
message appears rather than summing a transcript that is one request short.)

This exists because the most important recurring judgement in this design is *is this
component still worth its cost*, and that cannot be answered from prose.
`/crystal-harness:status` prints `ledger.py report`: a per-agent and a per-round table, and the
evaluator's share of the run. Set `harness.costPerMTokUsd` and it adds estimated
dollars — as four per-category rates, because most tokens in a long session are
cache reads, which cost a fraction of fresh input.

Without this, the "what to strip" section below would be an opinion. With it, "the
evaluator found nothing in the last four sprints and cost 38% of the run" is a fact.

What it does not cover: the orchestrating session's own usage, and a codex
review's tokens (its wall time is recorded; its cost is not reported back). If a
transcript cannot be read the entry is written with `tokens: null` and the report
says how many calls are missing — a hole is reported, never estimated.

### Ownership, enforced

`hooks/hooks.json` registers one `PreToolUse` hook. It exists because each of the two
things it blocks silently destroys the design:

- `harness-generator` writing `qa.md`, `verdict.json`, or `screenshots/` under
  `sprints/NN/` or `final/NN/` — if the generator can write the verdict, every pass is
  self-awarded.
- `harness-evaluator` writing anything outside `.harness/` — if the evaluator can fix
  what it grades, it is the author of what it judges.
- **Either of them** writing `codex-review.md` or `test-changes.json` — the files
  both are blocked from. Each is evidence about the generator's diff, commissioned
  before the evaluator exists. A generator that can write one manufactures its own
  second opinion, or its own report on the tests it deleted; an evaluator that can
  write one edits the evidence it is about to cite.
- `harness-generator` writing anything under a round's `lenses/` — in parallel
  evaluation those files are the verdicts.
- **Either of them** writing `rules.json`, `issues.jsonl` or a round's
  `rules-to-check.json` — a generator that can edit the rules can delete the one
  that would catch it.
- `harness-investigator` writing anywhere but a round's `diagnosis/` directory —
  it diagnoses, and a diagnosis made on a tree it altered is of a different tree.

The same hook keeps both of them out of the orchestrator's files — `state.json`,
`handoff.md`, `journal.md`, `config.json`, `spec.md` — and out of `ledger.jsonl`:
an agent that can edit the ledger can make itself look cheap.

Everything else passes through untouched. There is no formatting hook and no
general logging hook; neither prevents a named failure, and scaffolding that
prevents nothing is the overhead this whole design argues against. The two other
hooks each answer one: `SessionStart` says a run already exists here, and
`SubagentStop` records the cost ledger above, because an entry a model has to
remember to write is an entry that goes missing.

How it behaves at the edges, and why:

- **It matches the agent by the last segment of `agent_type`.** Claude Code hands
  a plugin's agent to hooks as `crystal-harness:harness-generator`, not the bare
  name. Until 0.10.0 the guard compared the raw value against the bare names,
  matched nothing, and allowed every write — on every installed copy, with no
  symptom, while its own test suite (which used the bare names) passed. The tests
  now lead with the namespaced form.
- **It fails closed.** If the event cannot be parsed, or `python3` is missing, the
  guard exits 2 and the call is blocked with an explanation. A guard that waves
  through what it could not inspect is worse than no guard.
- **Paths are resolved with `realpath` and compared case-folded**, so neither
  `.harness/../src/App.tsx`, nor a symlink planted inside `.harness/`, nor
  `.HARNESS/sprints/01/VERDICT.JSON` on a case-insensitive filesystem gets past.
- **Bash coverage is deliberately asymmetric.** The generator is blocked from naming a
  verdict artifact in a shell command at all. The evaluator's Bash is *not* policed:
  it runs the project's install, build, test, dev, `curl` and `sqlite3` commands, and
  any redirection sniffer there would break more runs than it would catch. That
  residual gap is why the agent prompts state the rule as well.

The policy is in `scripts/guard_harness_artifacts.py`, invoked directly via `python3`
from `hooks/hooks.json` (python3 is assumed to be present).

## Configuration reference

`.harness/config.json`, written by `/crystal-harness:init` after you confirm it.

```jsonc
{
  "commands": {
    "install": "npm install",
    "dev": "npm run dev",
    "build": "npm run build",
    "test": "npm test",
    "backendDev": "uvicorn app.main:app --reload"   // null if there is no backend
  },
  "urls": {
    "app": "http://localhost:5173",
    "api": "http://localhost:8000"                  // null if there is no backend
  },
  "database": {                       // null if there is no backend
    "kind": "sqlite",
    "file": "./app.db",               // the evaluator reads this directly
    "url": null
  },
  "harness": {
    "useEvaluator": true,
    "useSprints": false,              // true → per-item contracts (v1 mode)
    "contextReset": true,             // false → keep one agent across phases
    "browserVerification": false,     // true → drive the UI with Playwright
    "codexReview": "auto",            // "auto" | true | false
    "teamBuild": false,               // true → first build split across builder teammates
    "maxBuilders": 3,                 // team build only: upper bound on builders
    "diagnoseRecurringIssues": false, // true → diagnose a blocking issue that came back
    "parallelEvaluation": false,      // true → one evaluator per lens, merged by a script
    "reproduceBlockingIssues": true,  // parallel evaluation only: re-try each blocking issue
    "maxSprints": 12,
    "maxRevisionsPerSprint": 5,
    "maxAcceptanceCriteria": 20,      // cap per sprint contract, enforced by validate_contract.py
    "maxFinalQaRounds": 5,
    "maxRunTokens": null,             // stop and ask once agents have used this many tokens
    "maxRunCostUsd": null,            // … or cost this much (needs costPerMTokUsd)
    "costPerMTokUsd": null            // {input, output, cacheWrite, cacheRead} in USD per MTok
                                      // → estimated $ in /crystal-harness:status
  }
}
```

On an existing repository, `/crystal-harness:init` detects `commands`, `urls` and `database`
from `package.json` scripts, the lockfile, framework configs, `pyproject.toml` and ORM
settings, then shows you each value annotated with where it came from. The defaults
apply only to a greenfield directory. **It never invents a dev command** — ambiguous
detection is a question, not a guess.

`useSprints` defaults to `false` because the generator and evaluator are pinned to
`claude-opus-5-5` (see below) regardless of this config — per-sprint decomposition
was a safety net for models that lost coherence over long sessions, and Opus 5.5
doesn't need it. Set it to `true` for a spec large or tightly-coupled enough that
reviewing it in small, evaluated increments beats one long build plus a converging
tail of final-QA rounds — there's no automatic signal for this, so ask if scope
looks large. `maxFinalQaRounds` defaults to 5, not 3, for the same reason: with
sprints off, defect-catching moves from many small per-sprint checks to fewer large
end-of-run ones, so the round budget needs more room to converge.

`browserVerification` defaults to `false`, and this is the change that makes a QA
round cheap. Driving the app through Playwright is the most expensive thing the
evaluator does by a wide margin, and most of what it catches is *visual*: the API,
the datastore and the project's own test suite already catch the defects that make
a build wrong. With it off the evaluator runs in `headless` mode and can still
return a pass — see "Verification modes" below for exactly what that pass covers
and what it does not. Turn it on for a run whose value is in the interface, and for
the final assessment of anything you intend to ship.

`codexReview` defaults to `"auto"`. See "Independent review".

`database` matters more than it looks: the evaluator confirms every write by reading
the datastore directly, so a run without it returns `persistenceVerified: false` on
everything that writes — and in headless mode, a project with neither a backend nor
a runnable test suite cannot reach a pass at all, because nothing would have been
executed.

Every `harness.*` flag can be turned off independently. That is deliberate; see
"What to strip".

### Which model each agent runs

Set in the agent frontmatter, not in `config.json` — this is the first thing to
revisit when a new model lands:

| Agent | Model | Effort | Why |
| --- | --- | --- | --- |
| `harness-planner` | `claude-opus-5-5` | `high` | Structured expansion of an idea into a spec |
| `harness-generator` | `claude-opus-5-5` | `xhigh` | Long-horizon coherence and hard implementation |
| `harness-evaluator` | `claude-opus-5-5` | `high` | Design and depth judgement, not just criterion matching |
| `harness-investigator` | `claude-opus-5-5` | `high` | Finding a cause the generator already missed once |

**Effort is the cost lever, not model tier.** All three agents run Opus 5.5; dropping
the generator from `xhigh` to `medium` moves cost far more than switching an agent to
a cheaper model such as Sonnet 5. Sweep effort against your own output before
reaching for a cheaper model.

## How the loop works

Per sprint, with `useSprints: true` (the smaller-increments alternative to the
default):

1. **Contract.** A fresh generator cuts the next sprint from the spec's feature
   ordering and writes `contract.md`: scope, out-of-scope, **pinned interfaces** (the
   routes, tables and testids the evaluator needs in order to test), and one or more
   acceptance criteria per item. A sprint aims for 10–15 criteria under a hard cap of
   `maxAcceptanceCriteria` (default 20, enforced by `validate_contract.py`), each
   naming a starting state, an action, and an observable result — in the browser,
   against the API, or in the datastore. Over the cap, scope moves to the next sprint.
2. **Review.** A fresh evaluator checks five things: is every criterion testable, does
   the sprint advance the spec, do the criteria cover *depth* rather than presence,
   is anything pinned that should have been left to the generator, and can criteria
   merge. Wording fixes are amendments the evaluator writes itself
   (`accepted-with-amendments`); only four kinds of finding send the contract back,
   and a revision edits just what they name. At most two rounds, then it escalates.
3. **Implement.** A fresh generator builds, commits at every checkpoint, runs the
   project's own build/typecheck/tests, fixes its own failures, and writes a
   `report.md` stating what is complete, what is partial, and what it did not attempt.
4. **Independent review.** If the `codex` plugin is available, the sprint's diff is
   reviewed by a non-Claude model and the result is written to `codex-review.md`,
   before the evaluator exists. Absent or unauthenticated codex → one line and the
   round carries on.
5. **Context reset.** `state.json` and `handoff.md` are written, then the evaluator is
   spawned as a new agent with no shared context. It is told file paths, never what
   the generator claims works.
6. **Evaluate.** The evaluator picks its verification mode from
   `browserVerification`. In `browser` mode it drives the app through Playwright —
   clicking, typing, dragging, resizing, tabbing, triggering empty and error states,
   reading console and network. In every mode it **confirms every write outside the
   UI** with `curl` and a direct datastore read, runs the project's test suite,
   exercises the API's failure paths, and reads the code — including
   `codex-review.md` — to locate the cause of each failure. It writes `qa.md`,
   `verdict.json`, and screenshots.
7. **Branch.** Pass → commit, next sprint. Fail → a fresh generator revises against
   the **blocking issues only**.
8. **Stop rather than loop.** The run halts and asks you when revisions are exhausted,
   when the same blocking issue recurs three times, when the evaluator runs degraded
   twice, or when `maxSprints` is reached.
9. **Final assessment.** When the feature ordering is exhausted, a fresh evaluator
   grades the whole product against `spec.md` with `SPEC-n` criteria it derives itself.
   Fail → a build round against the blocking issues, then re-assess. **The run is not
   done until this passes.**

**With `useSprints: false` (the default)**, steps 1–2 and 7–8 disappear: a single
fresh generator gets `spec.md` and builds the whole product in one long coherent
session, then the final assessment loop (step 9) runs rounds of QA and fixes to
completion or to `maxFinalQaRounds`. This is not hypothetical — a real run against a
10-item spec built the full product in one 72-minute generator session, then took
three final-QA rounds to reach a clean pass (round 1 found a real state-desync bug;
its fix caused two smaller regressions round 2 caught; round 3 confirmed all three
fixed with zero blocking issues, 39/39 criteria passing). Defect-catching that would
have happened per-sprint under `useSprints: true` happens in this end-of-run
convergence instead — which is why `maxFinalQaRounds` defaults higher (5) than a
sprint-mode final assessment would need.

### The rubric

Six dimensions, each 0–5 with written behavioral anchors:

| Dimension | Threshold | | Headless |
| --- | --- | --- | --- |
| **Product depth** | ≥ 4 | is the feature real, or a facade | graded |
| **Functionality** | ≥ 4 | works end to end, including edge and error paths | graded |
| **Code quality** | ≥ 3 | boundaries, duplication, error handling, real tests | graded |
| **Design quality** | ≥ 4 | coherent whole, distinct mood and identity | waived |
| **Originality** | ≥ 4 | deliberate decisions, not library defaults | waived |
| **Craft** | ≥ 3 | typography, spacing, states, contrast, responsiveness | waived |

**Any one dimension below a threshold that applies fails the sprint or the run, and
the thresholds are the weighting** — depth, design and originality sit at 4 while
craft and code quality sit at 3. There is no separate weighted score to compute or
store. The three waived in headless mode are the three that are judgements about a
rendered interface; with no browser they score `null`, which never satisfies a
threshold that does apply.

A criterion that was not exercised is `not_verified`, never `pass`, and
`not_verified` never counts toward a pass. Every blocking issue carries reproduction
steps, observed, expected, a screenshot, **and a cause** located in the code after the
failure was observed — never before.

Calibration examples — three or more per dimension, twenty in total, including a
polished artifact that scores low, a plain one that scores high, a build whose tests
all pass and whose depth is 2, and a codebase whose apparent discipline is the defect
— are in `skills/qa-rubric/references/calibration-examples.md`.

### Verification modes

Every verdict records the mode it was produced in, and the mode decides what a
`pass` is permitted to mean.

| mode | when | what it grades | can pass |
| --- | --- | --- | --- |
| `browser` | `browserVerification: true`, Playwright answered | all six dimensions | yes |
| `headless` | `browserVerification: false` | product depth, functionality, code quality | yes |
| `degraded` | `browserVerification: true`, Playwright did **not** answer | whatever it could reach | **no** |

The distinction between the last two is the whole design of the feature.
**Headless is verification nobody asked for; degraded is verification somebody
asked for and did not get.** A run never silently loses coverage it was configured
to have: two degraded rounds in a row stop the loop, and a headless round never
counts toward that, because nothing is broken.

In `headless` mode the evaluator does not touch Playwright. It installs, builds,
starts the app, runs the project's test suite, exercises every endpoint the round
touches including its failure paths, confirms each write in the datastore and after
a backend restart, and grades code quality by reading. Design, originality and
craft are scored `null` — not zero, and not guessed from the stylesheet — and their
thresholds are waived. Criteria that genuinely need a browser come back
`not_verified` with `browserOnly: true`, and `/crystal-harness:status` reports how
many, because that count is what tells you whether to re-run with the browser on.

Waiving half the rubric is only safe if the other half was earned, so a headless
pass additionally requires that something was actually executed (`apiVerified` or
`testsVerified`), that at least one criterion passed, and that **every**
`not_verified` criterion is a browser-only one — any other gap blocks the pass
exactly as it would in browser mode. `scripts/validate_verdict.py` enforces all of
it, along with the six thresholds themselves, and the orchestrator is told not to
interpret a rejected verdict generously.

What headless cannot catch, stated plainly: a control wired to nothing. The verb
exists, the endpoint works, the row changes — and the button that was supposed to
call it does not. That is the trade, and it is why the final assessment of anything
you intend to ship should run with `browserVerification: true`.

One thing the flag does *not* save: the plugin still registers Playwright MCP in
`.mcp.json`, so the server still starts with your session. A plugin's MCP block has
no conditionals. The saving is in the round — the evaluator's browser round-trips
are what the time goes on, not the server's startup.

### What the round did to the tests

The evaluator leans on the project's test suite twice. A failing suite is
conclusive, and on a re-check round a passing suite is what lets a criterion that
passed before be *carried* instead of verified again. But the generator writes
that suite, so it has a way to pass without being correct: delete the failing
test, skip it, or point the test command somewhere that always succeeds. None of
that turns the suite red.

Before any evaluator runs, `scripts/test_changes.py` reads the round's diff and
writes `test-changes.json` into the round directory: test files added, changed and
deleted, test cases removed, skip and `.only` markers added, a changed
`scripts.test` in `package.json`, and one flag — `weakened`. The evaluator reads it
before relying on the suite and treats an unjustified removal as a blocking issue.

The part that does not depend on anyone's judgement: when the report says
`weakened`, `validate_verdict.py --test-changes` rejects any verdict that carries a
pass from an earlier round. The whole round is verified afresh. The signal is
deliberately conservative — a legitimate refactor can trip it — because a false
alarm costs one fully verified round and a miss costs a pass nobody earned.

Like the codex review, neither agent may write the file; the guard blocks both.

### Project rules

A context reset means every evaluator starts a round knowing nothing about earlier
ones. That is the point of it — and it means a kind of defect missed once can be
missed again. Project rules are the memory that survives the reset, kept as data
and applied by code.

- After every validated verdict, `scripts/rules.py record` appends its issues to
  `.harness/issues.jsonl`. A verdict file is overwritten by the next round; the log
  is what remains.
- `/crystal-harness:rules` reads the log for what has **come back** — an issue seen
  in two or more rounds, a source file two or more distinct issues were traced to —
  drafts a rule for each candidate worth one, and stores only those you approve.
  One occurrence is an anecdote; a rule written from an anecdote is how a
  checklist fills with noise.
- A rule is a concrete `check` plus a **trigger that can be read from a diff**:
  path globs and keywords in added lines. A rule with no trigger is refused. Before
  each evaluation `rules.py match` writes the rules this round's diff triggers —
  usually none — to `rules-to-check.json`, so a round is asked only about what its
  own diff touches.
- The evaluator does each listed check in the product and lists the rule ids in
  the verdict. `validate_verdict.py --rules` rejects a verdict that leaves one
  out. A rule that does not hold is a blocking issue.

Rules are per project and live in `.harness/`, because a rule learned from one
codebase's mistakes is noise in another. Neither agent can edit the rules, the log,
or the list a round was handed.

### Diagnosing a recurring issue

Off by default (`diagnoseRecurringIssues: false`). The loop already tells a
generator on its second attempt that a patch has failed and it must change
approach, and stops for a human on the third. This adds something between: when a
blocking issue comes back once, the plugin's `diagnose` workflow finds out why
before the code is touched again.

A patch that fails usually fails because its cause was guessed, and the first
plausible explanation tends to be the one everyone keeps. So eight
`harness-investigator` agents are kept apart on purpose:

1. **Evidence** — one reproduces the issue and records what it sees, with no
   explanations. It is the only one allowed to run the application until the end.
2. **Hypotheses** — three argue the best case for a different *kind* of cause —
   the data is wrong (`state`), the control flow is wrong (`wiring`), the report is
   wrong (`premise`) — without seeing each other's work. Each must say why every
   fix already tried would have failed, and name an experiment that could sink it.
3. **Refutation** — three more each try to break one hypothesis.
4. **Diagnosis** — one runs the experiments of what survived and writes the root
   cause, what a fix has to change, and how to tell it worked, with a confidence
   it is told never to round up.

Investigators read and run. The guard confines their writes to the round's
`diagnosis/` directory; the fix is still the generator's, which is handed the
diagnosis and nothing else. It is the most expensive single step in the harness,
and it runs only on an issue that has already cost a revision.

### Inherited defects and flaky tests

Two smaller rules, both about not being misled by where a failure appears to come
from.

`/crystal-harness:init` records the commit a run started from. A defect whose cause
is unchanged since then is marked `preExisting` — inherited, not a regression. The
mark is not a discount: the issue blocks exactly when it would otherwise, which in
a final assessment means whenever the spec promises the behaviour. It changes how
the defect is read and fixed, not whether it counts.

A test that fails some of the time has a cause. The generator may not add a sleep,
a retry or a longer timeout to make it pass, and the evaluator runs the suite once
— a suite that needs a second run is failing. The test-change report lists every
sleep and retry a round added to its tests, so the evaluator sees each.

### Team build

Off by default (`teamBuild: false`). When on, the first build of a round is done by
up to `maxBuilders` generators working at the same time, each an agent-team
teammate named `builder-<name>`. Two generators on one working tree collide —
that is why the harness otherwise runs one at a time — so a team build happens
only under a **split plan**, and the parts of that agreement a script can check
are checked rather than asked for.

1. A generator, alone, writes `split.json`: for each builder a `scope` and the
   paths it `owns`, plus the **pinned interfaces** between them — routes and
   payload shapes, table names, exit codes — so nobody has to wait for anybody
   else's code to exist. If the work has no real seam it writes a one-builder
   plan, and the build runs as a normal single generator.
2. `scripts/team_build.py validate` rejects a plan in which two builders' paths
   overlap, a path uses a wildcard it cannot reason about, or two builders have
   nothing pinned between them.
3. The builders run. The ownership guard holds each to its own paths: a write
   anywhere else is denied, and the builder is told to ask the owner. A builder
   cannot edit the plan that bounds it.
4. Builders commit through `team_build.py commit`, which stages exactly the
   committing builder's paths under a lock. `git add`, `commit`, `stash`,
   `reset`, `checkout` and their relatives are denied to builders, because each
   acts on the whole tree while the others are mid-edit in it.
5. When they stop, `team_build.py check` lists what the plan does not allow —
   uncommitted work, a changed path nobody owns, a missing report — addressed to
   the builder who can fix it. Then `team_build.py report` joins the builders'
   own reports into the `report.md` the evaluator reads.

Fixes after a failed QA round are not split. They work a short list of blocking
issues and go to one generator, as always. Builders are never reused across
rounds, so the harness's context-reset rule holds.

One thing had to be closed for this to be safe. Hooks see a teammate under the
**name** the lead gave it, not the agent type it was spawned from, so the guard —
which recognises a role by agent type — would not see a generator started under
an arbitrary name. A second hook therefore decides who may be named what: a
`harness-generator` only `builder-<x>` for a builder `x` in the active plan, and
a `harness-evaluator` not at all. That hook matters even with `teamBuild` off,
for anyone who has agent teams enabled.

It needs agent teams (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`), which are
experimental and work only in an interactive session. Without them the build
says so in one line and uses a single generator.

### Parallel evaluation

Off by default (`parallelEvaluation: false`). When on, a round is graded by one
`harness-evaluator` per **lens** instead of one evaluator doing everything:

| Lens | Does | Scores |
| --- | --- | --- |
| `tests` | builds, runs the suite, checks `test-changes.json` | — |
| `api` | drives the API and reads the datastore; owns the criteria when there is no browser | product depth, functionality |
| `screen` | drives the interface with Playwright; exists only with `browserVerification: true`, and then owns the criteria | product depth, functionality, design, originality, craft |
| `code` | reads the diff and `codex-review.md` | code quality |

The plugin's `evaluate` workflow runs them: `code` alongside `tests` → `api` →
`screen`. The lenses that run the application go one after another on purpose —
they share its ports and its datastore, and an empty-state check that fails because
another lens just created a record is a false failure. So this mode buys focus and
a second look more than wall-clock time, and it costs more agents per round.

No model merges the results. Each lens writes its own verdict file under the
round's `lenses/` directory, and `scripts/merge_verdicts.py` produces the round's
`verdict.json` and `qa.md` by rules that can only be stricter than the parts:

- a dimension two lenses both score takes the **lower** score;
- every blocking issue from every lens is kept;
- the round passes only if **every** lens passed its own slice;
- if a lens is missing, malformed, self-contradictory, or stamped with another
  round or commit, there is **no verdict** — the script exits 2 and writes nothing.

The last rule is the same one `degraded` mode applies to a missing browser: a round
that measured less than it was configured to must not read as a verdict.

With `reproduceBlockingIssues: true`, the workflow then hands each blocking issue
to one more fresh evaluator that gets only the reproduction steps and the expected
behaviour — not the lens's notes and not the cause — and records on the issue
whether it saw the same failure. This is an annotation, not a filter: an issue
nobody could reproduce stays blocking and the round still fails. What changes is
the stopping rule — if the generator cannot reproduce it either, that is two
independent failures to reproduce, and the loop asks a human instead of spending a
second revision on it.

It is off by default for the reason every other default here has: there is no
measurement yet of what the lenses find that a single evaluator misses. Each lens
and each reproduction is its own ledger entry, so one run with it on and one with
it off, against the same spec, is the comparison that would justify the cost.

### Budget

`maxRunTokens` and `maxRunCostUsd` cap what a run may spend on agents, as counted by
the ledger. The orchestrator checks before every spawn (`ledger.py budget`) and
stops to ask when a cap is reached. Because a stopping rule stated only in prose is
a rule that gets skipped, a `PreToolUse` hook makes it a guarantee: once a cap is
reached it denies starting any harness agent or the `evaluate` workflow, and only a
human editing the cap in `config.json` lifts it.

A cost cap needs prices. `maxRunCostUsd` with no `costPerMTokUsd` is reported as
unenforceable and stops the run — a cap somebody set that silently does nothing is
worse than no cap. The hook itself fails open: it is a cost control, not an
ownership boundary, so an error in it never blocks work.

### Independent review

When the [`codex`](https://github.com/openai/codex-plugin-cc) plugin is installed
and authenticated, the orchestrator runs a review of each round's diff after the
generator finishes and before the evaluator is spawned, writing `codex-review.md`
into the round directory.

This exists because the evaluator, for all its separation from the generator, is
still a Claude model reading a diff a Claude model wrote. A second opinion from a
different vendor's model costs one CLI call and shares none of that prior.

It is deliberately **not** a gate. The evaluator reads the file as one input to
Code quality, treats every finding as a claim to confirm against the code, and
records in `qa.md` which it confirmed and which it rejected. A finding it could not
confirm never becomes a blocking issue, and nothing in the file can establish that
a feature works — it is more reading, and reading is not verification. The verdict
stays where it was.

Detection is operational: the harness finds the plugin's `codex-companion.mjs` and
asks it whether it is ready. Installed but not logged in counts as absent. On
`"auto"` an absent codex is a one-line note and the round continues; set
`codexReview: true` if you would rather hear about it, or `false` to never run it.
Its wall time is recorded in the ledger like any other component, so it can be
judged and stripped on evidence rather than taste.

## Resuming

The run is designed to survive `/clear`, a crash, and a new machine.

```
/crystal-harness:resume
```

It reads `state.json` → `handoff.md` → `config.json` → `spec.md` → the current round's
artifacts, in that order, and refuses to continue on any inconsistency: missing
handoff, handoff phase disagreeing with state, a `lastGoodCommit` that is not an
ancestor of `HEAD`, or `phase: "blocked"`. It prints a reconstruction summary —
including whether a final assessment has passed — and waits for you to choose.

`journal.md` is deliberately *not* used to reconstruct state. It is a human log and
contains superseded decisions.

## What to strip as models improve

Every component here encodes an assumption about what the model cannot do alone, and
those assumptions expire. In the source post's own v2, the sprint construct became
unnecessary once the model could sustain 2+ hour coherent sessions — this plugin's
generator and evaluator are pinned to `claude-opus-5-5`, a model in that class, so the
default configuration already reflects that stripping. What follows is what's already
stripped, what still isn't, and the evidence for each — not a to-do list.

**Use the ledger, not your impression.** `/crystal-harness:status` gives you tokens, wall time
and per-agent share; the per-round scores tell you whether rounds still buy anything.
When a future model lands, remove one component at a time and compare the next run's
final assessment against the last, the same way the change below was made.

**1. Sprints — already off by default (`useSprints: false`).** Sprints exist to bound
a session to what the model can hold coherently; Opus 5.5 doesn't need that bound. This
isn't a guess: a real run against a 10-item spec built the whole product in one
72-minute session and reached a clean final-QA pass in three rounds — cheaper and
faster than the sprint-mode equivalent for the same spec (one sprint alone ran
$20.13; the full v2 run, all 10 items to a pass, ran $44.18). Set `useSprints: true`
when a spec is large or tightly-coupled enough that small, reviewed-as-you-go
increments beat one long build plus a converging tail of final-QA rounds — there is
no automatic signal for this, so ask the human if scope looks large. If you're
evaluating a *newer* model than Opus 5.5 for the generator role, this is still the
first thing to re-check, the same way it was checked here.

**2. Browser verification — already off by default (`browserVerification: false`).**
This one is not a model-capability bet, it is a cost one, and it is the only entry
here where stripping *removes* coverage on purpose rather than because the
coverage stopped being needed. The browser is the most expensive instrument in the
harness and it is the only one that can catch a control wired to nothing; the API,
the datastore and the test suite catch everything that makes a build wrong rather
than wrong-looking. Off by default because most rounds are the second kind. *Signal
to turn it back on:* the product's value is in the interface, a round's failures
are clustering in surfaces rather than endpoints, or you are about to ship — the
final assessment of anything real should see the interface at least once.

**3. The evaluator on tasks the model already handles solo — `useEvaluator: false`.**
Still on by default, and the evidence from the same run says it should stay on: the
generator's own self-check pronounced its first fix correct, and only the evaluator
caught that the fix had silently caused two new regressions. That is the exact
failure this component exists to catch, and it fired on Opus 5, not just on older
models. **It is worth its cost only when the task sits beyond what the model does
reliably alone** — the same run showed that boundary hasn't moved past the evaluator
yet, at least for stateful, multi-surface UIs. *Signal it has:* the ledger shows the
evaluator taking a large share while several consecutive verdicts come back `pass`
with no blocking issues, and the non-blocking issues it raises were already in the
generator's report.

**4. The planner.** Load-bearing longer than the other two, because under-scoping is
a failure of what the prompt asked for, not of model capability. There is no flag —
stop running `/crystal-harness:plan` and write `spec.md` yourself. *Signal:* you barely edit
the spec, and a generator given the raw one-line idea produces the same feature list
the planner would have.

**5. The final assessment — keep it longest.** It is the only check graded against
criteria the generator never helped write. Its cost is one evaluator pass per run in
sprint mode; with sprints off it is however many rounds `maxFinalQaRounds` allows —
the real run above needed three.

**A caveat on all of this: n = 1.** One spec, one run, one model. Re-run this kind of
comparison — not just re-read this section — before trusting a default this plugin
ships to change your own project's behavior.

**6. The artifact protocol — keep it.** `handoff.md`, `state.json` and the file-based
contract are not compensating for a model weakness. They are how a run survives a
crash, a `/clear`, a new session, and a different machine. That does not expire with
context length.

**Diagnosis — off, and probably the last of these to earn a default.** *Signal to
turn it on:* runs that end `blocked` on the same issue three times, where the
second and third fixes were variations of the first. *Signal it is not paying:*
its diagnoses come back `low` confidence, or name the cause the evaluator had
already written in the verdict.

**Team build — not on yet either, for the same reason.** *Signal to turn it on:*
the product has a real seam and the single build is the long pole of the run.
*Signal to turn it back off:* the ledger shows the builders together costing well
over what one generator did on a comparable spec, or the evaluator's first round
keeps finding defects at the boundary the split plan drew.

**Parallel evaluation — not on yet, and the evidence decides.** It and team build
are the components here that were added rather than waiting to be stripped, so
they ship off.
*Signal to turn it on:* a single evaluator's rounds keep missing defects that a
later round or a human finds in one specific area — the API surface, the tests,
the code. *Signal to turn it back off:* the ledger shows the lenses costing a
multiple of a single evaluator while the merged verdicts match what the single
evaluator returned on the same build.

**7. The rubric — keep it, and keep re-calibrating it.** What expires is the
calibration, not the mechanism: as baseline output quality rises, a 3 on Originality
that was defensible becomes a 2. Re-read `calibration-examples.md` against your own
recent output periodically and move the anchors.

The honest summary: the parts that compensate for model limitations should be deleted
as those limitations disappear. The parts that encode *process* — files as the unit of
memory, a grader that is not the author — should not.

## Where this deviates from the source post, and why

- **Functionality is thresholded at 4, alongside design and originality.** The post
  emphasized design quality and originality *over* craft and functionality. That
  weighting suits a pure frontend-design loop; for a full-stack build, an app that
  does not work is not gradeable on anything else. Emphasis is instead expressed by
  craft and code quality sitting at 3.
- **Six dimensions rather than four.** The post used one four-dimension rubric for
  frontend design (design quality, originality, craft, functionality) and a different
  four for full-stack (product depth, functionality, visual design, code quality).
  This harness targets full-stack builds and carries the union, because dropping
  either set loses a failure class the post explicitly reported catching.
- **Revision budget is bounded.** The post's frontend loop ran 5–15 iterations and its
  best result arrived on the tenth. This harness defaults to 5 per sprint and 5 final
  rounds, and escalates early when an issue recurs without a change of approach. That
  trades some of the post's late-iteration upside for not burning a run on a stuck
  loop — raise `maxRevisionsPerSprint` if you want the post's behaviour.

## Layout

```
../.claude-plugin/marketplace.json   # repo-root marketplace catalog, points here via "./crystal-harness"
crystal-harness/
├── .claude-plugin/plugin.json
├── agents/{harness-planner, harness-generator, harness-evaluator, harness-investigator}.md
├── commands/{init,plan,build,qa,resume,status,rules}.md
├── skills/
│   ├── harness-protocol/SKILL.md        # .harness/ contract, both JSON Schemas, handoff template, ledger
│   ├── evaluation-lenses/SKILL.md       # the four lenses, the lens verdict file, reproducing an issue
│   ├── team-build/SKILL.md              # the split plan, and the rules a builder teammate works under
│   ├── sprint-contract/SKILL.md         # pinned interfaces and testable acceptance criteria
│   └── qa-rubric/
│       ├── SKILL.md                     # six dimensions, anchors, thresholds, verdict.json schema
│       └── references/calibration-examples.md
├── workflows/
│   ├── evaluate.js                      # parallel evaluation: one evaluator per lens, then reproductions
│   └── diagnose.js                      # a recurring issue: evidence, three hypotheses, refutations, diagnosis
├── hooks/hooks.json
├── scripts/
│   ├── guard_harness_artifacts.py       # the ownership policy the PreToolUse hook runs
│   ├── inject_harness_context.py        # SessionStart notice when a run exists here
│   ├── ledger.py                        # cost ledger: SubagentStop hook, codex append, report, budget gate
│   ├── test_changes.py                  # what a round did to the tests: deleted, skipped, re-pointed
│   ├── merge_verdicts.py                # lens verdicts → one verdict.json + qa.md, or no verdict at all
│   ├── team_build.py                    # split plan: validate, activate, per-builder commit, check, naming gate
│   ├── rules.py                         # issue log, rule candidates, approved rules, which rules a diff triggers
│   ├── validate_verdict.py              # verdict.json schema + what a pass may mean per mode
│   ├── validate_contract.py             # contract.md criterion cap, scope size, id integrity
│   ├── codex_review.py                  # find the codex plugin, review the diff, write codex-review.md
│   ├── test_guard.py
│   ├── test_validate_verdict.py
│   ├── test_validate_contract.py
│   ├── test_codex_review.py
│   ├── test_ledger.py
│   ├── test_test_changes.py
│   ├── test_merge_verdicts.py
│   ├── test_team_build.py
│   └── test_rules.py
├── .mcp.json                            # Playwright MCP
└── README.md
```

## License

MIT.

## Tests

```bash
python3 crystal-harness/scripts/test_guard.py
python3 crystal-harness/scripts/test_validate_verdict.py
python3 crystal-harness/scripts/test_validate_contract.py
python3 crystal-harness/scripts/test_codex_review.py
python3 crystal-harness/scripts/test_ledger.py
python3 crystal-harness/scripts/test_test_changes.py
python3 crystal-harness/scripts/test_merge_verdicts.py
python3 crystal-harness/scripts/test_team_build.py
python3 crystal-harness/scripts/test_rules.py
```

No framework and no dependencies.

**110 cases over the ownership guard**: the plugin-namespaced `agent_type` Claude
Code actually sends, both denial policies, the `codex-review.md`
and `test-changes.json` rows that deny both agents, the lens files, the cost ledger, a builder teammate held to its own paths and kept off tree-wide git commands, an investigator held to its findings, the project rules, both escape routes (`..` traversal and a symlink
planted inside `.harness/`), case-folding, the Bash path, every legitimate write,
and both fail-closed paths.

**61 cases over the verdict validator**: the schema, the rule that a weakened test
suite voids every carried pass, the rule that every triggered project rule is accounted for, and every rule about what a
`pass` may mean in each verification mode — the three dimensions headless must
leave `null`, the conditions a headless pass has to buy that waiver with, the
thresholds themselves, and the fact that a degraded round never passes.

**14 cases over the codex review helper**, against a fake companion so they need
no Codex CLI: the exit-code contract in both directions. A run only counts as a
review when the response carries a codex block, a status of exactly 0, and actual
review content — a failed, empty, unparseable or version-skewed response writes
nothing and exits 1 — and every non-zero outcome clears a leftover file from an
earlier round before it can be read as this round's evidence.

**15 cases over the contract validator**: the criterion cap at, over and under the
default and a configured value, missing or empty sections, duplicate ids, the 3–7
scope range, fenced examples not being counted, and an amendment or revision note
that references an id the contract does not have.

**24 cases over the test-change report**: each way of thinning a suite (a deleted
file, a removed case, a skip, an `.only`, an `xfail`, a re-pointed or removed test
command, a test renamed out of the test tree) and each legitimate change that must
not raise the alarm.

**47 cases over the verdict merge**: the lower of two scores standing, every issue
kept, one failing lens failing the round, a reproduction result annotating but
never removing an issue — and twenty-odd ways of refusing to merge at all, from a
missing lens to one that graded a different commit.

**55 cases over the team build**: every way two builders' paths can overlap, the
path forms a plan may not use, a commit that takes exactly one builder's files and
leaves another's untouched, the leftovers `check` reports and to whom, and the
gate that decides which agent may carry which name.

**29 cases over the project rules**: a round recorded twice not doubling the log,
what counts as having come back, a rule with no trigger or a trigger that matches
everything being refused, and the matcher — including a rule's own keyword in
`.harness/rules.json` not triggering that rule the moment it is added.

**73 cases over the cost ledger**: usage summed across every request rather than
the last, a final response that reaches the transcript after the hook has started
still being counted, a streamed response counted once, a re-stopped agent's snapshot
superseding rather than adding, the hook exiting 0 on every malformed input while
recording an unreadable transcript as `null` rather than zero, per-category
pricing, entries from a pre-0.10.0 `state.json` kept out of token totals, and the budget
caps with the hook that enforces them.

These nine are tested and the prompts are not, because these nine fail
*silently*. If the rule matcher stops triggering a rule, the evaluator is never
asked the question the rule exists to ask. If the split-plan validator starts accepting overlapping paths, the
build still completes — with one builder's work replaced by another's. If the test-change report stops noticing a deleted test, the suite
goes back to vouching for itself. If the merge turns lenient, a round that
measured less than it claims reads as a pass. If the ledger stops recording, or double-counts, the table still
looks plausible and every strip decision is made on it. If the contract validator stops rejecting, contracts drift back past
the cap and every phase of the run gets slower and costlier. If the guard stops denying, the harness keeps running and every verdict
becomes self-awarded. If the validator stops rejecting, a round that measured
nothing reads as a pass. If the review helper lies with its exit code, a round
records a second opinion it never got, or cites one about a different diff. None
has a visible symptom; a prompt that drifts produces output somebody reads.
