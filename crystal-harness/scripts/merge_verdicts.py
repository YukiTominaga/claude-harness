#!/usr/bin/env python3
"""Merge the lens verdicts of a parallel evaluation into one verdict.json.

With `harness.parallelEvaluation` on, a round is graded by several evaluators,
each looking through one lens (tests, api, code, and screen when the browser is
enabled) and each writing its own file under `<round>/lenses/`. No model merges
them. This script does, by rules that can only make the result stricter than its
parts:

- a dimension two lenses both score takes the LOWER score;
- every blocking issue from every lens is kept;
- the round passes only if every lens passed its own slice.

It refuses to produce a verdict (exit 2, nothing written) when a lens the
configuration calls for is missing, malformed, self-contradictory, or left over
from another round or commit. A round that measured less than it was configured
to must never read as a verdict — the same rule `degraded` mode enforces for a
missing browser.

It also folds in the result of independently reproducing each blocking issue
(`<round>/lenses/verify/<issue id>.json`), as an annotation only. A reproduction
never removes an issue and never turns a fail into a pass.

Usage:
    python3 merge_verdicts.py .harness/final/02 --round 2
    python3 merge_verdicts.py .harness/sprints/03 --round 1

Exit 0: `<round>/verdict.json` and `<round>/qa.md` written (validate the verdict
with validate_verdict.py as usual). Exit 2: not merged; every reason is printed.
Exit 1: usage or environment error.
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_verdict as vv  # noqa: E402 - the verdict schema lives there; reuse, do not restate

SCORE_KEYS = vv.SCORE_KEYS
THRESHOLDS = vv.THRESHOLDS
LABELS = {
    "productDepth": "Product depth",
    "functionality": "Functionality",
    "design": "Design quality",
    "originality": "Originality",
    "craft": "Craft",
    "codeQuality": "Code quality",
}

# What each lens grades. `dimensions` are the scores it must report — exactly
# these, no others. Order here is the order issues appear in the merged verdict.
LENSES = {
    "tests": {
        "dimensions": (),
        "env_required": ("testsVerified", "testChanges"),
        "env_allowed": ("testsVerified", "testChanges"),
    },
    "api": {
        "dimensions": ("productDepth", "functionality"),
        "env_required": ("apiVerified", "persistenceVerified"),
        "env_allowed": ("apiVerified", "persistenceVerified", "appUrl", "apiUrl"),
    },
    "screen": {
        "dimensions": ("productDepth", "functionality", "design", "originality", "craft"),
        "env_required": ("verificationMode", "playwrightAvailable"),
        "env_allowed": ("verificationMode", "playwrightAvailable", "degradedReason", "appUrl"),
    },
    "code": {
        "dimensions": ("codeQuality",),
        "env_required": ("codexReview",),
        "env_allowed": ("codexReview",),
    },
}
LENS_REQUIRED = (
    "lens", "phase", "round", "commit", "lensVerdict", "scores",
    "blockingIssues", "nonBlockingIssues", "environment", "evaluatedAt",
)
LENS_ALLOWED = set(LENS_REQUIRED) | {"sprint", "criteria"}

problems = []


def problem(where, message):
    problems.append(f"{where}: {message}")


def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def required_lenses(project_dir):
    """The lenses this run is configured to have. `screen` exists only with the browser on."""
    try:
        harness = read_json(os.path.join(project_dir, ".harness", "config.json"))["harness"]
        browser = harness.get("browserVerification") is True
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"merge_verdicts: cannot read harness.browserVerification from config.json: {exc}")
    return ["tests", "api", "screen", "code"] if browser else ["tests", "api", "code"]


def criteria_owner(lenses):
    """One lens owns the acceptance criteria: the one that drives the product end to end."""
    return "screen" if "screen" in lenses else "api"


def vv_errors(check, *args):
    """Run one of validate_verdict's checks and return the errors it raised."""
    del vv.errors[:]
    check(*args)
    found = list(vv.errors)
    del vv.errors[:]
    return found


def check_criterion(criterion, path):
    if not isinstance(criterion, dict):
        vv.err(path, "must be an object")
        return
    vv.check_keys(criterion, path, vv.CRITERION_REQUIRED, vv.CRITERION_ALLOWED)
    cid = criterion.get("id")
    if not isinstance(cid, str) or not re.fullmatch(r"(AC|SPEC)-[0-9]+", cid):
        vv.err(f"{path}.id", "must match ^(AC|SPEC)-[0-9]+$")
    if not isinstance(criterion.get("text"), str):
        vv.err(f"{path}.text", "must be a string")
    if criterion.get("result") not in ("pass", "fail", "not_verified"):
        vv.err(f"{path}.result", 'must be "pass", "fail" or "not_verified"')
    if "evidence" in criterion and not isinstance(criterion["evidence"], str):
        vv.err(f"{path}.evidence", "must be a string")
    if "browserOnly" in criterion and not isinstance(criterion["browserOnly"], bool):
        vv.err(f"{path}.browserOnly", "must be a boolean")


def validate_lens(name, data, expect, owner, headless):
    """Append every problem with one lens file. Returns True when it is usable."""
    before = len(problems)
    where = f"lenses/{name}.json"
    spec = LENSES[name]
    if not isinstance(data, dict):
        problem(where, "top level must be a JSON object")
        return False

    for key in LENS_REQUIRED:
        if key not in data:
            problem(where, f"missing required key {key!r}")
    for key in data:
        if key not in LENS_ALLOWED:
            problem(where, f"unexpected key {key!r}")
    if data.get("lens") != name:
        problem(where, f'"lens" is {data.get("lens")!r}, expected {name!r}')

    # Left over from another round, or graded a different tree: not this round's evidence.
    for key in ("phase", "round", "commit"):
        if key in data and data[key] != expect[key]:
            problem(where, f"{key} is {data[key]!r} but this round is {expect[key]!r} — a stale or misdirected lens file")
    if data.get("sprint") != expect["sprint"]:
        problem(where, f"sprint is {data.get('sprint')!r} but this round is {expect['sprint']!r}")

    scores = data.get("scores")
    if not isinstance(scores, dict):
        problem(where, "scores must be an object")
        scores = {}
    else:
        if set(scores) != set(spec["dimensions"]):
            problem(
                where,
                f"scores must have exactly the keys {sorted(spec['dimensions'])} — this lens grades "
                f"those dimensions and no others (got {sorted(scores)})",
            )
        for key, value in scores.items():
            if value is not None and (not vv.is_int(value) or not 0 <= value <= 5):
                problem(where, f"scores.{key} must be an integer 0..5 or null")

    criteria = data.get("criteria", [])
    if not isinstance(criteria, list):
        problem(where, "criteria must be an array")
        criteria = []
    if name == owner:
        if not criteria:
            problem(where, f"the {name} lens owns the acceptance criteria and reported none")
        for i, criterion in enumerate(criteria):
            for message in vv_errors(check_criterion, criterion, f"criteria[{i}]"):
                problem(where, message)
    elif criteria:
        problem(where, f"only the {owner} lens reports criteria; this lens must leave them out")

    for list_key, prefix in (("blockingIssues", "B"), ("nonBlockingIssues", "N")):
        issues = data.get(list_key)
        if not isinstance(issues, list):
            problem(where, f"{list_key} must be an array")
            continue
        for i, issue in enumerate(issues):
            for message in vv_errors(vv.check_issue, issue, f"{list_key}[{i}]"):
                problem(where, message)
            issue_id = issue.get("id") if isinstance(issue, dict) else None
            if not isinstance(issue_id, str) or not re.fullmatch(rf"{prefix}-{name}-[0-9]+", issue_id):
                problem(where, f"{list_key}[{i}].id is {issue_id!r}, must match ^{prefix}-{name}-[0-9]+$")
            if isinstance(issue, dict) and "verification" in issue:
                problem(where, f"{list_key}[{i}] sets verification — only the merge writes that field")

    env = data.get("environment")
    if not isinstance(env, dict):
        problem(where, "environment must be an object")
        env = {}
    else:
        for key in spec["env_required"]:
            if key not in env:
                problem(where, f"environment is missing {key!r}")
        for key in env:
            if key not in spec["env_allowed"]:
                problem(where, f"environment has unexpected key {key!r}")
        for key in ("testsVerified", "apiVerified", "persistenceVerified", "playwrightAvailable"):
            if key in env and not isinstance(env[key], bool):
                problem(where, f"environment.{key} must be a boolean")
        if "testChanges" in env and env["testChanges"] not in ("none", "reviewed", "absent"):
            problem(where, 'environment.testChanges must be "none", "reviewed" or "absent"')
        if "codexReview" in env and env["codexReview"] not in ("confirmed", "present", "absent"):
            problem(where, 'environment.codexReview must be "confirmed", "present" or "absent"')
        if name == "screen":
            mode = env.get("verificationMode")
            if mode not in ("browser", "degraded"):
                problem(where, 'environment.verificationMode must be "browser" or "degraded" for the screen lens')
            elif (mode == "browser") != (env.get("playwrightAvailable") is True):
                problem(where, "environment.playwrightAvailable must be true exactly when verificationMode is browser")

    verdict = data.get("lensVerdict")
    blocking = data.get("blockingIssues") if isinstance(data.get("blockingIssues"), list) else []
    if verdict not in ("pass", "fail"):
        problem(where, 'lensVerdict must be "pass" or "fail"')
    elif verdict == "fail":
        if not blocking:
            problem(where, "lensVerdict is fail but there is no blocking issue — the generator has nothing to work on")
    else:
        if blocking:
            problem(where, "lensVerdict is pass but blockingIssues is non-empty")
        for key in spec["dimensions"]:
            value = scores.get(key)
            if not vv.is_int(value):
                problem(where, f"lensVerdict is pass but scores.{key} is not an integer")
            elif value < THRESHOLDS[key]:
                problem(where, f"lensVerdict is pass but scores.{key} is {value}, below its threshold of {THRESHOLDS[key]}")
        if name == "screen" and env.get("verificationMode") == "degraded":
            problem(where, "lensVerdict is pass in degraded mode — the browser was asked for and did not answer")
        if name == owner:
            for i, criterion in enumerate(criteria):
                if not isinstance(criterion, dict):
                    continue
                if criterion.get("result") == "fail":
                    problem(where, f"lensVerdict is pass but criteria[{i}] is marked fail")
                if criterion.get("result") == "not_verified" and not (headless and criterion.get("browserOnly") is True):
                    problem(
                        where,
                        f"lensVerdict is pass but criteria[{i}] is not_verified"
                        + (" without browserOnly" if headless else "")
                        + " — an unexplained gap blocks a pass",
                    )
            if not any(isinstance(c, dict) and c.get("result") == "pass" for c in criteria):
                problem(where, "lensVerdict is pass but no criterion is marked pass")
    return len(problems) == before


def load_reproductions(round_dir, blocking_ids, expect):
    """{issue id: {"reproduced": bool, "evidence": str}} from lenses/verify/, validated."""
    verify_dir = os.path.join(round_dir, "lenses", "verify")
    found = {}
    if not os.path.isdir(verify_dir):
        return found
    for filename in sorted(os.listdir(verify_dir)):
        if not filename.endswith(".json"):
            continue
        where = f"lenses/verify/{filename}"
        try:
            data = read_json(os.path.join(verify_dir, filename))
        except Exception as exc:  # noqa: BLE001
            problem(where, f"could not be parsed: {exc}")
            continue
        if not isinstance(data, dict) or not isinstance(data.get("reproduced"), bool) or not isinstance(data.get("evidence"), str):
            problem(where, 'must be an object with "issueId", a boolean "reproduced" and a string "evidence"')
            continue
        if data.get("round") != expect["round"] or data.get("commit") != expect["commit"]:
            problem(where, "round or commit does not match this round — a stale reproduction")
            continue
        issue_id = data.get("issueId")
        if issue_id not in blocking_ids:
            problem(where, f"issueId {issue_id!r} is not a blocking issue of this round")
            continue
        found[issue_id] = {"reproduced": data["reproduced"], "evidence": data["evidence"]}
    return found


def merge(lens_data, lenses, expect, reproductions):
    owner = criteria_owner(lenses)
    headless = "screen" not in lenses

    scores = {}
    for key in SCORE_KEYS:
        values = [
            lens_data[name]["scores"].get(key)
            for name in lenses
            if key in LENSES[name]["dimensions"]
        ]
        if not values or any(v is None for v in values):
            scores[key] = None  # nobody graded it, or one of its graders could not
        else:
            scores[key] = min(values)

    blocking, non_blocking = [], []
    for name in lenses:
        for issue in lens_data[name]["blockingIssues"]:
            issue = dict(issue)
            if issue["id"] in reproductions:
                issue["verification"] = "reproduced" if reproductions[issue["id"]]["reproduced"] else "not_reproduced"
            blocking.append(issue)
        non_blocking.extend(lens_data[name]["nonBlockingIssues"])

    env_of = {name: lens_data[name]["environment"] for name in lenses}
    if headless:
        mode, playwright, degraded_reason = "headless", False, None
    else:
        mode = env_of["screen"]["verificationMode"]
        playwright = env_of["screen"]["playwrightAvailable"]
        degraded_reason = env_of["screen"].get("degradedReason")
    environment = {
        "verificationMode": mode,
        "playwrightAvailable": playwright,
        "degraded": mode == "degraded",
        "degradedReason": degraded_reason,
        "appUrl": env_of["api"].get("appUrl") or (env_of.get("screen") or {}).get("appUrl"),
        "apiUrl": env_of["api"].get("apiUrl"),
        "apiVerified": env_of["api"]["apiVerified"],
        "persistenceVerified": env_of["api"]["persistenceVerified"],
        "testsVerified": env_of["tests"]["testsVerified"],
        "codexReview": env_of["code"]["codexReview"],
        "testChanges": env_of["tests"]["testChanges"],
        "lenses": list(lenses),
    }

    overall = "pass" if all(lens_data[name]["lensVerdict"] == "pass" for name in lenses) else "fail"
    verdict = {
        "schemaVersion": 3,
        "phase": expect["phase"],
        "sprint": expect["sprint"],
        "round": expect["round"],
        "overall": overall,
        "scores": scores,
        "criteria": lens_data[owner]["criteria"],
        "blockingIssues": blocking,
        "nonBlockingIssues": non_blocking,
        "environment": environment,
        "evaluatedAt": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return verdict


def cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_issue(issue, reproductions):
    lines = [f"### {issue['id']} — {issue['summary']}"]
    if issue.get("criterionId"):
        lines.append(f"- Criterion: {issue['criterionId']}")
    lines.append("- Repro:")
    lines.extend(f"  {i}. {step}" for i, step in enumerate(issue.get("repro", []), 1))
    lines.append(f"- Observed: {issue['observed']}")
    lines.append(f"- Expected: {issue['expected']}")
    cause = issue.get("cause", {})
    location = ":".join(str(x) for x in (cause.get("file"), cause.get("line")) if x is not None)
    lines.append(f"- Cause: {location + ' — ' if location else ''}{cause.get('mechanism', '')}")
    if issue.get("screenshot"):
        lines.append(f"- Screenshot: {issue['screenshot']}")
    result = reproductions.get(issue["id"])
    if result is not None:
        word = "reproduced" if result["reproduced"] else "NOT reproduced"
        lines.append(f"- Independent reproduction: {word} — {result['evidence']}")
    return "\n".join(lines)


def render_qa(verdict, lens_data, lenses, previous, reproductions):
    env = verdict["environment"]
    mode = env["verificationMode"]
    title = (
        f"Sprint {verdict['sprint']:02d} QA" if verdict["phase"] == "sprint"
        else f"Final assessment round {verdict['round']:02d}"
    )
    out = [f"# {title} — {verdict['overall']}", "", f"Verification mode: {mode}"]
    if mode == "headless":
        out.append(
            "Browser verification was disabled for this run; design, originality and craft were not assessed."
        )
    elif mode == "degraded":
        out.append(
            f"This was a reduced check: browser verification was configured and did not work "
            f"({env.get('degradedReason') or 'no reason recorded'}). It cannot pass."
        )
    out += [
        "",
        "This verdict was merged by `merge_verdicts.py` from one evaluator per lens. Where two "
        "lenses scored the same dimension the lower score stands, and the round passes only if "
        "every lens passed. Each lens's own notes are in `lenses/<lens>.md`.",
        "",
        "## Lenses",
        "| Lens | Verdict | Blocking | Notes |",
        "| --- | --- | --- | --- |",
    ]
    for name in lenses:
        data = lens_data[name]
        out.append(f"| {name} | {data['lensVerdict']} | {len(data['blockingIssues'])} | `lenses/{name}.md` |")

    out += [
        "",
        "## Environment",
        f"- App URL: {env.get('appUrl') or '—'}; API URL: {env.get('apiUrl') or '—'}",
        f"- Test suite run and passing: {env['testsVerified']}",
        f"- API exercised outside the browser: {env['apiVerified']}; persistence confirmed: {env['persistenceVerified']}",
        f"- Test changes report: {env['testChanges']}; codex review: {env['codexReview']}",
        "",
        "## Scores",
        "| Dimension | Score | Previous | Threshold | Met |",
        "| --- | --- | --- | --- | --- |",
    ]
    previous_scores = previous.get("scores", {}) if isinstance(previous, dict) else {}
    for key in SCORE_KEYS:
        value = verdict["scores"][key]
        waived = mode == "headless" and key in vv.WAIVED_IN_HEADLESS
        before = previous_scores.get(key)
        out.append(
            f"| {LABELS[key]} | {'null' if value is None else value} | {'—' if before is None else before} | "
            f"{'waived' if waived else '≥ ' + str(THRESHOLDS[key])} | "
            f"{'—' if waived else ('yes' if vv.is_int(value) and value >= THRESHOLDS[key] else 'no')} |"
        )

    out += ["", "## Acceptance criteria", "| id | result | evidence |", "| --- | --- | --- |"]
    for criterion in verdict["criteria"]:
        out.append(f"| {criterion['id']} | {criterion['result']} | {cell(criterion.get('evidence', ''))} |")

    out += ["", "## Blocking issues"]
    if verdict["blockingIssues"]:
        for issue in verdict["blockingIssues"]:
            out += [render_issue(issue, reproductions), ""]
    else:
        out += ["None.", ""]
    out += ["## Non-blocking issues"]
    if verdict["nonBlockingIssues"]:
        for issue in verdict["nonBlockingIssues"]:
            out += [render_issue(issue, {}), ""]
    else:
        out += ["None.", ""]

    gaps = [c for c in verdict["criteria"] if c["result"] == "not_verified"]
    out += ["## Not verified"]
    if gaps:
        out += [
            f"- {c['id']}{' (browser-only)' if c.get('browserOnly') else ''}: {c.get('evidence', '')}" for c in gaps
        ]
    else:
        out += ["Nothing."]
    return "\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("round_dir", help=".harness/sprints/NN or .harness/final/NN")
    parser.add_argument("--round", type=int, required=True, help="the round number every lens file must carry")
    parser.add_argument("--project-dir", default=os.getcwd())
    args = parser.parse_args()

    round_dir = os.path.abspath(args.round_dir)
    project_dir = os.path.abspath(args.project_dir)
    parts = os.path.relpath(round_dir, project_dir).split(os.sep)
    if len(parts) != 3 or parts[0] != ".harness" or parts[1] not in ("sprints", "final") or not parts[2].isdigit():
        print("merge_verdicts: round_dir must be .harness/sprints/NN or .harness/final/NN", file=sys.stderr)
        return 1
    try:
        commit = subprocess.run(
            ["git", "-C", project_dir, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception as exc:  # noqa: BLE001
        print(f"merge_verdicts: cannot read HEAD: {exc}", file=sys.stderr)
        return 1

    expect = {
        "phase": "sprint" if parts[1] == "sprints" else "final",
        "sprint": int(parts[2]) if parts[1] == "sprints" else None,
        "round": args.round,
        "commit": commit,
    }
    lenses = required_lenses(project_dir)
    owner = criteria_owner(lenses)
    headless = "screen" not in lenses

    lens_data = {}
    for name in lenses:
        path = os.path.join(round_dir, "lenses", f"{name}.json")
        if not os.path.isfile(path):
            problem(f"lenses/{name}.json", "missing — this lens produced no verdict")
            continue
        try:
            data = read_json(path)
        except Exception as exc:  # noqa: BLE001
            problem(f"lenses/{name}.json", f"could not be parsed: {exc}")
            continue
        if validate_lens(name, data, expect, owner, headless):
            lens_data[name] = data

    seen = {}
    for name, data in lens_data.items():
        for list_key in ("blockingIssues", "nonBlockingIssues"):
            for issue in data[list_key]:
                if issue["id"] in seen:
                    problem(f"lenses/{name}.json", f"issue id {issue['id']} is used twice")
                seen[issue["id"]] = name

    reproductions = {}
    if not problems:
        blocking_ids = {issue["id"] for data in lens_data.values() for issue in data["blockingIssues"]}
        reproductions = load_reproductions(round_dir, blocking_ids, expect)

    verdict_path = os.path.join(round_dir, "verdict.json")
    qa_path = os.path.join(round_dir, "qa.md")
    previous = None
    try:
        previous = read_json(verdict_path)  # the round before, still on disk in a sprint directory
    except Exception:  # noqa: BLE001
        previous = None

    if not problems:
        verdict = merge(lens_data, lenses, expect, reproductions)
        # The merged verdict has to satisfy the same rules a single evaluator's
        # does. If consistent lenses still add up to something the validator
        # rejects, that is a reason not to merge, not a verdict to hand on.
        text = json.dumps(verdict, indent=2, ensure_ascii=False) + "\n"
        tmp_path = verdict_path + ".merging"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(text)
        check = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "validate_verdict.py"), tmp_path],
            capture_output=True, text=True,
        )
        if check.returncode != 0:
            os.remove(tmp_path)
            for line in check.stdout.strip().splitlines():
                problem("merged verdict", line.replace("invalid: ", "", 1))
        else:
            os.replace(tmp_path, verdict_path)
            with open(qa_path, "w", encoding="utf-8") as f:
                f.write(render_qa(verdict, lens_data, lenses, previous, reproductions))
            print(f"merged {len(lenses)} lenses ({', '.join(lenses)}) into {os.path.relpath(verdict_path, project_dir)}: {verdict['overall']}")
            return 0

    # Not merged, and nothing was written. A verdict.json still in this directory
    # is the previous round's (the lenses read it on a re-check), not this one's.
    print("not merged:")
    for line in problems:
        print(f"  {line}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
