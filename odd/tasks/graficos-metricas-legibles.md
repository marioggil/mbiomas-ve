# Fix: the catalog metrics charts were illegible (P1-1's second instance)

**Status**: implemented and verified — see §3 · **Branch**: `fix/graficos-metricas-legibles` · **Commit**: `31731cf`
**Opened by**: `.impeccable/critique/2026-10-15T05-25-10Z__viewer-index-html.md`, found while verifying the type scale.

## 1. The defect, measured

The composition chart scaled its text **up** (2.57×) and the catalog's three metrics charts scale it **down**:
`.catalog-metrics-body` laid out five 297px columns, so the SVG — drawn in a fixed 600-unit space — rendered at
**283px**, a scale of **0.472**, and its 13px labels rendered at **6.1px**. Visible in a screenshot, not only in
arithmetic: the species names, the counts and the chart's own subtitle were micro-text.

It is the same defect the type-scale unit fixed on the other chart, in the opposite direction, and it affects the
primary audience reading the feature the metrics block exists for.

## 2. What changed, and the one thing that was decided by measurement

`viewer/style.css` only:

1. **`.catalog-metrics-body`**: `minmax(280px, 1fr)` → `minmax(600px, 1fr)` — two figures per row on a desktop
   panel, one below 1224px.
2. **`.catalog-metrics-chart .catalog-metrics-svg`**: `width: 600px; max-width: 100%` — the chart renders at its own
   design width instead of filling the cell, so the viewBox scale stays 1.0 and every label keeps the size it was
   drawn for. The two-class selector beats `.panel-chart-svg`'s `width: 100%` regardless of rule order.
3. **No card chrome on the figures or the charts.** This one was not chosen, it was measured. Four framings were
   injected into the live page and the detector answered:

| Framing | Findings |
|---|---:|
| Figure as the card, chart plain inside it | **2** `nested-cards` |
| Figure plain, chart framed and hugging its own width | **3** |
| Figure plain, chart framed filling the cell | **3** |
| **Figure plain, chart plain (chosen)** | **0** |

The `<figure>` inside a grid cell already reads as a card pair to the rule, so any chrome below it is a card inside
a card. The block is now separated by its own heading and by the grid gap; each metric's bold title and its
denominator caption do the grouping. It is also the lighter composition, which is what the craft floor asks for.

## 3. Outcome (measured in the browser)

| Criterion | Before | After |
|---|---:|---:|
| Chart scale (SVG width ÷ 600) | **0.472** @1600 · @1280 · @960 | **1.0** in all three |
| Rendered label size | **6.1px** | **13px** |
| Columns in the metrics grid | 5 × 297px | **2 × 762px** @1600 and @1280, **1 × ~917px** @960 |
| SVG overflows its cell | no | no (−81px @1600, −1px @1280, −147px @960: the slack is symmetrical) |
| Horizontal scroll @1600 / 1280 / 960 | none | none |
| In-page detector, with the block expanded | 0 | **0** |
| Expanded grid height | 322px (one row of five columns) | 770px @1600 (two rows) |
| Collapsed block height | unchanged | unchanged — the block is collapsed by default, so page height at rest does not move |

The height cost is real and only appears when the block is expanded: two rows of charts instead of one. The block is
collapsed by default, so the page at rest is unaffected, and the type-scale unit already returned 333px of page
height with the composition chart's cap.

## 4. Open item found by this fix

**The visible title is stated twice, and before this fix nobody could see it.** The HTML caption reads "Especies más
mencionadas: top 8 de 534 nombres distintos" and the chart's own visible title repeats "Especies más mencionadas" plus
"Nombres distintos: 534 · menciones: 37". At 6px the duplication was invisible; at 13px it reads as a mistake.

Two defensible answers, and it is a composition decision, not a defect:

- **Keep the chart's internal title and drop the HTML caption's repetition**, leaving the caption for the denominator
  only. The chart stays self-describing when exported or copied as an image.
- **Keep the HTML caption and stop drawing the visible title inside the SVG**, keeping the `<title>` and `<desc>` for
  the accessible tree. Less duplication on screen, worse when the SVG travels alone.

Either is a small change in `viewer/catalog.js` (or the SVG builders in `viewer/metrics.js`); the second touches the
chart's geometry, the first does not.
