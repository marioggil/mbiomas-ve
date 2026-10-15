# Fix: the type scale is not a scale (P1-1 of the critique)

**Status**: implemented and verified — see §6 for the measured outcome · **Branch**: `fix/tipografia-visor` (from `origin/main`) ·
**Source of truth**: `.impeccable/critique/2026-10-15T05-25-10Z__viewer-index-html.md` (the critique that
opened this) and `PRODUCT.md` (users, constraints, principles).
**Decided with the owner**: this slice is the priority; the extent-notice issue was closed as a *decision*
(verbatim English stays); the chart fix takes the minimal route (a width cap plus declared sizes) rather
than restructuring the panel.

## 1. Measured baseline

The in-page detector, over the assessed bytes of `viewer/index.html` (`sha256:b6989f3b…`):

| Rule | N | What it is |
|---|---:|---|
| `undersized-ui-text` | **110** | 10px functional text: the catalog's class badges — "Fuera de la extensión", "Sin coordenada", "Ubicación de grano grueso" |
| `tiny-text` | **30** | 11px body text |
| `body-text-viewport-edge` | **3** | paragraphs 334 and 172 characters long bleeding to the viewport edge (left 14px) |
| `flat-type-hierarchy` | **1** | `h3 13px, body 14px, h2 15px, h1 18px (largest adjacent step 1.20:1; target 1.25:1)` |

Plus, measured in the browser: the composition chart's SVG scales its own text with the container
(`viewBox="0 0 600 320"`, rendered 1543px at a 1600 viewport → **2.57×**; 2.06× at 1280), so its 10px ticks
render at 20.6–28px and its 13px title at 26.8–37px — **larger than the application's own title** — while the
chart occupies ~660px of height.

The CLI (`detect --json --scope type`) reports **1** finding on this repository: it cannot resolve
`/static/style.css` (it looks for `viewer/static/style.css`; the service maps `/static/` → `viewer/`), so
**the in-page run is the ruler** for every number here.

## 2. The type system to build

Operate surface, dense, desktop-first: stability and scanability before expression, **one family** (the
existing `--font-stack`; no new face), and the fewest roles that make the hierarchy unmistakable. Size alone
does not carry the hierarchy — weight, space and tone do their part.

| Role | Today | Target | Why |
|---|---:|---:|---|
| Page title (h1) | 18 | **24** | Gives the one clear jump: 24 ÷ 17 = **1.41**, clearing the 1.25 target on the largest adjacent step, and stops the page title from being smaller than the chart's rendered title |
| Section title (h2) | 15 | **17** | One step down from the page title, still unmistakably a section |
| Subsection (h3) | 13 | **15** | 15 ≥ body 14: removes the inversion the critique flagged |
| Body | 14 | **14 (kept)** | A dense Operate surface with a desktop-first audience; the density is declared, not accidental |
| Label, metadata, help | 11 | **12** | The floor for the 30 `tiny-text` findings |
| Functional badge | 10 | **12** | The floor for the 110 `undersized-ui-text` findings — these are the labels of the classes the map cannot place, which the interface promised to declare |
| Chart text (rendered) | 20.6–37 | **11–13** | Via a wrapper width cap (scale ≈1.0–1.2) plus declared ticks 11, subtitle 11, title 13 |

Adjacent steps with the target set: 14→15 = 1.07, 15→17 = 1.13, **17→24 = 1.41** ✓.

Also from the craft floor, and inside this slice because they are typography:

- **Measure**: prose blocks capped to ~72ch, which also closes the three viewport-edge findings.
- **Tabular numerals** on the data figures (`font-variant-numeric: tabular-nums`), so the numbers in the panel
  and the chart legend align in columns instead of shifting per digit.
- **Space above a heading, more than below it** — the floor's spacing rule, checked on the computed values.

Out of the floor and out of this slice: selection, caret and scrollbar theming, and every layout
restructuring. The two-column composition panel belongs to P2-4.

## 3. Acceptance criteria (measured, before and after)

1. In-page detector over `viewer/index.html`: **144 → 0** findings, i.e. `undersized-ui-text` 110 → 0,
   `tiny-text` 30 → 0, `body-text-viewport-edge` 3 → 0, `flat-type-hierarchy` 1 → 0. Any remainder is
   explained individually.
2. Browser-measured chart text: ticks **11–13px**, title **≤16px**, chart height **≤400px** (from ~660px).
3. No layout regression: the catalog list keeps its `min(70vh,720px)` cap, no horizontal scrollbar appears at
   1600/1280/960, and the MapLibre attribution still does not overlap the study legend or the map notes (the
   no-overlap guarantee the repository documents).
4. The Python suite stays green (`/tmp/gm-rb/bin/python -m unittest discover -s tests`, 387 tests): this slice
   touches no Python, so it is a control, not a target.
5. Computed spacing: more space above each heading than below it, read from `getComputedStyle`.

## 4. Risks

- **`panel.js` builds the chart geometry on a fixed 600×320 space.** The chosen fix lives in CSS (a width cap:
  `max-width` on the chart wrapper) plus the *declared* font sizes, so no coordinate is recalculated. If the cap
  breaks the layout, fall back to an explicit SVG height and report it.
- **Raising the badges from 10px to 12px grows the catalog rows** (47px today). Verify the list cap and that no
  row content overflows.
- **The chart gets narrower** (~640px inside a ~1540px panel). That is the accepted trade: the alternative
  (full width at 1:1) needs a panel restructure, which is a different slice.

## 5. Open items

| # | Item | Blocks |
|---|---|---|
| T1-C1 | The chart's empty right-hand space invites a two-column panel (chart beside the level-2 breakdown) | Nothing; it is P2-4 |
| T1-C2 | Browser-surface theming (selection, caret, scrollbars) from the palette | Nothing; a later polish pass |

## 6. Outcome (measured in the browser, not derived from the CSS)

The worker's numbers were arithmetic because its tool surface has no browser; these were measured in the page.

| Criterion | Before | After |
|---|---|---|
| In-page detector, all rules | **144** | **0** (no findings line) |
| `undersized-ui-text` (10px functional) | 110 | **0** |
| `tiny-text` (11px body) | 30 | **0** |
| `body-text-viewport-edge` | 3 | **0** |
| `flat-type-hierarchy` | 1 (1.20:1) | **0** (largest adjacent step 24÷17 = **1.41**) |
| Rendered roles | h1 18 · h2 15 · h3 13 · badge 10 · help 11 | h1 **24** · h2 **17** · h3 **15** · badge **12** · help **12** · body 14 (kept) |
| Chart scale (viewBox 600) | 2.57× @1600 · 2.06× @1280 | **1.01×** (606px of SVG) |
| Chart text | ticks 20.6–28px · title 26.8–37px | ticks declared 12px (14px box) · title 13px (15px box) |
| Chart wrapper height | ~660px @1280 | **341px** |
| Page height @1600 | 4562px | **4229px** |
| Catalog rows | 47px | 49px (the badge grew 2px; the `min(70vh,720px)` cap is intact) |
| Horizontal scroll @1600/1280/960 | none | none |
| Overlaps @1600/1280/960 (attribution vs legend/notes, toolbar vs legend) | none | none |
| Toolbar vs legend @1280×500 (short viewport) | **90 × 31 px** overlap (pre-existing) | **26 × 15 px** — smaller than the baseline it inherited, because the help text now wraps instead of running 1085px wide |
| Suite | 387 OK | **387 OK** (control: no Python touched) |

Two adjustments were made after the first verification pass, both inside this unit: the reading measure went from
72ch to **64ch** (at 72ch the rendered lines measured ~87 characters, over the detector's 80 ceiling), and the SVG's
declared sizes went from 11 to **12px** with the cap tightened from 700px to **620px** (so the rendered size lands at
12.1px instead of 13.7px). `.map-tool-help` joined the measure cap for the reason in the table above.

### Follow-up found while verifying (out of this slice)

The catalog's three metrics charts reuse `.panel-chart-*` classes but their wrapper is `.catalog-metrics-chart`, so the
composition chart's cap does not cover them: **measured at scale 0.472×** (283px of SVG for a 600-unit viewBox), with
declared 13px text rendering a **7px box ≈ 5.5–6px nominal**. They are legible only by squinting, and it is the same
defect this slice fixed elsewhere. Fixing it means restructuring the metrics figures' grid (they are 283px cards in a
three-column row), which is layout work, not typography.
