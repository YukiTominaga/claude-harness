#!/usr/bin/env python3
"""Regression tests for the verdict validator.

This script gained the same failure mode the ownership guard has: if it stops
rejecting, the loop keeps running and a verdict that measured nothing reads as a
pass, with no visible symptom. That became load-bearing when browser verification
became optional — `headless` waives three of the six dimensions, and the only thing
standing between that waiver and a rubber stamp is the rule set below.

No framework — run it directly:

    python3 crystal-harness/scripts/test_validate_verdict.py

Exits 0 when every case matches, 1 otherwise.
"""

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile

VALIDATOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "validate_verdict.py")

OK, INVALID = "ok", "invalid"


def criterion(cid, result, **extra):
    return {"id": cid, "text": f"criterion {cid}", "result": result, **extra}


def issue(iid="B-1"):
    return {
        "id": iid,
        "summary": "the thing is broken",
        "repro": ["open the app", "click save"],
        "observed": "nothing happens",
        "expected": "the row is written",
        "cause": {"file": "src/api.ts", "line": 42, "mechanism": "the handler is never bound"},
    }


def base(mode):
    """A minimal verdict that must validate in the given mode."""
    verdict = {
        "schemaVersion": 3,
        "phase": "sprint",
        "sprint": 1,
        "round": 0,
        "overall": "pass",
        "scores": {
            "productDepth": 4,
            "functionality": 4,
            "design": 4,
            "originality": 4,
            "craft": 3,
            "codeQuality": 3,
        },
        "criteria": [criterion("AC-1", "pass")],
        "blockingIssues": [],
        "nonBlockingIssues": [],
        "environment": {
            "verificationMode": mode,
            "playwrightAvailable": mode == "browser",
            "degraded": mode == "degraded",
            "apiVerified": True,
            "persistenceVerified": True,
            "testsVerified": True,
        },
        "evaluatedAt": "2026-09-19T00:00:00Z",
    }
    if mode == "headless":
        for key in ("design", "originality", "craft"):
            verdict["scores"][key] = None
    if mode == "degraded":
        verdict["overall"] = "fail"
        verdict["environment"]["degradedReason"] = "Playwright MCP did not respond"
    return verdict


def mutate(mode, **changes):
    """A base verdict with dotted-path overrides applied, e.g. scores.design=2."""
    verdict = copy.deepcopy(base(mode))
    for path, value in changes.items():
        keys = path.split(".")
        target = verdict
        for key in keys[:-1]:
            target = target[key]
        if value is _DELETE:
            del target[keys[-1]]
        else:
            target[keys[-1]] = value
    return verdict


class _Delete:
    pass


_DELETE = _Delete()


def cases():
    return [
        # The three modes, each in the shape they are supposed to take.
        ("browser pass", base("browser"), OK, None),
        ("headless pass", base("headless"), OK, None),
        ("degraded fail", base("degraded"), OK, None),
        ("browser fail with null scores", mutate(
            "browser", overall="fail", blockingIssues=[issue()],
            **{"scores.design": None, "criteria": [criterion("AC-1", "fail")]},
        ), OK, None),
        ("headless fail with null scores", mutate(
            "headless", overall="fail", blockingIssues=[issue()],
            **{"scores.productDepth": None, "criteria": [criterion("AC-1", "fail")]},
        ), OK, None),
        ("headless pass, browser-only criterion waived", mutate(
            "headless", criteria=[criterion("AC-1", "pass"), criterion("AC-2", "not_verified", browserOnly=True)],
        ), OK, None),

        # Schema shape.
        ("schemaVersion 2 is the old schema", mutate("browser", schemaVersion=2), INVALID, "schemaVersion"),
        ("missing verificationMode", mutate("browser", **{"environment.verificationMode": _DELETE}), INVALID, "verificationMode"),
        ("unknown verificationMode", mutate("browser", **{"environment.verificationMode": "offline"}), INVALID, "verificationMode"),
        ("unknown top-level key", mutate("browser", weightedScore=3.4), INVALID, "unexpected key"),
        ("bad criterion id", mutate("browser", criteria=[criterion("AC1", "pass")]), INVALID, "AC|SPEC"),
        ("browserOnly must be boolean", mutate("browser", criteria=[criterion("AC-1", "pass", browserOnly="yes")]), INVALID, "browserOnly"),
        ("blocking issue without a cause", mutate(
            "browser", overall="fail",
            blockingIssues=[{k: v for k, v in issue().items() if k != "cause"}],
        ), INVALID, "cause"),
        ("unknown codexReview value", mutate("browser", **{"environment.codexReview": "maybe"}), INVALID, "codexReview"),

        # The mode and the environment flags must describe the same run.
        ("degraded flag without degraded mode", mutate("browser", **{"environment.degraded": True}), INVALID, "degraded"),
        ("degraded mode without the flag", mutate("degraded", **{"environment.degraded": False}), INVALID, "degraded"),
        ("browser mode without playwright", mutate("browser", **{"environment.playwrightAvailable": False}), INVALID, "playwrightAvailable"),
        ("headless mode claiming playwright", mutate("headless", **{"environment.playwrightAvailable": True}), INVALID, "playwrightAvailable"),

        # Headless waives three dimensions; it may not score them anyway.
        ("headless scoring design", mutate("headless", **{"scores.design": 4}), INVALID, "scores.design"),
        ("headless scoring craft on a fail", mutate(
            "headless", overall="fail", blockingIssues=[issue()],
            **{"scores.craft": 3, "criteria": [criterion("AC-1", "fail")]},
        ), INVALID, "scores.craft"),
        ("headless passing a browser-only criterion", mutate(
            "headless", criteria=[criterion("AC-1", "pass", browserOnly=True)],
        ), INVALID, "browserOnly"),

        # Thresholds are not advisory, and null never satisfies one that applies.
        ("browser pass below product depth", mutate("browser", **{"scores.productDepth": 3}), INVALID, "threshold"),
        ("browser pass below craft", mutate("browser", **{"scores.craft": 2}), INVALID, "threshold"),
        ("browser pass with a null score", mutate("browser", **{"scores.originality": None}), INVALID, "scores.originality"),
        ("headless pass below code quality", mutate("headless", **{"scores.codeQuality": 2}), INVALID, "threshold"),

        # What a headless pass has to buy the waiver with.
        ("headless pass with nothing executed", mutate(
            "headless", **{"environment.apiVerified": False, "environment.testsVerified": False},
        ), INVALID, "nothing was executed"),
        ("headless pass with no criterion passing", mutate(
            "headless", criteria=[criterion("AC-1", "not_verified", browserOnly=True)],
        ), INVALID, "no criterion is marked pass"),
        ("headless pass with an unexplained gap", mutate(
            "headless", criteria=[criterion("AC-1", "pass"), criterion("AC-2", "not_verified")],
        ), INVALID, "only a browser-only gap is waived"),

        # A degraded run never passes, whatever else is true of it.
        ("degraded pass", mutate("degraded", overall="pass"), INVALID, "degraded"),

        # The rules that predate the modes, still enforced.
        ("pass with a blocking issue", mutate("browser", blockingIssues=[issue()]), INVALID, "blockingIssues is non-empty"),
        # A verdict goes back for correction once, so a broken environment block
        # must not hide the faults that hold in every mode.
        ("unreadable mode still reports a blocking-issue pass", mutate(
            "browser", blockingIssues=[issue()],
            **{"environment.verificationMode": _DELETE},
        ), INVALID, "blockingIssues is non-empty"),
        ("pass with a failed criterion", mutate(
            "browser", criteria=[criterion("AC-1", "pass"), criterion("AC-2", "fail")],
        ), INVALID, "marked fail"),
        ("final phase with a sprint number", mutate("browser", phase="final"), INVALID, "sprint"),
    ]


def main():
    root = tempfile.mkdtemp(prefix="verdict-test-")
    path = os.path.join(root, "verdict.json")
    try:
        failures = []
        for name, verdict, expected, needle in cases():
            with open(path, "w", encoding="utf-8") as f:
                json.dump(verdict, f)
            proc = subprocess.run(
                ["python3", VALIDATOR, path], capture_output=True, text=True
            )
            got = OK if proc.returncode == 0 else INVALID
            ok = got == expected
            if ok and needle and needle not in proc.stdout:
                ok = False
                got = f"invalid, but not about {needle!r}"
            if not ok:
                failures.append(name)
                if proc.stdout.strip():
                    print(f"      {proc.stdout.strip().splitlines()[0]}")
            print(f"{'PASS' if ok else 'FAIL'}  {name:<44} want={expected:<8} got={got}")

        print()
        if failures:
            print(f"{len(failures)} failing case(s): {', '.join(failures)}")
            return 1
        print(f"all {len(cases())} verdict cases pass")
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
