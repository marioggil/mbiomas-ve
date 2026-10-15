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

With no rectangle nothing is filtered, so the universe is all 255; a rectangle covering the whole map would keep 245, the
reachable ceiling, because the 10 `no_coordinate` studies can never be inside one.

The institution line chart the requester imagined works over the whole corpus (the top five are active in 7–11 of 12
editions) and empties out inside an area: Mérida's richest institution has 6 talks spread over 3 editions.

### 3.2 The ROR enrichment is not trustworthy, and the curated table must say so

`data/enrichment-cache/ror.sqlite` (220 named RORs, in the sibling repo) resolves only part of the picture, and
several assignments are visibly wrong. Measured examples: `ror.org/01f2hnj65` is INCE while the affiliation text
says "Instituto Nacional de Parques"; `ror.org/0354nax61` is a writers' school while the text says "Escuela de
Biología, Facultad de Ciencias, U.C.V."; `ror.org/030vkw561` is a Venezuelan university while the text says
"Instituto Alexander von Humboldt". And one author carries the literal string `No disponible` in the ROR column.

Verdicts recorded in `data/curated/congresos/ror-instituciones.json` over the 42 real ids: **26 usable** and **16
doubtful**, plus one sentinel value. The doubtful ones carry **26 of the 282 talk-institution pairs (9.2%)**, and the
top-15 institutions by talks are all in the usable set, so the charts keep their signal once the doubtful ones are
declared instead of charted. Annex C1: this draft needs the owner's review.

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
5. Top-level `ror_instituciones`: the curated `ror → nombre` map, so the client never reads the curated file.
6. The curated table declares each ROR's `estado` (`ok`/`dudoso`) and the sentinel list; **the build stops** if a
   ROR id in the corpus has no curated entry — the same hard rule the granularity taxonomy already enforces.
7. Contract tests: sentinel casing, a serialised list inside a string, `'[]'`, `None`, ROR dedup inside one study,
   the sentinel ROR value, the missing-curated-entry abort, and the pinned reference numbers of §3.1/§3.2.
8. D9: `STUDIES_SCHEMA_VERSION` 3 → 4 with its explanatory comment moved to v4, and invariant checks for the new
   fields — every study's `especies` is a list of non-empty strings, every `rores` is a sorted list of unique ids each
   present in `ror_instituciones`, every entry of `ror_instituciones` carries a non-empty `nombre` and an `estado` in
   `{ok, dudoso}`, and `human_reviewer` is a non-empty string — so a malformed artifact still stops the service
   instead of reaching the client. One control test per branch.

### F2 — view and client aggregation

`viewer/metrics.js` (new, pure functions, no DOM), `viewer/catalog.js` (list filter + metrics block),
`viewer/app.js` (generalise `commitClip` at `:1390` to a second consumer), `viewer/index.html`, `viewer/style.css`.
One shared predicate decides both the list filter and the metrics, so they cannot disagree. Hand-rolled SVG (no CDN,
per `viewer/vendor/VERSION.txt`). `tools/serve_viewer.py` is **not** touched.

### F3 — verification

Python-pinned reference numbers against the committed artifact (Llanos `30/9/2/19`; Mérida 2013 `n=1, 11`; 2019
cumulative 283 with the top five at 38/33/30/25/23), a real browser pass on `./run.sh serve` recording the same
numbers, and the full suite green on the combined interpreter.

## 6. Commits

Following the project's split (artifacts first, then the tool, so the review candidate is the tool): the curated
table, then the regenerated artifact, then the builder plus its tests and this document.

## 7. Open items

| # | Item | Blocks |
|---|---|---|
| F1-C1 | The 42 curated rows are a **draft**: the 16 `dudoso` verdicts and every display name need the owner's review, like the granularity taxonomy did | Nothing technically; the charts default to `ok` and declare the rest |
| F1-C2 | `data/enrichment-cache/ror.sqlite` lives in the sibling repo, so it is a **reference for curation**, never a build input | Curation only |
| F2-C1 | The `n` threshold below which the series are replaced by a ranking is not fixed yet (proposal: `n < 5`) | F2 acceptance |
