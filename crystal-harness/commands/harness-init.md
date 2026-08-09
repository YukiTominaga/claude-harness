---
description: Initialize a harness run in this directory — detect the stack, confirm config, create .harness/, verify git and Playwright MCP.
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
- `docker-compose.y*ml`, `.env.example` — database and service URLs.
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
  "stack": { "frontend": "react-vite-ts", "backend": "fastapi", "database": "sqlite" },
  "commands": {
    "install": "npm install",
    "dev": "npm run dev",
    "build": "npm run build",
    "test": "npm test",
    "backendDev": "uvicorn app.main:app --reload"
  },
  "urls": { "app": "http://localhost:5173", "api": "http://localhost:8000" }
}
```

For an existing project with no backend, set `commands.backendDev` and `urls.api` to
`null` rather than inventing them.

## 2. Show the config and wait

Print the full proposed `.harness/config.json`, annotating each `commands` and
`urls` value with where it came from (`detected from package.json scripts.dev`,
`greenfield default`, `you told me`). Then stop and ask for confirmation or edits.

Do not write any file before the human confirms.

The `harness` block, with these defaults, is part of what you show:

```json
{
  "harness": {
    "usePlanner": true,
    "useEvaluator": true,
    "useSprints": true,
    "maxSprints": 12,
    "maxRevisionsPerSprint": 3,
    "contextResetPolicy": "per-sprint"
  }
}
```

## 3. Write the run state

After confirmation, create:

- `.harness/config.json` — as confirmed.
- `.harness/state.json` — `phase: "init"`, `currentSprint: null`, `sprints: []`,
  `consecutiveFailures: 0`, `repeatedIssueFingerprints: {}`, `lastGoodCommit` set to
  `git rev-parse HEAD` if the repo has a commit, else `null`.
- `.harness/journal.md` — one entry recording initialization and the detected stack.
- `.harness/handoff.md` — using the template in `harness-protocol`, with
  "Next action" = run `/crystal-harness:harness-plan <idea>`.
- `.harness/sprints/`, `.harness/artifacts/` — empty directories with `.gitkeep`.

Add to `.gitignore` if a git repo exists: `.harness/artifacts/`. Everything else
under `.harness/` is committed on purpose — it is the run's memory, and losing it
loses the ability to resume.

## 4. Verify the environment

Report each of these as a checked line, and do not paper over a failure:

- **git** — `git rev-parse --is-inside-work-tree`. If not a repo, run `git init` and
  say so. If the repo is on `main`/`master`, create and switch to a work branch
  (`harness/<slug>`), because the loop commits continuously.
- **Playwright MCP** — call `browser_navigate` against `about:blank`, then
  `browser_close`. If it fails, report the exact error and tell the human the
  evaluator will run in degraded mode (visual and interaction criteria will come
  back `not_verified`, never `pass`) until it is fixed. Do not disable the evaluator
  to work around it.
- **install command** — do not run it; just confirm the tool exists on PATH
  (`node`, `python3`, `uv`, whichever the config needs).

## 5. Report

Print: the written config, the git branch, the environment check results, and the
next command to run. Nothing else happens in this command — no planning, no
scaffolding, no code.
