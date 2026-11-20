#!/usr/bin/env python3
"""Report what a round did to the project's tests — deterministically.

The evaluator leans on the project's own test suite twice: a failing suite is
conclusive, and on a re-check round a passing suite is what lets a criterion
that passed before be carried instead of re-verified. But the generator writes
that suite. A change that can modify the check that judges it has a way to pass
without being correct: delete the test, skip it, or point the test command at
something that always succeeds. None of that shows up as a red suite.

This script reads the diff between the commit a round started from and HEAD
and reports, for the evaluator and for validate_verdict.py:

- test files added, modified, deleted, renamed;
- test cases removed and added inside modified test files;
- skip / only markers added;
- a changed `scripts.test` in package.json.

`weakened` is true when any of those reduces what the suite checks. It is a
conservative signal, not a verdict — a legitimate refactor can trip it. The cost
of a false alarm is one round verified in full instead of carried; the cost of
a miss is a pass nobody earned.

Usage:
    python3 test_changes.py --base <commit> --out .harness/final/02/test-changes.json
    python3 test_changes.py            # no base: everything since the empty tree

Exit 0 with the report written (weakened or not). Exit 1 if git could not
produce the diff — the orchestrator must then say the report is absent, not
assume the tests are untouched.
"""

import argparse
import json
import os
import re
import subprocess
import sys

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

TEST_PATH = re.compile(
    r"""(
        (^|/)(tests?|__tests__|specs?|e2e|integration)(/|$)      # a test directory
      | (^|/)test_[^/]+\.py$                                     # test_x.py
      | [._-](test|spec)\.[A-Za-z0-9]+$                          # x.test.ts, x_spec.rb
      | _test\.(go|py|rb|exs?|dart)$                             # x_test.go
      | Tests?\.(java|kt|kts|cs|scala|swift)$                    # XTest.java
    )""",
    re.VERBOSE,
)

TEST_DECL = re.compile(
    r"""(
        ^\s*(it|test|describe|context)(\.(each|concurrent))?\s*[(`]    # JS / TS
      | ^\s*(async\s+)?def\s+test_\w*\s*\(                            # Python
      | ^\s*func\s+(Test|Benchmark|Fuzz)\w*\s*\(                      # Go
      | ^\s*\#\[(\w+::)?test\]                                        # Rust
      | ^\s*@(Test|ParameterizedTest|Theory|Fact)\b                   # JVM / .NET
      | ^\s*(it|specify|scenario|test)\s+["']                         # Ruby
    )""",
    re.VERBOSE,
)

SKIP_MARKER = re.compile(
    r"""(
        \b(it|test|describe|context)\.(skip|todo|only|failing)\b
      | \b(xit|xtest|xdescribe|fit|fdescribe)\s*\(
      | @pytest\.mark\.(skip|skipif|xfail)\b
      | \bpytest\.(skip|xfail)\s*\(
      | \bunittest\.(skip|skipIf|skipUnless|expectedFailure)\b
      | \bt\.Skip(f|Now)?\s*\(
      | \#\[ignore\b
      | @(Disabled|Ignore)\b
      | \bSkip\s*=\s*"
    )""",
    re.VERBOSE,
)


def git(repo, *args):
    proc = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def is_test_path(path):
    return bool(TEST_PATH.search(path))


def name_status(repo, base):
    """[(status, old_path, new_path)] for every path changed between base and HEAD."""
    out = git(repo, "diff", "-M", "--name-status", "-z", base, "HEAD")
    fields = out.split("\0")
    changes, i = [], 0
    while i < len(fields) and fields[i]:
        status = fields[i]
        if status[0] in ("R", "C"):
            changes.append((status[0], fields[i + 1], fields[i + 2]))
            i += 3
        else:
            changes.append((status[0], fields[i + 1], fields[i + 1]))
            i += 2
    return changes


def changed_lines(repo, base, old_path, new_path):
    """(removed lines, added lines with their new line numbers) for one file."""
    out = git(repo, "diff", "-M", "-U0", base, "HEAD", "--", old_path, new_path)
    removed, added, new_line = [], [], 0
    for line in out.splitlines():
        if line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            new_line = int(match.group(1)) if match else 0
        elif line.startswith("+++") or line.startswith("---"):
            continue
        elif line.startswith("+"):
            added.append((new_line, line[1:]))
            new_line += 1
        elif line.startswith("-"):
            removed.append(line[1:])
    return removed, added


def package_test_script(repo, rev, path):
    try:
        data = json.loads(git(repo, "show", f"{rev}:{path}"))
    except Exception:  # noqa: BLE001 - absent at that revision, or not JSON
        return None
    scripts = data.get("scripts") if isinstance(data, dict) else None
    value = scripts.get("test") if isinstance(scripts, dict) else None
    return value if isinstance(value, str) else None


def build_report(repo, base):
    head = git(repo, "rev-parse", "HEAD").strip()
    base_sha = EMPTY_TREE if base is None else git(repo, "rev-parse", f"{base}^{{commit}}").strip()

    files = {"added": [], "modified": [], "deleted": [], "renamed": []}
    cases = {"added": 0, "removed": 0}
    skip_markers, command_changes, reasons = [], [], []

    for status, old_path, new_path in name_status(repo, base_sha):
        if os.path.basename(new_path) == "package.json" and status in ("M", "R"):
            before = package_test_script(repo, base_sha, old_path)
            after = package_test_script(repo, head, new_path)
            if before is not None and before != after:
                command_changes.append({"file": new_path, "before": before, "after": after})
                reasons.append(f"{new_path}: scripts.test changed from {before!r} to {after!r}")

        old_is_test, new_is_test = is_test_path(old_path), is_test_path(new_path)
        if not (old_is_test or new_is_test):
            continue

        if status == "D":
            files["deleted"].append(old_path)
            reasons.append(f"{old_path}: test file deleted")
            continue
        if status == "A":
            files["added"].append(new_path)
        elif status == "R":
            files["renamed"].append([old_path, new_path])
            if old_is_test and not new_is_test:
                reasons.append(f"{old_path}: renamed to {new_path}, which no longer looks like a test file")
        else:
            files["modified"].append(new_path)

        removed, added = changed_lines(repo, base_sha, old_path, new_path)
        removed_decls = sum(1 for text in removed if TEST_DECL.search(text))
        added_decls = sum(1 for _n, text in added if TEST_DECL.search(text))
        cases["removed"] += removed_decls
        cases["added"] += added_decls
        if status != "A" and removed_decls > added_decls:
            reasons.append(
                f"{new_path}: {removed_decls} test declaration(s) removed, {added_decls} added"
            )
        for number, text in added:
            if SKIP_MARKER.search(text):
                skip_markers.append({"file": new_path, "line": number, "text": text.strip()[:200]})
                reasons.append(f"{new_path}:{number}: skip/only marker added")

    return {
        "base": base_sha,
        "head": head,
        "testFiles": files,
        "testCases": cases,
        "skipMarkersAdded": skip_markers,
        "testCommandChanged": command_changes,
        "weakened": bool(reasons),
        "reasons": reasons,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=None, help="commit the round started from; omit for the empty tree")
    parser.add_argument("--out", default=None, help="write the JSON report here as well as to stdout")
    parser.add_argument("--repo", default=os.getcwd())
    args = parser.parse_args()

    try:
        report = build_report(args.repo, args.base)
    except Exception as exc:  # noqa: BLE001
        if args.out and os.path.exists(args.out):
            os.remove(args.out)  # never leave an earlier round's report to be read as this one's
        print(f"test_changes: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
