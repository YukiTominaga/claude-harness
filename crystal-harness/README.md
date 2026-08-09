# crystal-harness

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

## Install

```bash
git clone <this repo>
claude
```

Then, inside Claude Code:

```
/plugin marketplace add /absolute/path/to/claude-harness/crystal-harness
/plugin install crystal-harness@crystal-harness-local
```

Restart Claude Code. Or, for a throwaway trial without installing:

```bash
claude --plugin-dir /absolute/path/to/claude-harness/crystal-harness
```

Verify — the inventory should show 3 agents, 1 MCP server, 1 hook, and 9 skills (the
six commands are counted as skills alongside the three reference skills):

```bash
claude plugin details crystal-harness
```

Requires `node`/`npx` (Playwright MCP is fetched on first use) and `python3` (the
ownership hook).

### Updating

```bash
claude plugin marketplace update crystal-harness-local
claude plugin update crystal-harness@crystal-harness-local
claude plugin enable crystal-harness          # <- do not skip this
```

Observed on Claude Code 2.1.226: `plugin update` installs the new version and leaves
it **disabled**. The symptom is that every `/crystal-harness:*` command comes back
`Unknown command` in the next session while `plugin list --json` shows the new version
with `"enabled": false`. Re-enable, then restart.

## Quickstart

```
/crystal-harness:harness-init
/crystal-harness:harness-plan a pomodoro timer with session history
/crystal-harness:harness-build
```

`harness-init` shows you the detected config and waits. `harness-plan` shows you the
spec and waits. `harness-build` then runs the loop — sprints, then the final
assessment — and only stops when it needs a decision from you.

At any point:

```
/crystal-harness:harness-status                # where is the run, and what has it cost
/crystal-harness:harness-qa [n|final]          # grade the current tree, standalone
/crystal-harness:harness-resume                # after a crash, /clear, or a new session
```

> Plugin commands are namespaced: the real invocation is
> `/crystal-harness:harness-init`, not `/harness-init`.

## The `.harness/` artifact contract

Every agent-to-agent handoff is a file. No agent may depend on having seen another
agent's conversation.

```
.harness/
├── config.json          # harness configuration
├── spec.md              # planner output: the product specification
├── state.json           # run state + the cost ledger
├── handoff.md           # rolling context-reset handoff artifact
├── journal.md           # append-only human-readable log
├── artifacts/           # Playwright scratch output (gitignored)
├── sprints/01/
│   ├── contract.md      # generator proposes, evaluator accepts
│   ├── report.md        # generator's completion report + self-check
│   ├── qa.md            # evaluator verdict, human-readable
│   ├── verdict.json     # evaluator verdict, machine-readable
│   └── screenshots/
└── final/01/            # end-of-run assessment, one directory per round
    ├── qa.md
    ├── verdict.json
    ├── report.md
    └── screenshots/
```

Full definitions, both JSON Schemas, and the `handoff.md` template live in the
`crystal-harness:harness-protocol` skill.

`handoff.md` is the load-bearing artifact. It must be sufficient for a completely
fresh agent with zero prior context to continue: current goal, what is done *and
verified*, exactly where work stopped, known-broken things, decisions not to be
relitigated, **approaches already tried and rejected**, the files that matter, and
**one** next action. A handoff whose phase disagrees with `state.json` is a hard error
— `harness-resume` refuses to continue until a human resolves it.

### The cost ledger

`state.json` carries an append-only `ledger`: one entry per subagent call, with the
agent, phase, wall time and token count reported by the Agent tool.

This exists because the most important recurring judgement in this design is *is this
component still worth its cost*, and that cannot be answered from prose.
`/harness-status` aggregates it into a per-agent table and names the evaluator's share
of the run. Set `harness.costPerMTokUsd` and it converts to estimated dollars.

Without this, the "what to strip" section below would be an opinion. With it, "the
evaluator found nothing in the last four sprints and cost 38% of the run" is a fact.

### Ownership, enforced

`hooks/hooks.json` registers one `PreToolUse` hook. It exists because each of the two
things it blocks silently destroys the design:

- `harness-generator` writing `qa.md`, `verdict.json`, or `screenshots/` under
  `sprints/NN/` or `final/NN/` — if the generator can write the verdict, every pass is
  self-awarded.
- `harness-evaluator` writing anything outside `.harness/` — if the evaluator can fix
  what it grades, it is the author of what it judges.

Everything else passes through untouched. There is no logging hook and no formatting
hook; neither prevents a named failure, and scaffolding that prevents nothing is the
overhead this whole design argues against.

How it behaves at the edges, and why:

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

`scripts/guard-harness-artifacts.sh` is a thin wrapper whose only job is turning a
missing interpreter into a loud block; the policy is in
`scripts/guard_harness_artifacts.py`.

## Configuration reference

`.harness/config.json`, written by `harness-init` after you confirm it.

```jsonc
{
  "stack": {
    "frontend": "react-vite-ts",
    "backend": "fastapi",
    "database": "sqlite"              // or "postgres"
  },
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
    "usePlanner": true,
    "useEvaluator": true,
    "useSprints": true,               // false → one long coherent session (v2 mode)
    "maxSprints": 12,
    "maxRevisionsPerSprint": 5,
    "maxFinalQaRounds": 3,
    "contextResetPolicy": "per-sprint", // "per-sprint" | "per-phase" | "never"
    "costPerMTokUsd": null            // set to show estimated $ in harness-status
  }
}
```

On an existing repository, `harness-init` detects `commands`, `urls` and `database`
from `package.json` scripts, the lockfile, framework configs, `pyproject.toml` and ORM
settings, then shows you each value annotated with where it came from. The defaults
apply only to a greenfield directory. **It never invents a dev command** — ambiguous
detection is a question, not a guess.

`database` matters more than it looks: the evaluator confirms every write by reading
the datastore directly, so a run without it returns `persistenceVerified: false` on
everything that writes.

Every `harness.*` flag can be turned off independently. That is deliberate; see
"What to strip".

## How the loop works

Per sprint, with `useSprints: true`:

1. **Contract.** A fresh generator cuts the next sprint from the spec's feature
   ordering and writes `contract.md`: scope, out-of-scope, **pinned interfaces** (the
   routes, tables and testids the evaluator needs in order to test), and one or more
   acceptance criteria per item. A substantial sprint has 15–30 criteria, each naming
   a starting state, an action, and an observable result — in the browser, against the
   API, or in the datastore.
2. **Review.** A fresh evaluator checks four things: is every criterion testable, does
   the sprint advance the spec, do the criteria cover *depth* rather than presence,
   and is anything pinned that should have been left to the generator. At most two
   rounds, then it escalates.
3. **Implement.** A fresh generator builds, commits at every checkpoint, runs the
   project's own build/typecheck/tests, fixes its own failures, and writes a
   `report.md` stating what is complete, what is partial, and what it did not attempt.
4. **Context reset.** `state.json` and `handoff.md` are written, then the evaluator is
   spawned as a new agent with no shared context. It is told file paths, never what
   the generator claims works.
5. **Evaluate.** The evaluator drives the app through Playwright — clicking, typing,
   dragging, resizing, tabbing, triggering empty and error states, reading console and
   network — **then confirms every write outside the UI** with `curl` and a direct
   datastore read, exercises the API's failure paths, and reads the code to locate the
   cause of each failure. It writes `qa.md`, `verdict.json`, and screenshots.
6. **Branch.** Pass → commit, next sprint. Fail → a fresh generator revises against
   the **blocking issues only**.
7. **Stop rather than loop.** The run halts and asks you when revisions are exhausted,
   when an issue recurs three times, when it recurs twice *with no change of approach*,
   when the evaluator runs degraded twice, or when `maxSprints` is reached.
8. **Final assessment.** When the feature ordering is exhausted, a fresh evaluator
   grades the whole product against `spec.md` with `SPEC-n` criteria it derives itself.
   Fail → a build round against the blocking issues, then re-assess. **The run is not
   done until this passes.**

With `useSprints: false` (v2 mode) steps 1–2 and 6–7 disappear: the generator gets
`spec.md` and runs one long coherent session, then the final assessment loop runs
rounds of QA and fixes to completion.

### The rubric

Six dimensions, each 0–5 with written behavioral anchors:

| Dimension | Threshold | Weight | |
| --- | --- | --- | --- |
| **Product depth** | ≥ 4 | 3 | is the feature real, or a facade |
| **Design quality** | ≥ 4 | 3 | coherent whole, distinct mood and identity |
| **Originality** | ≥ 4 | 3 | deliberate decisions, not library defaults |
| **Functionality** | ≥ 4 | 2 | works end to end, including edge and error paths |
| **Craft** | ≥ 3 | 1 | typography, spacing, states, contrast, responsiveness |
| **Code quality** | ≥ 3 | 1 | boundaries, duplication, error handling, real tests |

**Any one dimension below its threshold fails the sprint or the run.** The emphasis on
depth, design and originality is expressed by their thresholds sitting at 4 while
craft and code quality sit at 3. `weightedScore` is reported per round as a trend
signal — it is not a gate.

A criterion that was not exercised is `not_verified`, never `pass`, and
`not_verified` never counts toward a pass. Every blocking issue carries reproduction
steps, observed, expected, a screenshot, **and a cause** located in the code after the
failure was observed — never before.

Calibration examples — three or more per dimension, twenty in total, including a
polished artifact that scores low, a plain one that scores high, a build whose tests
all pass and whose depth is 2, and a codebase whose apparent discipline is the defect
— are in `skills/qa-rubric/references/calibration-examples.md`.

### If Playwright is unavailable

The evaluator degrades to a clearly labelled reduced check: build succeeds, dev server
starts, app responds, tests pass, API behaves under `curl`, datastore contains what a
write should have produced, code quality gradeable. Every visual and interactive
criterion is marked `not_verified`, unassessable dimensions are `null`, and a degraded
run **never** returns `pass`. Two degraded runs in a row stop the loop.

## Resuming

The run is designed to survive `/clear`, a crash, and a new machine.

```
/crystal-harness:harness-resume
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
unnecessary once the model could sustain 2+ hour coherent sessions.

**Use the ledger, not your impression.** `/harness-status` gives you tokens, wall time
and per-agent share; the `weightedScore` trend tells you whether rounds still buy
anything. Remove one component at a time and compare the next run's final assessment
against the last. Ranked from least to most load-bearing:

**1. Sprints — `useSprints: false`.** The weakest component and the first to go.
Sprints exist to bound a session to what the model can hold coherently. *Signal:*
contracts get accepted on the first round every time, sprint boundaries start looking
arbitrary, and sprint N spends its first commits undoing a seam that only existed
because sprint N-1 had to end somewhere. Then switch to v2 mode; the final assessment
loop is unchanged.

**2. The evaluator on tasks the model already handles solo — `useEvaluator: false`.**
The most expensive component: a second full agent, a browser, and a serialized round
trip per round. **It is worth its cost only when the task sits beyond what the model
does reliably alone.** *Signal:* the ledger shows the evaluator taking a large share
while several consecutive verdicts come back `pass` with no blocking issues, and the
non-blocking issues it does raise were already in the generator's report. Keep it for
anything visual, interactive, or genuinely novel. Even then, consider keeping only the
final assessment and dropping per-sprint QA — that is the cheapest configuration that
still has an independent grader.

**3. The planner — `usePlanner: false`.** Load-bearing longer than the other two,
because under-scoping is a failure of what the prompt asked for, not of model
capability. *Signal:* you barely edit the spec, and a generator given the raw one-line
idea produces the same feature list the planner would have.

**4. The final assessment — keep it longest.** It is the only check graded against
criteria the generator never helped write. Its cost is one evaluator pass per run.

**5. The artifact protocol — keep it.** `handoff.md`, `state.json` and the file-based
contract are not compensating for a model weakness. They are how a run survives a
crash, a `/clear`, a new session, and a different machine. That does not expire with
context length.

**6. The rubric — keep it, and keep re-calibrating it.** What expires is the
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
  best result arrived on the tenth. This harness defaults to 5 per sprint and 3 final
  rounds, and escalates early when an issue recurs without a change of approach. That
  trades some of the post's late-iteration upside for not burning a run on a stuck
  loop — raise `maxRevisionsPerSprint` if you want the post's behaviour.

## Layout

```
crystal-harness/
├── .claude-plugin/{plugin.json, marketplace.json}
├── agents/{harness-planner, harness-generator, harness-evaluator}.md
├── commands/harness-{init,plan,build,qa,resume,status}.md
├── skills/
│   ├── harness-protocol/SKILL.md        # .harness/ contract, both JSON Schemas, handoff template, ledger
│   ├── sprint-contract/SKILL.md         # pinned interfaces and testable acceptance criteria
│   └── qa-rubric/
│       ├── SKILL.md                     # six dimensions, anchors, thresholds, verdict.json schema
│       └── references/calibration-examples.md
├── hooks/hooks.json
├── scripts/{guard-harness-artifacts.sh, guard_harness_artifacts.py}
├── .mcp.json                            # Playwright MCP
└── README.md
```

## License

MIT.

## Tests

```bash
python3 crystal-harness/scripts/test_guard.py
```

21 cases over the ownership guard: both denial policies, both escape routes
(`..` traversal and a symlink planted inside `.harness/`), case-folding, the Bash
path, every legitimate write, and both fail-closed paths. No framework and no
dependencies.

The guard is the only executable code in this plugin, and its failure mode is
silent — if it stops denying, the harness keeps running and every verdict becomes
self-awarded with no visible symptom. That is why it has a test and the prompts do
not.
