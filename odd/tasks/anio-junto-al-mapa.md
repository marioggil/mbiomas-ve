# Feature: the year control sits with the map

**Status**: implemented and verified · **Branch**: `fix/anio-junto-al-mapa` (from `origin/main` `6acc637`) · **Commit**: `e1c7d20` ·
**Unit**: P2-4a of the design critique (`.impeccable/critique/2026-10-15T05-25-10Z__viewer-index-html.md`), decided by the owner.

## 1. The defect, measured

The year control is the last row of the page grid: `.time-bar` is a `<footer>` with `grid-area: time`, so it is the
final row of a four-screen document. Measured at `6acc637`, before this unit:

| | 1600x1000 | 1280x800 | 390x844 |
|---|---|---|---|
| Document height | 4220px (4.22 screens) | 4013px (5.02) | 4661px (5.52) |
| Map | y=79 | y=79 | y=216 |
| **Year bar** | **y=4114 → 4.11 screens** | 3906 → 4.88 | 4554 → 5.40 |
| **Year-to-map distance** | **4.04 screens** | 4.78 | 5.14 |
| First catalogue row | y=969 → 0.97 screens | 902 → 1.13 | 1278 → 1.51 |

The problem is not only distance, it is **feedback**. The control exists to scrub the year and watch the map change;
four screens apart, the user chooses between seeing the map or seeing the year. A jump link (the cheap device this
project already used in `odd/tasks/teclado-fin.md`) does **not** fix that: it lands the user at the bar, four screens
from the map, to scrub blind. Measured in the browser: `position: sticky; bottom: 0` does work here (the only ancestor
is `body`, with no clipping), but it permanently occupies 106px of the viewport — and with the first catalogue row at
969px against 894px of usable height, it would **cover** the page's authoritative surface. Both were rejected.

## 2. What to build

Move the year control under the map, inside the map panel, as a one-row band:

1. **`viewer/index.html`**: wrap the map's canvas region in a new `<div class="map-canvas">` holding `#map`,
   `.map-controls` and `.map-overlays` — the three children `.map-panel` has today, in the same order — and move the
   `<footer class="time-bar" id="time-bar" tabindex="-1" aria-label="Selector de año">` block from after the
   composition `<aside>` to directly after that wrapper, still inside `<section class="map-panel">`. Keep the id, the
   classes, `tabindex="-1"` and the `aria-label`: `viewer/app.js` reaches the control through
   `#year-slider`/`#year-value`/`#year-min`/`#year-max` (lines 48-51) and **must not need a single edit**.
2. **`viewer/index.html`**: reorder the two skip links so they follow document order — the year (now under the map)
   before the composition panel. Both keep their targets and both targets keep `tabindex="-1"`.
3. **`viewer/style.css`**: remove the `time` row from all three `grid-template-areas` declarations (desktop, and the
   two single-column variants) and drop `grid-area: time` from `.time-bar`.
4. **`viewer/style.css`**: make `.map-panel` a column (`display: flex; flex-direction: column`), `.map-canvas`
   `position: relative; flex: 1 1 auto; min-height: 0`, and the bar `flex: 0 0 auto`. `.map-canvas` becomes the
   containing block for the absolutely positioned chrome (`.map-controls`, `.map-overlays`), which is why the wrapper
   exists: without it those three would anchor to the whole panel and overlap the new band.
5. **`viewer/style.css`**: lay the band out as a **single row** where there is width for it (label, slider, value, and
   the min/max range inline), keeping the current stacked shape at narrow widths through a media query. Keep the
   `--bg-bar` colours, the padding, the `border-top` and the `.time-bar:focus` outline rule untouched.

## 3. The forced choice, and why the map pays

The panel has `height: clamp(260px, 50vh, 720px)` and `overflow: hidden`, and `.map` fills it with `inset: 0`. A band
inside the panel therefore has to take its height from somewhere:

- **Chosen**: the panel keeps its height and the map cedes the band's height (~55px in the one-row shape, ~106px if
  stacked). Nothing below the map moves, so P2-4b is not made worse.
- **Rejected**: let the map row grow by the band's height. The map would keep its 500px, but the row would stop being
  `50vh` — against the code's own documented intent ("Deterministic viewport-derived height. The map row no longer
  competes with the panel via `1fr`", `style.css:402-408`) — and the first catalogue row would drop from 0.97 to
  ~1.08 screens, deepening the defect this unit's sibling is meant to fix.

## 4. Acceptance criteria

1. `#time-bar` is a child of `.map-panel`, directly after `.map-canvas`, and the four control ids are unchanged.
2. No `grid-template-areas` declaration contains a `time` row, and no rule assigns `grid-area: time`.
3. The map panel's `height` declaration is unchanged, so **the first catalogue row's y does not move** (±2px at
   1600x1000 against the 969px baseline).
4. The band is one row at 1600x1000 and the map area keeps at least ~440px of the 500px row.
5. The two skip links follow document order; Tab+Enter still lands on the panel and on the year, both with a visible
   focus ring.
6. The `.map-tool-help` collision that `odd/tasks/tipografia-visor.md` fixed at 1280x500 does **not** come back: the
   map canvas is now shorter, which is exactly what brought it out last time.
7. No horizontal scroll at 1600/1280/960/390; in-page detector reports 0; suite is 387 OK.

## 7. Outcome, measured

The writer's patch was verified against the base in a **second worktree** (`6acc637`) with the same data linked in, so
both servers served identical inputs. Bare numbers are the new state; the comparison column is what makes them evidence.

| | 1600x1000 | 1280x800 | 1280x500 | 960x700 | 390x844 |
|---|---|---|---|---|---|
| Year, screens from the map | **0.44** (was 4.04) | 0.43 | 0.52 | 0.42 | 0.50 |
| Map canvas | 442px (was 500) | 342 | **260 = base** | 292 | **425** (base 422) |
| Year band | 58px | 58 | 58 | 58 | 105 |
| First catalogue row | **969 = base** | 902 = base | 820 (+58) | 922 = base | 1386 |
| Chrome collision vs base | none = base | none = base | **32px = base's 32** | 1px | **14px, better than base's 17** |
| Document | 4114 (was 4220) | 3906 | 3614 | 3907 | 4662 |
| Horizontal scroll | 0 | 0 | 0 | 0 | 0 |

The document does shrink by the old bar's 106px, and the first catalogue row does **not** move at the primary sizes: the
map row keeps its viewport-derived height and the band lives inside it.

## 8. What the browser pass changed, and what it left

The first version of the patch failed acceptance criterion 6, and the pass found why: the band took its height from the
map, so the map's canvas shrank and the top-anchored toolbar met the bottom-anchored overlays. Comparing against the base
in the same conditions named the damage exactly (the overlap grew by precisely the canvas that was lost). Two fixes:

1. **The panel's floor now carries the band** (`clamp(318px, 50vh, 720px)`, and `clamp(530px, 50vh, 720px)` where the
   band stacks). The map's own 260px floor is what must survive, not the panel's; at 1280x500 the canvas is back to the
   base's 260px and the overlap back to the base's 32px.
2. **The band stacks only below 560px, not below 960px.** The writer reused the file's single-column boundary, but below
   it the map is still the panel's full width (945px at 960) and the row needs ~509px. Stacking at 960 cost the map 47px
   for nothing and was the sole cause of a new overlap there.

One more fix followed from the move itself: `.time-bar:focus` used an outset ring, and inside `.map-panel` (which clips)
three of its four sides were cut off. It is now inset (`outline-offset: -3px`) and verified visible by keyboard.

**Left open, deliberately**: the 32px toolbar/overlay overlap at 1280x500 is **pre-existing** — the base has it too, at the
same size — so it is not this unit's to fix; it belongs with the map's chrome budget. And the 106px the page gives back
does not pay for P2-4b: the first catalogue row still starts at 0.97 screens at 1600x1000.

## 9. Risks

- **The map area shrinks ~55px.** That is the cost the owner accepted, and it is why the one-row shape matters: it
  halves the price of the move. Verifying it visually at 1600/960/390 is part of the browser pass.
- **The dark band no longer closes the page.** The bar's `--bg-bar` treatment was designed as a footer; under the map
  it becomes a band between the map and the catalogue. Verify the visual rhythm at all four widths.
- **`<footer>` inside the map section** is now a footer *of the map panel*. Semantically acceptable; worth noting
  rather than changing the element (the classes and the layout are what carry the meaning).
- **The 1280x500 chrome collision** (criterion 6) is the likeliest regression.

## 10. Verification

Run, all of it: the suite (`387 OK, 49 skips`); the browser pass above at six widths (1600x1000, 1280x800, 1280x500,
960x700, 560x844, 390x844) against the base worktree as the control; the skip-link round trip by keyboard (**Tab** to
"Saltar al selector de año", **Enter** to `FOOTER#time-bar` with a visible 2px `rgb(37,99,235)` ring at `-3px` offset);
zero horizontal scroll at every width; and the detector, twice — in page (0 findings, `rules: {}`, the same shape the
previous unit recorded) and as a **differential** through the CLI, which reports the same two findings before and after,
both of them the already-proven false positives (`flat-type-hierarchy` with the browser's 16/16/16/16 defaults, and
`em-dash-overuse`). The diff adds **no** `font-size`, `line-height`, `letter-spacing`, `font-weight`, `color` or
`background` declaration, which is the detector's whole rule space, so a new finding was not possible.

The viewer has **no persisted automated test**, so this pass is the verification of record and the Python suite is only
the control.
