---
name: sprint-contract
description: How to draft and how to review a sprint contract — the agreement between generator and evaluator on what a sprint builds and how success will be checked in a browser. Use when writing .harness/sprints/NN/contract.md or reviewing one for testability.
---

# Sprint contract

A contract bridges the gap between `spec.md` (what the product is) and an
implementation (what runs). It exists because both ends fail without it:

- Without a contract, the generator picks its own finish line and the evaluator
  grades against a different one. Every verdict becomes an argument about scope.
- With a fully specified implementation, the generator inherits someone else's
  design errors and cascades them. So the contract fixes **scope and observable
  outcome**, and says nothing about how.

The contract is written *before* implementation and agreed *before* implementation.
Editing acceptance criteria after seeing the result is the single most common way a
harness turns into self-grading.

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

## Acceptance criteria
<One or more per scope item. Each has a stable id.>

- **AC-1** — Given <starting state>, when <a user action expressible as clicks,
  typing, navigation, drag, or resize>, then <an outcome observable in the
  rendered page, the URL, or the console/network>.
- **AC-2** — …

## Verification notes
<How to reach the relevant screens: seed data needed, routes, any login. The
evaluator starts from a cold app and must not have to guess.>

## Spec coverage
<Which sections of spec.md this sprint advances, by heading.>

---

## Evaluator review — round <n>
Decision: accepted | changes-requested
<If changes-requested: numbered, specific edits. Each names the AC and the
replacement wording. "Be more specific" is not a review comment.>
```

## Writing acceptance criteria

An acceptance criterion must be checkable by driving a browser. The test is: could
someone with no access to the source verify it?

Good:

- **AC-3** — Given the timer is running with 30s remaining, when the user clicks
  Pause and waits 3s, then the displayed time is still 30s and the button label
  reads "Resume".
- **AC-4** — Given zero saved sessions, when the user opens /history, then an empty
  state with the text "No sessions yet" is shown and no console error is logged.
- **AC-5** — At a 375px-wide viewport, the controls row does not overflow
  horizontally and every button remains fully visible.

Not acceptable — these cannot be exercised, so they become the evaluator's opinion:

- "The code is clean and well organised."
- "State management is correct."
- "The timer works." (which timer, from what state, observed how?)
- "Good error handling." (which error, triggered how, shown where?)

Rules:

- Every criterion names a **starting state**, an **action**, and an **observable
  result**. Missing starting state is the usual defect; "when the user clicks
  Reset" is untestable if the app could be in any state.
- Include at least one **edge or error path** per sprint — empty state, invalid
  input, network failure, or boundary value. Sprints with only happy paths pass
  and then break in front of the human.
- Include at least one **non-functional** criterion the browser can see: a viewport
  width, a focus/hover/disabled state, a loading state, or "no uncaught console
  errors during the flow".
- Criteria ids are stable. When a criterion is reworded in review, keep the id.
  Verdicts across revisions are matched by id.

## Reviewing a contract (evaluator)

Two questions only, in this order:

1. **Is every criterion testable in a browser?** If not, request a specific
   replacement wording — do not reject and hand the problem back.
2. **Does this sprint actually advance `spec.md`?** A sprint that polishes
   already-passing work while a prioritized spec feature is untouched should be
   rejected with the feature named.

Also check the cheap failure modes: criteria that restate the scope item without
adding an observation; a sprint with no edge path; "out of scope" left empty when
the goal obviously implies deferred work.

Do not review implementation approach. The contract does not contain one, and if
it does, that is itself a defect to flag.

## Round limit

At most **two** review rounds. If the second round still requests changes, stop and
escalate to the human with both drafts and the outstanding disagreement. Looping
on contract wording burns the run before any code exists.

Record the outcome in `journal.md` either way.
