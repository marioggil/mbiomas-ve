# Feature: congress metrics for a selected map area

**Status**: F1 in progress · **Branch**: `feat/metricas-congresos-area`, stacked on
`fix/catalogo-anio-xi` (the catalog resync, unpushed) · **Authorized**: 2026-10-15
**Parent record**: [`catalogo-estudios-202.md`](catalogo-estudios-202.md) (display contract, D12 `study_id` shape,
D14 undated path, schema v3) and [`plataforma-cobertura-ve.md`](plataforma-cobertura-ve.md) (T8c, the rectangle draw
this feature reuses).
**Sibling record**: `Congresos_CVE_V2/docs/metricas.md` — the same question asked against the full 6.204-row corpus,
with decisions A1–A5 and the coverage trap. Its numbers are **not** transferable to this project: here the corpus is
the 255 human-verified studies, not 6.204.

## 1. Goal

When the user draws a rectangle on the map, the catalog panel must (a) filter its list to the studies inside the
drawing and (b) show metrics for that area: a species chart and an institution contribution-over-time chart. The
full-corpus case (no rectangle) must stay useful, because it is where the institution series actually has a signal.

**Non-goals**: taxonomic rollup (GBIF), co-institution network, comparing two areas, normalising institution names
beyond the curated table, and feeding `study_gap` in the priority index.

## 2. Decisions

| # | Decision | Consequence |
|---|---|---|
| D1 | **Universe: all 255 studies**, declaring the human/machine split (mario 212 / IA 43) | needs `human_reviewer` in the artifact |
| D2 | **Area = every study whose coordinate falls inside the rectangle**, flagged by location granularity (not only `placeable`) | ceiling 245; the 10 studies without coordinates are declared, never silently dropped |
| D3 | **Species: top-N bars + distinct-species-per-edition series** | must survive a long tail (top name has 8 mentions of 534) |
| D4 | **Institutions: cumulative stacked area** per institution (top-5 + "others") | the legend states that a cumulative series never falls |
| D5 | **The rectangle filters the list *and* adds the metrics**, reusing the C10 chip pattern | one gesture, two effects; the panel stays the authoritative view |
| D6 | **Aggregation happens in the client** (the browser already holds all 255 studies) | no metrics endpoint in the server; the arithmetic is JS without a persisted test |
| D7 | **Parsing never crosses into JS.** The builder emits `especies[]` and `rores[]` already parsed | D6's untested surface becomes arithmetic, not judgement |
| D8 | **`human_reviewer` travels in the artifact** (`mario`/`IA`) | the KPI can declare D1's split without re-reading the parquet |
| D9 | **The artifact moves to `schema_version` 4 and the import-time validator acknowledges it**, validating the new fields' invariants as it already does for the classes | `tools/serve_viewer.py` enters F1's surface, bounded to `STUDIES_SCHEMA_VERSION`, its docstring and the new invariant branches. Without this the service refuses to start on its own artifact |

## 3. Measured facts (verified, not assumed)

Measured 2026-10-15 against `data/derived/venezuela/congresos/catalogo-estudios.json` (schema v3) and the raw
parquet. Every number below decides a piece of the design.

| Measurement | Value |
|---|---|
| Studies / `placeable` / `coarse_location` / `outside_extent` / `no_coordinate` | 255 / **145** / 87 / 13 / 10 |
| Studies with a coordinate (the reachable ceiling for D2) | **245** |
| `especiesmencionadas` non-null | 194 of 255 (113 of 145 placeable) |
| Distinct species names after parsing | **534** — top is `peces` with **8** mentions (`aves` 7, `mamíferos` 5) |
| Field shapes still present | `str` 194, `None` 61; sentinels survive verbatim: `"['N.A.']"`, `'[]'`, `'No se mencionan especies específicas'` |
| Authors with `ror` / distinct ROR ids | 546 of 715 (76.4%) / **42** plus one sentinel value, `No disponible`, carried by a single author |
| Studies with at least one usable ROR / talk-institution pairs | 226 / **282** |
| Co-affiliation per study (distinct RORs, sentinel dropped) | 0 → 29 studies, 1 → 175, 2 → 46, 3 → 5 |
| Top institutions by talks (`ROR`) | 38 (11 editions), 33 (11), 30 (8), 25 (11), 23 (7) |
| Distinct free-text institution strings | 319 (up to 30 variants for one ROR, mean 5.3) |
| `human_reviewer` | mario 212 / IA 43 — not in the artifact at measurement time; **F1 adds it** |
| Years | 1991, 1994, 1999, 2001, 2003, 2005, 2007, 2009, 2011, 2013, 2015, 2019 (irregular, 0 null) |

### 3.1 Area density — the measurement that decides the chart shapes

Under D2, a rectangle keeps every study whose coordinate falls inside it, whatever its `display_class`; the `T0`/`T1`/`T2`
columns are the location granularity of those studies, which is not the same partition as `display_class`.

| Area drawn | n | T2 | T1 | T0 | with species | distinct species | distinct RORs |
|---|---:|---:|---:|---:|---:|---:|---:|
| Guayana/Imataca | 32 | 32 | 0 | 0 | 15 | 45 | 10 |
| Mérida ±0.25° | 16 | 10 | 2 | 4 | 15 | 38 | 7 |
| Caracas ±0.3° | 14 | 11 | 2 | 1 | 11 | 38 | 7 |
| **Llanos/Orinoco** | **30** | **9** | **2** | **19** | 21 | 47 | 19 |
| Barinas ±0.25° | 4 | 2 | 1 | 1 | 2 | 2 | 1 |
| no rectangle (no spatial filter) | 255 | 158 | 31 | 66 | 189 | 534 | 42 |
| for reference, `placeable` only | 145 | 145 | 0 | 0 | 110 | 353 | 30 |

With no rectangle nothing is filtered, so the universe is all 255. A rectangle equal to the COG extent — the largest
one the map can draw — keeps **224**: 245 studies carry a coordinate, minus the 21 whose coordinate falls outside the
extent (13 `outside_extent` and 8 coarse T0 mentions that geocoded abroad). The 10 `no_coordinate` studies can never
be inside any rectangle, and 224 — not 245 — is the number a full-extent rectangle must return.

The institution line chart the requester imagined works over the whole corpus (the top five are active in 7–11 of 12
editions) and empties out inside an area: Mérida's richest institution has 6 talks spread over 3 editions.

### 3.2 The ROR enrichment is not trustworthy, and the curated table must say so

`data/enrichment-cache/ror.sqlite` (220 named RORs, in the sibling repo) resolves only part of the picture, and
several assignments are visibly wrong. Measured examples: `ror.org/01f2hnj65` is INCE while the affiliation text
says "Instituto Nacional de Parques"; `ror.org/0354nax61` is a writers' school while the text says "Escuela de
Biología, Facultad de Ciencias, U.C.V."; `ror.org/030vkw561` is a Venezuelan university while the text says
"Instituto Alexander von Humboldt". And one author carries the literal string `No disponible` in the ROR column.

Verdicts recorded in `data/curated/congresos/ror-instituciones.json` over the 42 real ids: **26 verified** and **16
doubtful**, plus one sentinel value. The doubtful ones carry **26 of the 282 talk-institution pairs (9.2%)**, and the
top-15 institutions by talks are all in the verified set. **The owner reviewed the table on 2026-10-15 and accepted the
doubtful ones into the charts** (`grafica: true` on all 42): the verdict stays recorded as the watermark — the chart
declares how many of its pairs come from doubtful entries — but it no longer excludes anything. F1-C1 is closed.

## 4. Risks and mitigations

| # | Risk | Mitigation |
|---|---|---|
| **M1** | D2 lets coarse mentions in: Llanos is 30 studies of which **21 are coarse and 19 are T0** (the "mentions Venezuela, no place" pile). A chart that hides the granularity reads centroids as presence | The granularity is **in the chart**, not in a tooltip: every metric header carries a stacked `n` by T2/T1/T0, and each top-N row declares its coarse share. Llanos is the pinned fixture |
| **M2** | D3's richness series spikes on a single talk: Mérida 2013 has **n=1 and 11 species**; Guayana 2001 has n=3 and 14 | The richness line is drawn **over bars of `n`** on the same X axis. A spike over a bar of 1 cannot be misread. Mérida 2013 is the pinned fixture |
| **M3** | D6/D7's JS arithmetic has no persisted test | (a) the builder's parsing is covered by contract tests; (b) the expected numbers are pinned in Python against the committed artifact; (c) F3 records a real browser pass, as the project already does for the 255-study catalog |
| **M4** | Coverage is uneven (74% of studies declare species, 76% have a ROR, 7–34 talks per edition) | Every chart publishes its denominator; the empty state is a result ("2 talks in the area: no series to draw"), not a two-point line |

## 5. Phases

### F1 — data (Python, tested)

`tools/build_study_catalog.py`, `data/curated/congresos/ror-instituciones.json` (new),
`data/derived/venezuela/congresos/catalogo-estudios.{json,csv}`, `tests/test_study_catalog_contract.py`,
`tools/serve_viewer.py` (bounded to D9: the constant, its docstring and the new invariant branches),
`tests/test_serve_viewer_studies.py`.

1. `schema_version` 3 → 4.
2. Per study, keep the raw text and add `especies[]`: sentinels compared **lowercased** (`n.a.`, `n/a`, `na`,
   `s/d`, `s.a.`, `-`, `''`), bracketed serialised lists unwrapped, split on commas, trimmed, empty dropped.
3. Per study, add `rores[]`: the ROR ids of its authors, deduplicated, sentinel values dropped, sorted.
4. Add `human_reviewer` (`mario`/`IA`).
5. Top-level `ror_instituciones`: the curated map projected for the client as `ror → {nombre, estado, grafica}`, so
the client never reads the curated file.
6. The curated table declares each ROR's `estado` (the verdict: `ok`/`dudoso`), its `grafica` (the decision: does it
count and get drawn) and the sentinel list; **the build stops** if a ROR id in the corpus has no curated entry — the
same hard rule the granularity taxonomy already enforces.
7. Contract tests: sentinel casing, a serialised list inside a string, `'[]'`, `None`, ROR dedup inside one study,
   the sentinel ROR value, the missing-curated-entry abort, and the pinned reference numbers of §3.1/§3.2.
8. D9: `STUDIES_SCHEMA_VERSION` 3 → 4 with its explanatory comment moved to v4, and invariant checks for the new
   fields — every study's `especies` is a list of non-empty strings, every `rores` is a sorted list of unique ids each
   present in `ror_instituciones`, every entry of `ror_instituciones` carries a non-empty `nombre`, an `estado` in
   `{ok, dudoso}` and a boolean `grafica`, and `human_reviewer` is a non-empty string — so a malformed artifact still
   stops the service instead of reaching the client. One control test per branch.

### F2 — view and client aggregation

`viewer/metrics.js` (new, pure functions, no DOM), `viewer/catalog.js` (list filter + metrics block),
`viewer/app.js` (generalise `commitClip` at `:1390` to a second consumer), `viewer/index.html`, `viewer/style.css`.
One shared predicate decides both the list filter and the metrics, so they cannot disagree. Hand-rolled SVG (no CDN,
per `viewer/vendor/VERSION.txt`). `tools/serve_viewer.py` is **not** touched by F2.

Settled while building it:

| Point | Decision |
|---|---|
| Metrics universe | The **area**, not the list: the edition filter and the search narrow the list only, or the 12-edition series would collapse to one point. The block shows its own denominator |
| Spatial filters | Mutually exclusive in the catalog: the most recent gesture wins, and one chip declares which is active |
| The rectangle on the map | A marker click replaces the catalog's area filter but does **not** erase the drawing, so the composition panel keeps its clip stats and re-drawing is not the price of a click |
| `MIN_TALKS_FOR_SERIES` | **5** (F2-C1 closed). Barinas, at 4 talks, is the empty-state case |
| Tie-breaks | Count desc, then lowercased name asc — with string comparison, never `localeCompare`, so two renders cannot disagree |
| The block's default | **Collapsed**, with a one-line summary (`255 charlas · 245 con coordenada · 226 con institución · 534 nombres`), because the study list is the panel's primary content and three charts were pushing it off the first screen. Drawing an area expands it; clearing it folds it back; a manual fold is respected until the next area gesture |
| The edition buttons | They **count inside the area** once one is drawn (`Todas (14)`, and `(0)` for an edition the area does not reach), because a button that promises 15 studies and shows none is the same defect as a chart that hides its granularity |

### F3 — verification

**Done, and this is the record.**

*Independent Python recomputation versus the real browser.* Four rectangles were drawn in a Playwright pass over
`tools.serve_viewer` on `127.0.0.1:8017`, the rectangle the browser actually committed was captured by wrapping
`MapBiomasCatalog.setArea`, and the DOM numbers were compared against a separate Python implementation over that same
rectangle. Every field matched, four times: `n`, the T2/T1/T0 split, with-species, with-ROR, the ok/doubtful pair
split, the reviewer split, the distinct species count and the whole top-8 ranking **including its display forms and
its tie order**.

| Rectangle (as the browser committed it) | n | T2/T1/T0 | species | pairs ok/dudoso | top |
|---|---:|---|---|---|---|
| no rectangle | 255 | 158/31/66 | 189 · 534 distinct | 282 (256/26) | peces 8, Aves 7, mamíferos 5 |
| Mérida `-71.533,8.275,-71.046,8.784` | 14 | 9/2/3 | 13 · 36 | 19 (18/1) | Pheidole fallax 2, then 1s |
| Venezuela centroid `-66.365,7.766,-65.878,8.275` | 14 | **3/0/11** | 9 · 27 | 16 (14/2) | anfibios 2, aves 2, mamíferos 2 |
| Barinas `-70.11,7.90,-69.61,8.40` | 4 | 2/1/1 | 2 · 2 | 1 (1/0) | Panicum maximum 1, Zea mays 1 |
| Llanos `-68.015,7.015,-64.010,9.024` | 29 | 9/2/18 | 21 · 47 | 34 (30/4) | six-way tie at 3, resolved by name |

The centroid row is M1's case in the wild: **11 of 14 studies are T0**, so the T0 count is what keeps that area
honest. The Barinas row is M2/M4's: 4 talks, the ranking and the KPIs, **no series**, and the sentence that says why.

*Independent verification of the client code* (a separate verifier with its own harnesses): the pure functions
reproduce 255 / 224 (COG extent) / 534 / 282-256-26 / Llanos 30-9-2-19 / Barinas 4 / cumulative 38-33-30-25-23. Those
figures are the **verdict** split, and they did not change when the owner accepted the doubtful entries into the
charts: what changed is the charting, so `others[11]` went from 107 to **133** and the charted total from 256 to
**282**. 14 emitted SVGs parse as XML with `role="img"`, `viewBox`, `<title>` and `<desc>`; names carrying
`&`, `<` and `"` are escaped; malformed, NaN and inverted bboxes never throw and are contained at the `setArea`
boundary; the Python suite stays green.

*Two defects found by looking at the rendered page and fixed before the commit*: the block pushed the study list below
the fold on every load (hence the collapsed default), and the Spanish counters read `1 tienen institución (ROR)` and
`1 pares charla-institución` on a one-study area (hence the number-agreement helper).

## 6. Commits

Following the project's split (artifacts first, then the tool, so the review candidate is the tool): the curated
table, then the regenerated artifact, then the builder plus its tests and this document.

## 7. Open items

| # | Item | Blocks |
|---|---|---|
| F1-C1 | ~~The 42 curated rows are a draft: the 16 `dudoso` verdicts and every display name need the owner's review~~ **closed 2026-10-15**: the owner reviewed the table and accepted the 16 doubtful assignments for the charts (`grafica: true` on all 42), with the verdict kept as the declared watermark | — |
| F1-C2 | `data/enrichment-cache/ror.sqlite` lives in the sibling repo, so it is a **reference for curation**, never a build input | Curation only |
| F2-C1 | ~~The `n` threshold below which the series are replaced by a ranking~~ **closed in F2**: `MIN_TALKS_FOR_SERIES = 5` | — |
