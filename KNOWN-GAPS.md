# Known gaps

**What this file is.** The record of what this repository does not do, written when the owner declared this state a
stable version. It separates three things that are easy to confuse: **decisions made against a change** (with the
measurement behind them), **known rough edges** that were left standing, and **open work** that nobody has started. Every
number here was measured; none is an estimate.

**The state it records.** `main` at the merge of PR #31, after two design critiques were worked end to end: the first
(23/40 on `2df212d`) and the second (29/40 on `bc97587a…`, snapshot in `.impeccable/critique/`). The unit records behind
each change are in `odd/tasks/`.

---

## 1. The structural gap a stable version does not fix

**The viewer has no persisted automated test.** The Python suite (387 tests) covers the data pipeline, the artifact
validators and the builders; **nothing covers the page**. Every UI change in this repository was verified by measuring it
in a browser at the time, and that evidence lives in the unit records — it is not reproducible by a CI run. So "stable"
here means *measured at a point in time*, not *guarded against regressions*. The clearest consequence: `viewer/*.js` is
about 7,000 lines with no test harness, and three defects found on this page were found by looking at it (the figure that
survived a cleared area, the 33px legend panel, the empty breakdown after clearing).

If someone wants to spend effort here, this is where it compounds: a DOM stub already exists in the unit records' method
and the panels' logic is deliberately pure functions in `viewer/metrics.js`.

## 2. Decisions made against a change

These were proposed, measured and declined. Reopening one means reopening the measurement, not the opinion.

| What was proposed | Why it was declined |
|---|---|
| **Translating the mandatory extent notice** into Spanish | The owner's decision: the published wording is kept **verbatim** because that sentence is what stands behind every figure against the ~18 % extent difference. Recorded, not a defect. |
| **Capping the catalogue rows' width** ("acotar el ancho de las filas") | Measured: a 100ch cap moves **57 of 255 titles from one line to two** and takes the first row from 49px to 66px — it would undo the fold the same critique asked for. The full-width row is what keeps titles whole and rows short. |
| **A mobile-first or mobile-optimised layout** | `PRODUCT.md` is desktop-first ("no mobile requirement exists today"). The single-column layout works and is verified at 390x844, but it is not optimised: 396px of chrome, and the chart scales to 0.58x. |
| **Keeping the catalogue's first row above the fold** | The catalogue's first row is now at ~1566px, below the fold. That is the hierarchy `PRODUCT.md` declares: the map, the composition panel and the drawn-area statistics are the product; the 255 studies are **"a secondary layer"**. The fold belongs to the composition. |
| **Populating the `study_gap` term of the priority index** | 255 studies across twelve editions cannot populate an H3 res 8–9 gap index: almost every hexagon would read zero and "zero studies" there means "nobody published in these twelve congresses", not "nobody studied it". The term stays disabled at weight **0.0**. |
| **Making the composition chart follow the drawn window** (deferred, not declined) | It needs the server to compute 40 years of clip statistics for the bbox (one year costs 10–246 ms today). The chart declares its own scope in its subtitle instead, so the figure is honest while the feature waits. See §4. |

## 3. Known rough edges, with their measurements

Left standing deliberately, each with what it costs a user.

| Where | What happens | Measured |
|---|---|---|
| Composition panel, while a clip is in flight | The "Calculando…" row pushes the breakdown down, so the chart and the list are briefly misaligned | **58px**, for the 10–246 ms of the request |
| Composition panel, provenance expanded | The panel grows | **693px → 1055px**, user-initiated and collapsible |
| Year slider | No debounce: every `input` event re-fires `/api/composition/year` (and `/api/clip-stats` with an area) | one request per event |
| Composition chart | Hover only changes the cursor: choosing among 40 years stays blind | — |
| Map, "Dibujar zona" | The mode persists after drawing and a marker click then selects nothing | a stray click reports a mode hint or "Rectángulo demasiado pequeño" |
| Catalogue rows | `formatHa` uses a thousands comma and a decimal point | unconfirmed against the Venezuelan convention |
| Composition chart at ≤390px | The chart scales with its container and its text with it | **0.58×** (the 620px cap only limits the upper bound) |
| Catalogue panel, provenance footer | It sits below the list's internal 70vh scroll box, so the block is not visible at the same time as the list | footer at y=2272, list at 1566 |
| Map chrome at short viewports | The toolbar's help text and the overlay notes overlap | **1px** at 960x700, **6px** at 1024x768, **32px** at 1280x500 (all pre-existing; the map's canvas needs ≥ ~293px) |
| Coordinate field | The decimal-comma rejection is textual: it catches a comma between two digits, not every malformed value | a value like `-71.51.8` still fails later with the existing message |
| Catalogue detail | A page-sized `aria-live` region: the whole detail is re-announced on every selection | — |
| Provenance, a source missing at import | The failure is reported ("ilegible", "no leído") and stays reported until the process restarts | by design: the parse-once discipline |
| Clearing a clip while a year change is in flight | The previous year's rows show for a moment until the new response lands | self-correcting |
| `viewer/panel.js` | `onChartHover` only sets `cursor: pointer`: dead code with a listener | — |
| `viewer/index.html` | The favicon declares `type="image/svg+xml"` while pointing at `/favicon.ico` | — |

## 4. Open work, ranked

1. **Accessibility, the two recorded-not-done items.** There is no `<main>` landmark, and the 255 catalogue rows have no
   roving focus: the composition panel's controls are reachable in 21 tab stops, but the list itself is 255 consecutive
   stops. Both were recorded when the DOM order was fixed and neither was started.
2. **The map has no scale bar and no compass.** Without a scale, the magnitude of a drawn rectangle cannot be read on the
   map at all — only afterwards, in the panel. `NavigationControl` is added with `showCompass: false`. *(Second critique,
   P2.)*
3. **The coordinate field is one free-text box for four numbers.** Four number inputs — or at least `inputmode`/`pattern`
   — would remove the whole class of parsing errors the field currently documents instead of preventing. *(P2.)*
4. **`role="application"` on the map** puts screen readers in application mode for the whole map, and the markers, the
   collision ring and the clip rectangle have no text equivalent. Worth an explicit decision either way. *(P2.)*
5. **The catalogue detail should not be one page-sized `aria-live`.** *(P2.)*
6. **The D7 extent notice appears twice on one screen** with identical wording (the map's overlay and the panel's footer).
   `PRODUCT.md` asks for both; at 1600px they are simultaneously visible. *(P2.)*
7. **The composition chart's series is the whole mapped extent even when an area is drawn.** It says so in its own
   subtitle, so it does not lie, but recomputing those 40 years for the window is the feature the panel's own answers
   would complete.
8. **The overlapping chrome measurements above**: the map's canvas needs about 293px before its top-anchored toolbar meets
   its bottom-anchored overlays. Every size below that has a documented overlap.

## 5. Decisions that belong to the owner

- **The code has no licence.** `CC BY 4.0` governs the MapBiomas data (`NOTICE.md`); the software in this repository
  claims no licence, and choosing one is a separate decision. `README.md` says so where a reader would look.
- **`study_gap` stays at 0.0** unless the corpus ever justifies it (§2).
- **No tag marks this state.** The repository has no release tags and no versioning policy; "stable" here is the state of
  `main`, and this file is the record of what that state still owes.

## 6. Where the rest lives

- `odd/tasks/*.md` — one record per unit: the measured defect, the plan, the acceptance criteria, the outcome and the
  verification. The chronological evidence behind every entry above.
- `.impeccable/critique/` — both critique snapshots with their target fingerprints.
- `PRODUCT.md` — what the product is for, the hierarchy the layout follows, and the positioning that the panel's
  provenance now makes visible.
- `NOTICE.md` — the data licence, the required citation and the list of changes.
- `README.md` — the reader-facing limitations, including the ones that affect how a figure should be read.
