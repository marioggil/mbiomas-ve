# Fix: the composition chart is encoded in colour only (P1-3, third slice)

**Status**: implemented and verified — §4 · **Branch**: `fix/grafico-sin-color` (from `origin/main`) · **Commit**: `212fd55` ·
**Opened by**: `.impeccable/critique/2026-10-15T05-25-10Z__viewer-index-html.md`, issue **P1-3** (persona flag for Sam).

## 1. The defect, measured

The stacked area chart identifies its six bands **by hue alone**, and its accessible name carries no data.

**Measured on the served page**: the six level-1 group colours, their relative luminance, and the luminance ratio
between the closest pairs. Luminance is what remains when hue is removed — what a reader with a colour-vision
deficiency sees, and what a black-and-white print shows.

| Pair | Luminance ratio |
|---|---:|
| Áreas agrícolas ↔ No observado | **1.14** |
| Formaciones boscosas ↔ Áreas sin vegetación | **1.21** |
| Áreas sin vegetación ↔ Cuerpos de agua | 1.55 |
| Herbazales y arbustales ↔ Áreas agrícolas | 1.63 |

Two pairs sit at 1.14 and 1.21: without hue there is **no difference between those bands at all**. Telling them apart
requires the reader to match a swatch in the legend to a band in the chart by colour, which is exactly the sense that
is missing.

**And the chart says nothing to a screen reader**: the SVG is `role="img"` with
`aria-label="Serie temporal apilada de cobertura por grupo nivel 1"` and **no `<title>` and no `<desc>`**. The only
visible text inside it is the axes. The legend below is a readable list — that is its merit — but the chart itself
names no series and states no value.

## 2. What to build

1. **Direct labels inside the bands**, at the right edge (the last year), for every band thick enough to hold one.
   The label carries the group's name, which is the identity the colour was standing in for. Bands too thin for a
   label are skipped and the skip is reported, not hidden — the two candidates are the smallest groups
   (1.12 % and 0.00 % of the area).
2. **A `<title>` and a `<desc>` in the SVG.** The title names the chart; the desc names the six groups with their
   share and hectares **for the selected year**, and it is updated when the year changes, in the same place the legend
   values are updated. The chart then states its own numbers instead of delegating them entirely to the list below.
3. **Per-band label colour, chosen by contrast.** A single label colour cannot work across six bands: measured
   arithmetic on the palette says the widest band (`#1f8d49`) leaves white at **4.23:1** and `--fg-strong` at
   **4.40:1**, so **neither reaches the 4.5:1 floor** and the literal rule would leave the *largest* band unlabelled —
   backwards from the purpose. Pure black would clear it at 4.97:1, and it is the anti-pattern the craft floor
   refuses. **Resolution: every label is a plate** — a rounded `--fg-strong` box with white text — so the contrast is
   constant at **18.61:1** on all six bands and no colour is negotiated per band. The plate is annotation, not data,
   which is why it can be dark over any band. The labels' minimum band thickness rose from 14px to **20px** so the
   plate fits inside the band it belongs to.

**Not in this slice**: making the legend items interactive so hovering or focusing one highlights its band. That is the
stronger fix and it also closes part of the chart's keyboard gap, but it adds focusable controls and interaction state,
so it is its own unit.

## 3. Acceptance criteria (measured in the browser)

1. Every band whose thickness at the right edge is **≥ 14px** carries a visible label; the count is reported and the
   skipped bands are named with their thickness.
2. No label is clipped by the plot area, and none overlaps another label or an axis label.
3. The contrast of each label against the band it sits on measures **≥ 4.5:1**, read from `getComputedStyle`.
4. The SVG has a `<title>` and a `<desc>`; the desc names the six groups and its values **change when the year
   changes** (verified by reading it before and after moving the slider).
5. No regression: the legend still shows name, share and hectares for the selected year; the chart keeps its scale
   (1.01) and its geometry; the in-page detector stays at zero; no horizontal scroll; the suite stays at 387.

## 4. Outcome (measured in the browser)

| Criterion | Result |
|---|---|
| Bands labelled / skipped | **3 labelled** (Formaciones boscosas 139.9 px, Áreas agrícolas 44.5 px, Herbazales y arbustales 35.3 px); 3 skipped by thickness: Cuerpos de agua 9.6 px, Áreas sin vegetación 2.6 px, No observado 0.0 px |
| Label inside the plot, no clipping | `insidePlot: true` for all three |
| Labels overlapping each other | **none** |
| Contrast of the label text | **18.61:1 constant** — white on the plate's `--fg-strong`, independent of the band beneath |
| `<title>` / `<desc>` | `Cobertura por grupo (nivel 1) · 1985–2024`; the desc names all six groups with share and hectares |
| The desc follows the year | 2024 → `Año 2024. Formaciones boscosas 60.31 % …`; 1985 → `Año 1985. Formaciones boscosas 63.08 % …`, and the legend's first value matches in both |
| Chart geometry | untouched: `viewBox 0 0 600 320`, hit rect `x=44 y=56 w=544 h=232`, 6 area paths |
| Horizontal scroll / detector / suite | none / **0** / 387 OK |

The contradiction this unit started with is the interesting part of it, and it was mine: the brief cited a 4.96:1
ratio for "near-black" on the widest band, but that figure belongs to *pure* black — the palette's `--fg-strong`
measures 4.40:1 there. The implementation stopped and reported it instead of picking a side, which is why the answer
is a plate for every label instead of an exception for one band.

## 5. Risks

- **The labels live inside the plot**, so their placement depends on the last year's stacked values and on the label's
  width. A band can be thick but narrow in the last year — the label must be measured against the plot width, not
  assumed to fit.
- **The darkest bands are the thin ones**, so the contrast rule and the thickness rule interact: a band can be
  labelled and still land under 4.5:1, which is why the colour is chosen per band and the floor is enforced.
