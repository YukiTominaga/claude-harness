---
name: evaluation-lenses
description: How a harness-evaluator grades one slice of a round when harness.parallelEvaluation is on — the tests, api, code and screen lenses, the lens verdict file each writes, and how a blocking issue is independently reproduced. Use when a prompt names you as a lens or as a reproducer.
---

# Evaluation lenses

In parallel evaluation a round is graded by several evaluators, each looking at it
through one **lens**. You are one of them. You grade your slice to the standard the
`harness-evaluator` agent definition and the `qa-rubric` skill already set — every
anti-sycophancy rule, the scope discipline, the specificity required of a failure,
the rule that reading code never establishes a pass. A lens narrows what you look
at. It does not lower the bar.

Nobody merges the lens verdicts by judgement. `scripts/merge_verdicts.py` does it by
rule: where two lenses score the same dimension the lower score stands, every
blocking issue is kept, and the round passes only if every lens passed. It refuses
to produce a verdict at all if your file is missing, malformed, self-contradictory,
or stamped with another round or commit. So the file format below is not a
suggestion.

## What you write

Two files, in `<round directory>/lenses/`. Nothing else, and never the round's own
`verdict.json` or `qa.md` — those are produced by the merge.

- `<lens>.md` — your notes: what you ran, what you observed, the evidence behind
  each result, at the level of detail the evaluator's `qa.md` template asks for.
- `<lens>.json` — your lens verdict:

```json
{
  "lens": "api",
  "phase": "final",
  "sprint": null,
  "round": 2,
  "commit": "<the commit sha your prompt gave you>",
  "lensVerdict": "fail",
  "scores": { "productDepth": 4, "functionality": 3 },
  "criteria": [
    { "id": "SPEC-1", "text": "…", "result": "pass", "evidence": "…" }
  ],
  "blockingIssues": [
    { "id": "B-api-1", "criterionId": "SPEC-4", "dimension": "functionality",
      "summary": "…", "repro": ["…"], "observed": "…", "expected": "…",
      "cause": { "file": "app/notes.py", "line": 42, "mechanism": "…" } }
  ],
  "nonBlockingIssues": [],
  "environment": { "apiVerified": true, "persistenceVerified": true,
                   "appUrl": null, "apiUrl": "http://localhost:8000" },
  "evaluatedAt": "2026-11-20T06:00:00Z"
}
```

Rules the merge enforces — get any of them wrong and the round has no verdict:

- `phase`, `sprint`, `round` and `commit` are exactly what your prompt gave you.
- `scores` has **exactly** your lens's dimensions (table below), each an integer
  0–5 against the `qa-rubric` anchors, or `null` only if you genuinely could not
  assess it. Do not add a dimension that belongs to another lens.
- `criteria` is present only in the lens that owns the criteria: `screen` when your
  prompt says the browser is enabled, otherwise `api`. Items use the `verdict.json`
  shape (`id`, `text`, `result`, `evidence`, optional `browserOnly`, `screenshot`).
- Issue ids are `B-<lens>-<n>` for blocking and `N-<lens>-<n>` for non-blocking,
  with the `verdict.json` issue shape. Reuse the id when the same defect survives
  from the previous round — recurrence tracking depends on it. Never set
  `verification`; the merge writes it.
- `lensVerdict` is your pass or fail over your own slice, and it has to agree with
  the rest of the file. `pass` needs no blocking issue, every one of your scores at
  or above its threshold, and — if you own the criteria — none marked `fail`, at
  least one marked `pass`, and no `not_verified` except a `browserOnly` one in a
  run without a browser. `fail` needs at least one blocking issue: a fail the
  generator cannot act on is not a verdict.

| Lens | Dimensions it scores | `environment` keys |
| --- | --- | --- |
| `tests` | none — `"scores": {}` | `testsVerified`, `testChanges` |
| `api` | `productDepth`, `functionality` | `apiVerified`, `persistenceVerified`, optional `appUrl`, `apiUrl`, `rulesChecked` |
| `code` | `codeQuality` | `codexReview` |
| `screen` | `productDepth`, `functionality`, `design`, `originality`, `craft` | `verificationMode` (`browser` or `degraded`), `playwrightAvailable`, optional `degradedReason`, `appUrl` |

If the `Write` tool is rejected for either file by a policy you did not expect, write
the identical content with Bash (`cat > … <<'EOF'`). Do not return without both files.

## The running application

The lenses that run the application — `tests`, `api`, `screen`, and every
reproducer — run **one after another**, never at the same time, because they share
its ports and its datastore. That is arranged for you; your part is to leave it the
way you found it:

- Start what you need from `.harness/config.json`'s `commands`. If the app URL
  already answers before you start anything, something was left running: stop it
  if you can find it, otherwise use it and say so in your notes.
- **Stop every process you started before you finish.** A dev server left behind
  holds the port the next lens needs.
- Data you create stays in the datastore for the next lens. Name what you create
  recognisably, and assert on your own records, not on counts or on an empty table
  — unless you emptied it yourself for an empty-state check, in which case say so.

The `code` lens runs alongside all of this and must not start, stop or call the
application at all.

## `tests` lens — is the project's own evidence sound

1. Install and build as `config.json` says. A build or type error is a blocking
   issue with the literal command and output.
2. Run the test suite once and record the literal outcome. Set `testsVerified` to
   whether it ran and passed. A failing suite is a blocking issue.
3. Read `<round directory>/test-changes.json` if it exists (it is written before
   you are started; never write it yourself). Set `testChanges` to `reviewed` if it
   listed any change to the tests, `none` if it listed nothing, `absent` if there
   is no such file. If it says the suite was `weakened`, check each of its
   `reasons` against the diff and against the generator's `report.md`: a deleted,
   skipped or re-pointed test with no stated, defensible reason is a blocking
   issue, because the suite it belonged to is evidence the other lenses lean on.
   The report also lists sleeps and retries added to tests
   (`waitsAndRetriesAdded`); apply the evaluator's rule for those. And run the
   suite **once**: a suite that needs a second run to pass is failing.
4. Judge whether the tests are worth leaning on at all — would they fail if the
   behaviour broke? A suite that asserts nothing is a non-blocking issue here and a
   Code quality matter for the `code` lens.

You score no dimension. Your `lensVerdict` is `fail` when the build, the suite or
the test changes produced a blocking issue, and `pass` otherwise.

Your reply ends with one line the next lenses will be given: whether the suite ran
and passed, and whether the tests were weakened.

## `api` lens — the product outside the browser

Follow the evaluator's "Get the app running" and "Verify the API, the datastore and
the test suite directly" steps, except that you do not run the test suite — the
`tests` lens did, and your prompt carries its result.

- For every endpoint the round adds: the happy path, wrong method, missing required
  field, unknown id, and a payload violating a stated constraint. One request each.
- Every write: perform it, re-read it through a fresh request, and confirm it in
  the datastore directly.
- **If you own the criteria** (no browser in this run): verify every criterion you
  can reach through the API, the datastore and the running app, exactly as the
  `qa-rubric` headless procedure says; mark the ones that genuinely need a rendered
  interface `not_verified` with `browserOnly: true`. In a final assessment's first
  round you derive the `SPEC-n` criteria yourself from the spec, as the evaluator
  does.
- **If you do not own the criteria** (the `screen` lens does): you still probe the
  whole API surface and file what you find as issues, with `criterionId: null`.

- **Project rules are yours.** If the round directory has `rules-to-check.json`,
  do each listed rule's `check` in the product and list every rule id you checked
  in `environment.rulesChecked`, held or not. A rule that does not hold is a
  blocking issue. The merge carries your list into the verdict, and the validator
  rejects a verdict that leaves a listed rule out.
- Mark an issue `preExisting: true` under the evaluator's rule for that, whichever
  lens you are.

Score `productDepth` and `functionality` from what you could drive.

## `screen` lens — the product through its interface

Only exists when `harness.browserVerification` is `true`. Follow the evaluator's
"Establish the verification mode" and "Exercise the application like a user" steps
in full, including confirming each write outside the UI yourself. You own the
criteria: every one is performed through the interface.

If Playwright MCP does not respond you are `degraded`: say so with the exact error
in `degradedReason`, set `playwrightAvailable` to `false`, score what you could not
assess `null`, mark the criteria you could not exercise `not_verified`, file the
blocking issue the `qa-rubric` degraded procedure asks for, and set `lensVerdict` to
`fail`. A degraded lens never passes.

Score all five of your dimensions against the anchors. Screenshots go in the
round's `screenshots/` directory as usual.

## `code` lens — the one graded by reading

Follow the evaluator's "Grade Code quality" step: read the round's diff (the whole
tree in a final assessment's first round), apply the anchors, and treat
`codex-review.md`, if present, as claims to confirm against the code. Set
`codexReview` to `confirmed`, `present` or `absent` as the evaluator's rules say.

Nothing you read establishes that a feature works, and you do not run the
application. A defect you found by reading is a Code quality issue with a `cause`;
it is blocking only when it puts `codeQuality` below its threshold.

## Re-check rounds

When your prompt says this is a re-check and names the commit the previous round
graded, the evaluator's "Re-check rounds" rules apply to your slice:

- The previous round's `verdict.json` is still in the round directory (sprint QA)
  or in the previous `final/NN` directory. Read it. Your earlier issues are the
  ones whose ids carry your lens name; re-verify each by its repro and reuse the id
  if it survives.
- If you own the criteria, reuse the previous ids and wording exactly. Re-verify
  every criterion that was `fail` or `not_verified`, and every one whose feature
  the diff touches. A criterion that passed before and that the diff cannot have
  affected may keep `pass` with evidence starting **exactly** `carried from round
  <n>:` — but only if your prompt says the suite ran and passed **and** the tests
  were not weakened. If either is not so, carry nothing and re-verify everything.
- `code`: grade from the diff since the previous commit.

## Reproducing a blocking issue

When your prompt names you a **reproducer**, you are a separate evaluator who has
not seen the lens's reasoning, and your prompt gives you one blocking issue: its id,
its reproduction steps, what was observed and what was expected. You were
deliberately not given the cause. Do not look for it.

Start from a cold application, follow the steps literally, and report what happens.
Write `<round directory>/lenses/verify/<issue id>.json`:

```json
{ "issueId": "B-api-1", "round": 2, "commit": "<the commit sha from your prompt>",
  "reproduced": true,
  "evidence": "the literal commands or actions, and the literal output or state you saw" }
```

`reproduced` is `true` only if you saw the observed behaviour the issue describes.
If a step cannot be followed as written, or the behaviour differs, it is `false` and
your evidence says exactly where it diverged. You are not fixing the issue,
improving its wording, or deciding whether it matters. A result of `false` does not
remove the issue — it tells the generator and the human how much weight the report
carries — so there is nothing to gain by leaning either way. Stop anything you
started before you finish.
