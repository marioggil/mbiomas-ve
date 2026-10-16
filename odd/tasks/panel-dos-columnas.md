# Feature: the composition panel's width and its detail

**Status**: implemented and verified · **Branch**: `fix/panel-dos-columnas` (from `origin/main` `c6a1475`) · **Commit**: `<pending>` · **Unit**: 3 of the plan after the second critique, with the shape the owner contributed.

## 1. The defect, measured

The composition panel is **1585px wide** and its chart is **620px**: the typography unit capped the chart there so it would
stop scaling its own text with the container (at 2.57x its title was larger than the page's `h1`), and that cap left
**937px of dead width** beside it — a void the same unit created and never filled. Under the chart, the level-2 breakdown
is **27 rows of 60px = 1733px**, and the panel ends up **2426px tall**, which is 1.51 screens below the map it answers:

| | y | height |
|---|---|---|
| Map panel | 79 | 500 |
| Legend column | 79 | 500 |
| Study catalog | 579 | 1013 |
| **Composition panel** | **1591** | **2426** |
| — its chart | 1684 | 341 (620 wide) |
| — its chart legend | 2039 | 116 (1557 wide) |
| — its breakdown list | 2208 | 1733 (27 rows) |

The document is 4.02 screens at 1600x1000 and 4.66 at 1280x800.

## 2. What to build

The owner's shape, measured with an injected prototype before writing any code: **the chart and its legend on the left,
the breakdown on the right, and the breakdown clamped** behind a "ver más".

Measured with the prototype:

| | Today | This shape |
|---|---|---|
| Panel, 1600x1000 | 2426px | **665px** |
| Document | 4.02 screens | **2.26** |
| Panel, 1280x800 | 2426px | **665px** (2.46 screens) |
| Panel, 960x700 (stacked, clamped) | 2426px | **1249px** (measured; the prototype's 1212 hid the breakdown title) |
| Chart | 620x341 | **620x341, unchanged** |
| Visible rows | 27 | **8 of 27** |

1. **`viewer/index.html`**: wrap `#panel-chart` and `#panel-legend` in a new `<div class="panel-chart-block">`. The ids do
   not change, so `panel.js` needs no edit for this part. The wrapping is what makes the legend sit directly under the
   chart: without it, a list spanning two grid rows redistributes the height and pushes the legend ~984px down, which the
   prototype did and the measurement caught.
2. **`viewer/index.html`**: add the breakdown's disclosure control after `#panel-breakdown-list` — a real `<button>` with
   `aria-expanded` and `aria-controls`, in the idiom the file already uses five times.
3. **`viewer/style.css`**: the two-column layout, **only from 1101px up** (`@media (min-width: 1101px)`) so every narrower
   width keeps today's stacked order byte for byte:
   - `.panel-panel` becomes a grid, `grid-template-columns: 660px minmax(0, 1fr)`, with the chart block in the first
     column and the breakdown in the second, both starting at the same row so their tops align.
   - The first column is 660px and **the chart never renders narrower than 620px**: that cap is what keeps its text in the
     11-13px band, so the column must not shrink it.
   - The clamp: 8 rows visible, the rest hidden while collapsed. Use the file's own pattern — one class on the body or on
     the panel decides what is hidden, and the control sits outside the content it hides.
4. **`viewer/panel.js`**: the disclosure's state, its label and its toggle:
   - The label says how many it reveals (`Ver las 19 clases restantes` / `Ver menos`), read from the rendered rows so it
     cannot disagree with the list.
   - The control is **hidden when the list has 8 rows or fewer** (an area with six classes must not offer a "ver más" that
     reveals nothing).
   - **The state resets to clamped on every render**, so the panel is short by default after a clip or a year change. Say
     so in the code.
   - The busy row added by `odd/tasks/cifra-fantasma.md` (`#panel-breakdown-busy`) is inserted before
     `#panel-breakdown-list`; give it a place in the grid so it does not break the columns.
5. Keep every existing behaviour: the chart's `<desc>` and its scope sentence, the breakdown's title and its denominator
   labels, the `aria-busy` mark, and the row that shows the area's figure.

## 3. Acceptance criteria

1. At **1600x1000 and 1280x800 the panel is ≤700px tall** and the document ≤2.6 screens.
2. **The chart is 620px wide at both sizes** and its text stays in the 11-13px band.
3. **The chart and the breakdown start at the same y** (top-aligned, within a few px), and **the chart's legend sits
   directly under the chart** (gap ≤ 20px).
4. **The breakdown shows 8 rows** with a working disclosure: expanding shows all 27, `aria-expanded` follows, the label
   carries the count, and the control is keyboard reachable (Tab, Enter, Space).
5. **Below 1101px nothing changes**: the stacked order, the chart at 620, and the clamp still applied (the panel ≈1212px at
   960x700).
6. With an area drawn, the list, its title and the disclosure's count all follow the drawn window, and the busy row still
   appears while the clip is in flight.
7. No new `font-size`, `line-height`, `font-weight`, colour or background declaration; the in-page detector stays at 0.
8. Suite `387 OK`; `node --check` clean on every touched JS file.

## 6. Outcome, measured

All eight criteria hold, measured on a fresh origin (a new port) after two refinements the pass forced:

| | 1600x1000 | 1440x900 | 1280x800 | 1100x800 | 960x700 | 390x844 |
|---|---|---|---|---|---|---|
| Panel | **660px** | 660 | **660** | 1249 | 1249 | 1271 |
| Document | **2.25 screens** | 2.48 | **2.58** | 3.19 | 3.98 | 3.88 |
| Chart | 620x341 | 620 | 620 | 620 | 620 | 347x196 |
| Chart-to-breakdown alignment | **0px** | 0 | 0 | 491 (stacked) | 491 | 345 |
| Chart-to-legend gap | **14px** | 14 | 14 | 14 | 15 | 14 |
| Visible rows | **6 classes + the total** | | | | | |

- **The clamp and its control**: 6 class rows plus the year's total visible out of 26 classes; the label reads *"Ver las 20 clases restantes"* and follows the data (with a drawn window it becomes *"Ver las 6 clases restantes"* for that window's 12 classes). `aria-expanded` follows, the glyph follows, and **Enter and Space both toggle it** from the keyboard with the focus on the button.
- **With an area drawn**: the list and the title follow the window, the clamp resets to collapsed, and the busy row from `odd/tasks/cifra-fantasma.md` appears in the second column and clears.
- **The detector reports 0** in page; suite `387 OK`; no horizontal scroll at any of the six widths.

### The two refinements the pass forced

1. **Eight rows left the panel at 758px against the 700px ceiling.** The clamp is now **6**, which is also the better default on the merits: the rows are sorted by area and the first six carry 93.34 % of 2024 between them, so the tail — every one of them under 4 % — is exactly what a "ver más" is for. The panel came down to 660px.
2. **The clamp was hiding the year's total.** `> :nth-child(n + 9)` folded *every* child past the eighth, including the `Suma del año` line: while collapsed the panel showed six classes and no total, and the control's count could not say so. The selector is now `> .panel-bar:nth-child(n + 7)`, so only class rows fold and the total stays where the six rows add up to it.

## 7. What this verification found that is not this unit's

**Clearing a drawn area leaves the breakdown empty.** `panel.clearClip()` sets `breakdownList.innerHTML = ""` with a comment saying the list stays empty *"until the per-year render lands"*, and `app.js`'s `clearClip` then calls `setYear(currentYear)` — which **no-ops when the year has not changed**. So the promised render never lands: the panel keeps the title *"Clases (nivel 2) en 2024 — ordenadas por área"* with **no rows under it**. It is pre-existing (this unit's diff only added a busy-state call to that function) and it is the same family as the ghost figure: a surface showing a state whose supporting content was never restored. Recorded here rather than fixed inside a layout unit.

## 8. Risks

- **The legend under the chart is the one thing the prototype got wrong**, which is why the wrapper is part of the spec and
  the gap is an acceptance criterion.
- **The grid and the clamp interact**: hiding rows with a body class while the grid places the list in a column means the
  margin/gap must be checked at both states, expanded and clamped.
- **The 1101px boundary**: at 1100 the panel is 1212px wide and the two columns would leave the chart 660px and the list
  ~380px, too narrow for its bars. Below the boundary the stacked layout is not a fallback, it is the design.
- **A gratuitous "ver más"**: with eight or fewer classes the control must not exist, or it promises rows that are not
  there.

## 9. Verification

Run: `node --check viewer/panel.js`; the suite (`387 OK`); the browser pass above at six widths on a fresh origin; the clamp and its control by mouse and by keyboard; the drawn-area render and the busy row; the in-page detector (0). The worker's own validation covered the state machine with a stub-DOM harness (init, open, close, a 9-row render, an 8-row render, the error and clear paths) and the diff's shape — no new `font-size`, `line-height`, `font-weight`, colour or background declaration.
