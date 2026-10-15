# Fix: the composition panel's two denominators (P2-5)

**Status**: implemented and verified — §5 · **Branch**: `fix/dos-denominadores` (from `origin/main`) · **Commit**: `<pending>` ·
**Opened by**: `.impeccable/critique/2026-10-15T05-25-10Z__viewer-index-html.md`, issue **P2-5** (persona flag: Valentina).

## 1. The defect, measured

The panel shows two different denominators at the same time and only one of them declares which it is:

| Element | No area drawn | Area drawn |
|---|---|---|
| The chart's subtitle | `% de la extensión válida · cursor en el año seleccionado` | **unchanged** |
| The chart's `<desc>` (screen readers) | the six groups with the **map's** shares for the year | **unchanged** |
| The legend (the chart's own key) | the **map's** shares and hectares | **unchanged** — still the map's |
| The breakdown's title | `Clases (nivel 2) en {year} — ordenadas por área` | **`Clases en la zona seleccionada ({year})`** — declares its scope |
| The breakdown's rows | the map's level-2 for the year | the **window's** level-2 |

So the panel answers two different questions — *the whole map over 40 years* and *the drawn area this year* — and the top one
never says which it is. A screenshot of the chart next to the clipped bars can be labelled as "the area" and be wrong. It is
a **product-truth** defect, not a styling one: the panel is the authoritative surface and it omits the one fact that
separates its two halves.

## 2. What to build

The state, declared where each number is read. No new data, no server change:

1. **The chart's subtitle becomes stateful.** With no area it keeps today's text exactly (the default state must not get
   noisier). With an area it names its scope: the map's valid extent, and that the drawn area does not change this chart.
2. **The chart's `<desc>` carries the same scope**, so a screen reader gets the denominator before the numbers.
3. **Nothing else changes.** The legend is the chart's own key (`aria-label="Leyenda del gráfico apilado"`) and inherits the
   chart's declared scope, so it does not need a second caption saying the same thing three elements apart. The breakdown
   already declares its scope in its title.

**The substantive claim to verify, not just the copy**: the chart, its legend and its description are **not** affected by the
clip — the chart keeps the map's series and shares. The unit's job is to say so, and the measurement has to prove that the
numbers genuinely do not move.

## 3. Acceptance criteria (measured in the browser)

1. **Before drawing**: the subtitle and the desc are byte-identical to today's.
2. **After drawing** (with the coordinate field): the subtitle names the map's valid extent and states that the drawn area
   does not change the chart; the desc's first sentence says the same.
3. **The numbers do not move**: the legend's first item (share and hectares for the selected year) and the chart's series
   read exactly the same value before and after drawing — the claim the copy makes is true.
4. **The breakdown still declares the area**: its title keeps naming the selected zone, and its rows are the window's.
5. **The state survives a year change**: with an area active, moving the year keeps the scope in the subtitle and the desc
   and updates the year inside the desc.
6. **Clearing the area restores the default copy exactly.**
7. **No regression**: the subtitle fits inside the chart's drawing area (measured: the text's bounding box against the
   viewBox, since the longer sentence is the risk), the in-page detector stays at **0**, the suite stays at **387**.

## 5. Outcome (measured in the browser)

| | No area | Area drawn | After clearing |
|---|---|---|---|
| The chart's subtitle | `% de la extensión válida · cursor en el año seleccionado` | `% de la extensión válida del mapa · el área trazada no lo cambia` | **byte-identical to the original** |
| The chart's `<desc>` | `Año 2024. Formaciones boscosas 60.31 % …` | `Extensión válida del mapa; el área trazada no lo cambia. Año 2024. …` | restored |
| **The chart's legend** (first value) | `60.31 % · 65,511,997.353565 ha` | **`60.31 % · 65,511,997.353565 ha`** — identical | identical |
| The breakdown's title | `Clases (nivel 2) en 2024 — ordenadas por área` | `Clases en la zona seleccionada (2024) — ordenadas por área` | restored |
| The breakdown's first row | `Bosque · 1,157,645,737.503857 ha · 53.07 % de la extensión válida` | `Bosque · 129,929.149105 ha · 43.31 % de la zona seleccionada` | — |
| With the year moved while the area is active | — | the subtitle keeps its scope and the desc updates the year | — |
| The subtitle inside the chart | 303px wide, −259px of slack | **348px wide, −214px** — no overflow, measured against the viewBox | — |
| In-page detector | **0** | | |

The row that matters is the third one: the copy now says the chart does not move with the area, and the measurement proves it does
not — the legend's share and hectares are identical before and after. Without that check the fix would have been a sentence nobody
verified.

### Why the legend got no caption of its own

The legend is the chart's own key — its `aria-label` is *"Leyenda del gráfico apilado"* — so it reads under the chart's declared
scope, and the breakdown carries its own title. Adding a third sentence saying "whole map" between them would repeat the
caveat three elements apart, which is noise, not clarity. The caption belongs to the figure, and the figure is the chart.

## 6. Risks

- **The subtitle lives inside a fixed 600-unit SVG**. A longer sentence can overflow the drawing area or collide with the
  title above it; the copy is deliberately short and the box is measured, not assumed.
- **State drift**: the flag lives in `viewer/panel.js` and is set from the two functions the clip already calls
  (`renderClip` / `clearClip`), so there is one place that knows the scope rather than two that could disagree.
