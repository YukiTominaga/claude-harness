# Evaluator eval

Does the evaluator find a defect that is known to be there, and does it pass an
app that is known to be sound? Every default in this plugin — and every optional
component that ships off — rests on an answer to that, and until this suite the
answer was one run. This measures it.

```bash
python3 evals/run.py                         # every case once
python3 evals/run.py --runs 3 --max-cost-usd 40
python3 evals/run.py --case 'seeded-*'
```

It prints, and writes to `evals/results/<timestamp>/summary.md`:

```
Seeded defects detected: 5/6 (83%).
False alarms on clean apps: 0/2 (0%).
```

alongside `result.json` and `report.html` from `claude plugin eval`.

## What a case is

Each case gives the evaluator a small Notes API and asks for a final assessment,
exactly as the build loop would: the spec, the config, the round directory, and
nothing about the code.

| Cases | Fixture | Correct verdict |
| --- | --- | --- |
| `seeded-*` (6) | an app that passed a final assessment, with **one** defect put in, behind a thin test suite that stays green | `fail`, with the seeded defect named among the blocking issues |
| `clean-*` (2) | that app untouched with its full suite, and a second implementation of the same spec written independently | `pass`, no blocking issue |

The six defects are the kinds this harness says it catches: a write that reports
success and is rolled back, an error path that answers like the happy path,
correct data in the wrong order, state that does not survive a restart, a stated
edge case with the wrong status, and a field that is accepted and thrown away.

Because the seeded apps' tests pass, a defect cannot be found by running the
suite. It has to be found the way the evaluator is told to work: by exercising
the product and reading the datastore.

## How it is graded

By regex over the `verdict.json` the evaluator wrote. No model grades a model.

- A seeded case is **detected** only if the verdict fails the round **and** a
  pattern for that defect matches inside `blockingIssues`. Failing the round for
  another reason — the thin tests, say — is not a detection.
- A clean case is a **false alarm** unless the verdict is `pass` with an empty
  `blockingIssues`.

## What keeps the suite honest

`python3 scripts/test_eval_fixtures.py` builds every fixture the way a run does and
checks it is what it claims: each clean app behaves as the spec says; each seeded
app's suite passes while a probe shows exactly its one defect and nothing else;
each grader pattern matches a verdict that names the defect and ignores one that
fails for an unrelated reason. Without that, a mutation that silently stopped
applying would be scored as the evaluator missing a bug.

Cases are generated from one table. To add or change one, edit
`_fixtures/make_cases.py` (and `_fixtures/mutate.py` for a new defect), run it,
extend the probe table in `scripts/test_eval_fixtures.py`, and commit the result.

## Using it to change something

The point of the numbers is to make a change to the harness arguable. Change
**one** thing — an effort level in an agent's frontmatter, a section of a prompt,
`parallelEvaluation` in `_fixtures/setup.sh` — run the suite with `--runs 3` or
more before and after, and compare. Eight cases are few: a difference of one case
is noise until it repeats. Add cases before trusting a small gain, and add them
from defects a real run missed, not from ones today's evaluator already catches.

What this suite cannot tell you: how the evaluator does on an interface (there is
no browser case), on a large codebase, or on judgement dimensions such as design
and originality. It measures one thing — defect detection through an API — on one
small app.

## Requirements and caveats

- Claude Code 2.1.269 or later, for `claude plugin eval`.
- The OS sandbox backend, because the evaluator runs the app with Bash and
  `claude plugin eval` refuses to grant a shell it cannot confine. On Linux:
  `bubblewrap` and `socat`.
- `run.py` evaluates a **renamed temporary copy** of the plugin. Where the plugin
  is installed through managed settings, `claude plugin eval .` on the working
  copy loads its hooks but not its agents — the managed install locks the name —
  and every case would fail with "agent type not found".
- Runs go one at a time; every fixture listens on port 8765.
- The evaluator runs on the model and effort pinned in
  `agents/harness-evaluator.md`. `--model` sets only the session that relays the
  request to it. Cost is `claude plugin eval`'s list-price estimate.
- Run as root (as in some containers), the sandbox makes every Bash call end with
  a "Read-only file system" line and a non-zero exit code. The case prompt tells
  the evaluator so; expect that note to be irrelevant on an ordinary machine.
