#!/usr/bin/env python3
"""Regression tests for scripts/merge_verdicts.py.

In parallel evaluation this script is the only thing that turns several lens
verdicts into the one the loop acts on. If it merges leniently — takes the
higher of two scores, drops an issue, accepts a lens file left over from an
earlier round, or produces a verdict when a lens never reported — a round that
measured less than it claims reads as a pass, and nothing shows.

No framework — run it directly:

    python3 crystal-harness/scripts/test_merge_verdicts.py

Exits 0 when every case passes, 1 otherwise.
"""

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MERGE = os.path.join(HERE, "merge_verdicts.py")
VALIDATE = os.path.join(HERE, "validate_verdict.py")

FAILURES = []
COUNT = 0


def check(name, condition, detail=""):
    global COUNT
    COUNT += 1
    if not condition:
        FAILURES.append(name)
    print(f"{'PASS' if condition else 'FAIL'}  {name}{'' if condition else '  <- ' + str(detail)[:500]}")


def issue(issue_id, **extra):
    return {
        "id": issue_id,
        "summary": "DELETE /notes/{id} returns 204 but the row is still there",
        "repro": ["curl -X DELETE localhost:8000/notes/1", "sqlite3 app.db 'select count(*) from notes where id=1'"],
        "observed": "count is 1",
        "expected": "count is 0",
        "cause": {"file": "app/notes.py", "line": 42, "mechanism": "the handler never commits"},
        **extra,
    }


def criterion(cid, result, **extra):
    return {"id": cid, "text": f"criterion {cid}", "result": result, "evidence": "exercised", **extra}


class Project:
    """A scratch project with a git HEAD, a config, and a round directory."""

    def __init__(self, browser=False, round_dir=".harness/final/02", round_number=2):
        self.root = tempfile.mkdtemp(prefix="merge-test-")
        self.round_dir = os.path.join(self.root, round_dir)
        self.round_number = round_number
        self.browser = browser
        os.makedirs(os.path.join(self.round_dir, "lenses"))
        with open(os.path.join(self.root, ".harness", "config.json"), "w", encoding="utf-8") as f:
            json.dump({"harness": {"browserVerification": browser}}, f)
        for args in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"]):
            subprocess.run(["git", "-C", self.root, *args], check=True, capture_output=True)
        with open(os.path.join(self.root, "app.py"), "w", encoding="utf-8") as f:
            f.write("print('hi')\n")
        subprocess.run(["git", "-C", self.root, "add", "-A"], check=True, capture_output=True)
        subprocess.run(["git", "-C", self.root, "commit", "-q", "-m", "x"], check=True, capture_output=True)
        self.commit = subprocess.run(
            ["git", "-C", self.root, "rev-parse", "HEAD"], check=True, capture_output=True, text=True
        ).stdout.strip()
        self.sprint = int(os.path.basename(round_dir)) if "/sprints/" in round_dir else None
        self.phase = "sprint" if self.sprint else "final"

    def lens(self, name, **overrides):
        """A lens verdict that passes its own slice."""
        base = {
            "lens": name,
            "phase": self.phase,
            "sprint": self.sprint,
            "round": self.round_number,
            "commit": self.commit,
            "lensVerdict": "pass",
            "blockingIssues": [],
            "nonBlockingIssues": [],
            "evaluatedAt": "2026-11-20T06:00:00Z",
        }
        owner = "screen" if self.browser else "api"
        if name == "tests":
            base.update(scores={}, environment={"testsVerified": True, "testChanges": "reviewed"})
        elif name == "api":
            base.update(
                scores={"productDepth": 4, "functionality": 4},
                environment={"apiVerified": True, "persistenceVerified": True, "apiUrl": "http://localhost:8000"},
            )
        elif name == "code":
            base.update(scores={"codeQuality": 4}, environment={"codexReview": "absent"})
        elif name == "screen":
            base.update(
                scores={"productDepth": 5, "functionality": 4, "design": 4, "originality": 4, "craft": 3},
                environment={"verificationMode": "browser", "playwrightAvailable": True, "appUrl": "http://localhost:5173"},
            )
        if name == owner:
            base["criteria"] = [criterion("SPEC-1", "pass"), criterion("SPEC-2", "pass")]
        base.update(copy.deepcopy(overrides))
        return base

    def write(self, name, data):
        path = os.path.join(self.round_dir, "lenses", f"{name}.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(data if isinstance(data, str) else json.dumps(data))

    def write_all(self, **overrides):
        names = ["tests", "api", "code"] + (["screen"] if self.browser else [])
        for name in names:
            self.write(name, self.lens(name, **overrides.get(name, {})))

    def reproduction(self, issue_id, reproduced, **overrides):
        verify = os.path.join(self.round_dir, "lenses", "verify")
        os.makedirs(verify, exist_ok=True)
        data = {"issueId": issue_id, "round": self.round_number, "commit": self.commit,
                "reproduced": reproduced, "evidence": "followed the repro from a cold app"}
        data.update(overrides)
        with open(os.path.join(verify, f"{issue_id}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def merge(self):
        proc = subprocess.run(
            ["python3", MERGE, self.round_dir, "--round", str(self.round_number), "--project-dir", self.root],
            capture_output=True, text=True,
        )
        verdict = None
        path = os.path.join(self.round_dir, "verdict.json")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                verdict = json.load(f)
        return proc, verdict

    def valid(self):
        proc = subprocess.run(["python3", VALIDATE, os.path.join(self.round_dir, "verdict.json")], capture_output=True, text=True)
        return proc.returncode == 0

    def qa(self):
        with open(os.path.join(self.round_dir, "qa.md"), "r", encoding="utf-8") as f:
            return f.read()

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


def refused(name, setup, needle, browser=False, **project):
    """A scenario that must exit 2, mention `needle`, and write no verdict."""
    p = Project(browser=browser, **project)
    try:
        setup(p)
        proc, verdict = p.merge()
        check(name, proc.returncode == 2 and needle in proc.stdout and verdict is None, proc.stdout or proc.stderr)
    finally:
        p.close()


def main():
    # ---- the plain cases
    p = Project()
    try:
        p.write_all()
        proc, v = p.merge()
        check("three passing lenses merge into a pass", proc.returncode == 0 and v and v["overall"] == "pass", proc.stdout + proc.stderr)
        check("the merged verdict satisfies validate_verdict.py", v is not None and p.valid())
        check(
            "headless: visual dimensions are null, mode is headless",
            v and v["scores"]["design"] is None and v["scores"]["craft"] is None
            and v["environment"]["verificationMode"] == "headless" and v["environment"]["playwrightAvailable"] is False,
            v and v["scores"],
        )
        check("the merged verdict records which lenses it came from", v and v["environment"]["lenses"] == ["tests", "api", "code"])
        check("criteria come from the owning lens", v and [c["id"] for c in v["criteria"]] == ["SPEC-1", "SPEC-2"])
        check("environment flags come from the lens that owns each", v and v["environment"]["testsVerified"] is True
              and v["environment"]["apiVerified"] is True and v["environment"]["codexReview"] == "absent"
              and v["environment"]["testChanges"] == "reviewed")
        qa = p.qa() if v else ""
        check("qa.md is written with the lens table and the mode", "| api | pass |" in qa and "Verification mode: headless" in qa, qa[:300])
    finally:
        p.close()

    p = Project()
    try:
        p.write_all(api={
            "lensVerdict": "fail", "scores": {"productDepth": 4, "functionality": 3},
            "criteria": [criterion("SPEC-1", "pass"), criterion("SPEC-2", "fail")],
            "blockingIssues": [issue("B-api-1", criterionId="SPEC-2", dimension="functionality")],
        }, code={"nonBlockingIssues": [issue("N-code-1", dimension="codeQuality")]})
        proc, v = p.merge()
        check("one failing lens fails the round", proc.returncode == 0 and v and v["overall"] == "fail", proc.stdout)
        check("its blocking issue and the other lens's note are both kept",
              v and [i["id"] for i in v["blockingIssues"]] == ["B-api-1"] and [i["id"] for i in v["nonBlockingIssues"]] == ["N-code-1"])
        check("a failing merged verdict is still valid", v is not None and p.valid())
        check("no reproduction file means no verification field", v and "verification" not in v["blockingIssues"][0])
    finally:
        p.close()

    p = Project(browser=True)
    try:
        p.write_all(api={"scores": {"productDepth": 4, "functionality": 5}})
        proc, v = p.merge()
        check("browser: four lenses merge, mode is browser", proc.returncode == 0 and v and v["environment"]["verificationMode"] == "browser"
              and v["environment"]["lenses"] == ["tests", "api", "screen", "code"], proc.stdout)
        check("a dimension two lenses score takes the lower score",
              v and v["scores"]["productDepth"] == 4 and v["scores"]["functionality"] == 4, v and v["scores"])
        check("browser: the screen lens owns the criteria and the visual scores",
              v and len(v["criteria"]) == 2 and v["scores"]["design"] == 4 and p.valid())
    finally:
        p.close()

    p = Project(browser=True)
    try:
        p.write_all(screen={
            "lensVerdict": "fail",
            "scores": {"productDepth": None, "functionality": None, "design": None, "originality": None, "craft": None},
            "environment": {"verificationMode": "degraded", "playwrightAvailable": False, "degradedReason": "MCP did not respond"},
            "criteria": [criterion("SPEC-1", "not_verified"), criterion("SPEC-2", "not_verified")],
            "blockingIssues": [issue("B-screen-1")],
        })
        proc, v = p.merge()
        check("a degraded screen lens yields a degraded, failing verdict",
              proc.returncode == 0 and v and v["overall"] == "fail" and v["environment"]["degraded"] is True
              and v["scores"]["productDepth"] is None and p.valid(), proc.stdout)
    finally:
        p.close()

    p = Project(round_dir=".harness/sprints/03", round_number=1)
    try:
        p.write_all(api={"criteria": [criterion("AC-1", "pass")]})
        proc, v = p.merge()
        check("a sprint round carries its sprint number", proc.returncode == 0 and v and v["phase"] == "sprint" and v["sprint"] == 3 and p.valid(), proc.stdout)
    finally:
        p.close()

    # ---- reproduction results are annotations, never a way out
    p = Project()
    try:
        failing = {"lensVerdict": "fail", "criteria": [criterion("SPEC-1", "fail"), criterion("SPEC-2", "fail")],
                   "blockingIssues": [issue("B-api-1"), issue("B-api-2")]}
        p.write_all(api=failing)
        p.reproduction("B-api-1", True)
        p.reproduction("B-api-2", False)
        proc, v = p.merge()
        marks = {i["id"]: i.get("verification") for i in (v or {}).get("blockingIssues", [])}
        check("each blocking issue is annotated with its reproduction result",
              marks == {"B-api-1": "reproduced", "B-api-2": "not_reproduced"}, proc.stdout + str(marks))
        check("an issue nobody could reproduce is still blocking and the round still fails",
              v and v["overall"] == "fail" and len(v["blockingIssues"]) == 2 and p.valid())
        check("qa.md says which issue was not reproduced", v is not None and "NOT reproduced" in p.qa())
    finally:
        p.close()

    def stale_reproduction(p):
        p.write_all(api={"lensVerdict": "fail", "criteria": [criterion("SPEC-1", "fail")], "blockingIssues": [issue("B-api-1")]})
        p.reproduction("B-api-1", False, round=1)

    refused("a reproduction left over from another round is refused", stale_reproduction, "stale reproduction")

    def unknown_reproduction(p):
        p.write_all()
        p.reproduction("B-api-9", False)

    refused("a reproduction for an issue that is not in this round is refused", unknown_reproduction, "not a blocking issue")

    # ---- refusing to merge
    def missing(p):
        p.write_all()
        os.remove(os.path.join(p.round_dir, "lenses", "code.json"))

    refused("a missing lens means no verdict", missing, "lenses/code.json: missing")

    def missing_screen(p):
        for name in ("tests", "api", "code"):
            p.write(name, p.lens(name))

    refused("browser configured but no screen lens means no verdict", missing_screen, "lenses/screen.json: missing", browser=True)
    refused("an unparseable lens file", lambda p: (p.write_all(), p.write("api", "{ not json")), "could not be parsed")
    refused("a lens file from an earlier round", lambda p: p.write_all(code={"round": 1}), "stale or misdirected")
    refused("a lens file that graded a different commit", lambda p: p.write_all(tests={"commit": "0" * 40}), "stale or misdirected")
    refused("a lens file for the wrong sprint", lambda p: p.write_all(api={"sprint": 4, "criteria": [criterion("AC-1", "pass")]}),
            "sprint is 4", round_dir=".harness/sprints/03", round_number=1)
    refused("a lens scoring a dimension that is not its own",
            lambda p: p.write_all(code={"scores": {"codeQuality": 4, "functionality": 5}}), "exactly the keys")
    refused("a lens leaving out one of its dimensions",
            lambda p: p.write_all(api={"scores": {"functionality": 4}}), "exactly the keys")
    refused("criteria reported by a lens that does not own them",
            lambda p: p.write_all(code={"criteria": [criterion("SPEC-9", "pass")]}), "only the api lens reports criteria")
    refused("the owning lens reporting no criteria", lambda p: p.write_all(api={"criteria": []}), "reported none")
    refused("a lens that passes with a blocking issue",
            lambda p: p.write_all(api={"blockingIssues": [issue("B-api-1")]}), "lensVerdict is pass but blockingIssues")
    refused("a lens that passes below a threshold",
            lambda p: p.write_all(api={"scores": {"productDepth": 3, "functionality": 4}}), "below its threshold")
    refused("a lens that passes with a null score",
            lambda p: p.write_all(code={"scores": {"codeQuality": None}}), "is not an integer")
    refused("a lens that passes with a failed criterion",
            lambda p: p.write_all(api={"criteria": [criterion("SPEC-1", "fail")]}), "is marked fail")
    refused("a lens that passes with an unexplained gap",
            lambda p: p.write_all(api={"criteria": [criterion("SPEC-1", "pass"), criterion("SPEC-2", "not_verified")]}),
            "not_verified without browserOnly")
    refused("a lens that fails without a blocking issue",
            lambda p: p.write_all(code={"lensVerdict": "fail"}), "nothing to work on")
    refused("an issue id that does not name its lens",
            lambda p: p.write_all(api={"lensVerdict": "fail", "criteria": [criterion("SPEC-1", "fail")], "blockingIssues": [issue("B-1")]}),
            "must match ^B-api-")
    refused("a malformed issue",
            lambda p: p.write_all(code={"nonBlockingIssues": [{"id": "N-code-1", "summary": "x"}]}), "missing required key")
    refused("a lens that sets the verification field itself",
            lambda p: p.write_all(api={"lensVerdict": "fail", "criteria": [criterion("SPEC-1", "fail")],
                                       "blockingIssues": [issue("B-api-1", verification="reproduced")]}),
            "only the merge writes that field")
    refused("a screen lens passing in degraded mode",
            lambda p: p.write_all(screen={"environment": {"verificationMode": "degraded", "playwrightAvailable": False}}),
            "degraded mode", browser=True)
    refused("a missing environment flag",
            lambda p: p.write_all(tests={"environment": {"testsVerified": True}}), "missing 'testChanges'")
    refused("lenses that each pass but leave nothing executed",
            lambda p: p.write_all(tests={"environment": {"testsVerified": False, "testChanges": "none"}},
                                  api={"environment": {"apiVerified": False, "persistenceVerified": False}}),
            "merged verdict")

    # ---- a refusal leaves the previous round's verdict alone
    p = Project(round_dir=".harness/sprints/03", round_number=2)
    try:
        earlier = {"round": 1, "overall": "fail", "marker": "previous round"}
        with open(os.path.join(p.round_dir, "verdict.json"), "w", encoding="utf-8") as f:
            json.dump(earlier, f)
        p.write_all(api={"criteria": [criterion("AC-1", "pass")]})
        os.remove(os.path.join(p.round_dir, "lenses", "tests.json"))
        proc, v = p.merge()
        check("a refused merge does not touch the verdict already in the directory", proc.returncode == 2 and v == earlier, proc.stdout)
        p.write("tests", p.lens("tests"))
        proc, v = p.merge()
        check("once the lens is there the merge replaces it", proc.returncode == 0 and v and v["round"] == 2 and "marker" not in v, proc.stdout)
    finally:
        p.close()

    proc = subprocess.run(["python3", MERGE, "/tmp", "--round", "1", "--project-dir", "/tmp"], capture_output=True, text=True)
    check("a path that is not a round directory exits 1", proc.returncode == 1, proc.stderr)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} failing case(s): {', '.join(FAILURES)}")
        return 1
    print(f"all {COUNT} merge cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
