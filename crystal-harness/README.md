# crystal-harness

A Claude Code plugin that packages a multi-agent harness for long-running
application development. It separates the agent that builds from the agent that
grades, replaces "is this good?" with a thresholded rubric, resets context through
files instead of compacting it, and makes each sprint an agreement rather than a
guess.

Modeled on Anthropic's
[Harness Design for Long-Running Application Development](https://www.anthropic.com/engineering/harness-design-long-running-apps).

## The failure modes it addresses

| Failure | What it looks like | What the harness does |
| --- | --- | --- |
| **Context degradation** | As the window fills, the agent quietly cuts scope and declares the work finished. | Context **reset**, not compaction. At every phase boundary the run writes `handoff.md` and a *fresh* agent picks it up. Nothing depends on conversation history. |
| **Self-evaluation bias** | An agent asked to grade its own output praises mediocre work. | Generation and evaluation are different agents with different prompts, different tools, and no shared context. A hook makes the boundary structural, not advisory. |
| **Ungradable subjective quality** | "Looks good to me." | Four rubric dimensions, hard thresholds, 0–5 behavioral anchors, and few-shot calibration examples — including a polished artifact that scores low and a plain one that scores high. |
| **Under-scoping** | A one-line prompt produces a thin three-feature app. | A planner writes a scope-complete spec before any code exists — expansive on scope, deliberately silent on implementation. |

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

Verify:

```bash
claude plugin details crystal-harness   # 6 commands, 3 agents, 3 skills, 1 MCP server, 1 hook
```

Requires `node`/`npx` (Playwright MCP is fetched on first use) and `python3` (the
ownership hook).

## Quickstart

```
/crystal-harness:harness-init
/crystal-harness:harness-plan a pomodoro timer with session history
/crystal-harness:harness-build
```

`harness-init` shows you the detected config and waits. `harness-plan` shows you the
spec and waits. `harness-build` then runs the loop and only stops when it needs a
decision from you.

At any point:

```
/crystal-harness:harness-status                # where is the run
/crystal-harness:harness-qa                    # grade the current tree, standalone
/crystal-harness:harness-resume                # after a crash, /clear, or a new session
```

> Plugin commands are namespaced. The brief for this plugin refers to `/harness-init`;
> the real invocation is `/crystal-harness:harness-init`.

## The `.harness/` artifact contract

Every agent-to-agent handoff is a file. No agent may depend on having seen another
agent's conversation.

```
.harness/
├── config.json          # harness configuration
├── spec.md              # planner output: the product specification
├── state.json           # machine-readable run state
├── handoff.md           # rolling context-reset handoff artifact
├── journal.md           # append-only human-readable log
├── artifacts/           # Playwright scratch output (gitignored)
└── sprints/01/
    ├── contract.md      # generator proposes, evaluator accepts
    ├── report.md        # generator's completion report + self-check
    ├── qa.md            # evaluator verdict, human-readable
    ├── verdict.json     # evaluator verdict, machine-readable
    └── screenshots/
```

Full definitions, both JSON Schemas, and the `handoff.md` template live in the
`crystal-harness:harness-protocol` skill.

`handoff.md` is the load-bearing artifact. It must be sufficient for a completely
fresh agent with zero prior context to continue the run: current goal, what is done
*and verified*, exactly where work stopped, known-broken things, decisions not to be
relitigated, the files that matter, and **one** next action. A handoff whose phase
disagrees with `state.json` is a hard error — `harness-resume` refuses to continue
until a human resolves it, because a stale handoff reads as authoritative.

### Ownership, enforced

`hooks/hooks.json` registers one `PreToolUse` hook. It exists because each of the two
things it blocks silently destroys the design:

- `harness-generator` writing `.harness/sprints/*/qa.md`, `verdict.json`, or
  `screenshots/` — if the generator can write the verdict, every pass is
  self-awarded.
- `harness-evaluator` writing anything outside `.harness/` — if the evaluator can fix
  what it grades, it is the author of what it judges.

Everything else passes through untouched. There is no logging hook and no formatting
hook; neither prevents a named failure, and scaffolding that prevents nothing is the
overhead this whole design argues against.

The hook covers `Write`/`Edit`/`MultiEdit`/`NotebookEdit`. It does not intercept
writes made through `Bash` — that is a real gap, and the reason the agent prompts
state the rule as well as the hook enforcing it.

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
  "harness": {
    "usePlanner": true,
    "useEvaluator": true,
    "useSprints": true,               // false → one long coherent session (v2 mode)
    "maxSprints": 12,
    "maxRevisionsPerSprint": 3,
    "contextResetPolicy": "per-sprint" // "per-sprint" | "per-phase" | "never"
  }
}
```

On an existing repository, `harness-init` detects `commands` and `urls` from
`package.json` scripts, the lockfile, framework configs, and `pyproject.toml`, then
shows you each value annotated with where it came from. The defaults above apply
only to a greenfield directory. **It never invents a dev command** — ambiguous
detection is a question, not a guess, because a wrong `commands.dev` makes every
evaluation fail for reasons unrelated to the code.

Every `harness.*` flag can be turned off independently. That is deliberate; see
"What to strip".

## How the loop works

Per sprint, with `useSprints: true`:

1. **Contract.** A fresh generator cuts the next sprint from the spec's feature
   ordering and writes `contract.md`: scope, out-of-scope, and one or more
   acceptance criteria per item — each a browser-observable given/when/then.
2. **Review.** A fresh evaluator checks two things only: is every criterion testable
   in a browser, and does this sprint actually advance the spec. At most two rounds,
   then it escalates to you.
3. **Implement.** A fresh generator builds, commits at every checkpoint, runs the
   project's own build/typecheck/tests, and fixes its own failures before writing
   `report.md` — a report that states plainly what is complete, what is partial, and
   what it did not attempt.
4. **Context reset.** `state.json` and `handoff.md` are written, then the evaluator
   is spawned as a new agent with no shared context. It is told file paths, never
   what the generator claims works.
5. **Evaluate.** The evaluator starts the app and drives it through Playwright —
   clicking, typing, dragging, resizing, tabbing, triggering empty and error states,
   reading console and network — then writes `qa.md`, `verdict.json`, and
   screenshots.
6. **Branch.** Pass → commit, next sprint. Fail → a fresh generator revises against
   the **blocking issues only**, up to `maxRevisionsPerSprint`.
7. **Stop rather than loop.** The run halts and asks you when revisions are
   exhausted, when the same issue id fails twice with no progress, when the evaluator
   runs degraded twice, or when `maxSprints` is reached. Every stop is journaled with
   its reason.

With `useSprints: false` (v2 mode) steps 1–2 disappear: the generator gets `spec.md`
and runs one long coherent session, and there is a single end-of-run evaluator pass
over the spec's behaviour and edge-case sections.

### The rubric

Four dimensions, each 0–5 with written behavioral anchors:

| Dimension | Threshold |
| --- | --- |
| Functionality — works end to end, including edge and error paths | **≥ 4, and it is a gate** |
| Design quality — coherent spacing, type, and color systems | ≥ 3 |
| Originality — evidence of deliberate decisions, not framework defaults | ≥ 3 |
| Craft — typography, alignment, states, responsiveness, a11y basics | ≥ 3 |

Functionality below 4 fails the sprint regardless of the other three. A criterion
that was not exercised is `not_verified`, never `pass`, and `not_verified` never
counts toward a pass. Calibration examples — three or more per dimension, with the
reasoning — are in `skills/qa-rubric/references/calibration-examples.md`.

### If Playwright is unavailable

The evaluator degrades to a clearly labelled reduced check: build succeeds, dev
server starts, app responds, project tests pass. Every visual and interactive
criterion is marked `not_verified` with the reason, unassessable dimensions are
`null`, and a degraded run **never** returns `pass`. Two degraded runs in a row stop
the loop — the harness is not measuring anything and more sprints will not help.

## Resuming

The run is designed to survive `/clear`, a crash, and a new machine.

```
/crystal-harness:harness-resume
```

It reads `state.json` → `handoff.md` → `config.json` → `spec.md` → the current
sprint's contract and verdict, in that order, and refuses to continue on any
inconsistency: missing handoff, handoff phase disagreeing with state, a
`lastGoodCommit` that is not an ancestor of `HEAD`, or `phase: "blocked"`. It prints
a reconstruction summary and waits for you to choose: continue from "Next action", or
roll back to the last good commit first.

`journal.md` is deliberately *not* used to reconstruct state. It is a human log and
it contains superseded decisions.

## What to strip as models improve

Every component here encodes an assumption about something the model cannot do
alone, and those assumptions expire. In the source post's own v2, the sprint
construct became unnecessary once the model could sustain 2+ hour coherent sessions.
Ranked from least to most load-bearing — strip in this order:

**1. Sprints — `useSprints: false`.** The weakest component, and the first to go.
Sprints exist to bound a session to what the model can hold coherently. *Signal that
it is overhead:* the generator's sprint boundaries start looking arbitrary, contracts
get accepted on the first round every time, and sprint N spends its first commits
undoing a seam that only existed because sprint N-1 had to end somewhere. Then switch
to v2 mode and keep one end-of-run evaluation.

**2. The evaluator on tasks the model already handles solo — `useEvaluator: false`.**
The evaluator is the most expensive component: a second full agent, a browser, and a
serialized round trip per sprint. **It is worth its cost only when the task sits
beyond what the model does reliably alone.** For a CRUD screen against a schema the
model has seen a thousand times, the evaluator will confirm what the generator's own
tests already established, at several times the price. *Signal that it is overhead:*
verdicts come back `pass` with no blocking issues for several sprints running, and
the non-blocking issues it does raise are ones the generator's report already
listed. Keep it for anything visual, interactive, or genuinely novel — that is where
self-assessment is still worst.

**3. The planner — `usePlanner: false`.** Load-bearing for longer than the other two,
because under-scoping is a failure of *what the prompt asked for*, not of model
capability, and a richer spec still produces a richer app. *Signal that it is
overhead:* you find yourself barely editing the spec, and a generator given the raw
one-line idea produces the same feature list the planner would have written.

**4. The artifact protocol — keep it.** `handoff.md`, `state.json`, and the file-based
contract are not compensating for a model weakness. They are how a run survives a
crash, a `/clear`, a new session, and a different machine. That requirement does not
expire with context length.

**5. The rubric — keep it, and keep re-calibrating it.** Thresholds and anchors are
how "is this good?" stays answerable. What *does* expire is the calibration: as
baseline output quality rises, a 3 on Originality that was defensible becomes a 2.
Re-read `calibration-examples.md` against your own recent output periodically and
move the anchors.

The honest summary: the parts of this harness that compensate for model limitations
should be deleted as those limitations disappear. The parts that encode *process* —
files as the unit of memory, a grader that is not the author — should not.

## Layout

```
crystal-harness/
├── .claude-plugin/{plugin.json, marketplace.json}
├── agents/{harness-planner, harness-generator, harness-evaluator}.md
├── commands/harness-{init,plan,build,qa,resume,status}.md
├── skills/
│   ├── harness-protocol/SKILL.md        # .harness/ contract, both JSON Schemas, handoff template
│   ├── sprint-contract/SKILL.md         # how to write and review acceptance criteria
│   └── qa-rubric/
│       ├── SKILL.md                     # dimensions, anchors, thresholds, verdict.json schema
│       └── references/calibration-examples.md
├── hooks/hooks.json
├── scripts/guard-harness-artifacts.sh
├── .mcp.json                            # Playwright MCP
└── README.md
```

## License

MIT.
