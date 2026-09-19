#!/usr/bin/env python3
"""Regression tests for the codex review helper's exit-code contract.

The orchestrator decides what happened from the exit code alone, so that code
carries one promise: **--out holds a review of the current diff if and only if
the script exits 0.** Both ways of breaking it are silent. Write a file for a
failed codex run and exit 0, and a round records a review it never got. Leave an
earlier round's file in place on a skip, and the evaluator cites findings about
the previous diff as evidence about this one. Neither shows up as an error
anywhere.

A fake `codex-companion.mjs` stands in for the real plugin, so these cases run
without a Codex CLI or an account. No framework — run it directly:

    python3 crystal-harness/scripts/test_codex_review.py

Exits 0 when every case matches, 1 otherwise.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "codex_review.py")

FAKE_COMPANION = """
const [subcommand] = process.argv.slice(2);
const setup = JSON.parse(process.env.FAKE_SETUP || '{"ready":true}');
const review = process.env.FAKE_REVIEW;
if (subcommand === "setup") {
  console.log(JSON.stringify(setup));
} else if (review === undefined) {
  process.stderr.write("Error: fake companion has no review configured\\n");
  process.exitCode = 1;
} else {
  console.log(review);
}
"""

READY = json.dumps({"ready": True})
NOT_READY = json.dumps({"ready": False, "node": {"available": True}, "codex": {"available": False}})


def payload(status=0, stdout="## Finding\\nSomething is wrong at src/a.ts:10."):
    return json.dumps({
        "review": "Review",
        "target": {"label": "working tree"},
        "codex": {"status": status, "stderr": "" if status == 0 else "Error: codex run failed", "stdout": stdout},
    })


def run(root, out, env_extra, args=()):
    env = dict(os.environ)
    env.pop("CRYSTAL_HARNESS_CODEX_ROOT", None)
    env["CLAUDE_CONFIG_DIR"] = os.path.join(root, "empty-config")
    env.update(env_extra)
    proc = subprocess.run(
        [
            sys.executable, SCRIPT,
            "--out", out,
            "--codex-root", os.path.join(root, "codex"),
            "--cwd", root,
            *args,
        ],
        capture_output=True, text=True, env=env,
    )
    return proc.returncode, os.path.exists(out), proc


def cases():
    return [
        (
            "successful review is written and exits 0",
            {"FAKE_SETUP": READY, "FAKE_REVIEW": payload()},
            (), 0, True,
        ),
        (
            "codex non-zero status writes nothing and exits 1",
            {"FAKE_SETUP": READY, "FAKE_REVIEW": payload(status=1, stdout="")},
            (), 1, False,
        ),
        (
            "codex non-zero status with partial text still exits 1",
            {"FAKE_SETUP": READY, "FAKE_REVIEW": payload(status=2)},
            (), 1, False,
        ),
        (
            "unparseable stdout exits 1",
            {"FAKE_SETUP": READY, "FAKE_REVIEW": "not json at all"},
            (), 1, False,
        ),
        (
            "unauthenticated codex skips with 3",
            {"FAKE_SETUP": NOT_READY, "FAKE_REVIEW": payload()},
            (), 3, False,
        ),
        (
            "--required turns an unavailable codex into 1",
            {"FAKE_SETUP": NOT_READY, "FAKE_REVIEW": payload()},
            ("--required",), 1, False,
        ),
    ]


def main():
    root = tempfile.mkdtemp(prefix="codex-review-test-")
    try:
        companion_dir = os.path.join(root, "codex", "scripts")
        os.makedirs(companion_dir)
        with open(os.path.join(companion_dir, "codex-companion.mjs"), "w", encoding="utf-8") as f:
            f.write(FAKE_COMPANION)
        out = os.path.join(root, "round", "codex-review.md")
        os.makedirs(os.path.dirname(out))

        failures = []

        def check(name, ok, detail=""):
            if not ok:
                failures.append(name)
                if detail:
                    print(f"      {detail}")
            print(f"{'PASS' if ok else 'FAIL'}  {name}")

        for name, env, args, want_code, want_file in cases():
            # Every case starts with a leftover from an "earlier round": whatever
            # the outcome, it must never survive as this round's evidence.
            with open(out, "w", encoding="utf-8") as f:
                f.write("# Codex review — PREVIOUS ROUND\n")
            code, exists, proc = run(root, out, env, args)

            ok = code == want_code and exists == want_file
            detail = ""
            if not ok:
                detail = f"exit={code} (want {want_code}), file={exists} (want {want_file}); {proc.stderr.strip()[:200]}"
            if ok and exists:
                with open(out, "r", encoding="utf-8") as f:
                    body = f.read()
                if "PREVIOUS ROUND" in body:
                    ok, detail = False, "the previous round's file was not replaced"
            check(name, ok, detail)

        # The stale file must be gone even when the plugin is missing entirely,
        # which is the path that never reaches the companion at all.
        with open(out, "w", encoding="utf-8") as f:
            f.write("# Codex review — PREVIOUS ROUND\n")
        proc = subprocess.run(
            [sys.executable, SCRIPT, "--out", out, "--codex-root", os.path.join(root, "nonexistent"), "--cwd", root],
            capture_output=True, text=True,
            env={**os.environ, "CLAUDE_CONFIG_DIR": os.path.join(root, "empty-config"),
                 "CRYSTAL_HARNESS_CODEX_ROOT": ""},
        )
        check(
            "a missing plugin still clears the previous round's file",
            proc.returncode == 3 and not os.path.exists(out),
            f"exit={proc.returncode}, file={os.path.exists(out)}",
        )

        # --check must never touch --out; it is a probe, not a run.
        with open(out, "w", encoding="utf-8") as f:
            f.write("# Codex review — PREVIOUS ROUND\n")
        proc = subprocess.run(
            [sys.executable, SCRIPT, "--check", "--codex-root", os.path.join(root, "codex"), "--cwd", root],
            capture_output=True, text=True,
            env={**os.environ, "FAKE_SETUP": READY,
                 "CLAUDE_CONFIG_DIR": os.path.join(root, "empty-config")},
        )
        check(
            "--check reports readiness without writing or clearing",
            proc.returncode == 0 and os.path.exists(out),
            f"exit={proc.returncode}, file={os.path.exists(out)}",
        )

        print()
        if failures:
            print(f"{len(failures)} failing case(s): {', '.join(failures)}")
            return 1
        print(f"all {len(cases()) + 2} codex review cases pass")
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
