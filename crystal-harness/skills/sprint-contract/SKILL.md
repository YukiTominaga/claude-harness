---
name: sprint-contract
description: How to draft and how to review a sprint contract — the agreement between generator and evaluator on what a sprint builds, which implementation details are pinned, and how success will be verified in the browser, the API and the datastore. Use when writing .harness/sprints/NN/contract.md or reviewing one.
---

# Sprint contract

A contract bridges the gap between `spec.md` (what the product is) and an
implementation (what runs). It exists because the spec is deliberately high-level,
and something has to connect user stories to testable behaviour.

Without it, the generator picks its own finish line and the evaluator grades against
a different one, and every verdict becomes an argument about scope.

The contract is written *before* implementation and agreed *before* implementation.
Editing acceptance criteria after seeing the result is the most common way a harness
turns into self-grading.

## What a contract does and does not fix

**It fixes**: the scope of the sprint, the observable behaviours that define done,
and **the implementation details the evaluator needs in order to test** — route
paths and methods, storage table and column names, query parameters, `data-testid`
hooks, the shape of an error response, the URL a screen lives at.

**It does not fix**: how the feature is built. Component structure, state
management, module layout, algorithms, and library choices are the generator's to
decide. A contract that dictates those hands the generator someone else's design
errors, and those cascade.

The line is: *if the evaluator has to know it to write a test, pin it. Otherwise
leave it alone.* `GET /api/sessions?from=&to=` returning `{items: [...]}` is a
contract detail. "Use a reducer for board state" is not.

## Template

`.harness/sprints/NN/contract.md`:

```markdown
# Sprint NN contract

## Goal
<One sentence. What a user can do after this sprint that they could not before.>

## Scope
<Numbered list of items to build. 3–7 items. Each is user-visible.>

## Out of scope for this sprint
<Explicit. Items from spec.md deliberately deferred, so the evaluator does not
grade them and the generator does not build them.>

## Pinned interfaces
<Only what the evaluator must know to test, one line per item:
`METHOD /path → status, top-level keys`, `table(col, col, …)`, query parameters,
data-testid hooks, URLs. No full JSON bodies, no type definitions, no restating
the spec. Nothing about internal structure.>

## Acceptance criteria
<One or more per scope item, each with a stable id. Aim for 10–15; the hard cap
is `harness.maxAcceptanceCriteria` (default 20), checked by
`validate_contract.py`. Over the cap, move a scope item to "Out of scope" —
never compress criteria into vagueness to fit. One criterion may check several
observations of one action (the UI, the API response and the row), and
should.>

- **AC-1** — Given <starting state>, when <a user action expressible as clicks,
  typing, navigation, drag, resize or keypress>, then <an outcome observable in
  the rendered page, the URL, the console or the network>.
- **AC-2** — <API> Given <state>, when `POST /api/x` with <payload>, then
  <status, response shape, and the resulting row in <table>>.
- **AC-3** — <persistence> After <UI action> and a full reload, <what is still
  true in the UI> and <what row exists in the datastore>.

## Verification notes
<How to reach the relevant screens and data: seed data, routes, login, how to
start the backend, where the database file is. The evaluator starts from a cold
app and must not have to guess.>

## Spec coverage
<Which sections of spec.md this sprint advances, by heading. Spec edge cases
this contract leaves out are still graded by the final assessment's SPEC-n
criteria; the contract only has to define done for this sprint.>

---

## Evaluator review — round <n>
Decision: accepted | accepted-with-amendments | changes-requested
<Numbered items, each tagged [blocking] or [amendment]. Each names the AC and the
replacement wording. "Be more specific" is not a review comment.>
```

Keep the whole contract, review blocks excluded, to roughly 200 lines. A contract
past that is restating the spec or pinning shapes the evaluator does not need, and
every extra line is re-read by every agent in every round of the sprint.

## Writing acceptance criteria

A criterion must be checkable by driving the browser, calling the API, or reading
the datastore. The test is: could someone with no access to the source verify it?

Good:

- **AC-3** — Given the timer is running with 30s remaining, when the user clicks
  Pause and waits 3s, then the displayed time is still 30s and the button reads
  "Resume".
- **AC-4** — Given zero saved sessions, when the user opens `/history`, then an
  empty state with the text "No sessions yet" is shown and no console error is
  logged.
- **AC-5** — At a 375px-wide viewport, the controls row does not overflow and every
  button remains fully visible.
- **AC-6** — `POST /api/sessions` with `{"startedAt": null}` returns 422 and no row
  is inserted into `sessions`.
- **AC-7** — After completing a session in the UI and reloading the page, the
  session is listed, and `sqlite3 app.db "select count(*) from sessions"` returns 1.

Not acceptable — these cannot be exercised, so they become the evaluator's opinion:

- "The code is clean and well organised." (Code quality is graded from the rubric,
  not from a contract criterion.)
- "State management is correct."
- "The timer works." (which timer, from what state, observed how?)
- "Good error handling." (which error, triggered how, shown where?)

Rules:

The coverage rules below say what the criteria must cover, not how many ids they
take. One criterion may satisfy several of them: put the persistence check in the
`then` clause of the write it follows, and cover several endpoints' failure paths
in one criterion with a short table (`POST /a`, `PUT /a/:id`, `DELETE /a/:id` ×
missing field / unknown id → 4xx and no row changes).

- Every criterion names a **starting state**, an **action**, and an **observable
  result**. Missing starting state is the usual defect.
- **Every write is covered by a persistence check.** A UI-only criterion cannot
  distinguish a saved record from React state. If the sprint writes anything, at
  least one criterion must survive a reload and be confirmed outside the UI.
- **Every endpoint the sprint adds is covered by at least one failure check**:
  wrong method, missing field, unknown id, or a constraint violation.
- Include at least one **edge or error path** per sprint. Sprints with only happy
  paths pass and then break in front of the human.
- Include at least one **non-functional** criterion the browser can see: a viewport
  width, a focus/hover/disabled state, a loading state, or "no uncaught console
  errors during the flow".
- **Prefer the observable result over the gesture.** "When the user clicks Delete,
  the row is gone from `GET /api/notes` and from the `notes` table" is checkable in
  either verification mode; "when the user clicks Delete, the row disappears from
  the list" is only checkable in a browser. A criterion phrased around the
  datastore result keeps its evidence when `harness.browserVerification` is
  `false`, and one phrased around the rendering does not. When both matter, name
  the gesture and the result in the same criterion rather than writing two.
- **Depth, not just presence.** For each scope item, ask what verbs the domain
  implies — create, edit, delete, reorder, drag, undo — and make sure each one in
  scope is exercised by some criterion. A criterion that only asserts something
  renders will pass on a facade, and the rubric will then fail the sprint on
  Product depth anyway. If the verbs do not fit under the cap, the sprint is too
  big: defer a scope item.
- Criterion ids are stable. When a criterion is reworded in review, keep the id.
  Verdicts across rounds are matched by id.

## Reviewing a contract (evaluator)

Five questions, in this order:

1. **Is every criterion testable** — in the browser, against the API, or in the
   datastore? If not, write the replacement wording yourself as an amendment; do
   not reject and hand the problem back.
2. **Does this sprint actually advance `spec.md`?** A sprint polishing
   already-passing work while a prioritized spec feature is untouched should be
   rejected with the feature named.
3. **Do the criteria cover depth, or only presence?** If a scope item's criteria
   would all pass on a read-only facade, name the missing verb.
4. **Is anything pinned that should not be?** Route shapes and testids belong in the
   contract. Component structure, state management and library choices do not —
   flag those as over-specification, because the generator will inherit the error.
5. **Is it within the cap, and can criteria merge?** Name any criteria that check
   the same action and give the merged wording.

Do not review implementation approach beyond question 4.

### Blocking versus amendment

Only four findings are `[blocking]` and send the contract back to the generator:

- a criterion that cannot be tested and has no testable rewording that keeps its
  intent;
- the sprint skips a prioritized spec feature or does not advance the spec
  (question 2);
- over-specification of implementation (question 4);
- a write in scope with no persistence check anywhere in the contract.

Everything else — rewording a criterion, adding a missing verb or failure path to
an existing criterion, merging — is an `[amendment]`: write the
replacement wording in the review block under the criterion's id. If every item is
an amendment, the decision is `accepted-with-amendments`, and the contract goes
straight to implementation with the amendments in force. An amendment supersedes
the drafted wording of the same id for the generator building it and for the QA
that grades it. It may not add a scope item, and it may not push the criterion
count over the cap — to add a verb, fold it into an existing criterion or name the
criterion it replaces.

The anti-sycophancy rules the evaluator grades by exist for QA, where softening a
failure hides a defect. A contract has no defect to hide yet; the rules for
blocking are the four above, and nothing else is.

## Revising a contract (generator)

A `changes-requested` contract goes to a fresh generator with only `contract.md`
(including its review block) — not prior verdicts or the handoff, and not the spec
unless a `[blocking]` item is about spec coverage; the first draft already
accounted for those. Edit the criteria and sections the
`[blocking]` items name, apply the `[amendment]` items verbatim, and do not rewrite
the rest. Append:

```markdown
## Revision <n> changes
- AC-4 — <one line: what changed and which review item it answers>
```

The next review round checks only the ids and sections listed there and whether
each previous `[blocking]` item is resolved. It may not raise new blocking items
against wording that did not change — a finish line that moves every round is how
contracts take three rounds.

## Round limit

At most **two** review rounds. If the second round still requests changes, stop and
escalate to the human with both drafts and the outstanding disagreement. Looping on
contract wording burns the run before any code exists.

Record the outcome in `journal.md` either way.

## Final QA has no contract

The end-of-run assessment grades against `spec.md` itself, not a contract. The
evaluator derives criteria from the spec's "Behaviour and states", "Edge cases" and
"Feature ordering" sections and ids them `SPEC-1`, `SPEC-2`, … Nobody negotiates
them, which is the point: the last check must not be graded against a target the
generator helped set.
