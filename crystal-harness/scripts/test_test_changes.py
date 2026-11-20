#!/usr/bin/env python3
"""Regression tests for scripts/test_changes.py.

The report it produces decides whether a re-check round may carry earlier
passes on the strength of the test suite. If it stops noticing a deleted or
skipped test, the suite the generator wrote goes back to vouching for itself,
and nothing looks different. So each way of weakening a suite has a case here,
and so does each legitimate change that must not trip the alarm.

No framework — run it directly:

    python3 crystal-harness/scripts/test_test_changes.py

Exits 0 when every case passes, 1 otherwise.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_changes.py")

FAILURES = []
COUNT = 0


def check(name, condition, detail=""):
    global COUNT
    COUNT += 1
    if not condition:
        FAILURES.append(name)
    print(f"{'PASS' if condition else 'FAIL'}  {name}{'' if condition else '  <- ' + str(detail)[:400]}")


def git(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True)


def write(repo, path, content):
    full = os.path.join(repo, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)


def commit(repo, message):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return subprocess.run(
        ["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


JS_TESTS = """import { add } from '../src/math'

describe('add', () => {
  it('adds two numbers', () => {
    expect(add(1, 2)).toBe(3)
  })
  it('handles negatives', () => {
    expect(add(-1, -2)).toBe(-3)
  })
})
"""

PY_TESTS = """def test_create_note(client):
    assert client.post("/notes", json={"title": "a"}).status_code == 201


def test_delete_note(client):
    assert client.delete("/notes/1").status_code == 204
"""


def new_repo():
    repo = tempfile.mkdtemp(prefix="test-changes-")
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    write(repo, "src/math.ts", "export const add = (a: number, b: number) => a + b\n")
    write(repo, "src/__tests__/math.test.ts", JS_TESTS)
    write(repo, "tests/test_notes.py", PY_TESTS)
    write(repo, "package.json", json.dumps({"name": "x", "scripts": {"test": "vitest run", "dev": "vite"}}, indent=2))
    base = commit(repo, "base")
    return repo, base


def report(repo, base, out=None, expect=0):
    cmd = ["python3", SCRIPT, "--repo", repo]
    if base is not None:
        cmd += ["--base", base]
    if out:
        cmd += ["--out", out]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != expect:
        raise AssertionError(f"exit {proc.returncode}, wanted {expect}: {proc.stderr}")
    return json.loads(proc.stdout) if proc.returncode == 0 else None


def scenario(name, mutate, expect_weakened, also=None):
    repo, base = new_repo()
    try:
        mutate(repo)
        commit(repo, name)
        r = report(repo, base)
        ok = r["weakened"] is expect_weakened and (also is None or also(r))
        check(name, ok, r)
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def main():
    # ---- changes that reduce what the suite checks
    scenario(
        "deleting a test file is weakening",
        lambda repo: os.remove(os.path.join(repo, "tests/test_notes.py")),
        True,
        lambda r: r["testFiles"]["deleted"] == ["tests/test_notes.py"],
    )
    scenario(
        "removing a test case from a file is weakening",
        lambda repo: write(repo, "tests/test_notes.py", PY_TESTS.split("\n\n\ndef test_delete_note")[0] + "\n"),
        True,
        lambda r: r["testCases"] == {"added": 0, "removed": 1} and r["testFiles"]["modified"] == ["tests/test_notes.py"],
    )
    scenario(
        "adding it.skip is weakening",
        lambda repo: write(repo, "src/__tests__/math.test.ts", JS_TESTS.replace("it('handles", "it.skip('handles")),
        True,
        lambda r: len(r["skipMarkersAdded"]) == 1 and r["skipMarkersAdded"][0]["line"] == 7,
    )
    scenario(
        "adding it.only is weakening — it silences every other case",
        lambda repo: write(repo, "src/__tests__/math.test.ts", JS_TESTS.replace("it('adds", "it.only('adds")),
        True,
    )
    scenario(
        "adding a pytest skip marker is weakening",
        lambda repo: write(repo, "tests/test_notes.py", PY_TESTS.replace("def test_delete", "@pytest.mark.skip(reason='flaky')\ndef test_delete")),
        True,
        lambda r: r["skipMarkersAdded"][0]["file"] == "tests/test_notes.py",
    )
    scenario(
        "adding an xfail marker is weakening",
        lambda repo: write(repo, "tests/test_notes.py", PY_TESTS.replace("def test_delete", "@pytest.mark.xfail\ndef test_delete")),
        True,
    )
    scenario(
        "pointing scripts.test at something else is weakening",
        lambda repo: write(repo, "package.json", json.dumps({"name": "x", "scripts": {"test": "echo ok", "dev": "vite"}}, indent=2)),
        True,
        lambda r: r["testCommandChanged"] == [{"file": "package.json", "before": "vitest run", "after": "echo ok"}],
    )
    scenario(
        "removing scripts.test altogether is weakening",
        lambda repo: write(repo, "package.json", json.dumps({"name": "x", "scripts": {"dev": "vite"}}, indent=2)),
        True,
        lambda r: r["testCommandChanged"][0]["after"] is None,
    )

    def rename_out(repo):
        os.makedirs(os.path.join(repo, "docs"))
        git(repo, "mv", "tests/test_notes.py", "docs/notes_examples.py")

    scenario(
        "renaming a test file to a non-test path is weakening",
        rename_out,
        True,
        lambda r: r["testFiles"]["renamed"] == [["tests/test_notes.py", "docs/notes_examples.py"]],
    )

    # ---- legitimate changes that must not raise the alarm
    scenario(
        "a sleep added to a test is reported but is not weakening",
        lambda repo: write(repo, "tests/test_notes.py", PY_TESTS.replace("def test_delete_note(client):", "def test_delete_note(client):\n    time.sleep(2)")),
        False,
        lambda r: len(r["waitsAndRetriesAdded"]) == 1 and r["waitsAndRetriesAdded"][0]["file"] == "tests/test_notes.py",
    )
    scenario(
        "a retry added to a test is reported",
        lambda repo: write(repo, "src/__tests__/math.test.ts", "jest.retryTimes(3)\n" + JS_TESTS),
        False,
        lambda r: len(r["waitsAndRetriesAdded"]) == 1,
    )
    scenario(
        "a sleep in application code is not a test change",
        lambda repo: write(repo, "src/worker.py", "import time\ntime.sleep(1)\n"),
        False,
        lambda r: r["waitsAndRetriesAdded"] == [],
    )
    scenario(
        "adding a test case is not weakening",
        lambda repo: write(repo, "tests/test_notes.py", PY_TESTS + "\n\ndef test_list_notes(client):\n    assert client.get('/notes').status_code == 200\n"),
        False,
        lambda r: r["testCases"] == {"added": 1, "removed": 0},
    )
    scenario(
        "adding a new test file is not weakening",
        lambda repo: write(repo, "tests/test_tags.py", "def test_tags(client):\n    assert True\n"),
        False,
        lambda r: r["testFiles"]["added"] == ["tests/test_tags.py"],
    )
    scenario(
        "rewording a test case is not weakening",
        lambda repo: write(repo, "src/__tests__/math.test.ts", JS_TESTS.replace("it('adds two numbers'", "it('adds two positive numbers'")),
        False,
        lambda r: r["testCases"] == {"added": 1, "removed": 1},
    )
    scenario(
        "changing a test body is not weakening",
        lambda repo: write(repo, "tests/test_notes.py", PY_TESTS.replace("== 201", "in (200, 201)")),
        False,
        lambda r: r["testFiles"]["modified"] == ["tests/test_notes.py"] and r["reasons"] == [],
    )

    def rename_within(repo):
        git(repo, "mv", "tests/test_notes.py", "tests/test_note_api.py")

    scenario("renaming a test file to another test path is not weakening", rename_within, False)
    scenario(
        "changing application source only is not weakening",
        lambda repo: write(repo, "src/math.ts", "export const add = (a: number, b: number) => b + a\n"),
        False,
        lambda r: r["testFiles"] == {"added": [], "modified": [], "deleted": [], "renamed": []},
    )
    scenario(
        "changing another package.json script is not weakening",
        lambda repo: write(repo, "package.json", json.dumps({"name": "x", "scripts": {"test": "vitest run", "dev": "vite --host"}}, indent=2)),
        False,
    )
    scenario(
        "a source file that merely mentions skip is not a test change",
        lambda repo: write(repo, "src/queue.ts", "export function skipAhead() { /* it.skip( */ }\n"),
        False,
    )

    # ---- the report file and the failure contract
    repo, base = new_repo()
    try:
        out = os.path.join(repo, ".harness", "final", "02", "test-changes.json")
        r = report(repo, base, out=out)
        with open(out, "r", encoding="utf-8") as f:
            on_disk = json.load(f)
        check("an unchanged tree reports nothing weakened", r["weakened"] is False and r["base"] == base, r)
        check("--out writes the same report that is printed", on_disk == r)

        report(repo, "no-such-commit", out=out, expect=1)
        check("an unknown base exits 1 and removes a stale report", not os.path.exists(out))

        r = report(repo, None)
        check(
            "no base means everything is new, so nothing is weakened",
            r["weakened"] is False and "tests/test_notes.py" in r["testFiles"]["added"],
            r,
        )
    finally:
        shutil.rmtree(repo, ignore_errors=True)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} failing case(s): {', '.join(FAILURES)}")
        return 1
    print(f"all {COUNT} test-change cases pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
