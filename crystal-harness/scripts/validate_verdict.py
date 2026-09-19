#!/usr/bin/env python3
"""Validate a verdict.json against the qa-rubric schema — deterministically.

The orchestrator must not interpret a malformed verdict generously, and asking
a model to eyeball a JSON document against a schema is exactly the kind of
check that silently degrades. This script is the qa-rubric skill's schema
(draft 2020-12, schemaVersion 3) hand-rolled in stdlib Python so it needs no
dependencies. Keep the two in sync: a schema change in the skill is not done
until it is reflected here.

It also enforces what a `pass` may mean in each verification mode. That part is
load-bearing: `browserVerification: false` waives three of the six dimensions, so
without a machine check, "headless" would be a way to get a pass by grading less.
The rules below are the price of the mode existing.

Usage:
    python3 validate_verdict.py .harness/sprints/03/verdict.json

Exits 0 printing "ok" when the file conforms; exits 1 listing every violation
otherwise, so the evaluator can be sent back once with the full list.
"""

import json
import re
import sys

SCORE_KEYS = ("productDepth", "functionality", "design", "originality", "craft", "codeQuality")
THRESHOLDS = {
    "productDepth": 4,
    "functionality": 4,
    "design": 4,
    "originality": 4,
    "craft": 3,
    "codeQuality": 3,
}
# Design, originality and craft are judgements about a rendered interface. With no
# browser there is nothing to judge, so headless scores them null and waives their
# thresholds rather than inviting a number derived from the stylesheet.
WAIVED_IN_HEADLESS = ("design", "originality", "craft")
MODES = ("browser", "headless", "degraded")
TOP_REQUIRED = (
    "schemaVersion", "phase", "round", "overall", "scores", "criteria",
    "blockingIssues", "nonBlockingIssues", "environment", "evaluatedAt",
)
TOP_ALLOWED = set(TOP_REQUIRED) | {"$schema", "sprint"}
CRITERION_REQUIRED = ("id", "text", "result")
CRITERION_ALLOWED = set(CRITERION_REQUIRED) | {"evidence", "browserOnly", "screenshot"}
ISSUE_REQUIRED = ("id", "summary", "repro", "observed", "expected", "cause")
ISSUE_ALLOWED = set(ISSUE_REQUIRED) | {"criterionId", "dimension", "screenshot"}
CAUSE_ALLOWED = {"file", "line", "mechanism"}
ENV_REQUIRED = ("verificationMode", "playwrightAvailable", "degraded")
ENV_ALLOWED = set(ENV_REQUIRED) | {
    "degradedReason", "appUrl", "apiUrl", "apiVerified", "persistenceVerified",
    "testsVerified", "codexReview",
}

errors = []


def err(path, message):
    errors.append(f"{path}: {message}")


def check_keys(obj, path, required, allowed):
    for key in required:
        if key not in obj:
            err(path, f"missing required key {key!r}")
    for key in obj:
        if key not in allowed:
            err(path, f"unexpected key {key!r}")


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def check_str_or_null(obj, key, path):
    if key in obj and obj[key] is not None and not isinstance(obj[key], str):
        err(f"{path}.{key}", "must be a string or null")


def check_issue(issue, path):
    if not isinstance(issue, dict):
        err(path, "must be an object")
        return
    check_keys(issue, path, ISSUE_REQUIRED, ISSUE_ALLOWED)
    for key in ("id", "summary", "observed", "expected"):
        if key in issue and not isinstance(issue[key], str):
            err(f"{path}.{key}", "must be a string")
    repro = issue.get("repro")
    if "repro" in issue and (
        not isinstance(repro, list) or any(not isinstance(step, str) for step in repro)
    ):
        err(f"{path}.repro", "must be an array of strings")
    if "dimension" in issue and issue["dimension"] not in SCORE_KEYS + (None,):
        err(f"{path}.dimension", f"must be one of {SCORE_KEYS} or null")
    check_str_or_null(issue, "criterionId", path)
    check_str_or_null(issue, "screenshot", path)
    cause = issue.get("cause")
    if "cause" in issue:
        if not isinstance(cause, dict):
            err(f"{path}.cause", "must be an object")
        else:
            check_keys(cause, f"{path}.cause", ("mechanism",), CAUSE_ALLOWED)
            if "mechanism" in cause and (
                not isinstance(cause["mechanism"], str) or not cause["mechanism"].strip()
            ):
                err(f"{path}.cause.mechanism", "must be a non-empty string")
            check_str_or_null(cause, "file", f"{path}.cause")
            if cause.get("line") is not None and not is_int(cause.get("line", 0)):
                err(f"{path}.cause.line", "must be an integer or null")


def check_mode_consistency(verdict, env, mode, criteria):
    """What the schema cannot say: what a pass is allowed to mean in this mode.

    Three modes, three different bargains. `browser` grades everything.
    `headless` waives the three dimensions that need a rendered interface, and
    pays for the waiver with the extra conditions below. `degraded` is a broken
    environment wearing the browser configuration, and can never pass.
    """
    scores = verdict.get("scores") if isinstance(verdict.get("scores"), dict) else {}
    criteria = criteria if isinstance(criteria, list) else []
    passing = verdict.get("overall") == "pass"

    # True in every mode, and checked even when the mode itself is unreadable: a
    # verdict goes back for correction once, so it has to carry every fault.
    if passing:
        if verdict.get("blockingIssues"):
            err("$.overall", "is pass but blockingIssues is non-empty")
        if any(isinstance(c, dict) and c.get("result") == "fail" for c in criteria):
            err("$.overall", "is pass but a criterion is marked fail")

    if mode is None or not isinstance(env, dict):
        return  # the shape errors already reported say why the rest cannot be judged

    if (env.get("degraded") is True) != (mode == "degraded"):
        err(
            "$.environment.degraded",
            f'must be true if and only if verificationMode is "degraded" (mode is "{mode}")',
        )
    if mode == "browser" and env.get("playwrightAvailable") is not True:
        err(
            "$.environment.playwrightAvailable",
            'must be true in "browser" mode — that mode means Playwright answered',
        )
    if mode in ("headless", "degraded") and env.get("playwrightAvailable") is not False:
        err("$.environment.playwrightAvailable", f'must be false in "{mode}" mode')

    if mode == "headless":
        for key in WAIVED_IN_HEADLESS:
            if scores.get(key) is not None:
                err(
                    f"$.scores.{key}",
                    'must be null in "headless" mode — it cannot be graded without a browser',
                )
        for i, criterion in enumerate(criteria):
            if (
                isinstance(criterion, dict)
                and criterion.get("browserOnly") is True
                and criterion.get("result") == "pass"
            ):
                err(
                    f"$.criteria[{i}]",
                    "is browserOnly but marked pass in headless mode — it cannot have been exercised",
                )

    if not passing:
        return

    if mode == "degraded":
        err(
            "$.overall",
            'is pass but verificationMode is "degraded" — browser verification was '
            "configured and did not work, so this round measured less than it was asked to",
        )
        return

    for key in SCORE_KEYS:
        if mode == "headless" and key in WAIVED_IN_HEADLESS:
            continue
        value = scores.get(key)
        if not is_int(value):
            err(f"$.scores.{key}", f'must be an integer to support a pass in "{mode}" mode')
        elif value < THRESHOLDS[key]:
            err(
                f"$.scores.{key}",
                f"is {value}, below its threshold of {THRESHOLDS[key]} — the verdict cannot be pass",
            )

    if mode == "headless":
        if not (env.get("apiVerified") is True or env.get("testsVerified") is True):
            err(
                "$.overall",
                "is pass in headless mode but neither apiVerified nor testsVerified is "
                "true — nothing was executed, so nothing was verified",
            )
        if not any(isinstance(c, dict) and c.get("result") == "pass" for c in criteria):
            err("$.overall", "is pass in headless mode but no criterion is marked pass")
        for i, criterion in enumerate(criteria):
            if (
                isinstance(criterion, dict)
                and criterion.get("result") == "not_verified"
                and criterion.get("browserOnly") is not True
            ):
                err(
                    f"$.criteria[{i}]",
                    "is not_verified without browserOnly in a headless pass — only a "
                    "browser-only gap is waived; any other gap blocks the pass",
                )


def main():
    if len(sys.argv) != 2:
        print("usage: validate_verdict.py <verdict.json>", file=sys.stderr)
        return 1

    try:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            verdict = json.load(f)
    except Exception as exc:  # noqa: BLE001
        print(f"invalid: could not read or parse {sys.argv[1]}: {exc}")
        return 1

    if not isinstance(verdict, dict):
        print("invalid: top level must be a JSON object")
        return 1

    check_keys(verdict, "$", TOP_REQUIRED, TOP_ALLOWED)

    if "schemaVersion" in verdict and verdict["schemaVersion"] != 3:
        err("$.schemaVersion", "must be 3")
    if "phase" in verdict and verdict["phase"] not in ("sprint", "final"):
        err("$.phase", 'must be "sprint" or "final"')
    sprint = verdict.get("sprint")
    if sprint is not None and (not is_int(sprint) or sprint < 1):
        err("$.sprint", "must be an integer >= 1 or null")
    if verdict.get("phase") == "final" and sprint is not None:
        err("$.sprint", "must be null when phase is final")
    rnd = verdict.get("round")
    if "round" in verdict and (not is_int(rnd) or rnd < 0):
        err("$.round", "must be an integer >= 0")
    if "overall" in verdict and verdict["overall"] not in ("pass", "fail"):
        err("$.overall", 'must be "pass" or "fail"')
    if "evaluatedAt" in verdict and not isinstance(verdict["evaluatedAt"], str):
        err("$.evaluatedAt", "must be an ISO-8601 string")

    scores = verdict.get("scores")
    if "scores" in verdict:
        if not isinstance(scores, dict):
            err("$.scores", "must be an object")
        else:
            check_keys(scores, "$.scores", SCORE_KEYS, set(SCORE_KEYS))
            for key in SCORE_KEYS:
                value = scores.get(key)
                if key in scores and value is not None and (not is_int(value) or not 0 <= value <= 5):
                    err(f"$.scores.{key}", "must be an integer 0..5 or null")

    criteria = verdict.get("criteria")
    if "criteria" in verdict:
        if not isinstance(criteria, list):
            err("$.criteria", "must be an array")
        else:
            for i, criterion in enumerate(criteria):
                path = f"$.criteria[{i}]"
                if not isinstance(criterion, dict):
                    err(path, "must be an object")
                    continue
                check_keys(criterion, path, CRITERION_REQUIRED, CRITERION_ALLOWED)
                cid = criterion.get("id")
                if "id" in criterion and (
                    not isinstance(cid, str) or not re.fullmatch(r"(AC|SPEC)-[0-9]+", cid)
                ):
                    err(f"{path}.id", "must match ^(AC|SPEC)-[0-9]+$")
                if "text" in criterion and not isinstance(criterion["text"], str):
                    err(f"{path}.text", "must be a string")
                if "result" in criterion and criterion["result"] not in ("pass", "fail", "not_verified"):
                    err(f"{path}.result", 'must be "pass", "fail" or "not_verified"')
                if "evidence" in criterion and not isinstance(criterion["evidence"], str):
                    err(f"{path}.evidence", "must be a string")
                if "browserOnly" in criterion and not isinstance(criterion["browserOnly"], bool):
                    err(f"{path}.browserOnly", "must be a boolean")
                check_str_or_null(criterion, "screenshot", path)

    for list_key in ("blockingIssues", "nonBlockingIssues"):
        issues = verdict.get(list_key)
        if list_key not in verdict:
            continue
        if not isinstance(issues, list):
            err(f"$.{list_key}", "must be an array")
            continue
        for i, issue in enumerate(issues):
            check_issue(issue, f"$.{list_key}[{i}]")

    env = verdict.get("environment")
    mode = None
    if "environment" in verdict:
        if not isinstance(env, dict):
            err("$.environment", "must be an object")
        else:
            check_keys(env, "$.environment", ENV_REQUIRED, ENV_ALLOWED)
            for key in (
                "playwrightAvailable", "degraded", "apiVerified",
                "persistenceVerified", "testsVerified",
            ):
                if key in env and not isinstance(env[key], bool):
                    err(f"$.environment.{key}", "must be a boolean")
            for key in ("degradedReason", "appUrl", "apiUrl"):
                check_str_or_null(env, key, "$.environment")
            if "codexReview" in env and env["codexReview"] not in ("confirmed", "present", "absent", None):
                err("$.environment.codexReview", 'must be "confirmed", "present", "absent" or null')
            if "verificationMode" in env:
                if env["verificationMode"] not in MODES:
                    err("$.environment.verificationMode", f"must be one of {MODES}")
                else:
                    mode = env["verificationMode"]

    check_mode_consistency(verdict, env, mode, criteria)

    if errors:
        for message in errors:
            print(f"invalid: {message}")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
