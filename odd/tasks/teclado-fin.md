# Fix: reach the composition panel and the year without a pointer (P1-3, last slice)

**Status**: implemented and verified — §5 · **Branch**: `fix/teclado-fin` (from `origin/main`) ·
**Opened by**: `.impeccable/critique/2026-10-15T05-25-10Z__viewer-index-html.md`, issue **P1-3**.

## 1. The remaining barrier, measured

The critique's last accessibility item was "the composition chart only responds to the mouse". Measured, the honest
version is narrower and more useful:

| | |
|---|---|
| The chart's year selection | `click`/`mousemove` on an SVG `<rect>`: mouse only |
| The year slider (`input[type=range]`) | **fully keyboard operable already** — it is a native control |
| Its position in the tab order | **285 of 288** — behind the header, the legend, the map, the 13 edition filters and **255 row buttons** |

So the action has a keyboard path; what is missing is **reachability**. A reader tabbing from the top crosses a 255-row
list before touching a control that changes what the whole panel shows. Rewriting the catalogue's interaction model
(roving focus over the list) would fix it and is a much larger change with a real risk of breaking what works today.

**The proportionate fix is the standard one for a long list in the middle: skip links.** From the first tab stop of the
page, "Saltar al panel de composición" and "Saltar al selector de año" move the focus where the reader wants to be, in
one keystroke each. That also settles the chart's mouse-only click: with the slider reachable in two stops, the same
value has an equivalent keyboard path, which is what the requirement asks for. The chart's own click stays a
convenience for pointer users, and the panel's remaining distance is a *visual* question (P2-4: the year control four
screens from the map), not a keyboard blocker.

## 2. What to build

1. **Two skip links**, first children of `<body>`, before the header: `Saltar al panel de composición` → `#panel-panel`
   and `Saltar al selector de año` → `#time-bar`. Each target needs the id and `tabindex="-1"` so focus can land on a
   container that is not naturally focusable.
2. **They are invisible until focused** — that is the pattern, not a bug: hidden with the visually-hidden technique so
   they never take space or shift the grid (the `body` **is** the grid container, so an in-flow element would change the
   layout), and shown on focus as a visible control at the top-left.
3. **The landing is visible**: the target container shows a focus ring when the skip link lands on it, otherwise the
   reader cannot tell that the jump happened.
4. **The slider joins the focus ring convention.** It currently relies on the browser's own 1px outline while every
   other control in the interface uses the 2px accent ring; make it consistent.
5. **`.legend-empty` gets a rule.** The empty state exists in `app.js` ("La leyenda está vacía.") and has **no CSS at
   all**: it wraps inside the legend column's padding with no styling.

**Not in this slice**: a `<main>` landmark (the panels hang directly off the grid `body`; adding one is a grid
refactor), the catalogue's roving focus, and the visual distance of the year control.

## 3. Acceptance criteria (measured in the browser)

1. From a fresh load with the focus on `body`: the **first** Tab lands on the skip link for the composition panel, the
   **second** on the one for the year, and neither occupies space while unfocused (the layout at 1600 is unchanged: the
   same panel offsets as before).
2. Enter on the first moves the focus **inside** the composition panel (the panel or its target is `document.activeElement`,
   or the closest panel ancestor of the focused element is the panel), the panel shows a focus ring, and the browser has
   scrolled it into view.
3. Enter on the second lands in the time bar, and the year slider responds to keyboard input there (ArrowRight changes
   the year and the chart's cursor follows).
4. The slider's focus ring measures the same as the other controls' (2px solid, offset 1px).
5. `.legend-empty`: with the class applied to a probe element, its computed style differs from the browser default
   (`font-size` 12px, muted colour) — the empty legend is unreachable with the real artefact, so the check is a styling
   probe plus the rule's presence in the source.
6. No regression: the in-page detector stays at **0**; no horizontal scroll at 1600/1280/960/390; the tabs order after
   the two skip links continues as it does today (the header, the legend, the map…); the suite stays at **387**.

## 5. Outcome (measured in the browser)

| Criterion | Result |
|---|---|
| The page's first two tab stops | `Saltar al panel de composición`, then `Saltar al selector de año` |
| The links while unfocused | **1×1 px**, `position: absolute`, `clip: rect(0,0,0,0)` — and the geometry at 1600 is **identical** before and after (79 / 579 / 1687 / 4114, document 4220): they never became grid items |
| The first link focused | renders as a real control: **231×38 px at (8, 8)** with the 2px accent ring |
| Tab + Enter on it | `document.activeElement` is **`ASIDE#panel-panel`**, the panel carries the 2px accent ring and the page scrolled to y=1687 — the panel is now **two keystrokes** away instead of 285 tab stops |
| Second link + Enter | focus lands on **`FOOTER#time-bar`** |
| The year by keyboard | `ArrowLeft` moves 2024 → **2023 → 2022** and the chart's cursor follows (x1: 588 → 574.05 → 560.10) |
| `#year-slider` focus ring | `:focus-visible` matches; `solid 2px rgb(37, 99, 235)`, offset 1px — the same as every other control |
| `.legend-empty` | 12px, `rgb(75, 85, 99)`, padding `8px 2px` (probed by applying the class, since the real artefact never has an empty legend) |
| `tabindex="-1"` containers | **not** in the tab order (checked: neither `#panel-panel` nor `#time-bar` is among the 290 focusables) |
| Horizontal scroll @1600/1280/960/390 | none |
| In-page detector | **0** |
| Suite | **387 OK** (control: no Python touched) |

### What the measurement corrected

Two of my own probes were wrong before the code was: `document.body.focus()` does not reset the focus (the body is not focusable),
so the first attempt at the panel jump never left the time bar; and `ArrowRight` was pressed with the year already at its
maximum, where a range input correctly does nothing. Both were re-run properly, and both pass. The lesson is the usual one:
a failed probe is not a failed implementation until it is re-run in a state that can succeed.

### What this closes and what it leaves

With the slider reachable in two stops, the chart's mouse-only click stops being a keyboard blocker: the same value has an
equivalent keyboard path, which is what the requirement asks. What is left is **visual**, not interactive:

- **No `<main>` landmark.** The panels hang directly off the grid `body`, so wrapping them in one is a grid refactor, not
  a markup addition. Recorded here rather than smuggled in.
- **The catalogue's 255 row buttons are still 255 tab stops.** A roving-focus list is the proper fix and the right unit for
  it; the skip links are what makes it survivable meanwhile.
- **The year control stays four screens from the map** (P2-4, layout), and the chart's click remains a pointer convenience.

- **The skip links are the first thing in the layout's flow.** If they are not taken out of flow while hidden, they
  become grid items and shift every panel. The visually-hidden technique must keep them absolute.
- **`tabindex="-1"` targets**: a container with `tabindex="-1"` is focusable programmatically but must not join the tab
  order; check that tabbing past the header does not land on the panel container.
