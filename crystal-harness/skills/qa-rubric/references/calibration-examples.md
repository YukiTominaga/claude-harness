# Calibration examples

Worked examples for each rubric dimension. Read these before scoring. The anchors in
`SKILL.md` define the scale; these examples fix where the boundaries actually sit.

Each example is written as: what was observed → the correct score → why that score
and not the neighbouring ones.

Examples marked **⚠ trap** are the ones graders get wrong most often: polished
artifacts that score low, plain ones that score high, and polish on one dimension
pulling up another.

---

## Product depth

### P-a — score 2 — ⚠ trap

**Observed.** A digital audio workstation. The timeline renders clips with waveform
thumbnails at correct positions. The mixer shows per-channel faders, pan knobs and
level meters that animate during playback. An effects rack lists EQ, compressor and
reverb per channel. Playback works and sounds correct.

Clips cannot be dragged, moved, resized or split. The instrument channels have no
instrument UI at all — no synth knobs, no drum pads. The effect editors are numeric
sliders; there is no EQ curve, no compressor transfer graph.

**Score: 2.** Every surface renders and the app is genuinely impressive at a glance.
But the substance is display-only: the user can read state and cannot manipulate it.
Not 3: at 3 the primary object can at least be created and edited, with one verb
missing; here the central object of a DAW — the clip on the timeline — supports no
verbs. Not 1: controls do respond, playback and mixing work.

This is the single most common failure in generated applications and the reason this
dimension exists. **Design quality on this same build was 4.** Grade them
separately.

### P-b — score 3

**Observed.** A recipe manager. Recipes can be created, viewed, and edited. The
ingredient list within a recipe can be added to and removed from. Recipes cannot be
deleted — there is no delete control anywhere, and no API route for it. Everything
else the spec described works.

**Score: 3.** "The primary object can be created and read, but a significant verb
the domain implies is missing." Delete is not an edge case for a collection the user
owns. Not 4: 4 requires every verb the spec implies. Not 2: this is not display-only
— the user genuinely manipulates their data.

### P-c — score 4

**Observed.** A kanban board. Cards can be created, edited in place, dragged between
and within columns, archived and deleted. Columns can be renamed and reordered.
Every action persists across reload and is confirmed present in the database.
Keyboard shortcuts are absent and there is no bulk selection.

**Score: 4.** Every verb the spec implies is present and works end to end. Not 5: 5
requires depth beyond the spec — bulk actions and keyboard paths are exactly what is
missing. Not 3: no implied verb is absent.

### P-d — ⚠ trap — score 2 on a build whose tests all pass

**Observed.** An issue tracker. 140 unit tests pass. `POST /issues`, `PATCH
/issues/{id}` and `DELETE /issues/{id}` all exist and are covered. In the UI, the
issue list renders, the detail pane renders, and the "Assign" and "Add label"
buttons open menus that render the available options — selecting one closes the menu
and changes nothing. The wiring from menu selection to the PATCH call was never
written.

**Score: 2.** The backend depth is real and the frontend depth is a facade. Grade
what a user can do. A passing test suite is not evidence of product depth; it is
evidence that the tested units behave, which is a different claim.

---

## Functionality

### F-a — score 2

**Observed.** Recipe app. From the home page, creating a recipe works once.
Repeating the flow without reloading leaves the form populated with the previous
recipe's values, and Save creates a recipe merging old and new ingredients.
Navigating to a recipe, pressing Back, then clicking another renders a blank detail
pane; a reload fixes it.

**Score: 2.** The main flow completes exactly once along one path. The second pass
and back-navigation both break — not edge cases, but the next thing a user does. Not
3: at 3 the main flow is reliable. Not 1: the flow does complete once.

### F-b — score 3

**Observed.** Pomodoro timer. Start, pause, resume and reset behave correctly
including across a refresh mid-session. Completed sessions appear in history with
correct durations. With zero sessions saved, `/history` renders an empty container
with no text — nothing tells the user the page is empty rather than broken. No
console errors.

**Score: 3.** The main flow works and survives refresh. The empty state is missing,
and the rubric names empty state as an edge path. Not 4: 4 requires every criterion
including edge paths.

### F-c — score 3 — ⚠ trap: the UI lies about persistence

**Observed.** A notes app. Creating a note shows it in the list immediately and it
is still there after navigating away and back. After a hard reload, it is gone.
`sqlite3 app.db "select count(*) from notes"` returns 0; the POST is never sent and
the list is served from React state.

**Score: 3**, not 4 — "a write appears to succeed in the UI but is not persisted" is
named in the 3 anchor. The trap is that navigating away and back looks like proof.
It is not: only a reload plus an independent read of the datastore is.

### F-d — score 4

**Observed.** Kanban board. Cards drag between columns and persist across reload,
confirmed with a direct database read. Dropping outside any column returns the card
to its origin with no error. An empty title shows inline validation and does not
submit. With the API killed, Save surfaces a "Couldn't save — retry" banner and the
card stays editable. All seven criteria pass. Column headers are 1px misaligned.

**Score: 4.** Every criterion passes including error and invalid-input paths, and
persistence is independently confirmed. The alignment defect belongs to Craft. Not
5: rapid repeated drags and two-tab behaviour were never exercised.

### F-e — ⚠ trap — score 1

**Observed.** Analytics dashboard. Loads instantly, four charts render with smooth
entrance animations, filter chips highlight on click, the date picker opens cleanly.
Every chart shows identical numbers regardless of filter or date range; the network
tab shows no request fires on filter change.

**Score: 1.** It renders and it is pleasant, but the main flow — filtering — is
inert. "No console errors" gets misread as evidence of correctness; absence of an
error is evidence of nothing.

---

## Design quality

### D-a — score 1

**Observed.** Expense tracker. Buttons in three different blues across three
screens. Card padding 12px on the list, 20px on the detail, 8px in the modal.
Headings at 22px, 19px and 24px with no relationship. The error red also appears as
a decorative divider.

**Score: 1.** Styling exists but there is no system and colour carries no consistent
meaning. Not 2: at 2 there is a recognisable theme applied unevenly.

### D-b — score 3

**Observed.** Task manager. Consistent 4px spacing scale. Three type sizes plus a
caption, applied identically everywhere. One accent used only for primary actions,
one neutral ramp, semantic red and green only for status. A competent, generic SaaS
surface that would suit any product in the category.

**Score: 3.** Exactly the 3 anchor. Not 4: no deliberate hierarchy beyond
convention, and the palette has no intent beyond "blue is the action colour".
Genericness costs Originality, not Design.

### D-c — score 4

**Observed.** Reading-list app. Dense list view with tight leading and muted
metadata; the reading pane switches to a wide-measure serif at generous leading and
the chrome recedes to near-invisible. Accent appears exactly twice per screen. The
contrast between modes is clearly deliberate and the eye lands on the content both
times. Long titles wrap cleanly; the empty shelf uses the same restrained system.

**Score: 4.** Hierarchy, density and contrast used on purpose; the palette has an
intent. Not 5: no dense-data or error surface was exercised to prove the system
extends there.

### D-d — ⚠ trap — score 2

**Observed.** Landing page for a scheduling tool. Large hero with a purple-to-pink
gradient, glassmorphic cards, a floating gradient orb, smooth scroll animations.
Below the fold the app shell is an untouched component library default: grey table,
default form controls, system-font labels, none of the hero's palette or spacing.

**Score: 2.** "A theme is present but inconsistently applied" — verbatim the anchor.
The hero reads as high effort, which is what makes it a trap; the surface where
users spend their time was not designed at all. Grade the whole artifact, not the
first screenshot.

---

## Originality

### O-a — score 1

**Observed.** Habit tracker. Centered card on a gradient, component-library defaults
untouched, default radii and default primary colour, three-column feature grid,
headline in the largest available size. The layout would be identical for a CRM.

**Score: 1.** Defaults throughout; nothing indicates a decision. Not 0: content was
written for this product. Not 2: even the colours are stock.

### O-b — score 3

**Observed.** Pomodoro timer. Instead of a numeric countdown as the primary element,
the session is a horizontal bar filling across the viewport, with completed sessions
stacked underneath as a growing column so the day's work is the persistent
background. Everything else — buttons, settings sheet — is library default.

**Score: 3.** One substantive decision about how the primary object is represented,
fitting this product specifically. Not 4: a single decision; navigation, settings
and history are stock.

### O-c — score 4

**Observed.** Invoicing tool. The primary surface is the invoice itself, edited in
place at print proportions, with controls in a narrow rail that collapses when
typing. No list-then-detail navigation — invoices are reached from a year-strip.
Status is shown by paper texture and a stamp rather than a badge.

**Score: 4.** Navigation model, primary surface and status representation all follow
from the domain. Not 5: micro-interactions and transitions are conventional.

### O-d — ⚠ trap — score 4 on a plain-looking artifact

**Observed.** Internal on-call log. Visually spare: system font stack, white
background, one accent, no illustration, no animation. The entire interface is a
single keyboard-driven timeline — entries are typed into an always-focused line at
the bottom, timestamps are implicit, filtering happens by typing a prefix. There are
no buttons on the main surface.

**Score: 4.** Originality grades evidence of deliberate decision, not decoration.
The interaction model is specific to the domain — fast entry under pressure, no
mouse — and carried consistently. Its plainness is the decision. Scoring it 1
because it "looks unstyled" is grading Design, which here would be about 3.

---

## Craft

### C-a — score 1

**Observed.** Settings page. Labels sit 3px above their inputs on one row and 9px on
the next. Submit and Cancel are 2px out of vertical alignment. Nothing changes on
hover. Tabbing moves focus but no indicator is drawn. At 900px the sidebar overlaps
the content.

**Score: 1.** Alignment and rhythm errors with no interactive states. Not 2: 2
requires hover to at least exist.

### C-b — score 3

**Observed.** Notes app. Hover, visible focus rings, and a genuinely non-clickable
disabled state. Spinner while loading, written empty state. From 375px to 1440px
nothing overflows. Tab order follows visual order. Muted secondary text measures
about 3.8:1 against the background, and the icon-only archive button has no
accessible name.

**Score: 3.** All 3-anchor items present. Not 4: 4 requires sufficient contrast and
labelled controls, and both fail.

### C-c — score 4

**Observed.** Booking flow. Full keyboard operability end to end including the date
picker via arrow keys with a visible focus ring at every stop. All controls labelled.
Contrast passes on body and secondary text. Reserved space for results means no
layout shift. Transitions are instant with no motion.

**Score: 4.** Every 4-anchor item met. Not 5: 5 asks for considered transitions and
reduced-motion handling; there are no transitions to consider.

### C-d — ⚠ trap — score 2

**Observed.** Chat interface. Beautifully rendered bubbles, smooth typing indicator,
tasteful shadows and micro-animation on send. Tabbing from the composer jumps to
browser chrome — the send button is a `div` and never receives focus. No disabled
state while a message is in flight, and a second Enter sends a duplicate. An empty
conversation shows a blank area with no text. At 375px the composer is pushed
off-screen.

**Score: 2.** Hover and animation exist; focus, disabled and empty states are
missing or wrong and the layout breaks at a common width. The animation quality is
Design; the duplicate send is also a Functionality defect. Polish on one dimension
must not lift another.

---

## Code quality

### Q-a — score 1

**Observed.** Expense tracker, FastAPI + React. The same currency-formatting logic
appears in four components with three different rounding behaviours. Every route
handler opens its own database connection inline and builds SQL by f-string
interpolation. Errors are caught with `except Exception: pass` in six places, so a
failed write returns 200. There is no test directory.

**Score: 1.** "Works by accident": duplicated logic, no separation between transport
and domain, errors swallowed silently. Not 2: at 2 there is recognisable structure;
here every layer is mixed into the handler.

### Q-b — score 3

**Observed.** Kanban board. `api/`, `domain/`, `ui/` separated; the board reducer is
a pure module with 24 tests that fail when its behaviour is changed. Errors from the
API layer are typed and surface both a user-facing message and a logged detail. Two
small helpers are duplicated between two components, and one commented-out earlier
implementation of the drag handler is still in the file.

**Score: 3.** Coherent boundaries, explicit error handling, real tests. The
duplication is small-scale and the dead code is one block. Not 4: the abstractions
follow the framework (`useBoardState`, `BoardProvider`) rather than the domain, and
the dead code is exactly what the 3 anchor tolerates and the 4 anchor does not.

### Q-c — score 4

**Observed.** Invoicing tool. Modules are named for domain concepts (`invoice`,
`ledger`, `dunning`) not framework roles. Money is a single value type used
everywhere; no float arithmetic on amounts. Every failure path returns a typed
error the UI renders. Tests assert behaviour — mutating a rounding rule breaks
eleven of them. No dead code, no duplication.

**Score: 4.** Abstractions match the domain, naming is consistent, tests genuinely
fail when behaviour breaks. Not 5: a new contributor would still need to trace the
payment webhook by hand; the structure does not reveal it.

### Q-d — ⚠ trap — score 2 on a codebase that looks disciplined

**Observed.** A notes app with 38 files, an interface for every service, a
`repositories/` layer, a `factories/` layer and dependency injection throughout —
for a single-user SQLite app with four tables. Three of the five interfaces have
exactly one implementation and no test doubles. The tests mock the repository and
assert that the service calls the repository, which passes whether or not a note is
ever saved.

**Score: 2.** Speculative generality is a defect, and tests that assert their own
mocks are tautological — they would not fail if the behaviour broke. The apparent
discipline is the trap. Not 3: the tests do not cover the non-trivial logic in any
meaningful sense, and the layering is duplication of intent rather than structure.

---

## Cross-dimension check before writing the verdict

Ask these five questions. Each catches a specific scoring failure.

1. **Did I grade Product depth on what a user can do, not on what renders?** P-a and
   P-d are the traps. A surface that displays state perfectly and manipulates
   nothing is a 2, however good it looks and however many tests pass.
2. **Did I score Design and Originality independently?** A polished template is high
   Design and low Originality (D-c vs. O-a). A plain but deliberate interface is the
   reverse (O-d). If the two move together every time, they are not being graded
   separately.
3. **Did polish on one dimension raise another's score?** F-e, C-d and Q-d.
   Animation is not correctness; correctness is not accessibility; layering is not
   quality.
4. **Did I confirm every write outside the UI?** F-c. Navigating away and back is
   not proof. A reload plus a database or API read is.
5. **Is anything scored above 0 that I did not exercise?** If yes it is
   `not_verified`, not a score — except Code quality, which is graded by reading and
   only by reading.
