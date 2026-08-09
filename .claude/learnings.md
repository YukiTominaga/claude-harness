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
