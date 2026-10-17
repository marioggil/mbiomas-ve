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

## 6. Correction pass: the page now carries the report of 842a489

The published page still carried the **old** prose (7 sections) and the old section nav. This pass replaces it with the
report's corrected text (`odd/informes/imataca/informe.md`, commit `842a489`) and makes the two numbers that disagreed
agree, without typing either by hand.

### 6.1 What changed

| File | Change |
|---|---|
| `viewer/informe-imataca.html` | The title, the subtitle and the prose of all **nine** sections, verbatim in Spanish from `informe.md` (headings included). The nav is the nine md titles, with `#seccion-N` / `titulo-N` matching. The map figure stays inside section 1; the coverage, talks and species figures and the tables stay where the md has their data. The old subsection headings (`Dónde se escribió…`, `Qué se mencionó…`, `La curación, entrada por entrada`) are gone: the first two are now section titles, the third was page furniture and its two tables (the curation) stay in section 6 under their own captions. |
| `viewer/informe-imataca.js` | The coverage change column and the coverage figure's captions (the per-class panel caption **and** the figure `figcaption`) now print the artifact's `cambio_etiqueta` instead of a delta computed in the page. The dead `porcentajeConSigno` helper is removed. The two cross-references to "el informe rechaza por nombre el gráfico que los mezcla" / "no se leen como una causa" now say **sección 7** (the old prose had it as section 5). The provenance table's `Recomputación` row no longer describes the builder as the data pipeline: it names `./run.sh pipeline` for the data artifacts and `python3 tools/build_informe_imataca.py` for this page's artifact. |
| `tools/build_informe_imataca.py` | New derived field `cambio_etiqueta` per coverage class, with its rule documented at the constant block (see 6.2). No other number changes. |
| `data/derived/venezuela/informes/imataca.json` | Rebuilt: every class gains `cambio_etiqueta`; no other value moved (the diff on the numeric fields is only the trailing comma). |

### 6.2 The derived change label

The report's section 3 table does not print a plain delta for every class: it writes `×10` for `4.3 Uso Minero` and
`estable` for `1.4 Bosque inundable`, where a mechanical difference would print `+0,39 puntos` and `−0,02 puntos`.
The builder now derives the label per class and ships it as `cobertura.clases[*].cambio_etiqueta`:

- `estable` — `|delta_puntos| < 0,05`: the change rounds to `0,0` points at one decimal, the report's own resolution for
  "nothing moved".
- `×N` — the ratio between the two shares **as the report's table prints them** (two decimals) is `>= 10`; `N` is that
  ratio truncated toward zero. `0,42 / 0,04 = 10,5 → ×10`, the value `informe.md` carries. (The full-precision ratio is
  11,16, which would print `×11` and disagree with the report; the rule is documented on the constants.)
- otherwise — the signed delta in points, two decimals (`, ` decimal mark, `U+2212` minus).

The page never recomputes it: the change column and the figure captions read `cambio_etiqueta` from the artifact.

### 6.3 Checks run (no browser: structural and CLI only)

1. **Anchors and ids against the section titles** — scripted: the 9 md `##` headings, the 9 nav links and the 9
   `<section id=seccion-N aria-labelledby=titulo-N><h2 id=titulo-N>` tuples match one to one. `OK`.
2. **Prose block by block** — scripted: every md paragraph / bullet of each of the 9 sections, normalised (tags and
   markdown markers stripped, whitespace collapsed), equals the page's `<p>` / `<li>` sequence. All 9 sections `OK`
   (4/4/4/3/2/3/5/6/3 blocks).
3. **`node --check viewer/informe-imataca.js`** — `OK`.
4. **Builder reproduces the artifact with the new field** — `python3 tools/build_informe_imataca.py` runs clean and
   writes the 14 classes with `cambio_etiqueta`; mine gives `−1,86 puntos`, `+1,10 puntos`, `×10`, `+0,19 puntos`,
   `estable`, `+0,07 puntos`. Re-running is byte-identical (`sha256 e1cfef5d…` before and after).
5. **`python3 -m unittest discover -s tests`** — `Ran 387 tests … OK (skipped=49)`.
6. **`python3 -m py_compile tools/build_informe_imataca.py`** — `OK`.
7. **The service still imports the artifact** — `.venv/bin/python -c 'import serve_viewer'` (with `tools/` on the path)
   validates the artifact at import: `OK`.
8. **The change column is not typed into the HTML** — `grep` for `×10`, `x10`, `−1,86 puntos`, `+1,10 puntos`,
   `+0,19 puntos`, `+0,07 puntos`, `+0,39`, `−0,02` and `cambio_etiqueta` in `viewer/informe-imataca.html`: **0 matches**.
   The only place the labels exist is the artifact, and the JS reads them.
9. **Non-browser runtime smoke test of the page script** — a minimal DOM stub in Node loaded
   `viewer/informe-imataca.js`, fed it the rebuilt artifact and let it render. The coverage table's change column came
   out `−1,86 puntos (−47.844 ha)` / `+1,10 puntos (+28.275 ha)` / `×10 (+9.932 ha)` / `+0,19 puntos (+4.822 ha)` /
   `estable (−487 ha)` / `+0,07 puntos (+1.742 ha)`, the figure `figcaption` carries `×10`, and no `+0,39` is present.
   This is **not** browser verification.
10. **Working tree** — dirty on purpose (no `git add`/`commit`), and no viewer file outside the allowed edit surfaces
    was touched.

### 6.4 What could not be verified here (parent's job)

- **No browser**: the map drawing the box, the figures at 1600×1000 and 390×844, the print-media pass for the PDF, and
  the viewer's own page with the detector at 0 were **not** checked. The Node smoke test above is the closest thing and
  it is not a browser.
- **One residual difference from the md's table**: the coverage change column for `1.4 Bosque inundable` prints
  `estable (−487 ha)` because the page's change cell is `label (hectares)` uniformly, while the md's row carries
  `estable` alone. The label agrees; the hectares are the page's extra column. The parent may drop them for the stable
  row if it wants the cell character-for-character identical.

## 7. Owner's cuts: the page is back to six sections

`informe.md` moved to commit `3c40109` (six sections) and the page still carried the previous nine-section prose and
nav. This pass applies the owner's cuts to `viewer/informe-imataca.html`, `viewer/informe-imataca.js` and the dead rules
of `viewer/informe-imataca.css`. The builder, the artifact and every `procedencia.*` field are untouched.

### 7.1 What changed

| File | Change |
|---|---|
| `viewer/informe-imataca.html` | Removed the whole `2. Cómo leer las cifras antes de leerlas` section; renumbered sections 3–9 to 2–6 (`id=seccion-N` / `aria-labelledby=titulo-N` / `<h2 id=titulo-N>` and the printed number), and the nav to the six md titles. Removed the water paragraph `Sobre el agua…`; the `y lo declara acá…(human_reviewer, por estudio)` clause; the `Sin esa curación…` paragraph; and sections `7. Lo que este informe no dice` and `8. De dónde salen estos números`, including `<div id="procedencia-detalle">`. The map (§1), the coverage table and figures (§2), the talks table (§3), the institutions and species tables (§4/§5) and the print stylesheet stay. |
| `viewer/informe-imataca.js` | Removed the now-dead `pintarProcedencia` renderer (its `procedencia-detalle` div is gone) and its call. Fixed cross-references: the coverage figure caption says **sección 2**; the no-causality sentence that cited the removed **sección 7** is dropped; the talks caption no longer cites sección 7; comments updated. The change column still reads `clase.cambio_etiqueta`. |
| `viewer/informe-imataca.css` | Removed the rules that only served the removed blocks: `.lista-cautelas` / `.lista-metodo` and `.tabla-envoltura .digest`. |

### 7.2 Checks run (structural and CLI only, no browser)

1. **Nav ↔ sections** — scripted: 6 nav links, 6 section ids, and each `href="#seccion-N"` resolves to the section whose
   `aria-labelledby` and `<h2 id>` are `titulo-N`; all ids unique. `OK`.
2. **Prose block by block** — scripted: the `<p>` sequence of each of the six sections, normalised, equals the md's
   paragraph sequence (`4/3/3/2/2/3` blocks); six sections, no extra block. `OK`. Code fences, tables and the citation
   blockquote are not part of this comparison (the `<pre>` and `<blockquote>` are filled from the artifact).
3. **No leftovers** — `grep` for `Cómo leer las cifras`, `Sobre el agua`, `human_reviewer`, `clansia racemosa`,
   `Lo que este informe no dice`, `De dónde salen estos números`, `1.086.229,52`, `6.371.007,181`, `4,42 %` and
   `Harpia harpyja` over the page's three files: **0 matches**.
4. **`node --check viewer/informe-imataca.js`** — `OK`.
5. **`python3 -m unittest discover -s tests`** — `Ran 387 tests … OK (skipped=49)`.
6. **Change column from the artifact** — a Node DOM stub fed the committed artifact: the column prints
   `−1,86 puntos (−47.844 ha)` / `+1,10 puntos (+28.275 ha)` / `×10 (+9.932 ha)` / `+0,19 puntos (+4.822 ha)` /
   `estable (−487 ha)` / `+0,07 puntos (+1.742 ha)`, equal to the artifact's `cambio_etiqueta`; `procedencia-detalle`
   stayed empty; `grep` finds no change value typed into the HTML (`estable`'s only hit is the md prose "muy estable en
   su cobertura"). **Not** browser verification.
7. **Working tree** — dirty on purpose (no `git add`/`commit`); only the three page files were touched.

### 7.3 What could not be verified here (parent's job)

- **No browser**: the map, the figures at 1600×1000 and 390×844, and the print-media PDF pass are the parent's pass.
- The block-by-block comparison covers paragraphs only; the tables and the JS-filled `<pre>` / `<blockquote>` are checked
  structurally (ids present, renderer reads the artifact), not character by character.

## 8. Mining mentions: the report's new row and paragraph

`odd/informes/imataca/informe.md` (section 3) gained a second row in its talks table ("Mencionan minería") and a new
paragraph ("De qué se hablaba mientras eso pasaba."). This pass carries both into the shipped artifact and the page.

### 8.1 What changed

| File | Change |
|---|---|
| `tools/build_informe_imataca.py` | New criterion (`MINING_FIELDS` / `MINING_TERMS` / `MINING_CRITERION`) and `build_mining_mentions()`: it selects the catalogue studies whose geocoded point falls inside the study's box, matches the terms accent-insensitively and at word boundaries over `titulo`, `resumen`, `palabrasclaves` and `especiesmencionadas`, cross-checks the per-edition talk counts against `tabla-congresos.json`, and ships `congresos.mineria`. |
| `data/derived/venezuela/informes/imataca.json` | Rebuilt: one new object, `congresos.mineria` (`criterio`, `terminos`, `total`, `por_edicion`). Nothing else moved (asserted against `HEAD`). |
| `viewer/informe-imataca.html` | The new section 3 paragraph, verbatim in Spanish, after the review-assumption paragraph. No mining count is typed: the eight per-edition counts live only in the artifact. |
| `viewer/informe-imataca.js` | The section 3 talks table now uses the report's own layout — the editions across and the series down (`Charlas`, `Mencionan minería`, `Pares charla-institución`, `Instituciones`, `Pares dudosos`) plus a `Total` column. The mining row reads `congresos.mineria.por_edicion`, bolds the non-zero counts and leaves the zeros plain; the caption prints `congresos.mineria.criterio` and `terminos`. |

`viewer/informe-imataca.css` was not touched: the new row reuses the existing `.numero` / `.destacado` / `.dudoso`
conventions, and the print stylesheet is unchanged.

**Layout decision (review focus).** The task asks for a "Mencionan minería" *row* with its *eight counts*; the page's
table listed the editions as rows, so the row could not exist without transposing the table. The table now mirrors
`informe.md`'s layout, keeping all five series. If the intent was a mining **column** on the old per-edition table, this
is the one place to reverse.

### 8.2 Checks run (structural and CLI only, no browser)

1. **Builder reproduces the row** — `python3 tools/build_informe_imataca.py` prints `8 of 30 talks mention mining` and
   writes `congresos.mineria` = total `8`; `1999 2/2, 2001 1/3, 2003 4/6, 2005 0/9, 2007 0/2, 2011 0/1, 2013 1/2,
   2019 0/5`. Equal to the report's row. Re-running is byte-identical (`sha256 63f379c0…` before and after).
2. **Criterion cases** — `"suelo mineral"` and `"explotación forestal"` do **not** match; `MINERÍA`, `mineria`,
   `aurifero`, `diamantífera`, `bauxita`, `arco minero`, `actividad minera`, `explotación aurífera`, `dragado`,
   `aluvial` do. `OK`.
3. **Artifact diff is additive** — the rebuilt artifact equals `HEAD` except for `congresos.mineria`.
4. **`node --check viewer/informe-imataca.js`** — `OK`.
5. **`python3 -m unittest discover -s tests`** — `Ran 387 tests … OK (skipped=49)`.
6. **Prose block by block** — scripted on the seven sections (`4/3/4/2/2/5/3` blocks): every md paragraph/bullet,
   normalised, equals the page's `<p>`/`<li>` sequence, **including the new section 3 paragraph**. All seven `OK`.
7. **Talks table from the artifact** — a Node DOM stub fed the rebuilt artifact renders the table header
   `Edición | 1999 … 2019 | Total` and the row `Mencionan minería | 2 | 1 | 4 | 0 | 0 | 0 | 1 | 0 | 8`, equal to
   `congresos.mineria.por_edicion`; the four non-zero cells carry `.destacado` and the zeros do not. **Not** browser
   verification.
8. **No mining count typed into the HTML** — `grep` over `viewer/informe-imataca.html`: `Mencionan minería`, `mineria`,
   `por_edicion`, `<td` and `<table` all **0 matches**; the only `minería` is the report's own prose "8 mencionan
   minería". The JS reads `datos.congresos.mineria` / `mineria.por_edicion`.
9. **Working tree** — dirty on purpose (no `git add`/`commit`); only `tools/build_informe_imataca.py`,
   `data/derived/venezuela/informes/imataca.json`, `viewer/informe-imataca.html` and `viewer/informe-imataca.js` changed.

### 8.3 What could not be verified here (parent's job)

- **No browser**: the talk table's layout at 1600×1000 and 390×844 (ten columns scroll inside `.tabla-envoltura`), the
  print/PDF pass, the map and the figures were not checked. The Node stub above is not a browser.
- The block-by-block comparison covers prose only; the new table is checked functionally (the stub) and by grep, not
  pixel by pixel.
