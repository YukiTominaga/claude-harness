#!/usr/bin/env python3
"""Run the evaluator eval suite and report recall and false alarms.

    python3 evals/run.py                       # every case once, on the pinned models
    python3 evals/run.py --runs 3 --max-cost-usd 40
    python3 evals/run.py --case 'seeded-*'

What it measures. Each case hands the plugin's evaluator a small Notes API and
asks for a final assessment. In a `seeded-*` case one known defect was put into
an app that otherwise passes, behind a test suite that stays green; the case is
**detected** when the verdict fails the round and names that defect among its
blocking issues. In a `clean-*` case nothing was seeded; the case is a **false
alarm** unless the verdict is a pass with no blocking issue. Grading is by regex
over `verdict.json` — no model judges a model.

How it runs. This is a thin wrapper around `claude plugin eval`. It evaluates a
temporary copy of the plugin under another name, because where the plugin is
installed through managed settings, `claude plugin eval .` loads the working
copy's hooks but not its agents (the managed install locks the plugin name). The
copy is the working tree with `crystal-harness:` rewritten to the copy's name.

Needs Claude Code 2.1.269+, and — because the evaluator runs the app with Bash —
the OS sandbox backend (on Linux: bubblewrap and socat). Runs go one at a time:
every fixture listens on the same port.
"""

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COPY_NAME = "crystal-harness-eval"
REWRITE_DIRS = ("commands", "skills", "agents", "workflows", "evals")


def make_copy(destination):
    """The plugin under another name, with every self-reference following it."""
    shutil.copytree(PLUGIN, destination, ignore=shutil.ignore_patterns("results", "__pycache__", ".git"))
    manifest = os.path.join(destination, ".claude-plugin", "plugin.json")
    with open(manifest, "r", encoding="utf-8") as f:
        data = json.load(f)
    original = data["name"]
    data["name"] = COPY_NAME
    with open(manifest, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    for sub in REWRITE_DIRS:
        for dirpath, _dirs, files in os.walk(os.path.join(destination, sub)):
            for filename in files:
                path = os.path.join(dirpath, filename)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        text = f.read()
                except (UnicodeDecodeError, OSError):
                    continue
                changed = text.replace(f"{original}:", f"{COPY_NAME}:")
                changed = re.sub(r"(agentPrefix \|\| )'" + re.escape(original) + "'", rf"\1'{COPY_NAME}'", changed)
                if changed != text:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(changed)
    return original


def summarize(result):
    """Per-run outcomes, and counts over the runs that actually produced a verdict.

    A run with no verdict.json, or one that errored, measured nothing about the
    evaluator — the session never got as far as a verdict. It is reported as
    `invalid` and kept out of both rates, because counting it as a miss or as a
    false alarm would turn a harness problem into a finding about the evaluator.
    """
    rows = []
    counts = {"seeded": {"detected": 0, "valid": 0}, "clean": {"false_alarm": 0, "valid": 0}, "invalid": 0}
    for case in result.get("cases", []):
        name = case.get("name", "?")
        kind = "seeded" if name.startswith("seeded-") else "clean" if name.startswith("clean-") else "other"
        for index, run in enumerate(case.get("arms", {}).get("with", []), 1):
            graders = {g.get("name"): g.get("passed") for g in run.get("graders", [])}
            if run.get("error") or run.get("aborted") or not graders.get("verdict-written"):
                counts["invalid"] += 1
                outcome = "INVALID — " + ("run error" if run.get("error") or run.get("aborted") else "no verdict was written")
            elif kind == "seeded":
                counts["seeded"]["valid"] += 1
                if all(graders.values()):
                    counts["seeded"]["detected"] += 1
                    outcome = "detected"
                elif not graders.get("fails-the-round"):
                    outcome = "MISSED — passed the round"
                else:
                    outcome = "MISSED — failed the round without naming the defect"
            elif kind == "clean":
                counts["clean"]["valid"] += 1
                if all(graders.values()):
                    outcome = "passed"
                else:
                    counts["clean"]["false_alarm"] += 1
                    outcome = "FALSE ALARM"
            else:
                outcome = "passed" if all(graders.values()) else "failed"
            rows.append((name, index, outcome, run.get("turns"), run.get("durationSeconds"), run.get("costUsd")))
    return rows, counts


def render(result, rows, counts, args, plugin_version):
    def rate(hits, total):
        return f"{hits}/{total}" + (f" ({hits / total * 100:.0f}%)" if total else "")

    lines = [
        "# Evaluator eval",
        "",
        f"- Plugin: {plugin_version}   Claude Code: {result.get('claudeVersion', '?')}   run at: {result.get('startedAt', '?')}",
        f"- Runs per case: {args.runs}   main-session model: {args.model or 'default'}   "
        "evaluator model and effort: as pinned in agents/harness-evaluator.md unless overridden by the environment",
        f"- Estimated cost: ${result.get('costUsd', 0):.2f} (list price, from `claude plugin eval`)   "
        f"wall time: {result.get('durationSeconds', 0) / 60:.0f} min" + ("   **PARTIAL RUN**" if result.get("partial") else ""),
        "",
        f"**Seeded defects detected: {rate(counts['seeded']['detected'], counts['seeded']['valid'])}.**  ",
        f"**False alarms on clean apps: {rate(counts['clean']['false_alarm'], counts['clean']['valid'])}.**",
    ]
    if counts["invalid"]:
        lines += [
            "",
            f"**{counts['invalid']} run(s) were invalid and are in neither count** — they ended without a verdict, "
            "so they say nothing about the evaluator. Find out why before reading the numbers above "
            "(`--keep-temp` keeps each run's trace).",
        ]
    lines += ["", "| case | run | outcome | turns | seconds | est. USD |", "| --- | --- | --- | --- | --- | --- |"]
    for name, index, outcome, turns, seconds, cost in rows:
        cost_text = f"{cost:.2f}" if isinstance(cost, (int, float)) else "—"
        lines.append(f"| {name} | {index} | {outcome} | {turns if turns is not None else '—'} | "
                     f"{seconds if seconds is not None else '—'} | {cost_text} |")
    lines += [
        "",
        "A seeded case counts as detected only if the verdict fails the round **and** names the seeded",
        "defect among its blocking issues; failing for another reason is not a detection. A clean case",
        "is a false alarm when the verdict is anything but a pass with no blocking issue. With few",
        "cases and few runs these are counts, not rates to compare to a decimal place.",
    ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, default=1, help="runs per case (default 1)")
    parser.add_argument("--case", default=None, help="only cases matching this glob")
    parser.add_argument("--model", default=None, help="model for the main session of each case")
    parser.add_argument("--max-cost-usd", type=float, default=None, help="stop launching runs past this estimated cost")
    parser.add_argument("--keep-copy", action="store_true", help="keep the temporary plugin copy for inspection")
    parser.add_argument("--keep-temp", action="store_true", help="keep each run's workspace and trace (passed to claude plugin eval)")
    args = parser.parse_args()

    with open(os.path.join(PLUGIN, ".claude-plugin", "plugin.json"), "r", encoding="utf-8") as f:
        manifest = json.load(f)
    plugin_version = f"{manifest['name']} {manifest.get('version', '?')}"

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    out_dir = os.path.join(PLUGIN, "evals", "results", stamp)
    os.makedirs(out_dir, exist_ok=True)
    work = tempfile.mkdtemp(prefix="crystal-harness-eval-")
    copy = os.path.join(work, COPY_NAME)
    make_copy(copy)

    result_path = os.path.join(out_dir, "result.json")
    command = [
        "claude", "plugin", "eval", copy,
        "--trust-plugin", "--scaffold", "--allow-tools", "Bash", "Write",
        "--ablation", "none", "--no-publish", "--concurrency", "1",
        "--runs", str(args.runs), "--threshold", "0",
        "--report", os.path.join(out_dir, "report.html"), "--json", result_path,
    ]
    if args.case:
        command += ["--case", args.case]
    if args.model:
        command += ["--model", args.model]
    if args.max_cost_usd is not None:
        command += ["--max-cost-usd", str(args.max_cost_usd)]
    if args.keep_temp:
        command += ["--keep-temp"]

    print(f"evaluating a copy of {plugin_version} as {COPY_NAME}; results in {out_dir}", flush=True)
    proc = subprocess.run(command, cwd=copy)
    try:
        if not os.path.isfile(result_path):
            print(f"run.py: claude plugin eval exited {proc.returncode} and wrote no result", file=sys.stderr)
            return 1
        with open(result_path, "r", encoding="utf-8") as f:
            result = json.load(f)
        rows, counts = summarize(result)
        if not rows:
            print("run.py: no case ran — claude plugin eval loaded no cases (see its output above)", file=sys.stderr)
            return 1
        summary = render(result, rows, counts, args, plugin_version)
        with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as f:
            f.write(summary)
        sys.stdout.write("\n" + summary)
        # 2: the numbers are incomplete — a partial run, or runs that never reached a verdict.
        return 2 if result.get("partial") or counts["invalid"] else 0
    finally:
        if args.keep_copy:
            print(f"plugin copy kept at {copy}")
        else:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
