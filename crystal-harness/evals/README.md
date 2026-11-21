# Evaluator eval

Does the evaluator find a defect that is known to be there, and does it pass an
app that is known to be sound? Every default in this plugin — and every optional
component that ships off — rests on an answer to that, and until this suite the
answer was one run. This measures it.

```bash
python3 evals/run.py                         # every case once
python3 evals/run.py --runs 3 --max-cost-usd 40
python3 evals/run.py --case 'seeded-*'
python3 evals/run.py --case '*tracker*'      # only the harder cases
python3 evals/run.py --evaluator-model claude-sonnet-5-5   # the same cases, another evaluator
```

It prints, and writes to `evals/results/<timestamp>/summary.md`:

```
Seeded defects detected: 10/12 (83%).
False alarms on clean apps: 0/4 (0%).

| fixture | seeded defects detected | false alarms on clean apps |
| --- | --- | --- |
| notes | 6/6 | 0/2 |
| tracker | 4/6 | 0/2 |
```

alongside `result.json` and `report.html` from `claude plugin eval`.

## What a case is

Each case gives the evaluator an API and asks for a final assessment, exactly as
the build loop would: the spec, the config, the round directory, and nothing
about the code. There are two apps.

**Notes** — four operations on one resource, about 280 lines. Small enough that a
careful evaluator can try everything once.

| Cases | Fixture | Correct verdict |
| --- | --- | --- |
| `seeded-*` (6) | an app that passed a final assessment, with **one** defect put in, behind a thin test suite that stays green | `fail`, with the seeded defect named among the blocking issues |
| `clean-*` (2) | that app untouched with its full suite, and a second implementation of the same spec written independently | `pass`, no blocking issue |

The six defects are the kinds this harness says it catches: a write that reports
success and is rolled back, an error path that answers like the happy path,
correct data in the wrong order, state that does not survive a restart, a stated
edge case with the wrong status, and a field that is accepted and thrown away.
Each shows on the first request to the endpoint it lives in.

**Tracker** — projects and tasks, a `todo`/`doing`/`done` workflow, tasks that wait
on other tasks, filters and paging, archiving, moving and deleting; about 640
lines and a spec of some thirty rules. Trying everything once is no longer a
plan, and that is the point: these cases are here so the suite can tell a better
evaluator from a worse one.

| Cases | Fixture | Correct verdict |
| --- | --- | --- |
| `seeded-tracker-*` (6) | the app with **one** defect put in, behind a thin suite that stays green | `fail`, naming the defect |
| `clean-tracker-full-suite` | the app untouched, with its full suite | `pass`, no blocking issue |
| `clean-tracker-decoys` | the app rewritten in three places to **read** like a defect while behaving the same | `pass`, no blocking issue |

Why each tracker defect is hard — written down before any run, because a case
chosen for having been missed once measures luck:

| Defect | What it takes to see |
| --- | --- |
| a re-opened task keeps its `completed_at` | three transitions in order, then one field of the response |
| a task can be moved into an archived project | two features meeting: the rule holds on create, the other way in was not checked |
| deleting a blocker leaves what waited on it stuck | four steps: block, delete the blocker, read the waiter, try to finish it |
| a three-task cycle of blocking is accepted | three tasks; the two-task cycle anyone tries first is refused |
| `total` is the size of the page | more matching tasks than the page holds; with everything on one page it is right |
| `PATCH` stores tags without normalising them | a second path to a field: creation normalises, and that is the path that gets tested |

Each is an omission — a check or a clause that is not there — so the code that
remains reads as plausible. And the spec does not hand over the probe. It states
each rule once, as something that always holds — "`completed_at` is null unless
the status is `done`", "an archived project never gains a task", "blocking
relations never form a cycle" — not endpoint by endpoint, so which requests could
break a rule is for the evaluator to work out. The first draft of this spec
spelled the three-task cycle out as an example, and a trial run found that defect
in two minutes: a spec that reads like a test plan measures whether the evaluator
can follow one. The decoys are the mirror image: deletes that no
longer name the dependent rows because foreign keys cascade, an archive check
that moved from Python into the `UPDATE`, a `CASE` with no `ELSE`. An evaluator
that fails a round on how code looks, without observing a failure, fails that
case.

Because the seeded apps' tests pass, a defect cannot be found by running the
suite. It has to be found the way the evaluator is told to work: by exercising
the product and reading the datastore.

## How it is graded

By regex over the `verdict.json` the evaluator wrote. No model grades a model.

- A seeded case is **detected** only if the verdict fails the round **and** a
  pattern for that defect matches inside `blockingIssues`. Failing the round for
  another reason — the thin tests, say — is not a detection. The pattern cannot
  reach past that array: neither a criterion nor a non-blocking note that
  mentions the defect counts.
- A clean case is a **false alarm** unless the verdict is `pass` with an empty
  `blockingIssues`.
- A run that ends **without a verdict** — the session never reached the evaluator,
  or the run errored — is **invalid**. It is reported, and kept out of both
  counts: it says something about the harness around the evaluator, not about the
  evaluator. `run.py` exits 2 when any run was invalid; re-run with `--keep-temp`
  and read the trace before trusting the rest.

## What keeps the suite honest

`python3 scripts/test_eval_fixtures.py` builds every fixture the way a run does and
checks it is what it claims: each clean app behaves as the spec says — the
decoys included, which must differ from the base app in text and in nothing
else; each seeded app's suite passes while a probe shows exactly the facts its
one defect changes and no other; each grader pattern matches a verdict that
names the defect, in more than one phrasing, and ignores one that fails for an
unrelated reason, one that names a different tracker defect, and one where the
defect appears only in a criterion or a non-blocking note. Without that, a
mutation that silently stopped applying would be scored as the evaluator missing
a bug.

Cases are generated from one table. To add or change one, edit
`_fixtures/make_cases.py` (and `_fixtures/mutate.py` for a new defect or decoy),
run it, extend the probe and the sample verdicts in
`scripts/test_eval_fixtures.py`, and commit the result. Say why the case is hard
next to its mutation, before running it.

## Using it to change something

The point of the numbers is to make a change to the harness arguable. Change
**one** thing — an effort level in an agent's frontmatter, a section of a prompt,
`parallelEvaluation` in `_fixtures/setup.sh` — run the suite with `--runs 3` or
more before and after, and compare. Sixteen cases are few: a difference of one
case is noise until it repeats.

`--evaluator-model <id>` runs the same cases with every subagent — here, the
evaluator — forced onto another model, without editing the plugin. It is the
cheap way to ask "would a cheaper evaluator have found this?", and how
`BASELINE.md` checks that the suite can tell two evaluators apart at all.

What this suite cannot tell you: how the evaluator does on an interface (there is
no browser case), on a codebase of more than one file, or on judgement dimensions
such as design and originality. It measures one thing — defect detection through
an API — on two small apps.

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
  `agents/harness-evaluator.md` unless `--evaluator-model` forces another model.
  `--model` sets only the session that relays the request to it. Cost is
  `claude plugin eval`'s list-price estimate.
- Run as root (as in some containers), the sandbox makes every Bash call end with
  a "Read-only file system" line and a non-zero exit code. The case prompt tells
  the evaluator so; expect that note to be irrelevant on an ordinary machine.
