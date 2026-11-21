# Learnings

## 2026-08-09: `claude plugin update` can leave the plugin disabled
Seen once on Claude Code 2.1.226: updating a locally-installed plugin (0.1.1 → 0.2.0)
installed the new version but flipped `enabled` to `false`. Symptom: every slash
command returns `Unknown command` in the next session, with no other error — cost a
full background QA run before we checked. **Not reproducible** — the next update
(0.2.0 → 0.3.0) kept it enabled. Treat it as a state to verify, not a rule: after
`plugin update`, check `claude plugin list --json` for `"enabled": true` and run
`claude plugin enable <name>` only if it is false.

## 2026-08-09: the plugin cache is a snapshot, not a symlink
`~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/` is a copy taken at install
time. Editing the source tree does not affect a running session, and old version
directories are kept. So bump the version and re-run `marketplace update` +
`plugin update` + `plugin enable` before testing a change — and conversely, mid-session
source edits cannot explain odd behaviour in a run that started earlier.

## 2026-08-09: MCP tools from a bundled `.mcp.json` are namespaced by plugin
A server named `playwright` in a plugin's `.mcp.json` surfaces as
`mcp__plugin_<plugin-name>_<server-name>__<tool>` — e.g.
`mcp__plugin_crystal-harness_playwright__browser_click`. Agent frontmatter `tools:`
must use that prefix, not `mcp__playwright`. Verify empirically with
`claude --plugin-dir <dir> -p "list your mcp__ tools"` rather than guessing.

## 2026-08-09: PreToolUse hooks can identify the calling subagent
The hook event carries `agent_id` and `agent_type` when the tool call originates
inside a subagent. That makes per-role file-ownership policies enforceable in a hook
(e.g. "the generator may not write verdict.json, the evaluator may not write source"),
which prompt instructions alone cannot guarantee.

## 2026-08-09: a long headless harness run can hit the account's session usage limit
A background `claude -p /crystal-harness:harness-build` invocation ended with only
`You've hit your session limit · resets 5:30pm (Asia/Tokyo)` as output — not a
harness stopping rule, not an error in journal.md, just the subprocess's underlying
account hitting its usage cap mid-turn. The generator had already committed its
fixes (git history was intact) but never got to write report.md or hand off to the
evaluator; state.json/handoff.md were left exactly as the prior phase transition
left them (stale, but not corrupted — no partial/garbled writes). This is a
realistic risk for any harness run spanning multiple hours of Opus-5-at-xhigh
subagent work: budget for it by checking wall-clock cost against known reset
windows, and treat a bare rate-limit message with no journal entry as "safe to
resume once the window resets" rather than a harness bug — `/harness-resume`'s
consistency checks handle this fine since nothing was corrupted, only incomplete.

## 2026-08-09: headless `claude -p` kills its own background children after 600s
When an orchestrator running as `claude -p <command>` spawns a subagent that itself
runs long (e.g. harness-evaluator started in the background from inside the
orchestrator's own turn), and the orchestrator's top-level turn finishes and the
process tries to exit while that child is still running, the Claude Code CLI waits
600s then **terminates the still-running background child** and prints
`Background tasks still running after 600s; terminating. Set
CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0 to wait indefinitely.` The child leaves no
error in `.harness/journal.md` — it just never writes its output (in this case,
`final/02/qa.md` and `verdict.json` never appeared; only the directories the
evaluator's early setup had created did). Any leftover dev servers the killed child
started (uvicorn, vite) become orphaned processes holding the app's ports.
Fix for headless/scripted harness invocations: set
`CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0` (or a value covering the expected run time)
in the environment before invoking `claude -p` for any harness command that may
spawn a long-running subagent from inside a `-p` session. Also: after a kill like
this, check for and kill orphaned dev-server processes before resuming, or the
retry's server start will collide on the port.

## 2026-08-09: subagents sometimes cannot Write a "report" file — has recurred twice
Across two separate runs (a v1 sprint's report.md, and a v2 build's final/01/report.md),
a harness-generator subagent's `Write` call for its own report file was rejected, with
the agent's own text describing it as a subagent policy against agents writing report
files directly. This is NOT the crystal-harness plugin's own PreToolUse guard — verified
directly by piping the exact event through `guard-harness-artifacts.sh` and getting
`allow` (report.md is not in `PROTECTED_LEAVES`). Also not a hook in this user's
`~/.claude/settings.json` (hooks: `{}`) or the installed crystal plugin (no PreToolUse
hooks at all in 0.15.0). Likely a Claude Code Agent-tool-level behavior, not something
project-configurable. Workaround that has worked both times: the blocked writer either
uses Bash (heredoc/`cat >`) instead of Write, or returns the text and lets the caller
write it. Design implication: any agent instructed to "write X.md" should have a Bash
fallback in mind, since Write is not guaranteed to succeed for report-shaped files.

## 2026-08-09: `python3 - <<'PY'` in a hook eats the event
A hook receives its event JSON on stdin. Feeding the Python program itself in via a
heredoc consumes that stdin, so the script sees an empty/garbage payload and every
call fails identically. Put the program in a sibling `.py` file and `exec python3
that_file.py` so stdin stays the event. Passing the payload via `argv` instead also
breaks: a `Write` tool_input carries the whole file content and can exceed ARG_MAX.

## 2026-11-20: hooks see a plugin agent as `plugin:agent`, not its bare name
Measured on Claude Code 2.1.329: for a plugin's subagent, `agent_type` in hook events
(PreToolUse, SubagentStart/Stop) is the namespaced name — `crystal-harness:harness-generator`.
The ownership guard compared it to the bare `harness-generator`, matched nothing, and
allowed every write. No symptom anywhere: the guard exited 0, and its own tests passed
because they fed it the bare name. Found only by capturing a real event and replaying it
through the script. Rules that follow: a hook that keys on agent identity compares the
last `:` segment; a test for such a hook leads with the value Claude Code really sends;
and a "silent" component is not verified until a real event has gone through it.
(Supersedes the 2026-08-09 note on `agent_type`, which was written from synthetic events.)

## 2026-11-20: three kinds of agent, three shapes of `agent_type`
Same probe, with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` in an interactive session:
- **Subagent** from a plugin definition: `agent_type` = `plugin:name`.
- **Workflow agent**: `agent_type` = the `agentType` option passed to `agent()`
  (namespaced), or `workflow-subagent` when none is given. Hooks fire for it like any
  subagent, so `agentType: 'crystal-harness:harness-evaluator'` keeps the guard in force.
- **In-process teammate**: `agent_type` = the **name the lead gave it** (`w1`), not the
  subagent definition it was spawned from. The definition is visible only in the lead's
  own `PreToolUse` event for the `Agent` call (`tool_input.name` + `tool_input.subagent_type`).
  A guard that must know a teammate's role therefore needs either a naming convention
  enforced at spawn, or a registry written by a hook on that `Agent` call.
`TeammateIdle` carries `teammate_name` and `team_name`; `SendMessage` goes through
`PreToolUse` with `to` and `message`, so messages between roles can be denied by a hook.
A lead with live teammates can run a workflow at the same time — both completed.

## 2026-11-20: `subagent_tokens` is the last request, not the run
The `<usage>subagent_tokens: N` line in an Agent tool result (and `totalTokens` in the
PostToolUse `tool_response`) is the token count of the agent's **final API request**.
A three-request agent whose transcript sums to 64,685 reported 21,689. Teammate idle
notifications carry no token numbers at all. What does hold the truth is the transcript:
`SubagentStop` fires for subagents, workflow agents and teammates alike and hands the
hook `agent_transcript_path`; each assistant record has `message.usage` and `message.id`
(one response can span several lines sharing an id — count it once). This is observed
transcript layout, not a documented contract, so `ledger.py` records `tokens: null` with
a note when it cannot read one rather than guessing. `SubagentStop` also fires for
internal helpers with an empty `agent_type` and no transcript on disk; skip those.

One trap inside that: **the transcript is not complete when `SubagentStop` fires.** The
agent's last response is flushed asynchronously — measured ~100 ms after the hook
starts — so a hook that sums immediately drops the final request from every entry, and
the result still looks like a sensible number. Caught only by re-summing the transcript
after the session ended and comparing (2 requests recorded vs 3 on disk). The hook now
waits until the transcript's last assistant text equals the event's
`last_assistant_message`, capped at 3 s, and flags the entry if that never happens.
Any figure computed inside a stop hook needs the same after-the-fact comparison once.

## 2026-11-20: a managed install shadows `--plugin-dir` for the same plugin name
Where the plugin is installed through managed settings, `claude --plugin-dir <working copy>`
does not load the working copy: the debug log says `--plugin-dir copy of "crystal-harness"
ignored: plugin is locked by managed settings`, and the cached release runs instead —
agents, hooks and all — with nothing on screen to say so. A whole end-to-end test passed
against the old version before the missing ledger file gave it away. To test a working
copy there, copy it to a scratch directory, change `name` in its `plugin.json`
(e.g. `crystal-harness-dev`) and load that; confirm with `--debug-file` that hook lines
name the dev plugin.

## 2026-11-20: what a plugin workflow can and cannot do for the harness
Measured with `workflows/evaluate.js` on Claude Code 2.1.329:
- `agent()` with `schema` composes with a plugin `agentType` whose `tools:` list is
  restricted — the evaluator returned validated JSON. Use it for the small facts the
  script needs (which issues to reproduce); the judgement itself still goes in files.
- A thunk passed to `parallel()` may `await` several `agent()` calls in sequence, so
  "one agent beside a sequential chain" is expressible. That is the shape the lenses
  need: everything that runs the app shares its ports and datastore and must be serial.
- The script has no filesystem. Anything that must be checked deterministically
  (merging lens verdicts, validating them) has to run in the orchestrating session
  after the workflow returns — a workflow cannot be its own gate.
- A whole lens round on a 60-line toy API (tests, api, code, two reproductions; evaluators
  forced to Sonnet 5.5) recorded about 1.0M tokens in the ledger, almost all cache reads.
- The `PreToolUse` gate on `Agent|Workflow` denies in a live session with the reason
  shown to the model verbatim; the model stopped and reported it rather than retrying.

## 2026-11-20: a push that lands after the merge is silently not in main
PR #3 was squash-merged about a minute before a follow-up fix was committed and pushed
to the same branch. The push succeeded, the branch looked right, and main did not have
the fix. Nothing flags this. After any merge of a branch that had late commits, run
`git diff <branch tip> origin/main --stat`; anything it prints was left behind. Also:
restarting a merged branch needs a history rewrite, and a force push may be refused by
the permission mode — merging `origin/main` into the old branch (`-X ours` for the
hunks the late commit touched) gets the same tree with an ordinary push.

## 2026-11-20: what a live team build showed
`/crystal-harness:build` with `teamBuild: true`, agent teams on, interactive (tmux), two
builders on a two-part toy (API + CLI), everything forced to Sonnet 5.5:
- A hook sees a builder as `agent_type: "builder-api"` on every event, including
  `SubagentStop` and `TeammateIdle`. The guard denied `builder-api` a shell command that
  named `split.json`, live — the first denial of a harness agent observed in a real
  session rather than by replay.
- **`TaskCompleted` and `TaskCreated` never fired.** The lead coordinated by messages and
  created no tasks, so a gate hung on `TaskCompleted` would have gated nothing. And
  `TeammateIdle` fired twice per builder — once when it reported done, once on shutdown —
  so it cannot tell "finished" from "waiting". The post-build `team_build.py check`, run
  by the lead, is the gate that actually runs.
- `SubagentStop` also fires on each idle, so each builder wrote two ledger snapshots; the
  report's last-snapshot-per-agentId rule is what kept that from double counting.
- The builders never messaged each other: eleven pinned interfaces were enough for an API
  and a client to be written blind to each other and pass 69 tests together first time.
  The split plan, not the messaging, did the coordinating.
- Cost: split 0.28M tokens, builders 1.97M + 1.16M — 3.4M in all, about 12 minutes of
  agent time in under 6 minutes of wall clock. A single generator built the API half
  alone for 1.07M. Not a like-for-like comparison, but there is no sign yet that a team
  is cheaper; what it buys is wall-clock time and narrower contexts.

## 2026-11-20: the diagnose workflow on a fix that had already failed
Toy API whose DELETE never persisted, with a plausible failed fix already applied
(`db().commit()` — a commit on a brand-new connection). Eight investigators, Sonnet 5.5:
- The `state` and `wiring` investigators, kept apart, both landed on the wrong-connection
  commit; the `premise` investigator reported a dead end rather than inventing a cause, and
  the workflow skipped its refutation. The final investigator confirmed the cause by
  changing one line in a scratch copy and returned `high` confidence.
- The project tree was untouched afterwards (`git status` clean apart from the diagnosis
  files): the guard's "writes only under diagnosis/" held, and the scratch directory is
  where the experiment happened.
- With one obvious cause, three angles converge and the refutation stage adds little. The
  design earns its cost on issues where the angles disagree; this toy could not show that.
- Found by a test, not by a run: a rule's own keyword inside `.harness/rules.json` matched
  the rule as soon as the file was committed. Anything that reads a round's diff has to
  exclude `.harness/` — the harness's files are not the product.

## 2026-11-20: `claude plugin eval` on this plugin — what it took
Claude Code 2.1.329, in a root container where the plugin is also installed through
managed settings:
- **Granting Bash needs the OS sandbox backend.** Without `bubblewrap` and `socat` every
  run is refused before it starts ("sandbox required but unavailable"). `apt-get install`
  needed an `apt-get update` first.
- **A managed install locks the plugin name inside eval too.** `claude plugin eval .` on the
  working copy ran the plugin's hooks but offered none of its agents or skills
  ("Agent type 'crystal-harness:harness-evaluator' not found"). The score was simply 0 —
  no warning. Evaluating a renamed copy loads everything; `evals/run.py` does that.
- A scaffold script gets `$0` as its real path in the case directory, so fixtures can be
  shared files under `evals/` rather than heredocs repeated per case.
- A localhost server started by a subagent's Bash is reachable from the same sandbox.
- **As root, every sandboxed Bash call ends with `…/claude-0/cwd-XXXX: Read-only file
  system` and exit code 1**, whatever the command did. Left unexplained, an evaluator can
  read a passing test run as a failure. The case prompt explains it; a baseline taken as
  root carries that caveat.
- The plugin's guard works inside an eval run: it denied the evaluator a write to a source
  file, with the denial text shown to the model.
- YAML frontmatter in `prompt.md` rejects an unquoted value containing `: `, and when one
  case file fails to parse, **no** case runs and the tool still writes a result with zero
  cases — check the case count before reading a score.
- `--no-publish` is needed to keep the HTML report local; publishing to claude.ai is the
  default where the account supports it.
