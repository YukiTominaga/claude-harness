#!/usr/bin/env python3
"""Generate the eval cases from one table, so they cannot drift apart.

Every case asks the same thing — a final assessment of a small API by the
plugin's evaluator — and differs only in the fixture it is given and in what a
correct verdict looks like. Edit CASES or the templates here, run this script,
and commit the result:

    python3 evals/_fixtures/make_cases.py

The case directories it writes are what `claude plugin eval` reads; nothing at
eval time depends on this script.
"""

import json
import os
import re
import shutil

EVALS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# mutation -> (what was seeded, what a blocking issue must mention)
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
    "full-suite": ("notes-a full", "The Notes API as it passed a final assessment, with its own test suite."),
    "second-implementation": ("notes-b full", "A second, independently written implementation of the same spec."),
}

# The tracker cases. Each defect here needs more than one request to an endpoint
# to show — why each is hard is said next to it in mutate.py — and the app is
# large enough that trying everything once is no longer a plan.
TRACKER_SEEDED = {
    "reopen-keeps-completed-at": (
        "A task re-opened from done keeps its completed_at; the spec says leaving done sets it back to null.",
        r"completed_at|completedAt|completion (?:time|timestamp|date)",
    ),
    "move-into-archived-project": (
        "A task can be moved into an archived project; the spec says that is 409.",
        r"mov\w*[\s\S]{0,300}archiv|archiv\w*[\s\S]{0,300}mov",
    ),
    "deleted-blocker-still-blocks": (
        "Deleting a task leaves the relations in which it was the blocker, so what waited on it can never finish.",
        r"(?:delet|remov)\w*[\s\S]{0,300}(?:block|wait)|(?:block|wait)\w*[\s\S]{0,300}(?:delet|remov)|dangling",
    ),
    "indirect-cycle-accepted": (
        "A cycle of three blocking relations is accepted; only a direct two-task cycle is refused.",
        r"cycl|circular|transitiv|indirect",
    ),
    "total-counts-the-page": (
        "GET /tasks reports the size of the page as total, not the number of tasks that match.",
        r"\btotal\b",
    ),
    "patch-tags-not-normalised": (
        "PATCH stores tags as sent — not lower-cased, duplicates kept — so a tag filter misses them.",
        r"\btags?\b[\s\S]{0,300}(?:lower|upper|normali[sz]|\bcase|dedup|duplicat)|(?:lower|upper|normali[sz]|\bcase|dedup|duplicat)[\s\S]{0,300}\btags?\b",
    ),
}
TRACKER_CLEAN = {
    "full-suite": ("tracker full", "The Tracker API untouched, with its own test suite."),
    "decoys": (
        "tracker full decoy-cascading-deletes decoy-move-check-in-sql decoy-completed-at-case",
        "The Tracker API rewritten in three places to read like a defect while behaving the same.",
    ),
}

PROMPT = """---
description: {description}
tags: [{tags}]
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
# the file. Two things keep the match inside that array: the scan from its
# opening bracket stops at the next top-level key, whichever the evaluator wrote
# after blockingIssues, and so does every "within N characters" gap inside a key
# — otherwise a word in the last blocking issue could pair with one in the first
# non-blocking note.
STOP = r'(?!"(?:nonBlockingIssues|criteria|scores|environment|evaluatedAt)"\s*:)'
GRADER_NAMES = """---
type: regex
target: {target}
flags: is
weight: 2
pattern: '"blockingIssues"\\s*:\\s*\\[(?:{stop}[\\s\\S])*?(?:{key})'
---
"""


def bounded(key):
    """The key with each `[\\s\\S]{{0,N}}` gap unable to cross into another top-level key."""
    return re.sub(r"\[\\s\\S\]\{0,(\d+)\}", lambda m: "(?:" + STOP + r"[\s\S]){0," + m.group(1) + "}", key)


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
    write(os.path.join(directory, "prompt.md"), PROMPT.format(description=json.dumps(description, ensure_ascii=False), tags=tag))
    for grader_name, content in graders.items():
        write(os.path.join(directory, "graders", grader_name + ".md"), content)


def seeded(prefix, tags, fixture, table):
    for mutation, (description, key) in table.items():
        assert "'" not in key, f"{mutation}: a single quote would end the YAML scalar"
        case(
            f"{prefix}{mutation}", "Seeded defect: " + description, tags, f"{fixture} thin {mutation}",
            {
                "verdict-written": GRADER_WRITTEN,
                "fails-the-round": GRADER_FAILS.format(target=VERDICT_FILE),
                "names-the-defect": GRADER_NAMES.format(target=VERDICT_FILE, stop=STOP, key=bounded(key)),
            },
        )


def clean(prefix, tags, table):
    for name, (setup_args, description) in table.items():
        case(
            f"{prefix}{name}", "No seeded defect: " + description, tags, setup_args,
            {
                "verdict-written": GRADER_WRITTEN,
                "passes-the-round": GRADER_PASSES.format(target=VERDICT_FILE),
                "no-blocking-issues": GRADER_NO_BLOCKING.format(target=VERDICT_FILE),
            },
        )


def main():
    seeded("seeded-", "seeded, notes", "notes-a", SEEDED)
    clean("clean-", "clean, notes", CLEAN)
    seeded("seeded-tracker-", "seeded, tracker", "tracker", TRACKER_SEEDED)
    clean("clean-tracker-", "clean, tracker", TRACKER_CLEAN)
    total_seeded, total_clean = len(SEEDED) + len(TRACKER_SEEDED), len(CLEAN) + len(TRACKER_CLEAN)
    print(f"wrote {total_seeded} seeded and {total_clean} clean cases under {EVALS}")


if __name__ == "__main__":
    main()
