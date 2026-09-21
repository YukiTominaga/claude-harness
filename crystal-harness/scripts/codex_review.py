#!/usr/bin/env python3
"""Run a Codex code review over a round's diff and write codex-review.md.

The harness's evaluator is an independent grader, but it is still a Claude model
reading a diff a Claude model wrote. When the user has the `codex` plugin
(github.com/openai/codex-plugin-cc) installed, a second opinion from a different
vendor's model is available for the price of one CLI call, and it is worth taking.

This script is the deterministic part of that: find the plugin, decide whether it
can actually run, invoke it, and render its output into the round directory. The
orchestrator should not be doing plugin discovery in prose, and the evaluator must
not be the one commissioning its own inputs.

Detection is operational, not declarative. "The codex plugin is enabled" is taken
to mean: its `codex-companion.mjs` is on disk, and `codex-companion.mjs setup`
reports `ready` (Node present, Codex CLI installed, authenticated). A plugin that
is installed but unauthenticated cannot review anything, and reporting it as
available would turn a skip into a failed round.

Usage:
    python3 codex_review.py --out .harness/sprints/03/codex-review.md \
        [--base <ref>] [--scope auto|working-tree|branch] \
        [--mode review|adversarial-review] [--cwd <dir>] \
        [--codex-root <dir>] [--timeout 900] [--required]

    python3 codex_review.py --check          # can a review run here? no review is run

Exit codes:
    0  a review was written to --out (or, with --check, codex is ready)
    3  codex is not available here — skip it, this is not a failure
    1  codex is available but the review could not be produced

The exit code is the whole interface, so it has to mean exactly one thing:
**--out holds a real review of the current diff if and only if this exits 0.**
Parsing is not evidence of a review — a failed, truncated or version-skewed
companion still emits JSON — so the response must carry a codex block, a status
of exactly 0, and actual review content before anything is written. Any other
outcome removes the file first, including a leftover from an earlier round in
the same directory: a revision reuses its round directory, and a review of the
previous diff read as evidence about this one is worse than no review at all.

With --required, an unavailable codex exits 1 instead of 3, for the
`codexReview: true` configuration where a missing review is a real problem.
"""

import argparse
import datetime
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

COMPANION_RELPATH = os.path.join("scripts", "codex-companion.mjs")
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def log(message):
    print(f"codex_review: {message}", file=sys.stderr)


def claude_config_dir():
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    if configured:
        return os.path.expanduser(configured)
    return os.path.join(os.path.expanduser("~"), ".claude")


def companion_in(root):
    if not root:
        return None
    candidate = os.path.join(os.path.expanduser(root), COMPANION_RELPATH)
    return candidate if os.path.isfile(candidate) else None


def from_installed_plugins():
    """Read the install path the plugin manager recorded for `codex@<marketplace>`."""
    manifest = os.path.join(claude_config_dir(), "plugins", "installed_plugins.json")
    try:
        with open(manifest, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:  # noqa: BLE001 - absent or unreadable simply means "not found here"
        return None

    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, dict):
        return None

    for key, installs in plugins.items():
        if not key.startswith("codex@") or not isinstance(installs, list):
            continue
        for install in installs:
            if not isinstance(install, dict):
                continue
            found = companion_in(install.get("installPath"))
            if found:
                return found
    return None


def from_cache_glob():
    """Fall back to the plugin cache layout: cache/<marketplace>/codex/<version>/.

    Sorted so the lexically highest version directory wins. Versions here are
    plain semver strings from the marketplace, and the fallback only matters when
    the manifest is missing, so a full version parse is not worth it.
    """
    pattern = os.path.join(claude_config_dir(), "plugins", "cache", "*", "codex", "*", COMPANION_RELPATH)
    matches = sorted(glob.glob(pattern))
    return matches[-1] if matches else None


def find_companion(explicit_root):
    if explicit_root:
        found = companion_in(explicit_root)
        if not found:
            log(f"--codex-root {explicit_root} has no {COMPANION_RELPATH}")
        return found
    return (
        companion_in(os.environ.get("CRYSTAL_HARNESS_CODEX_ROOT"))
        or from_installed_plugins()
        or from_cache_glob()
    )


def first_error_line(stderr, returncode):
    """The most actionable line of a failed run.

    A node crash ends with the runtime banner ("Node.js v22.x"), so the last
    line is the least informative one. The line naming the error is what tells
    someone whether their codex install is broken or their repo is.
    """
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    for line in lines:
        if "error" in line.casefold():
            return line
    if lines:
        return lines[0]
    return f"exit {returncode} with no output"


def run_companion(companion, args, cwd, timeout):
    node = shutil.which("node")
    if not node:
        return None, "node is not on PATH"
    try:
        completed = subprocess.run(
            [node, companion, *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout}s"

    if not completed.stdout.strip():
        return None, first_error_line(completed.stderr, completed.returncode)

    try:
        return json.loads(completed.stdout), None
    except json.JSONDecodeError as exc:
        return None, f"could not parse --json output ({exc})"


def is_ready(companion, cwd, timeout):
    report, error = run_companion(companion, ["setup", "--json", "--cwd", cwd], cwd, timeout)
    if error:
        return False, error
    if not isinstance(report, dict):
        return False, "setup did not return an object"
    if report.get("ready") is True:
        return True, None

    for key, label in (("codex", "Codex CLI"), ("auth", "authentication"), ("node", "Node")):
        section = report.get(key)
        if isinstance(section, dict) and not (section.get("available") or section.get("loggedIn")):
            return False, f"{label} is not ready — run /codex:setup"
    return False, "setup reported not ready"


def render_findings(findings):
    lines = []
    ordered = sorted(findings, key=lambda f: SEVERITY_ORDER.get(str(f.get("severity")), 9))
    lines.append("| severity | file:line | finding |")
    lines.append("| --- | --- | --- |")
    for finding in ordered:
        location = str(finding.get("file", "?"))
        start = finding.get("line_start")
        if start:
            location = f"{location}:{start}"
        title = str(finding.get("title", "")).replace("|", "\\|")
        lines.append(f"| {finding.get('severity', '?')} | `{location}` | {title} |")
    lines.append("")

    for finding in ordered:
        lines.append(f"### {finding.get('severity', '?')} — {finding.get('title', 'untitled')}")
        location = finding.get("file")
        if location:
            span = finding.get("line_start")
            end = finding.get("line_end")
            if span and end and end != span:
                location = f"{location}:{span}-{end}"
            elif span:
                location = f"{location}:{span}"
            lines.append(f"- Location: `{location}`")
        confidence = finding.get("confidence")
        if isinstance(confidence, (int, float)):
            lines.append(f"- Codex confidence: {confidence}")
        lines.append("")
        lines.append(str(finding.get("body", "")).strip())
        recommendation = str(finding.get("recommendation", "")).strip()
        if recommendation:
            lines.append("")
            lines.append(f"**Codex recommends:** {recommendation}")
        lines.append("")
    return lines


def render(payload, mode, reviewed_sha=None):
    codex = payload.get("codex") if isinstance(payload.get("codex"), dict) else {}
    target = payload.get("target") if isinstance(payload.get("target"), dict) else {}
    generated = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines = [
        f"# Codex review — {payload.get('review', mode)}",
        "",
        f"Generated at: {generated}",
        f"Reviewed commit: {reviewed_sha or 'unknown'}",
        f"Target: {target.get('label', 'unknown')}",
        "",
        "> This is an independent review by a non-Claude model, run before the",
        "> evaluator was spawned. It is evidence about the code, not a verdict:",
        "> every finding below is a claim the evaluator must confirm against the",
        "> source before it affects a score, and no finding here establishes that",
        "> anything works.",
        "",
    ]

    structured = payload.get("result")
    if isinstance(structured, dict):
        lines.append(f"## Verdict: {structured.get('verdict', 'unknown')}")
        lines.append("")
        lines.append(str(structured.get("summary", "")).strip())
        lines.append("")
        findings = structured.get("findings")
        if isinstance(findings, list) and findings:
            lines.append("## Findings")
            lines.append("")
            lines.extend(render_findings(findings))
        else:
            lines.append("## Findings")
            lines.append("")
            lines.append("Codex reported no findings.")
            lines.append("")
        next_steps = structured.get("next_steps")
        if isinstance(next_steps, list) and next_steps:
            lines.append("## Codex's suggested next steps")
            lines.append("")
            lines.extend(f"- {step}" for step in next_steps)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n", len(structured.get("findings") or [])

    body = str(codex.get("stdout") or "").strip()
    lines.append("## Codex output")
    lines.append("")
    lines.append(body if body else "_Codex produced no review text._")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n", None


def unusable_reason(payload):
    """Why this payload is not a review, or None if it is one.

    A failed or truncated run still emits JSON on stdout, so parsing is not
    evidence of a review. Anything short of a real one has to fail: the exit
    code is the orchestrator's whole interface, and a file saying "Codex
    produced no review text" would record an independent opinion the round
    never got.

    The checks mirror render()'s own branch exactly, so nothing can pass here
    and then render as empty.
    """
    codex = payload.get("codex")
    if not isinstance(codex, dict):
        return "the response carried no codex block"

    status = codex.get("status")
    if not (isinstance(status, int) and not isinstance(status, bool) and status == 0):
        stderr = str(codex.get("stderr") or "").strip()
        detail = f": {first_error_line(stderr, status)}" if stderr else ""
        return f"codex reported status {status!r}{detail}"

    structured = payload.get("result")
    if isinstance(structured, dict):
        if not str(structured.get("summary") or "").strip():
            return "the structured review carried no summary"
        return None

    parse_error = payload.get("parseError")
    if parse_error:
        return f"codex output could not be parsed ({parse_error})"
    if not str(codex.get("stdout") or "").strip():
        return "codex returned no review text"
    return None


def head_sha(cwd):
    """The commit this review is about, stamped into the file it produces.

    A reader — the evaluator included — otherwise cannot tell which diff a
    review covered, and a file from an earlier round looks exactly like a
    current one.
    """
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    return completed.stdout.strip() or None


def clear_stale_output(path):
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        log(f"could not remove the previous {path} ({exc}); it may be stale")


def write_atomic(path, content):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".codex-review-", suffix=".md.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", help="path to write codex-review.md; required unless --check")
    parser.add_argument(
        "--check",
        action="store_true",
        help="report whether a review could run, and exit without running one",
    )
    parser.add_argument("--base", default=None, help="base ref for a branch-scoped review")
    parser.add_argument("--scope", default=None, choices=("auto", "working-tree", "branch"))
    parser.add_argument("--mode", default="review", choices=("review", "adversarial-review"))
    parser.add_argument("--cwd", default=os.getcwd(), help="the project to review")
    parser.add_argument("--codex-root", default=None, help="the codex plugin directory")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument(
        "--required",
        action="store_true",
        help="exit 1 rather than 3 when codex is unavailable (harness.codexReview: true)",
    )
    args = parser.parse_args()

    if not args.check and not args.out:
        parser.error("--out is required unless --check is given")

    unavailable = 1 if args.required else 3
    cwd = os.path.abspath(os.path.expanduser(args.cwd))
    verb = "reporting it as unavailable" if args.check else "skipping the review"

    # A revision round reuses its round directory, so an earlier round's review
    # would still be sitting at --out if this run skips or fails. The evaluator
    # reads whatever file is there as evidence about the current diff, so the
    # stale one is worse than none: clear it before anything can go wrong.
    if not args.check:
        clear_stale_output(args.out)

    companion = find_companion(args.codex_root)
    if not companion:
        log(f"the codex plugin was not found — {verb}")
        return unavailable

    ready, reason = is_ready(companion, cwd, min(args.timeout, 120))
    if not ready:
        log(f"the codex plugin is installed but not usable: {reason} — {verb}")
        return unavailable

    if args.check:
        print(f"codex is ready at {os.path.dirname(os.path.dirname(companion))}")
        return 0

    run_args = [args.mode, "--json", "--cwd", cwd]
    if args.scope:
        run_args += ["--scope", args.scope]
    if args.base:
        run_args += ["--base", args.base]

    payload, error = run_companion(companion, run_args, cwd, args.timeout)
    if error:
        log(f"the codex review failed: {error}")
        return 1
    if not isinstance(payload, dict):
        log("the codex review returned something other than an object")
        return 1

    reason = unusable_reason(payload)
    if reason:
        log(f"the codex review is not usable: {reason}")
        return 1

    content, finding_count = render(payload, args.mode, head_sha(cwd))
    write_atomic(args.out, content)

    if finding_count is None:
        print(f"codex review written to {args.out}")
    else:
        print(f"codex review written to {args.out} ({finding_count} findings)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
