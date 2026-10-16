# Feature: the Imataca case study, as a page on the same site

**Status**: in progress · **Branch**: `feat/informe-imataca` (from `origin/main`) · **Commit**: `<pending>` ·
**Owner's frame**: *"el idioma será español, generarías una página web disponible en el mismo sitio y un PDF, la página web
claramente tendrá un mapa donde mostrarás el área que se definió para el estudio y las demás cosas de este estudio"*, with
the viewer's public URL given as **https://biomas-cve.marioggil.xyz/**.

## 1. What exists already (do not rebuild it)

The study's research is done and its evidence is versioned:

| File | What it holds |
|---|---|
| `odd/informes/imataca/informe.md` | **The report's prose in Spanish** — the authoring text, and the PDF's content. The page must carry this text |
| `odd/informes/imataca/tabla-coberturas.json` | The box's level-2 composition, 10 years (8 edition years + 1985 + 2024), area and share per class |
| `odd/informes/imataca/tabla-congresos.json` | The 30 talks per edition, the species raw, the 10 institutions with their pair counts and `ok`/`dudoso` state |
| `odd/informes/imataca/especies-curadas.json` | The curation: 42 raw entries → 31 species-level (30 distinct), 1 genus, 3 families, 7 that are not names |
| `odd/informes/imataca/evidencia/clip-<year>.json` | The 10 raw API responses (each with `level1`, `level2`, the window/valid/nodata areas) |
| `odd/informes/imataca/evidencia/procedencia.json` | The consultation date, the composition artefact's identity, and each year's COG `output_sha256` |

**The box**: `w=-61.746314, s=6.60103, e=-60.246314, n=8.00103` — 165 × 156 km, 2,576,410 ha, 100 % observed.

## 2. What to build

### 2.1 The data the page reads

- **`tools/build_informe_imataca.py`** (new tool, in the repository's builder idiom): reads the evidence above and writes
  **one shipped artifact**, `data/derived/venezuela/informes/imataca.json`, holding the coverage table, the congress table,
  the curated species and the provenance, with the box and the consultation date. This mirrors how every other derived
  artifact in this repository is produced, and it is what makes the page's numbers regenerable instead of retyped.
- **`tools/serve_viewer.py`**: serve it at **`GET /api/informe/imataca`** (read once at import, like the other artifacts,
  and fail loudly if it is missing or malformed — it is committed, not user input).

**The image copies `tools/`, `viewer/`, `data/legend/` and `data/derived/`** and not `odd/`: the shipped JSON must live
under `data/derived/` and nothing the page needs at runtime may come from `odd/`.

### 2.2 The page

- **`tools/serve_viewer.py`**: **`GET /informe/imataca`** serving the page, following the pattern the root route already
  uses for `viewer/index.html`.
- **`viewer/informe-imataca.html`**, **`viewer/informe-imataca.css`**, **`viewer/informe-imataca.js`**: a self-contained
  page, in **Spanish**, with the viewer's public URL in the citation.
- **The prose**: carry `odd/informes/imataca/informe.md` into the page. The page is the published text; the markdown is
  the authoring copy, so the numbers must match it exactly (the parent spot-checks them).
- **The map**: a MapLibre map (the vendored `viewer/vendor/maplibre-gl.js` + `.css`, the same palette the viewer uses),
  showing **the study's box as a drawn rectangle** with its four coordinates labelled, over the 2024 tile layer from
  `/tiles/2024/{z}/{x}/{y}.png`. It must be legible at 1600×1000 and at 390×844.
- **The figures**: hand-rolled SVG, no chart library (the repository's rule). At minimum the coverage evolution across
  the 10 years with the six classes of `informe.md` § 3, and the two bar series of § 4 (talks per edition; distinct
  species per edition). Every figure carries its caption with the denominator it is a share of.
- **No CDN**: every asset is local, as everywhere else in this repository.

### 2.3 The PDF

Print is the PDF: a `@media print` stylesheet in `informe-imataca.css` that hides the interactive chrome, keeps the
figures, keeps the prose in one column, and prints the map's canvas (which is painted, so it prints; the page notes that
background graphics must be enabled). Do not add a PDF library.

## 3. Acceptance criteria

1. `GET /informe/imataca` serves the page and `GET /api/informe/imataca` the artifact; both work with the service started
   from a clean checkout.
2. **The map shows the box** as a rectangle with its coordinates labelled, over the 2024 tiles, at 1600×1000 and
   390×844, with no horizontal scroll.
3. **Every figure's numbers match the evidence**: the coverage series against `tabla-coberturas.json`, the talks and
   species against the curated tables, and the box's size against the artifact. Checked by the parent, not by the page.
4. **The prose is `informe.md`'s**: the same sections, the same numbers, the same caveats (the ~18 % extent, the geodesic
   method, the declared review assumption, the no-causality rule, the no-water-claim rule).
5. **The citation carries `https://biomas-cve.marioggil.xyz/`** with the date **16 de octubre de 2026**, and the licence
   line says the work is adapted and that the congress catalogue and the code are not MapBiCo data.
6. Print media shows the whole study as a document: no interactive controls, the figures intact, the map present, and the
   page usable at A4 width.
7. No new `font-size`, `line-height`, `font-weight`, colour or background declaration in `viewer/style.css` (the page has
   its own stylesheet); the viewer's own page is untouched; the in-page detector on **the viewer** stays at 0.
8. Suite `387 OK`; `node --check` on the new JS; `python3 -m py_compile` on the touched Python.

## 4. Risks

- **A second source of truth for the numbers.** The page must render from `/api/informe/imataca`, never from numbers typed
  into the HTML; if a number appears in the markup it must be a label, not a figure.
- **The prose in two places** (markdown + HTML) can drift. The parent's verification spot-checks the numbers, and any
  drift is a defect of this unit.
- **The print of a canvas**: MapLibre draws on a canvas that prints, but only with background graphics enabled and only
  for the rendered viewport. The page must say so rather than promise a perfect PDF.
- **The viewer's stylesheet** is built around a body grid; the new page must not import it wholesale. Reuse the palette's
  values, not its layout.
- **Mobile is not a target** (`PRODUCT.md`) but the page must not break at 390×844: the figures and the map stack.

## 5. Verification

The viewer has **no persisted automated test**: the verification of record is the parent's browser pass at 1600×1000 and
390×844 (the page loads; the map draws the box; the figures render; no horizontal scroll), a print-media emulation for the
PDF, a spot-check of every figure's numbers against the evidence files, and the viewer's own page still working with the
detector at 0. The Python suite is the control.
