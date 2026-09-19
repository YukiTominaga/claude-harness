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
<Only what the evaluator must know to test: routes and methods with request and
response shapes, table and column names, query parameters, data-testid hooks,
URLs. Nothing about internal structure.>

## Acceptance criteria
<One or more per scope item, each with a stable id. Be exhaustive — a
substantial sprint has 15–30 criteria, not 8. Every distinct behaviour, state
and failure mode gets its own id so a verdict can be partial and precise.>

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
<Which sections of spec.md this sprint advances, by heading.>

---

## Evaluator review — round <n>
Decision: accepted | changes-requested
<If changes-requested: numbered, specific edits. Each names the AC and the
replacement wording. "Be more specific" is not a review comment.>
```

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

- Every criterion names a **starting state**, an **action**, and an **observable
  result**. Missing starting state is the usual defect.
- **Every write gets a persistence criterion.** A UI-only criterion cannot
  distinguish a saved record from React state. If the sprint writes anything, at
  least one criterion must survive a reload and be confirmed outside the UI.
- **Every endpoint the sprint adds gets at least one failure criterion**: wrong
  method, missing field, unknown id, or a constraint violation.
- Include at least one **edge or error path** per sprint. Sprints with only happy
  paths pass and then break in front of the human.
- Include at least one **non-functional** criterion the browser can see: a viewport
  width, a focus/hover/disabled state, a loading state, or "no uncaught console
  errors during the flow".
- **Prefer the observable result over the gesture.** "When the user clicks Delete,
  the row is gone from `GET /api/notes` and from the `notes` table" is checkable in
  either verification mode; "when the user clicks Delete, the row disappears from
  the list" is only checkable in a browser. Both are legitimate criteria and a
  contract needs some of each — but a criterion phrased around the datastore result
  keeps its evidence when `harness.browserVerification` is `false`, and one phrased
  around the rendering does not. Write the gesture when the gesture is the point;
  write the result when the result is.
- **Depth, not just presence.** For each scope item, ask what verbs the domain
  implies — create, edit, delete, reorder, drag, undo — and write a criterion for
  each one in scope. A criterion that only asserts something renders will pass on a
  facade, and the rubric will then fail the sprint on Product depth anyway. Catching
  it at contract time is cheaper.
- Criterion ids are stable. When a criterion is reworded in review, keep the id.
  Verdicts across rounds are matched by id.

## Reviewing a contract (evaluator)

Four questions, in this order:

1. **Is every criterion testable** — in the browser, against the API, or in the
   datastore? If not, request a specific replacement wording; do not reject and hand
   the problem back.
2. **Does this sprint actually advance `spec.md`?** A sprint polishing
   already-passing work while a prioritized spec feature is untouched should be
   rejected with the feature named.
3. **Do the criteria cover depth, or only presence?** If a scope item's criteria
   would all pass on a read-only facade, name the missing verb.
4. **Is anything pinned that should not be?** Route shapes and testids belong in the
   contract. Component structure, state management and library choices do not —
   flag those as over-specification, because the generator will inherit the error.

Do not review implementation approach beyond question 4.

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
