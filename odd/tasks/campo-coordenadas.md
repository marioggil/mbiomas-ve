# Feature: draw an area by typing its coordinates (P1-3, second slice)

**Status**: implemented and verified — §6 · **Branch**: `feat/campo-coordenadas` (stacked on `fix/metricas-sin-desborde`, PR #16) ·
**Opened by**: `.impeccable/critique/2026-10-15T05-25-10Z__viewer-index-html.md`, issue **P1-3**, and **decided by the
owner** on 2026-10-15: a coordinate field, not arrow-key drawing.

## 1. Why this, and what it is not

The drawn-area flow — the rectangle, the composition statistics, the catalog filter and the congress metrics — is
**mouse-only** today: `map.on("mousedown"/"mousemove"/"mouseup")` with no keyboard equivalent anywhere. A reader who
cannot use a pointer cannot reach the feature at all.

Two keyboard routes were on the table. The owner chose the **coordinate field** over arrow-key drawing, and the
trade-off is worth recording: a field is verifiable, needs no new interaction model, and is **repeatable** — the same
area can be typed again next month, which arrow keys never give. Arrow keys would feel more like drawing and would
cost a cursor, a preview, a confirm step and a much larger test surface.

**Not in this slice**: the composition chart's missing keyboard access (`.panel-chart-hit` is still an unlabelled
`<rect>` with a click handler), the year slider sitting four screens from the map, and the raw `HTTP 413` message a
too-large area produces.

## 2. The contract it must reuse

| Piece | What it is |
|---|---|
| `bbox` | `[west, south, east, north]`, four finite numbers — the array `bboxFromCorners()` already returns |
| `commitClip(bbox)` (`viewer/app.js:1400`) | **The only commit path.** It stores the bbox, enables "Limpiar zona", writes the status line, notifies the catalog (`MapBiomasCatalog.setArea`) and fires the composition request. The field must call **this**, never `requestClip` |
| The status line's format | `bbox.map(n => n.toFixed(2)).join(", ")` — two decimals, in that order. The field uses the **same** order and format, so the app does not grow a second convention |
| `bboxFromCorners()` | Normalises any two corners into west/south/east/north and returns `null` when degenerate. The field accepts the four numbers in any order and normalises the same way |

## 3. What to build

1. **A labelled field in the map toolbar** (`.map-controls`, next to "Dibujar zona" / "Limpiar zona"), in a `<form>`
   so Enter submits and the submit control comes from the markup rather than from a keydown hack. A visible label
   naming the order (`oeste, sur, este, norte`) and a placeholder with a real example.
2. **Two-way**: typing four numbers and pressing Enter or the button commits exactly what a drag commits. And when a
   drag *does* commit, the field shows that bbox with the same formatting — one line inside `commitClip()`, which is
   what makes the two paths agree by construction instead of by discipline.
3. **Validation with a message, not a silent failure**: fewer than four numbers, a non-numeric value, or a value
   outside longitude ±180 / latitude ±90 is rejected in Spanish in the toolbar's existing live region, nothing is
   committed and the focus stays in the field. A rectangle typed in any corner order is **accepted** and normalised; a
   degenerate one (zero width or height) is rejected.
4. **"Limpiar zona" empties the field** too, so the field never shows an area that is no longer applied.
5. **The help text** now names both paths: a rectangle on the map, or the coordinates.

## 4. Acceptance criteria (measured in the browser)

1. **Keyboard-only end to end**: with no mouse input at all — tab to the field, type
   `-71.51, 8.26, -71.02, 8.76`, press Enter — the state is identical to the drag path: the rectangle drawn on the map,
   the composition panel computed for that window, the catalog list filtered to the studies inside, the metrics block
   open with its numbers, the chip present, and the field showing `-71.51, 8.26, -71.02, 8.76`.
2. **The same bbox as a drag**: the numbers the field produces for that input equal the numbers a drag over the same
   corners produces (`[west, south, east, north]`, compared value by value).
3. **Validation**: `abc`, `1, 2, 3`, `200, 0, 1, 1` and `1, 1, 1, 1` each produce a Spanish message, commit nothing
   (the previous area, if any, stays applied) and leave the focus in the field.
4. **Round-trip**: after a mouse drag, the field shows the committed bbox with two decimals and the same order as the
   status line.
5. **No regression**: the toolbar still does not overlap the study legend at 1600, 1280 and 960, and the collision
   measured at 1280×500 earlier is not worse; no horizontal scroll at those widths; the in-page detector stays at
   **0**; the Python suite stays at **387**.

## 6. Outcome (measured in the browser)

| Criterion | Result |
|---|---|
| The field's position in the tab order | **15 of 288** (the map's canvas is 8; the field is the first thing after the two toolbar buttons) |
| Keyboard-only end to end | typing `-71.51, 8.26, -71.02, 8.76` and pressing Enter leaves the state a drag leaves: chip `Área trazada: 16 estudios`, list at **16** rows, the metrics block open at `16 charlas en el área`, "Limpiar zona" enabled, focus still in the field |
| Enter submits natively | the form's submit does it; there is no `keydown` handler anywhere in the field's path |
| Validation | `abc` and `1, 2, 3` → *"Escriba cuatro números separados por comas, en el orden oeste, sur, este, norte."*; `200, 0, 1, 1` → *"Longitud fuera de rango (200): debe estar entre -180 y 180."*; `1, 1, 1, 1` → *"El área no tiene extensión: el ancho o el alto es cero."*. All four keep the previously committed area (16 rows, `16 charlas`), commit nothing, and return the focus to the field |
| Round-trip | after a drag the field reads `-63.93, 3.69, -61.76, 5.30` — the status line's own string; "Limpiar zona" empties it |
| Toolbar against the study legend | 1600 / 1280 / 960: the toolbar's **box** overlaps the legend's box while **none of its children do** (the legend sits in the container's empty right-hand space). At 1280×500 — a 260px map — the form's box pokes **9×31px** into the legend: accepted and recorded |
| Horizontal scroll @1600/1280/960/1280×500 | none |
| In-page detector, on load and in the rejected-area state | **0** in both |
| Suite | **387 OK** (control: no Python touched) |

### Three fixes beyond the delegated implementation

The field worked as specified; three things it exposed did not.

1. **The error message was a raw HTTP line.** Typing a decimal comma produced
   `HTTP 400 al obtener /api/clip-stats?year=2024&bbox=…` in the toolbar and in the panel. The clip path now maps the status to a sentence with the way
   out — 413 → *"El área es demasiado grande para calcularla: trace o escriba un rectángulo más chico."*, 400 → *"El área no se pudo calcular: revise
   que el rectángulo esté dentro de la extensión del mapa y que los decimales usen punto, no coma."*, 404, 503 and a default — and keeps the endpoint's
   own line in the console. `viewer/api.js` now attaches the status to the error object, which is why **this unit touched a fourth file**: the raw
   string is built there. That also closes a P2 from the critique (*clarify*), for the drag path as well as the field.
2. **The toolbar grew.** With the form and its label each on their own row the toolbar gained ~38px at every width, and the honest collision check
   at 1600/1280/960 still came out clean only because the legend sits where the container is empty — the crude box-against-box metric said 292×1 at
   960 and would have sent me chasing a pixel. The form and its label now share a row, the toolbar is 90px at 1600 (was 94) and 128px at 1280/960
   (was 132), and the child-level check is clean at those three widths.
3. **My longer error sentence bled to the panel's edge**, and the detector said so: `body-text-viewport-edge` fired on the rejected-area state.
   `.panel-breakdown-empty` joined the 64ch measure rule — prose respects the measure whether it is a help text or an error — and the state now
   measures 427px with **0** findings.

### Known limitation, with its two mitigations

**A decimal comma turns four values into a different four values.** `-71,51, 8,26` splits on the commas into `-71, 51, 8, 26`, which is a valid
input under the documented format, so it commits the box `-71.00, 26.00, 8.00, 51.00` instead of warning. In Venezuela the decimal separator is the
comma, so this is a real user error, and it cannot be disambiguated: the same four tokens are a legitimate `[west, south, east, north]`.

Two mitigations, both measured: the field **rewrites itself with the normalised values** on commit, so the misreading is visible immediately (the
round-trip is the safety net, not a nicety), and the server rejects the resulting box with the 400 sentence that names the decimal comma. The label
says *"Coordenadas con punto decimal"* and the placeholder shows dots. A proper fix would accept both conventions, which needs a stricter input
grammar than "four numbers separated by commas".

- **The toolbar is already the tightest corner of the map**: it holds two buttons, the help text and the status line,
  and at a 500px-tall viewport it already overlaps the study legend by 26×15px (measured, pre-existing). The field
  must not make that worse — wrapping the toolbar onto a second line is acceptable, growing its footprint sideways is
  not.
- **The field is a second way to produce a bbox**, and second ways drift. The mitigation is the contract in §2: one
  commit function, one format, one validation message channel.
