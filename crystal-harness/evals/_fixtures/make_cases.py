#!/usr/bin/env python3
"""Generate the eval cases from one table, so they cannot drift apart.

Every case asks the same thing — a final assessment of a small Notes API by the
plugin's evaluator — and differs only in the fixture it is given and in what a
correct verdict looks like. Edit CASES or the templates here, run this script,
and commit the result:

    python3 evals/_fixtures/make_cases.py

The case directories it writes are what `claude plugin eval` reads; nothing at
eval time depends on this script.
"""

import json
import os
import shutil

EVALS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# name -> (fixture, tests, mutation, what a blocking issue must mention)
SEEDED = {
    "delete-not-committed": (
        "DELETE returns 204 but the delete is rolled back; the note is still there.",
        r"commit|roll(?:ed|s)?[ -]?back|transaction|still (?:there|present|exists|readable|returned|in the)|not (?:removed|deleted|persisted)|survives|reappears|remains",
    ),
    "delete-unknown-returns-204": (
        "DELETE of an id that does not exist returns 204 instead of 404.",
        r"(?:unknown|non-?existent|missing|never[- ]existed|does not exist|doesn.t exist|no such|absent|already[- ]deleted)[\s\S]{0,200}\b(?:204|404)\b|\b(?:204|404)\b[\s\S]{0,200}(?:unknown|non-?existent|missing|never[- ]existed|does not exist|doesn.t exist|no such|absent|already[- ]deleted)",
    ),
    "list-newest-first": (
        "GET /notes returns notes newest first; the spec says creation order, oldest first.",
        r"\border\b|ordering|sorted|descending|\bDESC\b|reverse|newest|oldest",
    ),
    "restart-wipes-data": (
        "The datastore file is deleted when the server starts, so notes do not survive a restart.",
        r"restart|re-start|os\.remove|wipe|startup|start-up|on start|persist",
    ),
    "invalid-json-returns-422": (
        "Invalid JSON in a POST body returns 422; the spec says 400.",
        r"(?:invalid|malformed|not valid|unparse?able|bad) JSON[\s\S]{0,240}\b(?:400|422)\b|\b(?:400|422)\b[\s\S]{0,240}(?:invalid|malformed|not valid|unparse?able|bad) JSON",
    ),
    "body-discarded": (
        "POST accepts a body and stores an empty string; the note comes back without it.",
        r"\bbody\b",
    ),
}
CLEAN = {
    "full-suite": ("notes-a", "full", "The Notes API as it passed a final assessment, with its own test suite."),
    "second-implementation": ("notes-b", "full", "A second, independently written implementation of the same spec."),
}

PROMPT = """---
description: {description}
tags: [{tag}]
max_turns: 40
timeout_seconds: 3000
allowed_tools: [Agent, Read, Bash, Write, Glob, Grep, Skill]
---

Run a final assessment of the project in this directory with the harness evaluator.
That is the whole task: do not run a status or resume command first, whatever a
session-start note suggests.

Spawn the `crystal-harness:harness-evaluator` agent — do not give it a name — and
give it exactly this and nothing else:

> Final assessment, round 01. This is the first evaluation of this round, not a
> re-check. Read `.harness/config.json` and `.harness/spec.md`; the round directory
> is `.harness/final/01/`. Write `qa.md` and `verdict.json` there.
>
> Environment note: your commands run in a sandbox. If a command's output ends with
> a line like `/bin/bash: line 1: …: Read-only file system` and the tool reports a
> non-zero exit code, that is the sandbox's own bookkeeping after your command
> finished, not the command failing. Judge a command by its own output.

Do not tell the agent anything about the code, and do not grade the project
yourself. When it returns, reply with the overall verdict, the scores, and the id
and one-line summary of each blocking issue, exactly as `verdict.json` has them.
"""

VERDICT_FILE = "{ source: file, path: .harness/final/01/verdict.json }"

GRADER_WRITTEN = """---
type: file_exists
path: .harness/final/01/verdict.json
---
"""

# The defect has to be named among the blocking issues, not merely somewhere in
# the file: the tempered pattern stops at the nonBlockingIssues key.
GRADER_NAMES = """---
type: regex
target: {target}
flags: is
weight: 2
pattern: '"blockingIssues"\\s*:\\s*\\[(?:(?!"nonBlockingIssues")[\\s\\S])*?(?:{key})'
---
"""

GRADER_FAILS = """---
type: regex
target: {target}
pattern: '"overall"\\s*:\\s*"fail"'
---
"""

GRADER_PASSES = """---
type: regex
target: {target}
weight: 2
pattern: '"overall"\\s*:\\s*"pass"'
---
"""

GRADER_NO_BLOCKING = """---
type: regex
target: {target}
pattern: '"blockingIssues"\\s*:\\s*\\[\\s*\\]'
---
"""


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def case(name, description, tag, setup_args, graders):
    directory = os.path.join(EVALS, name)
    shutil.rmtree(directory, ignore_errors=True)
    write(os.path.join(directory, "case.yaml"),
          f'schema_version: "1.1"\nname: {name}\ncontext:\n  scaffold_script: fixture.sh\n')
    write(os.path.join(directory, "fixture.sh"),
          '#!/bin/bash\nexec bash "$(dirname "$0")/../_fixtures/setup.sh" ' + setup_args + "\n")
    os.chmod(os.path.join(directory, "fixture.sh"), 0o755)
    # json.dumps gives a double-quoted scalar, valid YAML whatever the description contains.
    write(os.path.join(directory, "prompt.md"), PROMPT.format(description=json.dumps(description), tag=tag))
    for grader_name, content in graders.items():
        write(os.path.join(directory, "graders", grader_name + ".md"), content)


def main():
    for mutation, (description, key) in SEEDED.items():
        assert "'" not in key, f"{mutation}: a single quote would end the YAML scalar"
        case(
            f"seeded-{mutation}", "Seeded defect: " + description, "seeded", f"notes-a thin {mutation}",
            {
                "verdict-written": GRADER_WRITTEN,
                "fails-the-round": GRADER_FAILS.format(target=VERDICT_FILE),
                "names-the-defect": GRADER_NAMES.format(target=VERDICT_FILE, key=key),
            },
        )
    for name, (fixture, tests, description) in CLEAN.items():
        case(
            f"clean-{name}", "No seeded defect: " + description, "clean", f"{fixture} {tests}",
            {
                "verdict-written": GRADER_WRITTEN,
                "passes-the-round": GRADER_PASSES.format(target=VERDICT_FILE),
                "no-blocking-issues": GRADER_NO_BLOCKING.format(target=VERDICT_FILE),
            },
        )
    print(f"wrote {len(SEEDED)} seeded and {len(CLEAN)} clean cases under {EVALS}")


if __name__ == "__main__":
    main()
