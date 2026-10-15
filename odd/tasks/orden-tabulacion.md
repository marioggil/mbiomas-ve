# Fix: the DOM order contradicted the visual order (P1-3, first slice)

**Status**: implemented and verified — §3 · **Branch**: `fix/orden-tabulacion` (from `origin/main`) · **Commit**: `26dc875` ·
**Opened by**: `.impeccable/critique/2026-10-15T05-25-10Z__viewer-index-html.md`, issue **P1-3**.

## 1. The defect, measured

The document order was legend → **catalog** → **panel** → **map** → time bar, while the grid placed the map beside
the legend at the top. Measured on the served page with the app.js populated:

| | Before |
|---|---:|
| Focusable elements on the page | 286 |
| **Index of the first focusable inside the map panel** | **278** |
| Index of the first focusable in the catalog panel | 8 |
| Focusable elements inside the composition panel | **0** |

A keyboard or screen-reader user passed the header, the legend and then **every one of the catalog's ~270 controls —
13 edition filters, the search box and 255 row buttons — before reaching the map**, which is the second most important
surface in the product and the only place the coverage is visible.

On mobile the mismatch was visible too: the single-column layout put the catalog at y=216 and the map at y=1533, while
the DOM said catalog first and the layout agreed — so the DOM order matched on mobile and contradicted on desktop.

## 2. What changed

1. **`viewer/index.html`**: the `<section class="map-panel">` block moves to immediately after the legend panel, so
   the document order becomes header → legend → **map** → catalog → panel → time.
2. **`viewer/style.css`**: the two single-column layouts (`max-width: 960px` and the duplicate at `720px`) reorder
   their `grid-template-areas` to header → legend → **map** → catalog → panel → time, so the visual order equals the
   document order at **every** viewport. The desktop template already placed the map beside the legend and is
   unchanged.

**Safety check before moving anything**: no CSS sibling combinator (`~`, `+`), no `nth-child`, and no JS access by
position — every panel is reached by id or class, and there are no positive `tabindex` values. The reorder cannot
break a selector or a handler.

**The visible change on mobile is deliberate**: a phone now shows the legend and then the map, with the catalog after
both. Mobile is not a target per `PRODUCT.md`, and the map is the entry point of the drawn-area flow (D5), so it is
coherent — but it is a change a reader should know about, so it is stated here and in the PR.

## 3. Acceptance criteria

All four measured on the served page, at 1600, 1280, 960 and 390:

1. The first focusable inside the map panel is within the first **15** positions (from 278).
2. The visual order of the five panels equals the document order at 1600, 1280, 960 and 390.
3. The desktop layout is **unchanged**: the legend and the map on the same row, catalog, panel and time bar in their
   previous positions.
4. No regression: no horizontal scroll, the documented no-overlap guarantee holds, the in-page detector stays at zero,
   and the Python suite stays green (387 — a control, no Python is touched).

## 4. Out of scope

- **The year slider stays in the footer**, four screens from the map. Moving it is a layout decision (a sticky bar or
  a map control), not an ordering fix, and it is the second half of the same critique finding.
- **Drawing with the keyboard** and **the composition panel's zero focusables** are the other two parts of P1-3 and
  need the owner's decision on the interaction.
- The duplicated `max-width: 720px` block in `viewer/style.css` is updated but not deduplicated: that is a separate
  cleanup.
