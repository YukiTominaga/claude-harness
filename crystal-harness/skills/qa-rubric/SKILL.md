---
name: qa-rubric
description: The graded rubric and pass/fail thresholds the evaluator applies to a sprint — functionality, design quality, originality, craft — plus the verdict.json schema. Use when grading a sprint, writing qa.md or verdict.json, or calibrating what a score means.
---

# QA rubric

"Is this good?" is not a question an agent can answer consistently. This rubric
replaces it with four dimensions, each with a written behavioral anchor per score
and a hard threshold. Grade against the anchors, not against your impression.

Read `references/calibration-examples.md` before scoring for the first time in a
run. The anchors alone drift; the worked examples are what hold the scale still.

## Thresholds

| Dimension | Threshold | Role |
| --- | --- | --- |
| Functionality | **≥ 4** | **Gate.** Below 4 the sprint fails regardless of every other score. |
| Design quality | ≥ 3 | |
| Originality | ≥ 3 | |
| Craft | ≥ 3 | |

`overall: "pass"` requires **all four** thresholds met **and** zero blocking issues
**and** zero acceptance criteria marked `fail`. Anything else is `overall: "fail"`.

A criterion marked `not_verified` never counts toward a pass. If enough criteria are
`not_verified` that you cannot tell whether the sprint works, the verdict is `fail`
with a blocking issue naming what could not be checked and why.

## 1. Functionality — does it work end-to-end for a real user

Includes edge paths and error paths, not only the happy path.

- **0** — Does not start, or the primary surface does not render.
- **1** — Renders, but the sprint's main flow cannot be completed at all.
- **2** — Main flow completes only along one narrow path; common variations break.
- **3** — Main flow works. At least one edge or error path is broken or missing
  (empty state, invalid input, refresh, back navigation, boundary value).
- **4** — Every acceptance criterion passes, including edge and error paths.
  Remaining defects are cosmetic and do not block a user.
- **5** — As 4, plus the app behaves correctly under conditions the contract did not
  name: rapid repeated actions, refresh mid-flow, two tabs, resize during use.

A partially working feature scores at most 3. "Works if you do it in the right
order" is 2.

## 2. Design quality — coherent visual identity

- **0** — Unstyled browser defaults.
- **1** — Styling applied but incoherent: colliding colors, arbitrary spacing, no
  discernible type scale.
- **2** — A theme is present but inconsistently applied; the same element type looks
  different on different screens.
- **3** — Consistent spacing scale, type scale, and color system. Nothing jars. The
  identity is generic but coherent.
- **4** — As 3, plus deliberate hierarchy: the eye lands where it should, density
  and contrast are used on purpose, the palette has an intent.
- **5** — As 4, and the visual system extends correctly to states it was not
  obviously designed for — errors, empty states, dense data, long strings.

## 3. Originality — deliberate decisions vs. framework defaults

This grades *evidence of a decision*, not novelty for its own sake. A well-argued
conventional choice is not a 1; an unexamined default is.

- **0** — Untouched starter template.
- **1** — Component library defaults throughout, default palette, default layout.
  Nothing indicates a choice was made.
- **2** — Colors and copy changed; structure and interaction are still stock
  centered-card-on-gradient or stock dashboard shell.
- **3** — At least one substantive layout or interaction decision fits *this*
  product rather than any product — how the primary object is represented, how the
  main action is reached.
- **4** — The interface's shape follows from the domain. Several decisions
  (navigation model, primary surface, information density) are specific to it.
- **5** — As 4, with a distinctive point of view carried consistently, including in
  micro-interactions and transitions.

Scoring note: a polished template is a 1–2 on this dimension even when it scores 4
on Design quality. That gap is the point of having both.

## 4. Craft — typography, alignment, states, responsiveness, a11y basics

- **0** — Overlapping or misaligned elements; unreadable text.
- **1** — Visible alignment and rhythm errors; no interactive states at all.
- **2** — Hover exists; focus, disabled, empty, and loading states are missing or
  wrong. Layout breaks at common widths.
- **3** — Hover/focus/disabled present, empty and loading states exist, layout holds
  from 375px to desktop, text is readable, no obviously broken tab order.
- **4** — As 3, plus keyboard operability of the main flow, visible focus rings,
  labelled controls, sufficient contrast, and no layout shift on load.
- **5** — As 4, with considered transitions, correct reduced-motion handling, and
  clean behaviour at extreme content lengths.

Check craft in the browser: tab through the flow, hover, disable-trigger, resize to
375px, and load with an empty data set. Craft asserted from reading CSS is
`not_verified`.

## Blocking vs. non-blocking

**Blocking** — any of: an acceptance criterion marked `fail`; any dimension below
its threshold; a console error thrown during a contract flow; data loss; a
navigation dead-end. Blocking issues are the *only* thing the generator revises
against.

**Non-blocking** — real but not gating: cosmetic misalignment, a nice-to-have state,
a slow-but-working path. Record them; they are inputs to a later sprint, not this
revision.

Every issue, blocking or not, needs: reproduction steps, observed behaviour,
expected behaviour, and a screenshot path.

## `verdict.json`

JSON Schema (draft 2020-12):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "harness sprint verdict",
  "type": "object",
  "required": ["schemaVersion", "sprint", "overall", "scores", "criteria", "blockingIssues", "nonBlockingIssues", "environment", "evaluatedAt"],
  "additionalProperties": false,
  "properties": {
    "schemaVersion": { "const": 1 },
    "sprint": { "type": "integer", "minimum": 1 },
    "revision": { "type": "integer", "minimum": 0 },
    "overall": { "enum": ["pass", "fail"] },
    "scores": {
      "type": "object",
      "required": ["functionality", "design", "originality", "craft"],
      "additionalProperties": false,
      "description": "null means the dimension could not be assessed (degraded mode); null never satisfies a threshold",
      "properties": {
        "functionality": { "type": ["integer", "null"], "minimum": 0, "maximum": 5 },
        "design": { "type": ["integer", "null"], "minimum": 0, "maximum": 5 },
        "originality": { "type": ["integer", "null"], "minimum": 0, "maximum": 5 },
        "craft": { "type": ["integer", "null"], "minimum": 0, "maximum": 5 }
      }
    },
    "criteria": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "text", "result"],
        "additionalProperties": false,
        "properties": {
          "id": { "type": "string", "pattern": "^AC-[0-9]+$" },
          "text": { "type": "string" },
          "result": { "enum": ["pass", "fail", "not_verified"] },
          "evidence": { "type": "string", "description": "what was actually done in the browser and what was observed" },
          "reason": { "type": "string", "description": "required when result is not_verified" },
          "screenshot": { "type": ["string", "null"] }
        }
      }
    },
    "blockingIssues": { "$ref": "#/$defs/issueList" },
    "nonBlockingIssues": { "$ref": "#/$defs/issueList" },
    "environment": {
      "type": "object",
      "required": ["playwrightAvailable", "degraded"],
      "additionalProperties": false,
      "properties": {
        "playwrightAvailable": { "type": "boolean" },
        "degraded": { "type": "boolean" },
        "degradedReason": { "type": ["string", "null"] },
        "appUrl": { "type": ["string", "null"] },
        "apiUrl": { "type": ["string", "null"] }
      }
    },
    "evaluatedAt": { "type": "string", "format": "date-time" }
  },
  "$defs": {
    "issueList": {
      "type": "array",
      "description": "ordered, most severe first",
      "items": {
        "type": "object",
        "required": ["id", "summary", "repro", "observed", "expected"],
        "additionalProperties": false,
        "properties": {
          "id": { "type": "string", "description": "stable across revisions; reuse the id when the same issue recurs" },
          "criterionId": { "type": ["string", "null"] },
          "summary": { "type": "string" },
          "repro": { "type": "array", "items": { "type": "string" } },
          "observed": { "type": "string" },
          "expected": { "type": "string" },
          "screenshot": { "type": ["string", "null"] },
          "severity": { "enum": ["blocking", "non-blocking"] }
        }
      }
    }
  }
}
```

Issue ids are stable across revisions. Reusing the id when the same defect survives
a revision is what lets the loop detect "same issue failing twice with no progress"
and escalate instead of grinding.

## Degraded mode

If Playwright MCP is unreachable, do not silently fall back to reading code. Set
`environment.playwrightAvailable: false`, `degraded: true`, and a `degradedReason`.
Mark every criterion that requires rendering, interaction, or visual judgement as
`not_verified` with that reason, set the scores you could not assess to `null`, and
add a blocking issue stating what the harness could not verify. A degraded run never
produces `overall: "pass"` — `null` does not satisfy a threshold.

The reduced check you *can* still do, clearly labelled as such in `qa.md`: does the
build succeed, does the dev server start, does the app respond at its URL, do the
project's own tests pass. Report those results and nothing more. Reading the source
and concluding a feature works is not a reduced check; it is the failure this
harness exists to prevent.
