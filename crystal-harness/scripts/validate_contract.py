#!/usr/bin/env python3
"""Validate the shape of a sprint contract.md — deterministically.

The sprint-contract skill caps acceptance criteria at
`harness.maxAcceptanceCriteria`. A cap written only in prose did not hold: every
coverage rule and every review question pushes toward one more criterion, and
real runs drifted to 34–40 per sprint, which made contracting, building and QA
all heavier. This script is what makes the cap a rule instead of a suggestion.

Checks:
- `## Acceptance criteria` exists and holds at least one `- **AC-n**` entry;
- the entry count is at most the cap (config, default 20);
- no id appears twice;
- `## Scope` holds 3–7 numbered items;
- review blocks and revision notes only reference ids that exist, so an
  amendment cannot smuggle criteria past the cap.

Usage:
    python3 validate_contract.py .harness/sprints/03/contract.md [--config .harness/config.json]

Exits 0 printing "ok" when the contract conforms; exits 1 listing every
violation otherwise, so the generator can be sent back once with the full list.
"""

import argparse
import json
import os
import re
import sys

DEFAULT_MAX_CRITERIA = 20
SCOPE_MIN, SCOPE_MAX = 3, 7

HEADING = re.compile(r"^##\s+(.+?)\s*$")
CRITERION = re.compile(r"^- \*\*(AC-\d+)\*\*")
SCOPE_ITEM = re.compile(r"^\d+\.\s")
ID_REF = re.compile(r"\bAC-\d+\b")


def sections(text):
    """Map each `## ` heading to its lines, ignoring fenced code blocks."""
    result = {}
    current = None
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = HEADING.match(line)
        if match:
            current = match.group(1)
            result.setdefault(current, [])
            continue
        if current is not None:
            result[current].append(line)
    return result


def load_cap(config_path):
    if not config_path or not os.path.exists(config_path):
        return DEFAULT_MAX_CRITERIA
    with open(config_path, encoding="utf-8") as fh:
        config = json.load(fh)
    cap = (config.get("harness") or {}).get("maxAcceptanceCriteria", DEFAULT_MAX_CRITERIA)
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
        raise ValueError(f"harness.maxAcceptanceCriteria must be a positive integer, got {cap!r}")
    return cap


def validate(text, cap):
    errors = []
    by_heading = sections(text)

    criteria_lines = by_heading.get("Acceptance criteria")
    if criteria_lines is None:
        errors.append("missing section '## Acceptance criteria'")
        ids = []
    else:
        ids = [m.group(1) for m in (CRITERION.match(line) for line in criteria_lines) if m]
        if not ids:
            errors.append("'## Acceptance criteria' has no '- **AC-n**' entries")
        if len(ids) > cap:
            errors.append(
                f"{len(ids)} acceptance criteria exceeds the cap of {cap} "
                "(harness.maxAcceptanceCriteria). Move trailing scope items to "
                "'Out of scope' rather than compressing criteria."
            )
        seen = set()
        for cid in ids:
            if cid in seen:
                errors.append(f"duplicate criterion id {cid}")
            seen.add(cid)

    scope_lines = by_heading.get("Scope")
    if scope_lines is None:
        errors.append("missing section '## Scope'")
    else:
        count = sum(1 for line in scope_lines if SCOPE_ITEM.match(line))
        if not SCOPE_MIN <= count <= SCOPE_MAX:
            errors.append(f"'## Scope' has {count} numbered items; expected {SCOPE_MIN}–{SCOPE_MAX}")

    known = set(ids)
    for heading, lines in by_heading.items():
        if not (heading.startswith("Evaluator review") or heading.startswith("Revision")):
            continue
        for ref in sorted({r for line in lines for r in ID_REF.findall(line)} - known):
            errors.append(
                f"'## {heading}' references {ref}, which is not in '## Acceptance criteria'. "
                "Amendments reword existing ids; they do not add new ones."
            )

    return ids, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("contract")
    parser.add_argument("--config", default=os.path.join(".harness", "config.json"))
    args = parser.parse_args()

    try:
        with open(args.contract, encoding="utf-8") as fh:
            text = fh.read()
        cap = load_cap(args.config)
    except (OSError, ValueError) as exc:
        print(f"{args.contract}: {exc}")
        sys.exit(1)

    ids, errors = validate(text, cap)
    if errors:
        for message in errors:
            print(f"{args.contract}: {message}")
        sys.exit(1)
    print(f"ok ({len(ids)} criteria, cap {cap})")


if __name__ == "__main__":
    main()
