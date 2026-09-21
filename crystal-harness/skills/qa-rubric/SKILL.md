---
name: qa-rubric
description: The graded rubric and pass/fail thresholds the evaluator applies — product depth, functionality, design quality, originality, craft, code quality — plus the verdict.json schema. Use when grading a sprint or a final end-of-run assessment, writing qa.md or verdict.json, or calibrating what a score means.
---

# QA rubric

"Is this good?" is not a question an agent can answer consistently. This rubric
replaces it with six dimensions, each with a written behavioral anchor per score and
a hard threshold. Grade against the anchors, not against your impression.

Read `references/calibration-examples.md` before scoring for the first time in a
run. The anchors alone drift; the worked examples are what hold the scale still.

## The two contexts you grade in

| | Sprint QA | Final QA |
| --- | --- | --- |
| Graded against | `contract.md`'s acceptance criteria | `spec.md` as a whole |
| Scope of "does it work" | this sprint's scope items | every feature the spec promised |
| Regression duty | earlier sprints must still work | the whole product must hold together |
| Artifact | `.harness/sprints/NN/` | `.harness/final/NN/` |

**A run is not finished until a final QA passes.** Sprint verdicts grade increments
against contracts they helped write; only the final pass asks whether the product
the spec described actually exists. A build where every sprint passed and the final
QA fails is a normal and expected outcome, not a contradiction.

## The three verification modes

Browser verification is expensive — it is the single largest cost in a QA round —
so it is a configuration choice, not a constant. `harness.browserVerification` in
`.harness/config.json` decides it. But an evaluation that quietly grades less than
it appears to is the failure this whole rubric exists to prevent, so the mode you
ran in is recorded in every verdict and it changes what a `pass` is allowed to mean.

| `environment.verificationMode` | When | `overall: "pass"` |
| --- | --- | --- |
| `browser` | `browserVerification: true` and Playwright MCP responded | allowed, all six thresholds apply |
| `headless` | `browserVerification: false` | allowed, but three dimensions are waived and browser-only criteria go unchecked |
| `degraded` | `browserVerification: true` and Playwright MCP did **not** respond | **never** |

The distinction between `headless` and `degraded` is the whole point and it is not
a technicality: **headless is verification somebody chose not to run; degraded is
verification somebody asked for and did not get.** A run must never silently lose
coverage it was configured to have. Two consecutive `degraded` verdicts stop the
loop; `headless` verdicts never do, because nothing is broken.

Never set `degraded: true` to excuse a browser you did not try to use in `headless`
mode, and never report `headless` when `browserVerification` was `true`.

## Thresholds

| Dimension | Threshold | Graded in `headless` |
| --- | --- | --- |
| Product depth | **≥ 4** | yes — from the API, the datastore and the project's own tests |
| Functionality | **≥ 4** | yes — same evidence |
| Code quality | ≥ 3 | yes — it was always graded by reading |
| Design quality | **≥ 4** | no — `null`, threshold waived |
| Originality | **≥ 4** | no — `null`, threshold waived |
| Craft | ≥ 3 | no — `null`, threshold waived |

`overall: "pass"` requires **every threshold that applies in the mode** to be met,
**and** zero blocking issues, **and** zero acceptance criteria marked `fail`. Any
one applicable dimension below its threshold fails the sprint or the run.

A waived dimension is scored `null`, never guessed. Design, originality and craft
are judgements about a rendered interface; producing a number for them from source
code is the exact substitution — reading in place of exercising — that this rubric
bans everywhere else. `null` is the honest answer, and `/crystal-harness:status`
renders it as a dash rather than a number, so a headless row and a browser row can
never be mistaken for each other.

**The thresholds are the weighting.** Product depth, design quality and originality
sit at 4 while craft and code quality sit at 3 — a product that is merely tidy and
merely working does not pass. Functionality also sits at 4: a full-stack app that
does not work is not gradeable on anything else. There is no separate weighted
score; the six scores per round are the trend a human reads to decide whether
another round is worth its cost.

### What a `headless` pass additionally requires

Waiving three dimensions is safe only if the other three were earned. A headless
`pass` requires all of:

- `design`, `originality` and `craft` are `null`; the other three are integers
  meeting their thresholds.
- `environment.apiVerified` **or** `environment.testsVerified` is `true`. Something
  was actually executed. A round where nothing ran is not a pass in any mode.
- At least one criterion has `result: "pass"`.
- Every `not_verified` criterion is marked `browserOnly: true`. A criterion you
  could not check for any *other* reason is an unexplained gap, and it blocks the
  pass exactly as it does in browser mode.

`validate_verdict.py` enforces all of this. Do not argue with it; a verdict it
rejects is a verdict the loop must not act on.

A criterion marked `not_verified` never counts toward a pass. If enough criteria are
`not_verified` that you cannot tell whether the work is sound, the verdict is `fail`
with a blocking issue naming what could not be checked and why.

The one exception is a criterion marked `browserOnly: true` in `headless` mode —
its evidence was waived by configuration, not lost. It still never counts *toward*
a pass; it simply does not block one. Mark `browserOnly` only where the criterion
genuinely cannot be reached without a browser. A criterion whose result is visible
in the API response or the datastore row is not browser-only just because the
contract phrased it as a click, and marking it so to avoid the work is how a
headless run becomes a rubber stamp.

## 1. Product depth — is the feature real, or is it a facade

This is the dimension that catches the most common way a generated app disappoints:
everything is present and nothing is finished. Grade what a user can actually *do*,
not what is rendered.

- **0** — The surface does not exist.
- **1** — The surface renders but is entirely static: no control does anything.
- **2** — Controls exist and respond, but the substance is display-only. Values can
  be read, not manipulated. Lists cannot be reordered, items cannot be edited in
  place, the visualisation cannot be interacted with.
- **3** — The primary object can be created and read, but a significant verb the
  domain implies is missing — no edit, no delete, no reorder, no drag, no undo.
- **4** — Every verb the contract (sprint QA) or the spec (final QA) implies is
  present and works. A user can complete real work end to end without hitting a
  stub.
- **5** — As 4, plus depth the spec implied but did not enumerate: bulk actions,
  keyboard paths, sensible defaults, states that compose.

The reference failure, from a build of a digital audio workstation: *"several core
DAW features are display-only without interactive depth: clips can't be dragged or
moved on the timeline, there are no instrument UI panels, and no visual effect
editors."* Every one of those surfaces rendered. None of them scored above 2.

Buttons that toggle but do nothing, sliders wired to no effect, and "coming soon"
panels are all 2s. A stub is a fail, not a partial credit.

In `headless` mode you still grade this dimension, from what you *can* drive: every
verb the domain implies should have an endpoint you can call and a row it changes,
and the project's own tests should exercise it. A verb with no reachable
implementation is the same 3 it would be in a browser. What you cannot see is
whether the surface wires up to it — so a headless verdict can catch a missing verb
but not a control that is connected to nothing, and that is precisely the gap the
mode trades away.

## 2. Functionality — does it work end to end for a real user

Includes edge paths and error paths, not only the happy path. Where product depth
asks *is the verb there*, functionality asks *does it behave correctly*.

- **0** — Does not start, or the primary surface does not render.
- **1** — Renders, but the main flow cannot be completed at all.
- **2** — Main flow completes only along one narrow path; common variations break.
- **3** — Main flow works. At least one edge or error path is broken or missing
  (empty state, invalid input, refresh, back navigation, boundary value), **or** a
  write appears to succeed in the UI but is not persisted.
- **4** — Every acceptance criterion passes, including edge and error paths, and
  every write survives a reload. Remaining defects are cosmetic.
- **5** — As 4, plus correct behaviour under conditions nobody specified: rapid
  repeated actions, refresh mid-flow, two tabs, resize during use, concurrent edits.

A partially working feature scores at most 3. "Works if you do it in the right
order" is 2.

## 3. Design quality — coherent visual identity

*"Does the design feel like a coherent whole rather than a collection of parts?"*

- **0** — Unstyled browser defaults.
- **1** — Styling applied but incoherent: colliding colors, arbitrary spacing, no
  discernible type scale.
- **2** — A theme is present but inconsistently applied; the same element type looks
  different on different screens.
- **3** — Consistent spacing scale, type scale, and color system. Nothing jars. The
  identity is generic but coherent.
- **4** — As 3, plus deliberate hierarchy: colors, typography, layout and imagery
  combine into a distinct mood. Density and contrast are used on purpose.
- **5** — As 4, and the visual system extends correctly to states it was not
  obviously designed for — errors, empty states, dense data, long strings.

## 4. Originality — deliberate decisions vs. defaults

*"Is there evidence of custom decisions, or is this template layouts, library
defaults, and AI-generated patterns? A human designer should recognize deliberate
creative choices."*

- **0** — Untouched starter template.
- **1** — Component library defaults throughout, default palette, default layout.
  Nothing indicates a choice was made.
- **2** — Colors and copy changed; structure and interaction are still stock. The
  tells: purple or violet gradients over white cards, centered hero on a dark
  radial background, three-column feature grid, stock dashboard shell.
- **3** — At least one substantive layout or interaction decision fits *this*
  product rather than any product.
- **4** — The interface's shape follows from the domain. Several decisions
  (navigation model, primary surface, information density) are specific to it.
- **5** — As 4, with a distinctive point of view carried consistently, including in
  micro-interactions and transitions.

A polished template is a 1–2 here even when it scores 4 on Design quality. That gap
is the reason both dimensions exist.

## 5. Craft — technical execution

Typography hierarchy, spacing consistency, color harmony, contrast ratios, states,
responsiveness, accessibility basics. A competence check, not a creativity check.

- **0** — Overlapping or misaligned elements; unreadable text.
- **1** — Visible alignment and rhythm errors; no interactive states at all.
- **2** — Hover exists; focus, disabled, empty, and loading states are missing or
  wrong. Layout breaks at common widths.
- **3** — Hover/focus/disabled present, empty and loading states exist, layout holds
  from 375px to desktop, text is readable, tab order follows visual order.
- **4** — As 3, plus keyboard operability of the main flow, visible focus rings,
  labelled controls, sufficient contrast, and no layout shift on load.
- **5** — As 4, with considered transitions, correct reduced-motion handling, and
  clean behaviour at extreme content lengths.

Check craft in the browser: tab through the flow, hover, trigger disabled, resize to
375px, load with an empty data set. Craft asserted from reading CSS is
`not_verified`. In `headless` mode there is no browser, so craft is `null` — do not
grade it from the stylesheet.

## 6. Code quality — the one dimension you grade by reading

Everywhere else in this harness, reading the code is not verification. Here it is
the method. Read the diff for the sprint, or the whole tree at final QA. This is
the one dimension that is graded identically in every mode.

If `codex-review.md` exists in the round directory, read it. It is an independent
review of the same diff by a different model, run before you were spawned, and it
is an **input to this dimension only**. Treat every finding in it as a claim, not a
fact: confirm it against the code yourself before it moves your score, and say in
`qa.md` which findings you confirmed and which you rejected. It never establishes
that anything works — it is more reading — and a finding you could not confirm
never becomes a blocking issue. Its absence means nothing; say so and grade as
usual.

- **0** — Does not build, or the source is generated noise.
- **1** — Works by accident: duplicated logic in several places, no separation
  between transport, domain and view, errors swallowed silently.
- **2** — Recognisable structure, but significant duplication, dead code left in,
  or error paths that log nothing and surface nothing.
- **3** — Coherent module boundaries, no large-scale duplication, errors handled
  explicitly with a user-facing message and a loggable detail, no dead code, and
  tests exist for the non-trivial logic.
- **4** — As 3, plus the abstractions match the domain rather than the framework,
  naming is consistent, and the tests would actually fail if the behaviour broke.
- **5** — As 4, and a new contributor could locate any feature from the structure
  alone.

Do not grade style preferences a formatter would settle. Do not demand abstraction
the size of the codebase does not justify — speculative generality is a defect here,
not a virtue.

## Blocking vs. non-blocking

**Blocking** — any of: an acceptance criterion marked `fail`; any dimension below a
threshold that applies in this mode; a console error thrown during a graded flow; a
write that does not persist; data loss; a navigation dead-end. Blocking issues are
the *only* thing the generator revises against.

**Non-blocking** — real but not gating: cosmetic misalignment, a nice-to-have state,
a slow-but-working path. Record them; they are inputs to a later sprint.

Every issue needs: reproduction steps, observed behaviour, expected behaviour,
**and a cause** — see below. Plus a screenshot path in `browser` mode; in
`headless` mode the equivalent evidence is the literal command and its output, in
the repro steps.

## Every failure must carry a diagnosis

Observing the failure is what makes it real. Locating it is what makes the report
useful. Do both, in that order, and never substitute the second for the first.

After you have reproduced a failure in the browser (or against the API), read the
code and find the mechanism. Report it as `cause`: the file, the line, and the
specific reason, at this level of precision:

> **FAIL** — Rectangle fill tool only places tiles at the drag start and end points
> instead of filling the region. `fillRectangle` exists but is not triggered on
> `mouseUp`.

> **FAIL** — Delete key handler at `LevelEditor.tsx:892` requires both `selection`
> and `selectedEntityId` to be set, but clicking an entity only sets
> `selectedEntityId`.

> **FAIL** — `PUT /frames/reorder` is declared after the `/{frame_id}` routes.
> FastAPI matches `reorder` as an integer `frame_id` and returns 422.

If you genuinely cannot locate the cause after a reasonable search, say so in
`cause` explicitly ("not located; searched X and Y"). An empty `cause` field on a
blocking issue is an incomplete verdict, not a neutral one.

The one thing this must never become: concluding from the code that a feature works.
That direction is banned. Code reading explains an observed failure; it never
establishes a pass.

## Beyond the browser: API and persistence

In `browser` mode this is the check that stops the UI from vouching for itself. In
`headless` mode it is the whole of your evidence, and everything below becomes
mandatory rather than supplementary — plus the project's own test suite, which you
run and whose result you record in `environment.testsVerified`.

A criterion is not verified until the data behind it is verified. For any flow that
writes:

1. Perform the write through the UI.
2. **Reload the page** and confirm it is still there.
3. Confirm it independently of the UI — hit the API endpoint with `curl`, or read
   the database (`sqlite3 <file> "select …"`, `psql -c`). The UI showing the value
   after a reload can still be a cache or local state.

Also exercise the API directly where the spec implies it: wrong method, missing
required field, unknown id, and a payload that violates a stated constraint. An API
that returns 200 for an invalid write is a blocking issue even when the UI never
sends one.

Read `.harness/config.json` for `urls.api` and the database location. If there is no
backend, say so in `qa.md` and skip this section rather than inventing one.

## `verdict.json`

JSON Schema (draft 2020-12):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "harness verdict",
  "type": "object",
  "required": ["schemaVersion", "phase", "round", "overall", "scores", "criteria", "blockingIssues", "nonBlockingIssues", "environment", "evaluatedAt"],
  "additionalProperties": false,
  "properties": {
    "schemaVersion": { "const": 3 },
    "phase": { "enum": ["sprint", "final"] },
    "sprint": { "type": ["integer", "null"], "minimum": 1, "description": "null when phase is final" },
    "round": { "type": "integer", "minimum": 0, "description": "revision number for a sprint, QA round for a final assessment" },
    "overall": { "enum": ["pass", "fail"] },
    "scores": {
      "type": "object",
      "required": ["productDepth", "functionality", "design", "originality", "craft", "codeQuality"],
      "additionalProperties": false,
      "description": "null means the dimension was not assessed — waived by headless mode, or unassessable in degraded mode. null never satisfies a threshold that applies.",
      "properties": {
        "productDepth": { "type": ["integer", "null"], "minimum": 0, "maximum": 5 },
        "functionality": { "type": ["integer", "null"], "minimum": 0, "maximum": 5 },
        "design": { "type": ["integer", "null"], "minimum": 0, "maximum": 5 },
        "originality": { "type": ["integer", "null"], "minimum": 0, "maximum": 5 },
        "craft": { "type": ["integer", "null"], "minimum": 0, "maximum": 5 },
        "codeQuality": { "type": ["integer", "null"], "minimum": 0, "maximum": 5 }
      }
    },
    "criteria": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "text", "result"],
        "additionalProperties": false,
        "properties": {
          "id": { "type": "string", "pattern": "^(AC|SPEC)-[0-9]+$" },
          "text": { "type": "string" },
          "result": { "enum": ["pass", "fail", "not_verified"] },
          "evidence": { "type": "string", "description": "what was actually done and what was observed; for not_verified, why it could not be checked" },
          "browserOnly": { "type": "boolean", "description": "this criterion cannot be checked without a browser. In headless mode a not_verified criterion must carry this flag; it then does not block a pass." },
          "screenshot": { "type": ["string", "null"] }
        }
      }
    },
    "blockingIssues": { "$ref": "#/$defs/issueList" },
    "nonBlockingIssues": { "$ref": "#/$defs/issueList" },
    "environment": {
      "type": "object",
      "required": ["verificationMode", "playwrightAvailable", "degraded"],
      "additionalProperties": false,
      "properties": {
        "verificationMode": { "enum": ["browser", "headless", "degraded"], "description": "browser = configured and working; headless = browserVerification is false; degraded = browserVerification is true but Playwright did not respond" },
        "playwrightAvailable": { "type": "boolean" },
        "degraded": { "type": "boolean", "description": "true if and only if verificationMode is degraded" },
        "degradedReason": { "type": ["string", "null"] },
        "appUrl": { "type": ["string", "null"] },
        "apiUrl": { "type": ["string", "null"] },
        "apiVerified": { "type": "boolean", "description": "true if endpoints were exercised outside the browser" },
        "persistenceVerified": { "type": "boolean", "description": "true if a write was confirmed in the datastore or via the API after a reload" },
        "testsVerified": { "type": "boolean", "description": "true if the project's own test suite was executed by the evaluator and passed" },
        "codexReview": { "enum": ["confirmed", "present", "absent", null], "description": "confirmed once its findings were checked against the code; present if the file exists but was not usable; absent otherwise" }
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
        "required": ["id", "summary", "repro", "observed", "expected", "cause"],
        "additionalProperties": false,
        "properties": {
          "id": { "type": "string", "description": "stable across rounds; reuse the id when the same defect recurs" },
          "criterionId": { "type": ["string", "null"] },
          "dimension": { "enum": ["productDepth", "functionality", "design", "originality", "craft", "codeQuality", null] },
          "summary": { "type": "string" },
          "repro": { "type": "array", "items": { "type": "string" } },
          "observed": { "type": "string" },
          "expected": { "type": "string" },
          "cause": {
            "type": "object",
            "required": ["mechanism"],
            "additionalProperties": false,
            "description": "found by reading the code AFTER observing the failure",
            "properties": {
              "file": { "type": ["string", "null"] },
              "line": { "type": ["integer", "null"] },
              "mechanism": { "type": "string", "description": "why it fails, or 'not located; searched …'" }
            }
          },
          "screenshot": { "type": ["string", "null"] }
        }
      }
    }
  }
}
```

Issue ids are stable across rounds. Reusing the id when the same defect survives a
revision is what lets the loop notice no progress and escalate instead of grinding.

## Headless mode

`harness.browserVerification` is `false`. Nobody expected a browser, so nothing is
broken and nothing is hidden — but the verdict must be explicit about what it did
not look at.

Set `verificationMode: "headless"`, `playwrightAvailable: false`, `degraded: false`,
`degradedReason: null`. Do not call a Playwright tool at all; an evaluation that
half-uses a browser is neither mode.

What you do instead, and it is not a reduced check — it is a different one, run to
the same standard:

- Install, build, and start the app. Startup errors are still findings.
- **Run the project's own test suite** and record the literal outcome. Set
  `testsVerified` to whether it ran and passed. Tests the generator wrote are not
  independent evidence of correctness, but a failing suite is conclusive.
- Exercise **every** endpoint the round touches, not just the ones a criterion
  names: happy path, wrong method, missing required field, unknown id, and a
  payload violating a stated constraint.
- Perform each write through the API and confirm it in the datastore. Then restart
  the backend and confirm it survived.
- Grade code quality by reading, including `codex-review.md` if present.

Score `design`, `originality` and `craft` as `null`. Score `productDepth`,
`functionality` and `codeQuality` normally. Mark each criterion you could not reach
`not_verified` with `browserOnly: true` and an evidence line saying browser
verification was disabled for this run. State the mode in the first line of `qa.md`,
and list every browser-only criterion under "Not verified" so the human sees the
size of what was skipped rather than a bare pass.

## Degraded mode

`harness.browserVerification` is `true` and Playwright MCP is unreachable. This is a
broken environment, not a configuration, and the difference must survive into the
verdict.

Do not silently fall back to reading code, and do not relabel the round as
`headless` — that would convert a failure into a setting. Set
`verificationMode: "degraded"`, `playwrightAvailable: false`, `degraded: true`, and
a `degradedReason` naming the exact error. Mark every criterion that requires
rendering, interaction, or visual judgement as `not_verified` with that reason, set
the scores you could not assess to `null`, and add a blocking issue stating what
could not be verified.

A degraded run never produces `overall: "pass"` — `null` does not satisfy a
threshold that applies, and in this mode the three visual thresholds still apply.
Two degraded verdicts in a row stop the loop: the harness is not measuring what it
was told to measure, and more rounds will not fix that.

The reduced check you *can* still do, clearly labelled as such at the top of
`qa.md`, is the headless list above. Report those and nothing more.
