---
description: Initialize a harness run in this directory — detect the stack, confirm config, create .harness/, and verify git plus whichever verification tools the config asks for.
argument-hint: "[target-dir]"
allowed-tools: Read, Write, Grep, Glob, Bash, Skill, mcp__plugin_crystal-harness_playwright__browser_navigate, mcp__plugin_crystal-harness_playwright__browser_close
---

Initialize a crystal-harness run. Target directory: `$1` if given, otherwise the
current working directory.

Read the `crystal-harness:harness-protocol` skill first — it defines every file you
are about to create.

## 1. Detect, do not assume

Inspect the target directory before writing anything:

- `package.json` — read `scripts` verbatim. `dev`, `build`, `test`, `typecheck`,
  `start`. Note the package manager from the lockfile: `package-lock.json` → npm,
  `pnpm-lock.yaml` → pnpm, `yarn.lock` → yarn, `bun.lockb` → bun. Use the right one
  in `commands.install`.
- `pyproject.toml` / `requirements.txt` / `uv.lock` / `poetry.lock` — Python backend.
  Look for a FastAPI/Flask/Django entrypoint and derive `commands.backendDev` from
  what is actually importable, not from a guess.
- `vite.config.*`, `next.config.*`, framework configs — for the real dev port.
  Default Vite 5173, Next 3000. If the config sets a port, use that.
- `docker-compose.y*ml`, `.env.example`, `alembic.ini`, ORM settings — the database
  URL **and the path to the SQLite file or the psql connection**. Record it as
  `database.url` and `database.file`. The evaluator confirms every write by reading
  the datastore directly, so a run without this cannot verify persistence and will
  return `persistenceVerified: false` on every criterion that writes.
- the client of a `curl`-able API: note the base path prefix (`/api`, `/v1`) if the
  backend mounts one, so the evaluator does not have to guess endpoint URLs.
- Existing `.harness/` — if present, this is a re-init. Show the diff between the
  existing config and what you detected, and change nothing without approval.

**Never invent a dev command.** If detection is ambiguous — two plausible
entrypoints, a monorepo with several dev scripts, a `dev` script that does something
other than serve the app — ask the human which one, listing what you found. A wrong
`commands.dev` makes every evaluation fail for a reason that has nothing to do with
the code.

Only fall back to these greenfield defaults when the directory has no project in it:

```json
{
  "commands": {
    "install": "npm install",
    "dev": "npm run dev",
    "build": "npm run build",
    "test": "npm test",
    "backendDev": "uvicorn app.main:app --reload"
  },
  "urls": { "app": "http://localhost:5173", "api": "http://localhost:8000" },
  "database": { "kind": "sqlite", "file": "./app.db", "url": null }
}
```

For an existing project with no backend, set `commands.backendDev`, `urls.api` and
`database` to `null` rather than inventing them, and say in the confirmation output
that persistence will not be independently verifiable.

## 2. Show the config and wait

Print the full proposed `.harness/config.json`, annotating each `commands` and
`urls` value with where it came from (`detected from package.json scripts.dev`,
`greenfield default`, `you told me`). Then stop and ask for confirmation or edits.

Do not write any file before the human confirms.

The `harness` block, with these defaults, is part of what you show:

```json
{
  "harness": {
    "useEvaluator": true,
    "useSprints": false,
    "contextReset": true,
    "browserVerification": false,
    "codexReview": "auto",
    "parallelEvaluation": false,
    "reproduceBlockingIssues": true,
    "teamBuild": false,
    "maxBuilders": 3,
    "diagnoseRecurringIssues": false,
    "maxSprints": 12,
    "maxRevisionsPerSprint": 5,
    "maxAcceptanceCriteria": 20,
    "maxFinalQaRounds": 5,
    "maxRunTokens": null,
    "maxRunCostUsd": null,
    "costPerMTokUsd": null
  }
}
```

`parallelEvaluation` defaults to `false`: a round is graded by one evaluator. Set
to `true`, each round is graded by one evaluator per lens — `tests`, `api`, `code`,
and `screen` when `browserVerification` is on — run by the plugin's `evaluate`
workflow and merged by a script that can only be stricter than its parts. It costs
more agents per round and there is not yet a measurement of what it finds that a
single evaluator misses, which is why it is off until the human asks for it; say
so if they do. `reproduceBlockingIssues` only matters with it on: each blocking
issue is then re-tried by a fresh evaluator given nothing but its steps, and the
result is recorded on the issue. It never removes an issue.

`teamBuild` defaults to `false`: one generator builds. Set to `true`, the first
build of a round is split across up to `maxBuilders` generators working at the
same time, each confined by a hook to the paths a validated split plan gives it.
It needs agent teams (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, experimental, and
an interactive session — not `claude -p`); without them the build quietly uses a
single generator. Offer it only when the product has a real seam — a server and a
client, independent modules — and say that it costs more tokens than one
generator and that nothing has yet measured what it buys.

`diagnoseRecurringIssues` defaults to `false`. Set to `true`, a blocking issue that
comes back after one fix is handed to the `diagnose` workflow before the generator
tries again: eight investigators gather evidence, argue three competing causes
apart, try to break each, and test what survives. It is the most expensive single
step in the harness and it runs only on an issue that has already cost a revision.

`maxRunTokens` and `maxRunCostUsd` cap what the run may spend on agents, as counted
by the ledger. Both default to `null` (no cap). When either is reached the loop
stops and asks, and a hook refuses to start another harness agent until the human
raises it. `maxRunCostUsd` needs `costPerMTokUsd` to be set — a cost cap with no
prices is reported as unenforceable and stops the run, rather than being ignored.

`browserVerification` defaults to `false`. Driving the app through Playwright is
the single most expensive thing a QA round does, and most rounds do not need it:
the API, the datastore and the project's own tests catch the defects that make a
build wrong, while the browser catches the ones that make it *look* wrong. With it
off, the evaluator runs in `headless` mode — design, originality and craft come
back `null` and browser-only criteria come back `not_verified`, but the round still
passes or fails on evidence.

Turn it on for a run whose value is in the interface: anything where a facade would
satisfy the API and fail the user, a visual redesign, or a final assessment you
intend to ship from. **Say so when you show the config** if the project you detected
has a frontend dev command, because that is exactly where the default costs the most
coverage — and ask the human rather than flipping it yourself.

`codexReview` defaults to `"auto"`: run an independent review of each round's diff
with the `codex` plugin ([openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc))
when it is installed and authenticated, and skip it silently when it is not. `true`
makes a missing codex an error the human hears about; `false` never runs it. The
review is recorded as `codex-review.md` in the round directory and read by the
evaluator as one input to Code quality — it never decides a verdict.

`useSprints` defaults to `false` (v2 mode) because `harness-generator` and
`harness-evaluator` are pinned to `claude-opus-5-5` regardless of this config — a
model capable enough that per-sprint decomposition is measured overhead, not a
safety net it needs. Set it to `true` if the human wants the smaller,
reviewed-as-you-go increments instead — a larger or more tightly-coupled spec than
a single Opus 5.5 session comfortably holds is the signal to do that, and there is no
way to detect that signal automatically, so ask if scope looks large.

`maxFinalQaRounds` defaults to 5, not 3, specifically because `useSprints: false`
moves defect-catching from many small per-sprint checks to fewer large end-of-run
ones — the round budget needs more room to converge without the early safety net.

`costPerMTokUsd` is optional. Set it and `/crystal-harness:status` will convert the ledger's
token counts into an estimated-USD column, which is what makes "is the evaluator
worth its cost on this project" answerable with a number. Left `null`, the ledger
still records tokens and wall time.

Prefer the per-category form, in USD per million tokens, with the prices the human
gives you for the model the agents run on — never fill them in from memory:

```json
"costPerMTokUsd": { "input": 0, "output": 0, "cacheWrite": 0, "cacheRead": 0 }
```

The ledger counts every request an agent made, and in a long session most of those
tokens are cache reads, which are priced far below fresh input. A single number is
still accepted and is applied to every token alike, which overstates a
cache-heavy run badly; say so if the human chooses it.

## 3. Write the run state

After confirmation, create:

- `.harness/config.json` — as confirmed.
- `.harness/state.json` — `schemaVersion: 3`, `phase: "init"`, `currentSprint: null`,
  `currentRound: null`, `sprints: []`, `finalRounds: []`, `repeatedIssueFingerprints: {}`,
  `lastGoodCommit` and `baseCommit` both set to `git rev-parse HEAD` if the repo has a
  commit, else `null`. `baseCommit` is never changed again: it is how a later
  evaluator tells a defect this run introduced from one it inherited.
- `.harness/journal.md` — one entry recording initialization and what was detected.
- `.harness/handoff.md` — using the template in `harness-protocol`, with
  "Next action" = run `/crystal-harness:plan <idea>`.
- `.harness/sprints/`, `.harness/final/`, `.harness/artifacts/` — empty directories
  with `.gitkeep`.

Add to `.gitignore` if a git repo exists: `.harness/artifacts/`. Everything else
under `.harness/` is committed on purpose — it is the run's memory, and losing it
loses the ability to resume.

## 4. Verify the environment

Report each of these as a checked line, and do not paper over a failure:

- **git** — `git rev-parse --is-inside-work-tree`. If not a repo, run `git init` and
  say so. If the repo is on `main`/`master`, create and switch to a work branch
  (`harness/<slug>`), because the loop commits continuously.
- **Playwright MCP** — **only when `browserVerification` is `true`.** Call
  `browser_navigate` against `about:blank`, then `browser_close`. If it fails,
  report the exact error and tell the human the evaluator will run in degraded mode
  (visual and interaction criteria will come back `not_verified`, never `pass`, and
  two degraded rounds stop the loop) until it is fixed. Do not disable the evaluator
  to work around it, and do not switch the config to `false` to make the error go
  away — that converts a broken environment into a setting.
  With `browserVerification: false`, skip this check and print one line saying the
  run will grade in headless mode and what that does not cover.
- **codex review** — only when `codexReview` is not `false`. Run
  `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/codex_review.py" --check`, which probes
  without reviewing anything. Exit 0 means each round gets an independent review;
  exit 3 means the plugin is absent, unauthenticated or broken, which is fine on
  `"auto"` — print the reason in one line and move on. Do not install anything.
- **install command** — do not run it; just confirm the tool exists on PATH
  (`node`, `python3`, `uv`, whichever the config needs).

## 5. Report

Print: the written config, the git branch, the environment check results, and the
next command to run. Nothing else happens in this command — no planning, no
scaffolding, no code.
