# Learnings

## 2026-08-09: `claude plugin update` leaves the plugin disabled
Updating a locally-installed plugin (`claude plugin update <name>@<marketplace>`)
installs the new version but flips `enabled` to `false`. Symptom: every slash command
returns `Unknown command` in the next session, and `claude plugin list --json` shows
the new version with `"enabled": false`. Fix: `claude plugin enable <name>`.
Cost us a full background QA run that failed instantly with no useful error.
Observed on Claude Code 2.1.226.

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

## 2026-08-09: `python3 - <<'PY'` in a hook eats the event
A hook receives its event JSON on stdin. Feeding the Python program itself in via a
heredoc consumes that stdin, so the script sees an empty/garbage payload and every
call fails identically. Put the program in a sibling `.py` file and `exec python3
that_file.py` so stdin stays the event. Passing the payload via `argv` instead also
breaks: a `Write` tool_input carries the whole file content and can exceed ARG_MAX.
