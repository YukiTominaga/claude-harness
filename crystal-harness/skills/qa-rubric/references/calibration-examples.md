# Calibration examples

Worked examples for each rubric dimension. Read these before scoring. The anchors in
`SKILL.md` define the scale; these examples fix where the boundaries actually sit.

Each example is written as: what was observed in the browser → the correct score →
why that score and not the neighbouring ones.

Two examples are marked **⚠ trap**. They are the cases graders get wrong most often:
a polished artifact that scores low, and a plain one that scores high.

---

## Functionality

### F-a — score 2

**Observed.** Recipe app. From the home page, clicking "New recipe", filling title
and one ingredient, and clicking Save adds the recipe to the list. Repeating the
flow a second time without reloading leaves the form fields populated with the
previous recipe's values, and Save creates a recipe that merges old and new
ingredients. Navigating to a recipe, pressing browser Back, then clicking another
recipe renders a blank detail pane; a reload fixes it.

**Score: 2.** The main flow completes exactly once along one path. The second pass
and back-navigation both break — these are not edge cases, they are what the next
thing a user does. Not 3: at 3 the *main* flow is reliable and only a genuine edge
path is broken. Not 1: the flow does complete at least once.

### F-b — score 3

**Observed.** Pomodoro timer. Start, pause, resume, and reset all behave correctly,
including across a page refresh mid-session. Completed sessions appear in history
with correct durations. With zero sessions saved, `/history` renders an empty
container with no text and no illustration — nothing tells the user what this page
is or that it is empty rather than broken. No console errors.

**Score: 3.** Main flow works and survives refresh, which is more than most 3s. But
the empty state is missing, and the rubric names empty state as an edge path.
Not 4: 4 requires every acceptance criterion including edge paths to pass, and the
contract's AC for the empty state fails. Not 2: nothing in the common path breaks.

### F-c — score 4

**Observed.** Kanban board. Cards drag between columns and persist across reload.
Dropping a card outside any column returns it to its origin with no error. Creating
a card with an empty title shows an inline validation message and does not submit.
Killing the API and clicking Save surfaces a "Couldn't save — retry" banner and the
card stays editable. All seven acceptance criteria pass. Column headers are 1px
misaligned with the card grid.

**Score: 4.** Every criterion passes including the error path and the invalid-input
path. The alignment defect is cosmetic and belongs to Craft, not Functionality.
Not 5: nothing was demonstrated beyond the contract — rapid repeated drags and
two-tab behaviour were never exercised. Not 3: no edge path is broken.

### F-d — ⚠ trap — score 1

**Observed.** Analytics dashboard. Loads instantly, four charts render with smooth
entrance animations, filter chips highlight on click, date-range picker opens and
closes cleanly. Every chart shows the same numbers regardless of which filter or
date range is selected; the network tab shows no request fires on filter change.

**Score: 1.** It renders and it is pleasant, but the sprint's main flow — filtering
data — does not work at all. The polish is on Design and Craft, which are separate
dimensions. Not 3: the main flow is not merely edge-broken, it is inert. This is the
case where "no errors in the console" gets misread as evidence of correctness;
absence of an error is not evidence of anything. **Functionality is the gate, so this
sprint fails no matter what Design scores.**

---

## Design quality

### D-a — score 1

**Observed.** Expense tracker. Buttons are three different shades of blue across
three screens. Card padding is 12px on the list, 20px on the detail, 8px in the
modal. Headings use 22px, 19px, and 24px with no relationship between them. A red
that appears in the error banner also appears as a decorative divider.

**Score: 1.** Styling exists but there is no system — no spacing scale, no type
scale, and colour carries no consistent meaning. Not 2: at 2 there is a recognisable
theme applied unevenly; here there is no theme to apply.

### D-b — score 3

**Observed.** Task manager. Spacing is consistently on a 4px scale. Type scale is
three sizes plus a caption, applied the same way everywhere. One accent colour used
only for primary actions, one neutral ramp for surfaces and text, semantic red and
green used only for status. The result is a competent, generic SaaS surface — it
would suit any product in the category.

**Score: 3.** Consistent spacing, type, and colour systems, nothing jars. That is
exactly the 3 anchor. Not 4: there is no deliberate hierarchy beyond convention —
every screen weights everything equally, and the palette has no intent beyond
"blue is the action colour". Genericness costs Originality, not Design.

### D-c — score 4

**Observed.** Reading-list app. Dense list view with tight leading and muted
metadata; the reading pane switches to a wide-measure serif at generous leading, and
chrome recedes to near-invisible. Accent colour appears exactly twice per screen.
Contrast between the two modes is clearly deliberate and the eye lands on the
content both times. Long book titles wrap to two lines cleanly; the empty shelf uses
the same restrained system rather than a stock illustration.

**Score: 4.** Hierarchy, density, and contrast are used on purpose and the palette
has an intent. Not 5: no dense-data or error surface was exercised to prove the
system extends there; only the long-title case was observed.

### D-d — ⚠ trap — score 2

**Observed.** Landing page for a scheduling tool. Large hero with a purple-to-pink
gradient, glassmorphic feature cards, a floating gradient orb behind the fold,
smooth scroll animations. Below the fold the app shell is an untouched component
library default: grey table, default form controls, system-font labels, none of the
hero's palette or spacing.

**Score: 2.** "A theme is present but inconsistently applied; the same element type
looks different on different screens" — verbatim the 2 anchor. The hero reads as
high effort, which is what makes this a trap; the product surface where users spend
their time was not designed at all. Grade the whole artifact, not the first
screenshot.

---

## Originality

### O-a — score 1

**Observed.** Habit tracker. Centered card on a gradient background, shadcn defaults
untouched, default border radii and default primary colour, a three-column feature
grid, headline in the largest available size. The layout would be identical if the
product were a CRM.

**Score: 1.** Component library defaults throughout; nothing indicates a decision.
Not 0: it is not the untouched starter template — content was written for this
product. Not 2: even the colours are stock.

### O-b — score 3

**Observed.** Pomodoro timer. Instead of a numeric countdown as the primary element,
the session is represented as a horizontal bar that fills across the width of the
viewport, with completed sessions stacked underneath it as a growing column so the
day's work is the persistent background of the screen. Everything else — buttons,
settings sheet — is component-library default.

**Score: 3.** One substantive decision about how the primary object is represented,
and it fits this product specifically: a timer whose point is accumulated focus.
Not 4: it is a single decision; navigation, settings, and history are stock. Not 2:
this is not a re-skinned default layout, it is a different answer to "what is on
screen".

### O-c — score 4

**Observed.** Invoicing tool. The primary surface is the invoice itself, edited in
place at print proportions, with the app's controls in a narrow rail that collapses
when typing. There is no list-then-detail navigation — invoices are reached from a
year-strip along the top. Status is shown by paper texture and a stamp rather than a
badge. The choices are consistent with "this is a document, not a database row".

**Score: 4.** Navigation model, primary surface, and status representation all
follow from the domain. Not 5: micro-interactions and transitions are conventional
and the point of view does not carry into them.

### O-d — ⚠ trap — score 4, on a plain-looking artifact

**Observed.** Internal on-call log. Visually spare: system font stack, white
background, one accent, no illustrations, no animation. But the entire interface is
a single keyboard-driven timeline — new entries are typed into an always-focused
line at the bottom, timestamps are implicit, and filtering happens by typing a
prefix rather than by any control. There are no buttons on the main surface at all.
Nothing here resembles a default dashboard.

**Score: 4.** Originality grades evidence of deliberate decision, not decoration.
The interaction model is specific to the domain (fast entry under pressure, no
mouse) and carried consistently. Its plainness is itself the decision. A grader who
scores this 1 because it "looks unstyled" is grading Design, which should be scored
separately — and here Design would be around 3.

---

## Craft

### C-a — score 1

**Observed.** Form-heavy settings page. Labels sit 3px above their inputs on one
row and 9px on the next. Submit and Cancel are 2px out of vertical alignment.
Nothing changes on hover. Tabbing moves focus but no focus indicator is drawn. At
900px wide the sidebar overlaps the content.

**Score: 1.** Visible alignment and rhythm errors and no interactive states at all —
the 1 anchor. Not 2: 2 requires hover to at least exist.

### C-b — score 3

**Observed.** Notes app. Buttons have hover, visible focus rings, and a greyed
disabled state that is genuinely non-clickable. The list shows a spinner while
loading and a written empty state. From 375px to 1440px nothing overflows and text
stays readable. Tab order follows the visual order. Contrast on the muted secondary
text measures about 3.8:1 against the background, and the icon-only archive button
has no accessible name.

**Score: 3.** All the 3-anchor items are present. Not 4: 4 requires sufficient
contrast and labelled controls, and both fail here. Not 2: focus, disabled, empty,
and loading states all exist and the layout holds.

### C-c — score 4

**Observed.** Booking flow. Full keyboard operability end to end, including the date
picker via arrow keys with a visible focus ring at every stop. All controls labelled;
the icon-only close button has an accessible name. Contrast passes on body and
secondary text. Reserved space for the results list means no layout shift when data
arrives. Transitions are instant with no motion at all.

**Score: 4.** Every 4-anchor item is met. Not 5: 5 asks for considered transitions
and reduced-motion handling; there are no transitions to consider, and extreme
content lengths were not tested.

### C-d — ⚠ trap — score 2

**Observed.** Chat interface. Beautifully rendered message bubbles, a smooth typing
indicator, tasteful shadows and micro-animation on send. Tabbing from the composer
jumps to the browser chrome — the send button is a `div` and never receives focus.
The composer shows no disabled state while a message is in flight and a second
Enter sends a duplicate. On an empty conversation the message area is blank with no
text. At 375px the composer is pushed off-screen by the sidebar.

**Score: 2.** Hover and animation exist; focus, disabled, and empty states are
missing or wrong and the layout breaks at a common width — the 2 anchor, exactly.
The animation quality is Design, and the duplicate-send is also a Functionality
defect. Do not let polish on one dimension pull up a score on another.

---

## Cross-dimension check before writing the verdict

Ask these three questions. Each catches a specific scoring failure:

1. **Did I score Design and Originality independently?** A polished template is high
   Design and low Originality (D-c vs. O-a). A plain but deliberate interface is the
   reverse (O-d). If the two scores move together every time, they are not being
   graded separately.
2. **Did any dimension's polish raise another's score?** F-d and C-d are the traps.
   Animation is not correctness; correctness is not accessibility.
3. **Is anything scored above 0 that I did not exercise in the browser?** If yes,
   it is `not_verified`, not a score. A feature I read the code for is
   `not_verified`.
