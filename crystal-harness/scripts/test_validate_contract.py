#!/usr/bin/env python3
"""Regression tests for the contract validator.

The criterion cap only holds while this script rejects. If it stops rejecting,
contracts drift back past the cap with no visible symptom other than a slower,
more expensive run.

No framework — run it directly:

    python3 crystal-harness/scripts/test_validate_contract.py

Exits 0 when every case matches, 1 otherwise.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

VALIDATOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "validate_contract.py")

OK, INVALID = "ok", "invalid"


def contract(criteria=5, scope=3, extra="", criteria_block=None):
    scope_lines = "\n".join(f"{i}. Item {i}" for i in range(1, scope + 1))
    if criteria_block is None:
        criteria_block = "\n".join(
            f"- **AC-{i}** — Given a state, when an action, then a result." for i in range(1, criteria + 1)
        )
    return f"""# Sprint 01 contract

## Goal
A user can do a thing.

## Scope
{scope_lines}

## Out of scope for this sprint
Nothing.

## Pinned interfaces
- `POST /api/x → 201, id`

## Acceptance criteria
{criteria_block}

## Verification notes
Start the backend.

## Spec coverage
Core flow.
{extra}"""


def cases():
    return [
        ("minimal contract", contract(), None, OK, None),
        ("exactly at the default cap", contract(criteria=20), None, OK, None),
        ("over the default cap", contract(criteria=21), None, INVALID, "exceeds the cap of 20"),
        ("config raises the cap", contract(criteria=25), {"harness": {"maxAcceptanceCriteria": 25}}, OK, None),
        ("config lowers the cap", contract(criteria=13), {"harness": {"maxAcceptanceCriteria": 12}}, INVALID, "cap of 12"),
        ("invalid cap in config", contract(), {"harness": {"maxAcceptanceCriteria": 0}}, INVALID, "positive integer"),
        ("missing criteria section", contract().replace("## Acceptance criteria", "## Criteria"), None, INVALID, "missing section '## Acceptance criteria'"),
        ("empty criteria section", contract(criteria_block="None yet."), None, INVALID, "no '- **AC-n**' entries"),
        ("duplicate id", contract(criteria_block="- **AC-1** — a\n- **AC-1** — b"), None, INVALID, "duplicate criterion id AC-1"),
        ("too few scope items", contract(scope=2), None, INVALID, "has 2 numbered items"),
        ("too many scope items", contract(scope=8), None, INVALID, "has 8 numbered items"),
        ("fenced AC lines are not counted", contract(
            criteria=20, extra="\n```\n- **AC-99** — example\n```\n",
        ), None, OK, None),
        ("amendment rewords an existing id", contract(
            extra="\n---\n\n## Evaluator review — round 1\nDecision: accepted-with-amendments\n1. [amendment] AC-2 — new wording\n",
        ), None, OK, None),
        ("amendment adds a new id", contract(
            extra="\n---\n\n## Evaluator review — round 1\nDecision: accepted-with-amendments\n1. [amendment] AC-6 — extra criterion\n",
        ), None, INVALID, "references AC-6"),
        ("revision notes name an unknown id", contract(
            extra="\n## Revision 1 changes\n- AC-9 — added\n",
        ), None, INVALID, "references AC-9"),
    ]


def main():
    root = tempfile.mkdtemp(prefix="contract-test-")
    path = os.path.join(root, "contract.md")
    config_path = os.path.join(root, "config.json")
    try:
        failures = []
        for name, text, config, expected, needle in cases():
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            if os.path.exists(config_path):
                os.remove(config_path)
            if config is not None:
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f)
            proc = subprocess.run(
                ["python3", VALIDATOR, path, "--config", config_path],
                capture_output=True, text=True,
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
        print(f"all {len(cases())} contract cases pass")
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
