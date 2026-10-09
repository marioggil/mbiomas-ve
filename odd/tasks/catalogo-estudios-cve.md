# Feature: CVE study catalog in the viewer (F4)

**Status**: in progress
**Branch**: `feat/catalogo-estudios-cve`
**Scope authorized**: F4 — display the human-reviewed study catalog inside the existing
viewer. **Explicitly NOT authorized**: enabling the `study_gap` term of the F3 priority index
(see section 6), and any change to the source coordinates (decision D11).

Parent feature record: `odd/tasks/plataforma-cobertura-ve.md`. That document carries decisions
D1–D8, the platform's measured evidence and its review debt; this one continues the decision
sequence at D9 and does not repeat it.

---

## 1. Goal

Show the study catalog in the platform: **31 human-reviewed abstracts** from the three
Congreso Venezolano de Ecología (CVE) editions, as a catalog panel that is the authoritative
view plus a secondary point layer on the existing annual map.

The catalog is the first data in this project that is not a raster. It is a list of studies —
where they were done — and its value is that it can be read against the 1985–2024 land cover
series.

## 2. Non-goals

- **Enabling the F3 `study_gap` term.** 31 studies over 28 locations cannot populate an H3
  res 8–9 gap index. Recorded in section 6, and it is the most likely mistake to make next.
- **Editing, normalising or re-geocoding the coordinates** (D11).
- **Parsing `ubicaciontemporal`** into machine dates. 10 of 31 rows carry it and the formats
  are mutually incompatible (`1988`, `1989,90`, `1989-90`,
  `Octubre de 1997 a junio de 1998`), so any automatic year link would be a guess.
- **Ingesting the full abstracts** beyond what display needs. `resumen` is stored and shown;
  no text search index, no embedding, no NLP.
- **Any new runtime dependency.** No pyarrow, no pandas, no geopandas in the service or in the
  image (D10). The image currently builds at 108 MB and that is worth protecting.

## 3. Decisions (binding)

| # | Decision | Consequence |
|---|---|---|
| D9 | The **catalog panel is the authoritative view**; the map point layer is secondary | Every study is reachable in the panel, including the ones the map cannot place. The map is an index into the catalog, not the other way round |
| D10 | The service reads a **versioned derived JSON** produced by a tool; the raw parquet stays raw and unversioned | Follows the established raster → COG → derived pattern. The derived artifact is inside `data/derived/`, which the Dockerfile already copies, so no new mount and no new dependency |
| D11 | The source coordinates are displayed **as they are**. No re-geocoding, no precision warning labels | `geo_confidence: high` is shown as-is even though it is constant across all 29 geocoded rows. The four Barinas studies collapse to one coordinate and this is recorded, not corrected |

**Rebuild-only dependency.** The builder needs `pyarrow` to read Parquet, and nothing else in the
project does. It is a rebuild-time dependency in exactly the sense the README already gives GDAL:
regeneration runs where the dependency is installed, and the versioned derived artifact is what
ships. `run.sh check` names it as rebuild-only, never as a serving prerequisite, and the image and
the service stay free of it (D10).

## 4. Measured facts about the input (verified, not assumed)

Source: `data/raw/congresos/congresos_revisados.parquet`, 59.7 KB, read with a throwaway
`uv` environment. **No project dependency was added**, and nothing was installed in `.venv`.

| Measurement | Value |
|---|---|
| Rows | **31** |
| `source_path`, `titulo`, `resumen`, `human_reviewed_at` | 31 distinct each — one row per abstract |
| Editions | **I / 1991 / Sartenejas** (14), **II / 1994 / Guanare** (14), **III / 1999 / Puerto Ordaz** (3) |
| Rows with `latitud`/`longitud` | 29 |
| Distinct coordinates | **26** |
| Coordinates shared by more than one study | **1** — `(8.1450535, −69.8567392)` carries **4** studies |
| Studies outside the raster extent | **1** — `(18.306781, −65.805511)` = Bosque Nacional del Caribe, **Puerto Rico** |
| Studies with no coordinate | **2** |
| `geo_confidence` | 1 distinct value among 29: `high` |
| `importance` | 1 distinct value: `1.0` |
| `human_verified` | 1 distinct value: `True`, reviewer `mario`, all 31 reviewed 2026-10-08 |
| `palabrasclaves` | **empty in all 31 rows**; the column is `list<string>` |
| `ubicaciontemporal` | 10 non-null, incompatible formats |
| `query_usado` | null in all 31 rows |
| `paises` | 4 distinct, including `["U.S.S."]` and `[]` |
| `rores` | ROR institution URLs, encoded as JSON arrays inside strings |

### 4.1 The collided coordinate, in full

This is the reason the display contract needs three exclusion classes rather than one. Four
studies of edition I resolved to a single point while their own location text names four
different granularities:

| Location text | What it actually is |
|---|---|
| `Barinas, Turen y Yaritagua` | a **multi-site** mention: Turén is in Portuguesa, Yaritagua in Yaracuy |
| `estado Barinas` | an **entire state** |
| `Jardín Botánico de la ULA, Barinas` | a **specific point** inside Barinas city |
| `Barinas` | the city |

One marker would assert that these are the same place. They are not.

### 4.2 The extent, for the record

`lon −73.51785335775641 → −57.9936177752449`, `lat 0.5274009033065727 → 12.654657238920112`,
taken from the source COG's own geotransform via `/api/meta`. The Puerto Rico study sits
**5.65° north** of that ceiling, so a map fitted to the extent can never draw it.

## 5. Display contract

**Map layer shows 24 of 31 studies. The panel accounts for all 31.**

| Class | Count | Map | Panel |
|---|---|---|---|
| Placeable | **24** | one marker, click selects the study | listed |
| Coordinate shared by several studies | **4** | excluded | listed, each with its own location text and the note that 4 studies share one coordinate |
| Outside the mapped extent | **1** | excluded | listed with the measured reason and the extent bounds |
| No coordinate | **2** | excluded | listed with `ubicaciongeografica` verbatim, which for both is empty |

Rules:

1. A marker represents **exactly one study**. No counter markers: the user chose exclusion over
   aggregation, so the map never implies a location the data does not establish.
2. Every exclusion carries a **reason string produced by the builder**, not by the frontend, so
   the reason is reviewable in the derived artifact and cannot drift between the two.
3. The D7 labelling stays untouched: studies are shown over the MapBiomas extent with the same
   boundary note, because the studies are plotted on a map whose area exceeds recognized borders.
4. No precision or confidence warnings (D11). The exclusions are stated as facts, not as
   editorial about data quality.

## 6. Warning: this catalog does not unlock the F3 index

`tools/priority_schema.py` ships `study_gap` **disabled at weight 0.0** with a rationale naming
project decision D2 ("study abstracts are not digitalized yet"). That rationale is now
*partially* stale: the abstracts are reviewed and digitalized, but they are **not ingested**.

That is not the same thing, and the gap is large:

- 31 studies over 28 locations, concentrated in three congress editions (1991, 1994, 1999).
- An H3 res 8–9 grid over the MapBiomas extent is tens of thousands of hexagons.
- Almost every hexagon has zero studies, and "zero studies" here would mean "nobody published
  about it in three specific congresses", not "nobody studied it".

Displaying the catalog is fully justified. **Enabling `study_gap` on this input is not**, and
anyone who reads "the catalog exists now" as "the term can be turned on" is about to publish a
map of publishing activity at three congresses as if it were a map of knowledge gaps.

## 7. Tasks

Each task closes with one work-unit commit and observed evidence.

### T1 — Derived catalog artifact and builder
- `tools/build_study_catalog.py` reads the raw parquet and writes
  `data/derived/venezuela/congresos/catalogo-estudios.json` plus a CSV, both versioned.
- The builder computes the section 5 classification and each exclusion's reason string at build
  time, so the service never recomputes and the reasons are reviewable in the artifact.
- Fails loudly on a missing column, a null in a column the contract requires, or a coordinate
  outside a plausible global range.
- **Evidence**: artifact produced from the real parquet with a rebuild-only interpreter that has
  `pyarrow` and GDAL together. Counts reproduce section 4 exactly: `placeable` 24,
  `shared_coordinate` 4, `outside_extent` 1, `no_coordinate` 2. `especiesmencionadas` keeps its 21
  non-null values. Two consecutive runs differ **only** in `generated_utc`, and the CSV is
  byte-identical between them. `git status` shows only the three intended paths and no temporary
  leftovers in the output directory.
- **Guards exercised, not assumed**: a missing `pyarrow`, a missing or unreadable
  `--labelling-json`, a non-list JSON column, a non-object author, an author missing one of its
  five fields, and a non-string institution each abort with exit 1 and a message naming the row.
  Validation runs before any write, and writes are atomic through a temporary file plus
  `os.replace`, so a failing run leaves no partial artifact.
- **The `n_autores` cross-check is clean**: `len(autores)` equals the source `n_autores` column in
  **31 of 31** rows, 67 authors in total. That check is not advisory: it aborts the build on any
  mismatch, so the artifact is only allowed to exist because it passed.
- **Two defects were found by reviewing the first artifact, and fixed before anything was built on
  top of it.** `study_id` had been composed as `cve-1991-pagina-5-2-p5-i2`, repeating the page and
  index the source stem already carries, and that id is about to become a URL path segment; it is
  now `cve-1991-pagina-5-2`, asserted unique and re-checked against `^[a-z0-9-]+$`. And `autores`
  and `instituciones` were being emitted as the raw JSON text of the source columns, which would
  have printed `[{"nombre": ...}]` into the panel that D9 makes the authoritative view; both are
  now parsed (`autores` into objects keeping `nombre`, `afiliacion`, `ror`, `pais` and `orcid`;
  `instituciones` into strings), which also cut the CSV from 27.1 KB to 14.9 KB.
  `especiesmencionadas` deliberately stays a verbatim **string**: it is free text, inconsistently
  comma-separated, and not valid JSON in every row, so parsing it would invent structure that is
  not there.

### T2 — Catalog contract tests — **DONE**
- `tests/test_study_catalog_contract.py`: **140 tests in 18 classes**, stdlib `unittest` only, and it
  runs on a bare interpreter because T2 also made the builder's heavy imports lazy (below). It
  covers the pure logic (`slugify`, `make_study_id`, `classify`, `display_class_for`,
  `exclusion_reason_for`, `check_n_autores`, both JSON column parsers, every reachable
  `validate_rows` failure, `build_study`, `build_catalog`, `_csv_value`) plus an integration anchor
  that asserts the **committed** artifact's display contract, so a regenerated catalog that breaks
  the contract fails a test instead of reaching the viewer.
- **Every check carries a control that proves it can fire.** The controls are pinned with
  `assertRaisesRegex`: the file contains **0 bare `assertRaises`**, 48 `assertRaisesRegex` sites, and
  each of the 27 contract branches has its own mutation control. The T10 lesson is applied up front
  rather than rediscovered.
- **Enabling change in the builder: the rebuild-only imports are now lazy.** The module previously
  did `raise SystemExit(1)` at import time when `pyarrow` or `osgeo` was missing, which killed the
  test runner during import and made `slugify` or `classify` unimportable. They now load inside
  `read_rows` and `cog_extent` and raise `StudyCatalogError` with the **identical wording**, and the
  CLI still prints that message to stderr and exits 1. A library module must not decide to exit.
- **Evidence**: `Ran 162 tests ... OK` (140 new plus the 22 pre-existing) in 0.142 s, with the lazy
  import proven on both the system interpreter and the repository `.venv`, which has neither
  dependency. The refactor is behaviour-preserving on real output: regenerating with the new code
  differs from the committed artifact **only** in `generated_utc`, and the CSV is byte-identical
  (`a8955935…` on both sides).
- **The controls are shown able to fail, by mutation**: forcing `display_class_for` to always return
  `placeable` produces 13 failures, `slugify` returning its input 7 failures plus 16 errors, ignoring
  the shared coordinate 4, disabling the `n_autores` check 3, and joining `_csv_value` strings 2.
  A green suite that has never been shown to go red is not evidence, and this one was.
- **A wrong premise of the parent, corrected by the writer**: the system `python3` *does* have GDAL;
  only `pyarrow` is missing. The bare-interpreter proof therefore also runs on the repository
  `.venv`, which has neither, and the GDAL-absent path is exercised by simulating the missing module
  rather than by relying on an interpreter that lacks it.
- **Coverage gaps, stated rather than implied**: `load_labelling` and `write_outputs` have no
  dedicated tests. `load_labelling` is patched in the CLI tests and `write_outputs` is exercised only
  indirectly, through the byte-identity rebuild.

### T3 — API — **DONE**
- Three read-only endpoints in `tools/serve_viewer.py`, as **pure additions**:
  `/api/studies/catalog`, `/api/studies/{study_id}` and `/api/studies/_load_counters`.
  Declaration order is deliberate and load-bearing: the two literal routes come **before** the
  `{study_id}` catch-all, or the catch-all would swallow them and `/api/studies/catalog` would
  answer `study not found: catalog`.
- `STUDIES_CATALOG_PATH` is `data/derived/<country>/congresos/…` and deliberately **not** under
  `DERIVED_ROOT`, because studies are not collection-scoped. Deriving it from `DERIVED_ROOT` would
  have produced a path that does not exist and a confusing startup failure.
- **Parsed once at import**, applying the T8a CRITICAL finding before it could repeat. The counter
  endpoint exists to make that invariant measurable rather than asserted, following the shape the
  composition endpoints already established.
- An import-time consistency check stops the service with a specific message on a missing,
  unparseable or internally inconsistent artifact. It validates the **superset** of what this
  document originally asked for: the brief said "the three `classes` counts" and the artifact ships
  **four**, so it checks the four-class total against `study_count`, the non-placeable subtotal
  against `excluded_count`, the placeable count against `map_visible_count`, and each declared count
  against the real per-class tally. The imprecision was reported rather than guessed at.
- **Evidence, reproduced by the parent rather than taken from the handoff**: `/api/studies/catalog`
  returns HTTP 200 with 31 studies and counts 24/4/1/2; `/api/studies/_load_counters` reads **1
  before and 1 after 24 requests** (20 catalog plus 4 per-study), which is the parse-once invariant
  measured rather than claimed; an unknown id returns **404** with `study not found: no-existe`; and
  `/api/health`, `/api/meta`, `/api/composition/series`, `/api/composition/year/2024` and one tile
  all still return 200. The diff against the previous revision is **additions only, zero deleted
  lines**, which is why no existing endpoint could have changed behaviour.

### T4 — Frontend: catalog panel and map layer
- A catalog section in `viewer/index.html`, rendered by a new module, with all 31 studies and
  per-class counts.
- A secondary point layer in `viewer/app.js`: 24 markers, click selects the study in the catalog.
- `viewer/api.js` remains the only file in the frontend containing `fetch`.
- **Evidence**: verified in a real browser, not a stubbed DOM. Layout measured at two viewports,
  because the T8b record shows layout defects are invisible to a stub.

### T5 — Packaging and documentation
- `run.sh`: a `stage_studies` stage and the parquet named in `check` as a rebuild-only
  prerequisite, since it is gitignored and therefore absent from a fresh clone.
- `README.md`: what the catalog is, the display contract, and the section 6 warning.
- **Evidence**: `check` on a fresh clone, `pipeline --dry-run`, and the container serving the
  catalog from the image with no new mount.

## 8. Dissent, recorded rather than acted on

The user chose to **exclude** the four Barinas studies from the map instead of showing them as one
marker with a count. This document records the disagreement because the choice is close and the
reason matters.

Three of those four name a place that is inside the extent and is locally unambiguous — the city
of Barinas, and the Jardín Botánico de la ULA within it. Excluding them costs real spatial
information: the map shows 24 of 31 studies where 28 are physically inside the mapped area. The
alternative was one marker carrying an explicit count, which would have preserved their presence
without asserting a single location.

Done the user's way because the map then never states anything the data cannot support, which is
the same discipline D7 applies to the extent. Any future change to this should be its own decision,
not a quiet edit.

## 9. Open items

| # | Item | Blocks |
|---|---|---|
| C1 | `data/raw/congresos/congresos_revisados.parquet` is gitignored, so a fresh clone cannot rebuild the catalog | Rebuild only. The derived artifact is versioned and ships, so serving is unaffected (D10) |
| C2 | Four studies share one coordinate and one study is mislocated in Puerto Rico | Recorded, not fixed (D11). Anyone reusing these coordinates for analysis, rather than display, must resolve this first |
| C3 | `palabrasclaves` is empty in all 31 rows, so keyword search cannot be offered | Nothing. Recorded so a future contributor does not design a filter over an empty column |
| C4 | The `study_gap` rationale in `tools/priority_schema.py` names D2 and will read as stale once someone notices the catalog exists | Nothing yet. Section 6 is the answer; do not flip the term |
