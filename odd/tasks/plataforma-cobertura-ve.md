# Feature: MapBiomas data platform — annual viewer + composition panel (Venezuela)

**Status**: in progress
**Branch**: `feat/plataforma-cobertura-ve`
**Scope authorized**: F0 (normalization) + F1 (statistics) + F2 (viewer)
**Out of scope for this authorization**: F3 (H3 priority index), F4 (study catalog), any publication/hosting on the internet

---

## 1. Goal

Publish the 40 annual MapBiomas Venezuela land cover & land use rasters (1985–2024,
Collection 3) as an interactive annual viewer with a composition panel, on a
multi-country-ready schema, running locally.

## 2. Non-goals (explicitly out of scope)

- H3 hexagon priority index and its configurable weight engine (F3).
- Study catalog / congress-abstract ingestion (F4) — input not digitalized yet.
- Public hosting, domain, CDN. Local execution only.
- Publishing derived products. License and attribution terms are **not yet
  resolved** (open item #1) and block publication, not development.

## 3. Decisions already made (do not re-litigate)

| # | Decision | Consequence |
|---|---|---|
| D1 | First deliverable = annual viewer + composition panel | Normalization and statistics are prerequisites, not extras |
| D2 | Study abstracts are not digitalized yet | "Study gap" term enters the H3 schema on day 1 with weight 0 |
| D3 | Priority = configurable weighted score, weights exposed and versioned | No black-box maps; needs weight sensitivity analysis |
| D4 | Unit = H3 hexagons res 8–9, full series 1985–2024 | Statistics engine must be parameterized by spatial unit from the start |
| D5 | Multi-country from day 1 | Every path, table and manifest carries `country` + `collection` |
| D6 | Local execution for now | No cloud services, no managed databases |
| D7 | Statistics and panel cover the **MapBiomas extent** (measured 1,086,079 km²), always labelled as such | No boundary mask and no ADM0 dependency; every area figure carries the label and a boundary note |
| D8 | **A single FastAPI service serves everything**: tiles, statistics, and the future H3 layer and study catalog | The viewer is no longer a set of static files; it needs the service running. Frontend data access stays behind one module so the API surface can still change cheaply |

## 4. Domain correction (binding for all artifacts)

The rasters are **land cover and land use** (`cobertura y uso del suelo`), **not soil
classification**. All artifact names, UI copy, table columns and docs must say
coverage/cover/use. This is a correctness issue, not a naming preference.

## 5. Inputs (verified)

| Input | Role |
|---|---|
| `data/raw/venezuela/collection-3/coverage-venezuela_classification_1985..2024.tif` (40 files, 2.9 GB) | Source rasters. EPSG:4326, 30 m, Byte, 57605×45000, nodata=0, **no overviews** |
| `data/legend/source/MB-Venezuela-Col-3-Legend-Code.pdf` | **Authoritative** legend: class hierarchy (level 1 + level 2), names ES/EN, hex colors |
| `data/legend/source/QGIS_Leyenda_col3.qml` | QGIS paletted style. Color source of truth **only where it agrees with the PDF** |

Known PDF vs QML color conflicts to preserve as documented discrepancies:
class 9 (`#7a6c00` vs `#7a5900`), class 12 (`#d6bc74` vs `#b8af4f`),
class 27 (`#ffffff` vs `#d5d5e5`).

### 5.1 Measured extent (decision D7)

The raster does **not** cover Venezuela as internationally recognized. Measured with
row-wise geodesic areas (authalic radius 6,371,007.181 m) over the 1/8 overview of
2024:

| Measurement | Value |
|---|---|
| Valid area in the raster (2024) | **1,086,079 km²** |
| Internationally recognized Venezuela | 916,445 km² |
| Excess | **+169,634 km² (+18.5 %)** |
| Area east of lon −59.8 | 103,014 km² (9.5 % of the total) |
| Claimed Guayana Esequiba, for scale | ~159,500 km² |

The excess is the disputed Guayana Esequiba plus border slivers of Colombia and
Guyana. Including or excluding that territory is a territorial stance, not a
technical choice. D7 records the user's decision: publish the MapBiomas extent,
precisely labelled, with no mask.

**Binding consequence for T4 and T8**: no area figure may be published without the
label `extensión MapBiomas Venezuela` and a note that it exceeds recognized borders.
A panel reading "Venezuela: 24.9 % forest" over 1,086,079 km² is not Venezuela, and
a reviewer comparing against official figures will find 18.5 % more area.

Area must never be computed as `pixel_count × constant`. The rasters are in
EPSG:4326, so a constant per-pixel area is wrong by several percent across 12° of
latitude; areas are accumulated row by row.

## 6. Constraints (measured, not assumed)

- 4 CPU cores, 15 GB RAM (8 GB available), 297 GB free on `/home`.
- Plain GTiff without overviews: decimated 1/16 read = 6.7 s/year.
  After COG conversion: 0.19 s/year (**~35× faster**).
- COG conversion cost measured at 25.5 s/year, 94.5 MB output
  (`-of COG -co BLOCKSIZE=512 -co COMPRESS=ZSTD -co LEVEL=9 -co NUM_THREADS=ALL_CPUS`).
  COG driver builds internal overviews itself; `gdaladdo` is not needed.
- 2.9 GB of raw rasters must never enter Git. Small derived tables (KB) are versioned.

## 7. Tasks

Each task closes with one work-unit commit and observed evidence.

### T1 — Scaffold, Git hygiene and branch
- Multi-country directory layout; `.gitignore` for raw/COG rasters.
- Branch `feat/plataforma-cobertura-ve` (repository has no commits yet: unborn HEAD).
- **Evidence**: `git status` clean of data; tree listing.

### T2 — Machine-readable codebook
- Derive `legend.json` + `legend.csv` from the PDF, cross-checked against the QML.
- Level 1 (6 groups) + level 2 (25 classes), names ES/EN, colors, documentation of
  the 3 color discrepancies.
- **Evidence**: JSON validates, 25 classes, colors match PDF, diff test vs QML.

### T3 — COG normalization + integrity manifest — **DONE**

- All 40 rasters converted to COG with 7 internal overview levels
  (2, 4, 8, 16, 32, 64, 128), ZSTD, 512×512 blocks, nodata preserved.
- Versioned manifest with source and output SHA-256 for every year:
  `data/derived/venezuela/collection-3/cog-manifest.json` (deliberately outside the
  gitignored `data/cog/`, so the checksums survive as reproducibility evidence).
- **Evidence**: 40/40 converted, 0 failed, years 1985–2024 with no gaps, 40 distinct
  input and 40 distinct output SHA-256, 4.44 GB of COG output, uniform creation
  options across all years. Integrity check compared 8 full-resolution 2048² windows
  per year against the source: 320 windows, **0 differing pixels** (~1.34 × 10⁹
  pixels compared exactly).
- **Measured speed-up**: decimated 1/16 read went from 6.7 s (raw) to 0.19 s (COG).

**Caveat on `class_set_sampled`**: this manifest field is sampled at 1/8 and
under-reports rare classes. It shows class 34 absent in 2023–2024, yet the
independent verification found 18 full-resolution class-34 pixels in 2024. Any claim
about rare classes must come from full-resolution counts (T5), never from this field.

**Resolved in T4/T5**: at native resolution class 34 is present in **all 40 years**
and declines monotonically from 989 to 18 pixels. The "legend drift" hypothesis
recorded in this document was **wrong**: it was an artifact of this sampled field,
not a change in the legend. The only genuine legend observation is that class 27
(`No observado`) never appears, because the data encodes non-observed as nodata 0.

**Independent verification (PASS)**: delegated to `gentle-ai-verify`, which refused to
take the tool's own reasoning as evidence and built a discriminating control — the
same window written twice as COG, once with NEAREST and once with AVERAGE. The
AVERAGE control fabricates 54 class codes that do not exist in the source, including
the forbidden aggregator ids `[10, 14, 22]`, with share errors up to +2879 %
relative. The NEAREST control fabricates 0. The COG under test, over 2,592,225,000
native pixels: **0 fabricated classes**, maximum absolute share deviation 0.0017 pp,
sampling rate 0.015624 against an exact 1/64. The pyramid is NEAREST with no
ambiguity.

### T4 — Composition statistics — **DONE**

- `tools/composition_stats.py` counts class pixels **exactly at native resolution**
  (never sampled, never read from overviews) and computes area with row-wise geodesic
  strips `R²·Δλ·(sin φ_top − sin φ_bot)` on the WGS84 authalic radius, derived from
  each file's own geotransform. A constant per-pixel area would be wrong by several
  percent across 12° of latitude.
- Counting uses one vectorised `bincount` per row block on a `row·256 + class` key,
  which keeps peak RSS at 567 MB instead of holding a 2.59 GB array.
- Versioned outputs (180 KB total) in
  `data/derived/venezuela/collection-3/composition/`:
  `composition-level1-…csv`, `composition-level2-…csv`,
  `composition-summary-…json`.
- **Evidence**: 40/40 years, 1504 s wall clock, peak RSS 567 MB, no errors. Read back
  from the CSVs independently of the tool: level-2 vs level-1 sums differ by **0
  pixels** and 3×10⁻⁶ ha of area; CSV totals match the JSON's `valid_area_ha` to
  0.000000 km²; class areas plus nodata equal the total extent at machine precision.
- **Area (D7 extent)**: valid **1,086,229.52 km²**, nodata **1,221,860.96 km²**,
  total 2,308,090.47 km² — stable across all 40 years.
- **D7 labelling**: `extent_label` and `boundary_note` sit at the top level of the
  summary JSON, so no consumer can miss them.
- **Cross-check**: class 34 in 2024 = **exactly 18 pixels**, matching the independent
  verifier's native-resolution count. The counting logic is corroborated by a second
  implementation.
- Dominant-class trend 1985 → 2024: Bosque 60,574,929 → 57,645,738 ha (−4.84 %),
  Uso agropecuario 16,270,004 → 19,208,278 ha (+18.06 %), Sabana/Herbazal
  9,698,373 → 8,743,380 ha (−9.85 %).
- **Glacier series (class 34, native pixels)**: 1985 **989** · 1990 643 · 2000 299 ·
  2012 101 · 2020 44 · 2024 **18**. Only two upward steps in 40 years (+0 and +1
  pixel); everything else is decline.
- **Schema smell, follow-up**: the summary JSON keys years at the top level
  (`"1985": {…}`) next to metadata keys, mixing namespaces for consumers. It should
  be nested under `per_year` in a later pass.

### T5 — Data integrity validation — **DONE**

- Class 34 (Glaciar) series — **resolved in T4**: present in all 40 years at native
  resolution, monotonic decline 989 → 18 pixels. The "class 34 disappears by 2024"
  legend-drift hypothesis is **refuted**; it was a 1/8 sampling artifact.
- Class 27 (`No observado`) vs nodata=0 semantics — **resolved in T4**: class 27 has
  exactly 0 pixels in every year. The data encodes "not observed" as nodata 0, which
  therefore conflates "outside the mapped extent" with "not observed". The summary
  JSON keeps nodata area in its own field, never merged into a class.
- Class 33 (Río, lago u océano) growth — **investigated in T5, see section 13**.
  Verdict: the largest individual gains are real infrastructure, externally
  corroborated; the remaining majority of the gain is unexplained and must not be
  attributed to a cause yet.
- **Evidence**: section 13 below.

### T6 — Reusable statistics engine (shape for F3) — **DONE**

- `tools/spatial_units.py` is the single source of truth for the spatial partition and
  for row-wise geodesic area. `compute_row_areas_m2` and `AUTHALIC_RADIUS_M` live only
  here; `composition_stats.py` imports them instead of defining them.
- `SpatialUnit` is the interface a future H3 implementation must satisfy: `name`,
  `describe()`, `unit_count`, per-block pixel-to-unit assignment with an `OUTSIDE_UNIT`
  sentinel, per-block per-unit areas, and stable `unit_ids`.
- `ExtentUnit` reproduces the committed behaviour: one unit, the whole raster.
- `H3Unit` is **declared but not implemented** and fails loudly, naming phase F3 and
  decision D4. `--unit h3` exits 1 with that message and writes no files. A stub that
  returned plausible-but-wrong numbers would be worse than no stub.
- `tools/priority_schema.py` encodes D3 and D2 as **mechanical invariants** in
  `__post_init__`, not as comments: weights must be finite and non-negative, term keys
  unique, and a disabled term must carry weight 0.0. Verified by construction: five
  violation cases (disabled with non-zero weight, negative, NaN, infinite, empty key)
  are all rejected. The shipped schema is `change_magnitude` 0.4,
  `transition_rarity_irreversibility` 0.4, `study_gap` **0.0 disabled**, `accessibility`
  0.2, and the study-gap rationale names D2.
- **Evidence, full 40-year regression** (the parent ran it, not the writer):
  1488 s, peak RSS 623 MB, 40/40 years. The level-1 CSV is **byte-identical** to the
  committed fixture (same SHA-256 `70a6e95f…`). The JSON matches the fixture on every
  numeric field for all 40 years with **0 differences**, plus two new fields
  (`spatial_unit`, `spatial_unit_metadata`) and the D7 labels preserved unchanged.
- **One quantified exception, stated rather than hidden**: the level-2 CSV differs from
  the fixture on exactly **1 row out of 1040**, in the last printed digit of `area_ha`
  (265812.097677 → 265812.097678 for year 2002, pixel_id 81). That is 1e-6 ha =
  0.01 m², a relative difference of 3.8e-15, which is float64 accumulation-order noise
  from the refactor. Pixel counts, share values and row order are all identical, and the
  internal assertion chain still passes at machine precision. This is evidence of
  numerical stability, not of a defect — but it is not a clean byte-for-byte pass and
  must not be reported as one. A future strict regression check must allow a 1e-6 ha
  tolerance on `area_ha`.
- **Deviation recorded**: `AUTHALIC_RADIUS_M` and a structurally similar geodesic area
  function remain duplicated in `tools/class_change_probe.py`, which was outside this
  task's allowed edit surfaces. The two operate on different abstractions (raster row
  versus configurable cell grid) and are not interchangeable today. Converging them is
  follow-up work, listed in section 14.

### T7 — Static tile pyramid — **DONE**

- `tools/build_tiles.py` builds a per-year XYZ raster pyramid in Web Mercator for all 40
years, using the official palette taken from the codebook. A paletted VRT carries the
256-entry colour table with alpha 0 for every index that is not a codebook `pixel_id`;
it is expanded to an RGBA VRT and tiled with
`-p mercator -r near --xyz -x -w none`. Both VRTs reference the COG and copy no raster
data, so colouring 2.6 GB per year costs nothing in storage.
- `-r near` is the correctness requirement established in T3: these are class codes,
and the gdal2tiles default of `average` would invent classes.
- **Storage estimate first, as the task required.** Measured per zoom on 2024 before
any full run: z0-6 19 tiles, z7-8 103, z9-10 1,110, z11 3,185, z12 12,147. That gave
15,332 tiles and 141 MB per year, so 613,280 tiles and 5.5 GB for 40 years, and the
feasibility verdict that no zoom cap and no dynamic tile server were needed.
- **Actual result**: **16,565 tiles and ~120 MB per year; 662,600 tiles and 4,987 MB of
PNG content (6.1 GB on disk with block padding) for the 40 years.** Wall clock
140-164 s per year, about 110 minutes in total across two runs.
- **My estimate was 8 % low and I know why**: the per-zoom measurements were right, but
my own summary step printed 15,332 instead of the correct 16,564 per-year sum. An
arithmetic slip in the reporting, not in the data. The feasibility conclusion held; the
number did not, and it is corrected here.
- **Independent structural verifications**, all read back from disk rather than trusted:
  - Every one of the 40 years has exactly 16,565 tiles, 13 zoom levels and tile counts
    per zoom identical to every other year.
  - The sorted tile path set is byte-identical across years: one single hash for all of
    them, so the pyramid geometry is stable year to year.
  - All **662,600 PNGs verified** for non-zero size, PNG signature and trailing `IEND`:
    **0 zero-byte, 0 malformed**.
  - Palette spot-check on 9 tiles across z8, z10 and z12: **zero colours outside the
    official palette**, and the classes present are real (3 Bosque, 4 Sabana arbolada,
    6 Bosque inundable, 11, 12, 13, 18, 21, 23, 24, 25, 29, 33, 66, 81). The tiles render
    the official classes with the official colours.
- The manifest records the codebook path and its SHA-256, so a palette change is
  detectable after the fact, plus the D7 labels at the top level.

**Two real gaps the interruption exposed, both fixed rather than papered over.** The
machine rebooted mid-build after 13 years, and recovery was run for the remaining 27:

1. **The manifest described the run, not the pyramid.** After the recovery run the
   manifest covered 27 years and the first 13 had no record at all. Fixed by adding
   `--scan-only`, which rebuilds the manifest from what is on disk and needs no COG
   directory. The real manifest now covers all 40 years.
2. **Tile integrity was counted, never verified.** The reboot left exactly one truncated
   tile: `1998/12/1326/1984.png`, 0 bytes. It was found by hand, and that is the problem,
   because `--resume` passes `-e` to gdal2tiles and `-e` skips files that already exist:
   **that empty tile would have been preserved silently forever**. Fixed by verifying
   every PNG in both modes and exiting non-zero on any malformed or zero-byte tile, while
   still writing the manifest so an operator can inspect what failed. The check was proven
   to fire on a deliberately broken scratch pyramid (`exit 1`,
   `integrity=BROKEN(zero=1, malformed=2)`).

### T8 — Viewer

Split into three slices so each review candidate stays reviewable. Decision D8 settled the
architecture: one FastAPI service for everything.

#### T8a — Map, year slider, legend — **DONE**

- `tools/serve_viewer.py`: FastAPI app. `GET /api/health` (diagnosable paths), `GET /api/meta`
  (built by reading the tiles manifest and the codebook, never duplicating their content in
  code: 40 years, zoom range, legend, D7 labels verbatim, and the extent bbox derived from the
  source COG's own geotransform), and `GET /tiles/{year}/{z}/{x}/{y}.png`.
- The tile route validates the year against the manifest, the zoom against the reported range,
  and x/y against the grid for that zoom; returns 404 for anything absent (transparent tiles are
  excluded by `-x` by design, and the client relies on 404), sets an immutable long-lived
  `Cache-Control`, and builds the path from validated integers so **path traversal is impossible**.
- `viewer/`: a MapLibre GL raster map fitted to the extent, a year slider over the 40 years, a
  hierarchical legend from `/api/meta` with the official colours, and the **D7 labelling always
  on screen** rather than behind a hover or a modal. MapLibre GL 5.6.2 is vendored under
  `viewer/vendor/` with its version recorded and its BSD-3-Clause licence kept alongside, so the
  viewer works offline with no CDN. All data access goes through `viewer/api.js`; it is the only
  file in the frontend with a `fetch` call.
- **Evidence, from a real browser** (the parent verified this; the writing agent had no browser
  and said so rather than implying success): the page loads with **zero console errors**, the map
  paints with the official palette, the legend renders 6 groups and 26 classes, the D7 label and
  boundary note are visible, and the slider switches years — the year label updates and tiles for
  the new year load with 200s, with a visibly different classification pattern between 2024 and
  1985.
- **One real defect was found in the browser and fixed before commit**: `onYearChanged` called
  `RasterTileSource.setTiles()` synchronously from inside a MapLibre event fired during `_render`,
  producing an `AbortError` on the initial load. It is now deferred through a coalesced
  `requestAnimationFrame`. Verified in the browser after the fix: reload shows zero console
  errors, and a burst of four rapid slider moves (1990, 2000, 2010, 1995) issued **zero tile
  requests for the intermediate years** and settled on 1995 — the coalescing holds in a real
  browser, not just in the agent's stubbed scheduling test.
- **Measured tile throughput, and the review finding this measurement exposed.** The first
  measurement — about 81 tiles/s via curl and 267 tiles/s via a Python client — was reported
  here as "adequate for local single-user use". That was the wrong standard: it reported the
  number without asking why it was not higher, for 662,600 static files served by Python. The
  native review did ask, and found the answer.
- **Review outcome: one CRITICAL finding, candidate-caused and deterministic.**
  `R3-SERVE-VIEWER-NO-CACHE-RELOAD` (reliability, `tools/serve_viewer.py:587-592`,
  `causal_disposition: introduced`, `evidence_class: deterministic`): `serve_tile` called
  `_load_manifest()` twice per request without caching the parsed JSON, so every single tile
  request re-read and re-parsed the manifest. The claim was verified with a controlled
  experiment rather than accepted: wrapping `_load_manifest` with a counter and serving 200
  tiles produced **exactly 400 calls, 2.0 per tile**.
- **Correction applied and measured**: the manifest and the codebook are now parsed once at
  module import and the routes read the parsed values. 23 diff lines, the exact size declared
  to the review against its bound of 200.

| Measurement | Before | After |
|---|---|---|
| `_load_manifest` calls while serving 200 tiles | **400** (2.0 per tile) | **0** |
| Throughput | ~303 tiles/s | **~440-460 tiles/s** |

The improvement is attributed, not merely correlated: it comes from removing those reads.
Behaviour was verified unchanged after the correction — an existing tile returns 200 with
`image/png` and an immutable `Cache-Control` and bytes identical to the file on disk; absent
tiles, out-of-range year and zoom, and path traversal all return 404; a non-integer parameter
returns 422; and `/api/meta` still reports 40 years, 6 groups, 26 classes and the verbatim D7
labels. A missing or malformed manifest now stops the service at import with a clear message
instead of degrading per request.

**Pending, and stated rather than hidden: the provider's targeted validation did not run.**
After the correction plan was accepted (`correction_lines: 23`), the review offered a
`provider_targeted_validator` slot, and every submission of that binding was refused as
"unknown, expired, or belongs to a different session route" — including a binding taken from
STATUS seconds earlier, so it is not a timing expiry but a route the capture facade does not
accept. T8a is therefore committed **with the correction verified by direct measurement and
without the validator's verdict**. That is a real gap: the measurement proves the defect is
gone and the behaviour is intact, but it is not the provider's independent confirmation that
the correction addresses exactly the frozen finding. The lineage
`review-59e2128a5b76f2a7` is left in `correction_required` and must not be resumed.

#### T8b — Composition panel — **DONE**

- `tools/serve_viewer.py` gained `GET /api/composition/series` (the 40-year series per level-1
group, with parallel `area_ha` and `share_pct` arrays aligned to the year list, plus the per-year
total) and `GET /api/composition/year/{year}` (the level-2 breakdown sorted by area descending,
404 for an unknown year). A diagnostic `GET /api/composition/_load_counters` was added and kept:
it is what makes the cache invariant measurable.
- The panel **serves the committed CSV values verbatim and recomputes nothing**, which is the only
way to guarantee the acceptance requirement that the panel cannot disagree with T4. The CSVs are
parsed **once at import**, applying the lesson of the CRITICAL finding from T8a before it could
repeat: instrumented counters read 1/1 before and after 50 requests, so zero parsing happens while
serving.
- The import-time consistency check fails loudly on a missing, malformed or mutually inconsistent
CSV pair: it verifies both CSVs cover the same years, that the level-1 and level-2 area sums agree
per year within 1e-3 ha, and that every class exists in the codebook. Verified by firing it with
malformed fixtures under /tmp, each stopping the service with a specific message.
- `viewer/panel.js` renders the **stacked area chart by hand as SVG** — 6 groups, y axis in share
of the valid extent, a cursor line that follows the slider, and click-to-select-year — plus the
level-2 bar breakdown for the selected year. No charting dependency was added and no second
library was vendored, so the frontend still has exactly one external dependency.

**The panel's figures match T4 exactly**, checked against the committed CSVs rather than against
the API alone. Four independent figures, all identical:

| Figure | Panel / API | Committed CSV |
|---|---|---|
| Formaciones boscosas 2024 | 65,511,997.353565 ha, 60.311377 % | identical |
| Formaciones boscosas 2000 (checked live after moving the slider) | 67,262,900.715957 ha, 61.923285 % | identical |
| Total level-1 1985 | 108,622,958.308388 ha | identical |
| Top class 2024 | Bosque 57,645,737.503857 ha, 53.069574 % | identical |

The 26 level-2 classes sum to the year total shown in the panel's "Suma del año" row
(108,622,951.648748 ha for 2024), which is itself the T4 total.

**Two layout defects were found in the browser and fixed, both by measurement rather than by
sight.** Neither could have been caught by the agent's stubbed-DOM smoke test, because a stubbed
DOM performs no layout:

1. **The map collapsed to zero width.** The body grid computed four tracks
   (`320px 0px 0px 722px`) and `section.map-panel` landed in a `0px` track, so the map rendered at
   0 x 32 px: the primary element of the application was invisible. Fixed by a named-area grid of
   2 columns by 4 rows with the composition panel in its own full-width row below the map, so the
   map cannot share a row with a fixed-width sibling.
2. **The panel then trapped its own content.** The first fix capped the panel with
   `max-height: min(45vh, 360px)` to protect the map row, which left a 360 px box holding
   **2692 px** of content: only **43 %** of the 652 px chart was visible and the level-2 breakdown
   was entirely below an inner scrollbar. Fixed by removing the cap and giving the map its own
   deterministic `height: clamp(260px, 50vh, 720px)`, so the **document scrolls instead of the
   panel**.

**Verified in a real browser at both viewports after the fixes**: map 400 px tall at 1280x800 and
285 px at 1042x569, matching the CSS prediction exactly; the MapLibre canvas matches its container
in both cases, so the resize hook works; the panel clips nothing internally; the page scrolls; and
scrolling reveals the whole chart and the breakdown.

**Known cosmetic noise, already recorded in section 14.3**: the larger map requests more tiles and
legitimately 404s on the transparent ones, so the browser console collects those 404s. That is
correct behaviour and must not become a 200, because the map client relies on 404 meaning "no
tile". The count grows with map size, which is why it is only visible now.

**Review outcome: one CRITICAL finding, corrected.** The provider classified this candidate as
**medium risk with a single lens** (`review-reliability`) rather than the four-lens treatment the
previous viewer candidate received, and that lens found `R3-PANEL-DOM-ID-MISMATCH`
(`viewer/panel.js:76`, `severity: CRITICAL`, `causal_disposition: introduced`,
`evidence_class: deterministic`): the panel selected its breakdown container by the id
`panel-breakdown`, which the HTML does not define — the real ids are `panel-breakdown-title`,
`panel-breakdown-empty` and `panel-breakdown-list`. The variable was therefore permanently null.

Worth stating plainly: the reviewer itself noted that rendering still worked, because the render
path uses `breakdownList`, which is selected correctly. So this was **not a functional defect** —
verified by hand: `breakdownRoot` was declared once and assigned once and **never read anywhere**,
pure dead code with a wrong selector. The correction removes it, 2 diff lines, exactly the size
declared to the review against its bound of 200. The severity classification is stronger than the
impact; what justified acting on it is that an unguarded null DOM reference is a trap for the next
edit, and the review only permits correcting findings it classifies as severe.

**The provider's targeted validation did not run, again.** After the correction plan was accepted
(`correction_lines: 2`), the review offered a fresh `provider_targeted_validator` slot and that
submission was refused as "unknown, expired, or belongs to a different session route" — the same
refusal T8a hit, now reproduced on a second lineage with a fresh binding. That rules out timing
and makes it a route the capture facade does not accept. T8b is therefore committed with the
correction verified by direct inspection and without the validator's verdict. The lineage
`review-45224636976d13ae` stays in `correction_required` and must not be resumed.

#### T8c — Clip statistics — **DONE**

- `GET /api/clip-stats?bbox=west,south,east,north&year=<int>` reads **only the drawn window** at
  native resolution, streamed in row blocks, and returns the level-1 and level-2 composition for
  that area with the D7 labelling attached. It **imports** `compute_row_areas_m2` from
  `tools/spatial_units.py` rather than writing another geodesic formula, so the single source of
  truth from T6 holds.
- **The acceptance test that matters passes.** A clip whose rectangle is the full raster extent
  reproduces the published composition: level-1 worst difference **2.66e-7 ha**, level-2 worst
  **4.64e-7 ha**, and the valid area 108,622,951.64874808 against the CSV's 108,622,951.648748, a
  difference of **8.9e-8 ha**. Over 108.6 million hectares that is a relative error of ~2.7e-15,
  float64 noise. The windowed computation **is** the same computation as the published one, which
  is the strongest available proof and was the point of this slice.
- Latency measured by the parent at three sizes: **10 ms** for ~15x15 km, **34 ms** for ~62x62 km,
  **246 ms** for ~177x177 km. Interactive with room to spare.
- Class 27 (`No observado`) is absent from the clip response because it has zero pixels everywhere;
  the CSV emits it as a zero row for schema stability while the clip omits it. Noted as a small
  inconsistency, not a defect.

**Three defects were found and fixed, two of them by the parent in a real browser.**

1. **Dragging panned the map instead of drawing.** `setDrawMode()` changed the cursor to
   `crosshair` but never disabled MapLibre's competing handlers; `dragPan` did not appear anywhere
   in the file. During a pan the geographic point under the cursor is invariant, so the mousedown
   and mouseup lngLat were identical and the rectangle collapsed to a point. Measured proof: two
   drags at nearly the same screen position produced longitudes of -72.49 and then -85.20, and a
   30-pixel shift cannot move a longitude 12.7 degrees, so the map itself had moved. Fixed by saving
   each handler's `isEnabled()` state on entering draw mode, disabling `dragPan`, `boxZoom` and
   `dragRotate`, and **restoring the saved state** on exit rather than blindly re-enabling.
2. **The degenerate-rectangle guard could never fire.** `bboxFromCorners` rejected a rectangle only
   when `east - west <= 0`, but a pan-induced point differs by about 7e-12 degrees, which is greater
   than zero, so the guard passed and the endpoint was called with a sub-micron rectangle that the
   server correctly rejected with 400. Fixed by comparing the **screen** space start and end points
   from the mouse events with a 5-pixel threshold, which is zoom-independent.
3. **The clip's share denominator was mislabelled.** The rows read "92.08 % de la extensión
   válida", but a clip's shares are of the **selected area's** valid extent, not the whole mapped
   extent — every percentage on screen had the wrong denominator named. Fixed with a
   `denominatorLabel` option, so a clip now reads "de la zona seleccionada" while the year breakdown
   keeps "de la extensión válida".

**Also corrected: the oversized-window bound was unreachable.** The tool shipped
`CLIP_STATS_MAX_PIXELS = 2_700_000_000`, just above the shipped raster's 2,592,225,000 pixels, while
its own docstring claimed 36 M. With that value the guard could never fire for any real request,
and a full-extent clip blocked the single worker for **18.7 s**. The parent corrected it to the
documented 36 M, which keeps the worst case at ~250 ms. Whole-extent audits belong to the
composition endpoints, which serve the published figures without a windowed read.

**Verified in a real browser after the fixes**: the drag produces a real bbox (1.55x0.43 degrees
over Venezuela) with the map not moving and exactly one request; the panel renders the clip's own
figures, identical to the API (Bosque 761,454.108851 ha at 92.08 %, window total 826,962.841697 ha);
a click with no movement fires **no** request and shows "Rectángulo demasiado pequeño"; and leaving
draw mode restores panning. Guards verified: 400 for an inverted, outside or malformed bbox, 404 for
an unknown year, 413 for an oversized window with a message naming the bound.

### T9 — Local packaging and documentation — **DONE**

- `run.sh` is the single entrypoint: `check` (what is present, what is missing and the exact
  command that produces it, separating what is needed to **serve** from what is needed only to
  **rebuild**), `pipeline` (the four stages in order, skipping the ones whose outputs exist, with
  `--force` and `--dry-run`), and `serve` (builds the environment, then starts uvicorn).
- `README.md` covers what the platform is, the mandatory labelling, and prominently that the data
  is **not** in the repository, plus the quickstart, the measured stage costs, what the viewer
  shows, a Dokploy deployment section, the behaviours that look like bugs but are not,
  multi-country, measured performance, the licence and attribution, and a limitations section.
- `Dockerfile` builds a 108 MB serve-only image, and `docker-compose.yml` is ready for Dokploy:
  external `dokploy-network`, no published ports because Traefik reaches the container over that
  network, the domain configured in the Domains tab, and only the two large data subdirectories
  mounted so the tracked metadata inside the image is not shadowed.

**Evidence, and this is the strongest part of the task, because the packaging work found five real
defects that nothing else had found.**

A real clone, reproduced with `git archive HEAD` plus the four new files, which is exactly what a
clone would contain: `check` exits 1 with a precise list (COG directory, tiles pyramid and viewer
dependencies missing as serving prerequisites, raw rasters as rebuild-only) and prints the symlink
recipe. With the data symlinked it reports only the missing environment. With `serve` run from
nothing, the clone **created its own environment, installed the 21 pinned packages and started in
10 s**, serving `/api/health`, `/api/meta`, a tile and the clip endpoint, with the clip returning
**826,962.8 ha over 11 classes, identical to the locally verified value**. `check` then exits 0.
`pipeline --dry-run` prints the commands for the stages whose inputs are missing and exits 0, and
`pipeline` skips all four stages in 1 s. The image builds in 40 s and, run with the compose's exact
volume layout, serves the same four endpoints with the same clip numbers.

**The five defects the packaging exposed:**

1. **`run.sh check` started a server and would have launched the whole pipeline.** Two log lines
   used backticks inside double-quoted strings, and in bash those are command substitution, so the
   message text `./run.sh serve` and `./run.sh pipeline` were executed. Observed as a hang killed
   with exit 137.
2. **`run.sh serve` could never work on a fresh clone.** It ran the prerequisites check, which
   requires the Python environment, *before* creating it, so every clean clone failed on the very
   thing the command was about to build. Reordered: build the environment, then verify.
3. **`set -euo pipefail` plus `n=$(find "$dir" ... | wc -l)` aborted the pipeline on a fresh
   clone.** When the directory does not exist `find` exits non-zero, `pipefail` fails the whole
   assignment and `set -e` kills the script, in the exact scenario the packaging exists for.
   Replaced with one `count_files` helper, which removes the class of bug rather than the two
   instances that happened to be reachable.
4. **`viewer/requirements.txt` omitted rasterio while claiming the opposite.** The file stated that
   the service pulls in no GDAL, rasterio or Pillow, but the clip endpoint imports rasterio
   lazily. The installed environment happened to have it, so everything worked locally while a
   clean install would serve the map, the legend and the composition panel normally and then fail
   on the first drawn rectangle. Now pinned, with the reason recorded.
5. **The image built fine and its clip endpoint failed at runtime.** rasterio's wheel links
   dynamically against `libexpat`, absent from `python:3.13-slim`, so the container returned 503
   with `libexpat.so.1: cannot open shared object file`. Found **only because the container was run
   rather than merely built**, which is why the packaging test runs it.

**A limitation this work established rather than assumed**: the container serves but cannot
rebuild, because every pipeline tool imports `from osgeo import gdal` and rasterio's wheels do not
provide the GDAL Python bindings. Regeneration therefore runs where GDAL is installed and the
result is synced. Serving needs no system GDAL.

#### Original task statement (kept for the record)

- Reproducible entrypoint (script/container) + README.
- License/attribution section left as an explicit **unresolved** placeholder.
- **Evidence**: clean-clone-to-running instructions executed once.

### T10 — Anchor the composition-summary schema — **DONE**

Raised by the `a48cb6c` review, which escalated with `R3-missing-coverage-v2-shape` (CRITICAL,
causality unknown): the v2 shape change recorded as resolved in 14.3 had no assertion anchoring
it, so flattening the years back to the top level, or dropping `schema_version`, would satisfy
every existing check.

- `tests/test_composition_summary_schema.py`, **stdlib `unittest` only**. The repository has no
test suite and no pytest, and adding a test dependency to close a coverage finding would trade one
gap for another. It runs under the **system** interpreter, because `tools/composition_stats.py`
imports `from osgeo import gdal` at module level and the pinned `.venv` has no GDAL.
- The test **drives the real writer** (`write_outputs`) with synthetic `YearTotals`, a minimal
  codebook, an `ExtentUnit` and a temporary output directory. It reads no raster and modifies no
  production code, so it adds no unreviewed production surface.
- Assertions: `schema_version == 2`; every `per_year` key is a four-digit year string and the
  `per_year` key set equals the reported `years` list; **no year key survives at the top level**;
  the per-year payload keeps its v1 field set; and `per_year` is an object, not a list.
- **Discriminating control, not optional** (the T3 lesson): the test includes cases that fail on a
  deliberately flattened or dropped-version summary, so it proves it can separate v2 from v1
  instead of merely passing over the current output.
- **Evidence**. 22 tests, all passing, in 0.002 s: `python3 -m unittest discover -s tests -v`
  reports `Ran 22 tests` then `OK`. Seven assert the contract against output produced by the real
  `write_outputs`; fifteen are controls, and each one pins the specific assertion it exercises with
  `assertRaisesRegex` rather than a bare `assertRaises`.
- **The first version of this test was wrong, and building the control is what caught it.** The
  initial control set used bare `assertRaises`, and its "flattened v1 summary" case was rejected by
  the missing-version check long before reaching the year-leak check. So the assertion this file
  exists for — that no year key survives at the top level — was never exercised: the suite was
  green and the regression was unguarded. Rewritten with `assertRaisesRegex`, the leak check now has
  two dedicated controls, one of them a summary valid in every other respect so that nothing else
  can reject it. This is the T3 lesson repeating itself: a check that has not been shown able to
  fail is not a check.
- **Verified against the real committed artifact, not only the synthetic fixture.** The committed
  `composition-summary-venezuela-collection-3.json` (40 years, `schema_version` 2, zero top-level
  year keys) satisfies the contract, and a copy of that same real summary with the years duplicated
  at the top level **and `schema_version` left intact** is rejected with
  `year keys leaked to the top level: ['1985', '1986', '1987', ...]`. That is the regression the
  finding named, demonstrated on the artifact that ships rather than on a toy.
- The test is written by the parent, not delegated: the writer route failed twice at launch and no
  native `Agent` fallback exists in this session. The deviation is recorded in 10.4.
- **Review outcome: approved with zero findings.** Lineage `review-d8600f6081945214`, tier
  `medium` with the single consolidated lens the provider selects for an executable change
  (`review-reliability`), 580 changed lines across three paths, **one** model run, state
  **approved**, authority **burned** (`gentle-ai.review-acknowledged/v1`). The provider returned no
  advisory findings at all, which makes this the first candidate in the feature to close clean.
  Note the ordering: the review ran **after** `b1905c7` was committed, so this paragraph is a later
  documentation-only commit. The reviewed artifact is byte-identical and its receipt stands; the
  paragraph records the outcome rather than changing the candidate.

## 8. Open items (blocking, not yet resolved)

| # | Item | Blocks |
|---|---|---|
| O1 | License and attribution terms for MapBiomas data | Publication only. Left deliberately undefined for now |
| O2 | Final hosting target | Nothing yet (D6: local) |
| O3 | H3 term weights and "interesting zone" thresholds | F3 start |
| ~~O4~~ | ~~Host-side subagent launch defect (see section 10)~~ **RESOLVED** by restarting Pi; kept struck through so the record is not silently renumbered. The underlying finding stays documented in 10.1 in case it recurs | Nothing |

| O5 | Country name hardcoded in `run.sh:57`, which overrides the multi-country path expression on line 53. A D5 violation, found by the T9 review and labelled only as a readability WARNING. Detail and the reason it was not fixed in place: section 14.4 | Multi-country correctness of `run.sh`. Deferred by explicit user decision at the close of T9 |

The `external.select_base_ref` route recorded as a tool-surface gap in section 12.2 turned out not
to be a gap: the attempt was malformed and the route works (section 12.3). One genuine facade gap
remains, `review.capture-validation`, which is what blocks the T8a and T8b targeted validations.

## 9. Commit log (evidence)

| Task | Commit | Evidence |
|---|---|---|
| T1 | `7bd98a5` | 40 rasters relocated to `data/raw/venezuela/collection-3/`; `git check-ignore` confirms no `.tif` is ever tracked; branch `feat/plataforma-cobertura-ve` created from unborn HEAD; 8 paths committed |
| T2 | `71d94c1` | `tools/build_codebook.py` emits `data/legend/venezuela-collection-3.{json,csv}`: 6 level-1 groups, 26 classes, unique pixel ids, colors taken from the PDF, 9 PDF-vs-QGIS discrepancies recorded instead of silently resolved |
| T3 | `84e786f` | 40/40 COG converted, 0 failed, 320 integrity windows with 0 differing pixels, 4.44 GB output, versioned manifest with 80 checksums; independent NEAREST verification PASS with a discriminating AVERAGE control (see section 7/T3) |
| T4 | `5961577` | 40/40 years of exact native-resolution composition, 1504 s, peak RSS 567 MB; level-2 vs level-1 = 0 pixel difference; class 34 in 2024 = exactly 18 pixels, matching the independent verifier; valid area 1,086,229.52 km² with the D7 label at the top level of the summary JSON; glacier series 989 → 18 pixels. **Committed without lens review** — see section 12 |
| T5 | `ba6b55f` | `tools/class_change_probe.py` plus the class-33 probe: 2,123,147 pixels (189,001.33 ha) of net water gain, of which the top two clusters are step changes externally corroborated as Caruachi (2003) and Boconó–Tucupido (1990); only 19.4 % of the gain sits in the top 10 cells, so the majority is unexplained. See section 13 |
| T6 | `9b243b0` | `tools/spatial_units.py` (single source of truth for units and geodesic area), `tools/priority_schema.py` (D2 and D3 as mechanical invariants, study_gap disabled at weight 0.0), and `composition_stats.py` parameterized by `--unit`. Full 40-year regression: level-1 CSV byte-identical, JSON numerics identical across all 40 years, level-2 CSV differs on 1 of 1040 rows by 1e-6 ha (float64 accumulation noise, relative 3.8e-15) |
| T7 | `9672341` | `tools/build_tiles.py` plus the 40-year pyramid: 662,600 tiles, 4,987 MB of PNG content, ~110 min. Every year 16,565 tiles, identical path set and identical per-zoom counts across all 40 years; all 662,600 PNGs integrity-verified with 0 zero-byte and 0 malformed; palette spot-check found 0 colours outside the official table. The mid-build reboot exposed two tool gaps (run-scoped manifest, unverified tiles) and both were fixed |
| T8a | `5d42cff` | `tools/serve_viewer.py` plus `viewer/` with vendored MapLibre GL 5.6.2. Verified in a real browser: zero console errors, map paints, legend 6 groups and 26 classes, D7 label always visible, slider switches years with 200s and a visibly different pattern between 2024 and 1985, and a burst of rapid slider moves coalesces with zero wasted tile requests. One real `AbortError` found in the browser and fixed before commit. The native review then found a CRITICAL, deterministic, candidate-caused defect — the manifest re-read twice per tile — verified at exactly 400 calls per 200 tiles, corrected in 23 lines, and measured after the fix at 0 calls and ~440-460 tiles/s. Committed **without the provider's targeted validation**, which could not be submitted |
| T8b | `4588fa7` | `GET /api/composition/series` and `/api/composition/year/{year}` serving the committed CSV values verbatim, parsed once at import (counters 1/1 after 50 requests), with an import-time consistency check proven to fire on malformed fixtures; `viewer/panel.js` with a hand-rolled SVG stacked area chart and the level-2 year breakdown, no new dependency. Figures verified identical to the committed CSVs on four independent values including a live check after moving the slider. Two layout defects found in the browser and fixed by measurement: the map collapsed to 0 x 32 px, then the panel trapped 2692 px of content in a 360 px box. Both viewports re-measured after the fixes: map 400 px at 1280x800 and 285 px at 1042x569, canvas matching its container, page scrolls. Reviewed at medium risk with one lens, which found a CRITICAL dead-code DOM id mismatch, corrected in 2 lines. Committed **without the provider's targeted validation**, refused twice on two lineages |

| T8c | `9b90445` | `GET /api/clip-stats`, reading only the drawn window at native resolution and importing the geodesic area from `tools/spatial_units.py`. Acceptance test: a clip of the full extent reproduces the published composition, worst difference 2.66e-7 ha on level 1 against a 108.6 million ha total, a relative error of ~2.7e-15. Latency 10 / 34 / 246 ms for ~15x15, ~62x62 and ~177x177 km. Three defects found and fixed, two of them in a real browser: dragging panned the map because `dragPan` was never disabled, so the rectangle collapsed to a point; the degenerate guard could never fire because it compared floats with `<= 0`; and the clip's share denominator was mislabelled. An unreachable oversized-window bound was also corrected. Reviewed and approved with no findings |
| T9 | this commit | `run.sh`, `README.md`, `Dockerfile` and `docker-compose.yml` for Dokploy. Verified with a real clone: `check` fails precisely and prints the symlink recipe, `serve` builds its own environment from nothing and starts in 10 s, and health, meta, tile and clip all serve with clip numbers identical to local. The image builds in 40 s and serves the same four endpoints under the compose's volume layout. **The packaging work itself found five real defects**, described in the T9 section: backticks in log strings executing `serve` and `pipeline`; `serve` checking for the environment before creating it; a `find`-under-`pipefail` landmine aborting the pipeline on a fresh clone; rasterio missing from `requirements.txt` while the file claimed it was absent; and `libexpat` missing from the image, found only by running the container |
| T10 | this commit | `tests/test_composition_summary_schema.py`, closing `R3-missing-coverage-v2-shape` from the `a48cb6c` escalation, plus the section 12.3 record and the README correction. Evidence: 22 tests pass in 0.002 s under the system interpreter; the checker accepts the real committed 40-year summary and rejects a copy of it with the years duplicated at the top level while `schema_version` stays intact; the first version of the suite was green while leaving that very assertion unexercised, and the control is what caught it. This commit also records the T6 review payment (lineage `review-42afa5987aa5f681`, approved, authority burned) and the corrected base-ref route |

## 10. Deviation record: harness routing defect

Two host-level defects block delegated implementation in this session. Both are
recorded here rather than worked around, because working around them would trade a
visible block for a hidden one.

### 10.1 Subagent launch fails for every agent

Error returned on every launch attempt:

```
could not register launched worktree: Select an existing worktree in the same Git clone as this session.
```

| Attempt | Agent | Mode | Result |
|---|---|---|---|
| 1 | `gentle-ai-worker` | background | same error |
| 2 | `gentle-ai-worker` | background, after `session_worktree_register` | same error |
| 3 | `gentle-ai-worker` | task, explicit `workspace_root` | same error, thrown while building the request |
| 4 (probe) | `gentle-ai-explore` | task, trivial read-only prompt | same error |

Attempt 4 proves the fault is in the runtime, not in the writer role or in the
task description.

Ruled out with evidence:

- Git 2.47.3, which supports `--path-format=absolute`.
- Repository healthy: `git worktree list` is clean, HEAD `71d94c1`.
- Both commands the resolver runs work by hand: `git rev-parse --path-format=absolute
  --show-toplevel` and `--git-common-dir` return the right paths with exit 0.
- No `GIT_*` variables in the environment to redirect routing.
- `session_worktree_register` on the repository root reported success.

Probable cause, read from the package source but not confirmed: `lib/session-worktree-registry.ts:84`
throws that message when `this.identity` is undefined or when the resolved
`commonDir` differs. In `extensions/gentle-agents.ts:1060` the child target comes
from that same registry, so the registry used by the agent launcher does not hold
the repository identity that the manually invoked registration does. This is a host
configuration defect, not a property of this repository, and it cannot be fixed
from inside the agent: no native `Agent` fallback tool is available in this
session.

**RESOLVED** after the user restarted Pi. The next launch succeeded and
`gentle-ai-worker` wrote `tools/normalize_to_cog.py`. The defect is real but
transient: it depends on the host process state at launch time, so a restart is a
valid remedy and the finding stays recorded in case it recurs.

### 10.2 Direct parent writes are limited to one code file per feature

`tools/normalize_to_cog.py` was refused before mutation:

```
ODD multi-file write refused before mutation: direct edits already changed
tools/build_codebook.py. Delegate this additional file through subagent_run,
preferring gentle-ai-worker and then worker.
```

The guard was re-tested after the user asked whether the limit was per-turn. It is
not: the refusal persists across turns, so the parent may directly author exactly
one code file for this feature, and every further file requires the delegation that
10.1 makes impossible.

Deliberately rejected workaround: generating the 40 COGs with an ad-hoc shell loop.
That would evade the guard while leaving ~3.8 GB of derived data with no versioned,
reproducible script — less verifiable than the block itself, not more.

### 10.3 Consequence

10.1 is resolved; 10.2 still holds for the rest of the feature: the parent may
directly author exactly one code file, so every further code artifact must be
delegated to `gentle-ai-worker`. Verification artifacts that are executed rather
than versioned can be run as inline commands, but any check worth keeping must be
delegated as a file.

T3 closed with the delegation route working. Nothing was broken and no data was
harmed while blocked: T1 and T2 were already committed and the raw rasters were
untouched throughout.

**It recurred on 2026-10-08**, twice in a row. Two `gentle-ai-worker` launches for the T10 test
file both returned `failed` with **one turn, zero tool calls** and `assistant reported an error`,
so the fault is in the child's first model call or in the launch path rather than in the task
description. A malformed delegation is ruled out: the host validates the
`## Allowed edit surfaces` block before launching, and the first attempt was rejected for exactly
that reason and relaunched in the accepted form. A Pi restart is again the remedy this record
points to. The workaround actually used, and the deviation it represents, is in 10.4.

### 10.4 The parent wrote the T10 test inline, and that is a recorded deviation

The routing ladder says a new code file is delegated. With the writer route failing twice at launch
(10.1) and no native `Agent` fallback available in this session, the parent wrote
`tests/test_composition_summary_schema.py` directly rather than leaving the work undone. The host's
own multi-file write guard **accepted** it, so the fallback was permitted rather than evaded: no
shell heredoc, no redirection, the sanctioned file-writing tool, and the guard's refusal would have
been reported instead of routed around.

The deviation is recorded because the ladder exists for a reason. In this case the parent had
already paid the context cost the ladder protects against: the exact `write_outputs` signature, the
codebook keys the writer reads, and the pre-write assertions the synthetic input must satisfy were
all derived while probing the failure, and the contract was then verified empirically with a real
call before a line was written. That is a fallback of last resort, not a shortcut, and it should not
be read as licence to write code inline next time the writer is healthy.

## 11. Review findings backlog

The T3 review (lineage `review-d0e8dcb9c0cad2ba`) closed **approved** with 17 findings,
all `informational` and non-blocking: none opened a correction and none is a reason to
re-run that review. The closing envelope carried each finding's id, lens, location,
severity and disposition but **not its body text**, so the entries below are an index
of where to look, not a summary of what they say. Read the bodies from the native
store when the listed files are next touched.

WARNING level:

| Id | Lens | Location |
|---|---|---|
| `R2-caveat-contradicts-manifest` | readability | `odd/tasks/plataforma-cobertura-ve.md:121-124` |
| `R2-error-contract-unguarded` | readability | `tools/normalize_to_cog.py:206-260` |
| `R3-001` | reliability | `tools/normalize_to_cog.py:206` |
| `R3-002` | reliability | `tools/normalize_to_cog.py:309` |
| `R4-1` | resilience | `tools/normalize_to_cog.py:203-259` |

SUGGESTION level, all in `tools/normalize_to_cog.py`: `R2-duplicate-success-filter`
(:372), `R2-manifest-window-bloat` (:252-256), `R2-pyramid-comment-overstates`
(:229-233), `R2-status-branch-noise` (:355-361), `R2-vacuous-integrity-true` (:262),
`R2-this-commit-placeholder` (doc :180-184), `R3-003` (:233), `R3-004` (:184-194),
`R3-005` (:334), `R4-2` (:371), `R4-3` (:345-347), `R4-4` (:188-192).

**Candidate sizing lesson**: including the generated 105 KB manifest in the T3 review
candidate inflated it from ~450 authored lines to 6363 and pushed each reviewer prompt
to 147 KB. From T4 onward, generated artifacts are excluded from the review candidate
and committed alongside the tool that produces them. T4 applied this: the candidate was
633 lines with only `tools/composition_stats.py` and this document.

## 12. T4 review debt (explicit, not hidden)

**T4 was committed without lens review.** The candidate was frozen and correct, the four
reviewer slots were issued and authorized twice, and both runs died in the provider
upstream, not locally:

| Attempt | Lens that failed | Failure | Elapsed |
|---|---|---|---|
| 1 | `review-readability` | `[server_error] upstream service failed` | 154 s |
| 2 | `review-readability` | `[server_error] upstream service timeout` | 600 s |

Both returned `prepared_reviewers: 0`, `submitted_reviewers: 0`,
`mutation_performed: false`, so nothing was contaminated and no partial result was
admitted. The decision to proceed anyway was the user's, taken with the cost of further
attempts (~10 min of wall clock each, no mutation on failure) on the table.

Consequences to carry forward:

- The lineage `review-81491992caa75a25` is left **open** in state `reviewing` with zero
  lens results. No operation available to this agent abandons a non-legacy lineage, so
  it stays as an orphan. Committing T4 changed the workspace, so the next `inspect` will
  project a fresh target; this lineage should be treated as dead, never resumed.
- The reviewer model `opencode-go/glm-5.3-flash` failed twice with long-generation
  upstream errors. If this recurs on T5, switch the lens model in
  `~/.pi/gentle-ai/models.json` before retrying.
- **Compensating evidence, which is why this debt is acceptable here**: the core
  correctness of `tools/composition_stats.py` is corroborated by a *second,
  independent implementation*. The `gentle-ai-verify` agent wrote its own native-
  resolution histogram and counted 18 pixels of class 34 in 2024; this tool, written
  separately, reproduces exactly 18. Agreement between two implementations on a rare
  class is stronger evidence of counting correctness than a style-oriented lens review.
  What is *not* covered by that evidence: error-handling contracts, resilience and
  readability of the new tool, and the same classes of finding that the T3 review
  raised. Those are open.
- **Not to be re-run**: do not re-review the T4 candidate. Its files are committed; any
  further review belongs to the next candidate that touches them.

### 12.1 T6 review debt — **PAID 2026-10-08, see section 12.3**

**T6 was also committed without lens review**, by the same user decision as T4, after two
provider-upstream failures on the frozen candidate:

| Attempt | Lens that failed | Failure | Elapsed |
|---|---|---|---|
| 1 | `review-risk` | `[server_error] upstream service failed` | 340 s |
| 2 | `review-resilience` | `[server_error] upstream service failed` | 225 s |

Both returned `prepared_reviewers: 0`, `submitted_reviewers: 0`,
`mutation_performed: false`, so nothing was contaminated and no partial lens result was
admitted. A third attempt was offered and declined in favour of committing.

Running total across the feature: the reviewer model `opencode-go/glm-5.3-flash` has now
failed **three** separate reviewer runs with long-generation upstream errors (T4 twice,
T6 twice — five failed runs in total counting each attempt). The common factor is the
endpoint, not the candidate: the T5 review succeeded on that same model once, and the
candidate sizing, memory and transcription causes were all eliminated separately. **The
recommended fix is to switch the lens model in `~/.pi/gentle-ai/models.json` to a
different family before the next review**, for example `opencode-go/grok-4.7` or
`opencode-go/kimi-k3`.

Consequences to carry forward:

- The lineage `review-84f62fbbac67a7d9` is left **open** in state `reviewing` with zero
  lens results, alongside T4's `review-81491992caa75a25`. No operation available to this
  agent abandons a non-legacy lineage, so both are orphans. Neither may be resumed.
- **Compensating evidence, which is why this debt is acceptable here**: T6's central claim
  is that the parameterized engine reproduces the already-verified numbers, and that was
  proven by the parent against the committed fixture over all 40 years — level-1 CSV
  byte-identical, JSON numerics identical, level-2 CSV differing on 1 of 1040 rows by
  1e-6 ha. What is *not* covered: resilience and readability of the refactor, the
  `spatial_units` interface design, and the priority-schema invariants. Those are open.
- **Not to be re-run**: do not re-review the T6 candidate. Its files are committed; any
  further review belongs to the next candidate that touches them.

### 12.2 Attempt to pay the review debt: the base-ref route is not exposed

The user authorized paying the T4 and T6 review debt. It looked payable: with a clean
workspace the provider itself asks for a base ref (`empty_candidate_base_ref_required`),
and a committed range is a supported target type (`base_ref`, and the negotiated feature
`base_ref_workspace_overlay`). The route was then attempted for real and is **not usable
with this facade**:

| Step | Result |
|---|---|
| `inspect` with a clean workspace at a detached HEAD on T6 | `empty_candidate_base_ref_required`, emitting a collect binding |
| The emitted binding | `captureOperation: **external.select_base_ref**`, schema `gentle-ai.review-base-ref-selection/v1` |
| `START` with `{"baseRef":"ba6b55f","committedOnly":true}` | **`Judgment Day graph-v1 START requires lineageId`** |
| Facade operations available | 25, and **none selects a base ref** |

So the provider renders the base-ref choice as a **host-owned external selection** and the
facade exposes no operation for it, while passing `baseRef` through `START` diverts into the
Judgment Day graph-v1 mode and demands a lineage that cannot exist before this very step
creates one. The raw CLI was deliberately **not** used: the injected contract states that Pi
never falls back to an agent-less lifecycle route, so stopping is the correct outcome rather
than driving the lifecycle outside the facade.

**Two facade gaps of the same class** are now confirmed with evidence, both provider-rendered
external selections with no facade operation:

| Gap | Needed for | Evidence |
|---|---|---|
| `external.select_base_ref` | Reviewing a **committed range**, i.e. the T4 and T6 debt | This attempt, with the exact error |
| `review.capture-validation` | The targeted validation after a correction (T8a, T8b) | Refused twice, on two lineages, with a fresh binding |

That is a tool-surface defect, not a defect of this project, and it is worth filing.

The repository state was restored afterwards and nothing was mutated: HEAD back on
`feat/plataforma-cobertura-ve` at `9b90445`, working tree clean, no stashes. One local,
unversioned change was made along the way, to `.git/info/exclude`: `.playwright-mcp/` and
`data/**/*.log` are now excluded through the local exclude file as well, because a detached
checkout of an older commit carries an older `.gitignore` that does not yet ignore them. That
is the documented way to keep tool output out of the review inventory at any revision.

**Consequence, as far as it was correct:** the T4 debt stays as recorded in section 12, and the
part of the T6 debt that the correct route did not reach also stays. The conclusion that the route
itself is unusable was **wrong**; see section 12.3, which corrects this paragraph and records the
T6 payment.

### 12.3 The debt was payable: section 12.2's conclusion was wrong

The route was retried on 2026-10-08 with the currently documented form and it works. Section 12.2
concluded "not usable with this facade" from a **single malformed attempt**, and that conclusion
was propagated into the README as a limitation. It is corrected here rather than left standing.

**What was malformed about the 12.2 attempt.** It sent
`{"baseRef":"ba6b55f","committedOnly":true}`. Two defects: `mode` was missing, and the `baseRef`
was an **abbreviated** commit id, which the facade rejects (it requires `HEAD`, a full 40- or
64-character commit id, or a ref name). With the correct form the
`Judgment Day graph-v1 START requires lineageId` error disappears entirely.

**The form that works**, recorded verbatim because this cost the project a wrong conclusion:

1. `git checkout --detach <tip commit>`, so the workspace is the candidate tip;
2. `inspect`, which returns `empty_candidate_base_ref_required` with `action: start`;
3. `start` with `input = {"mode":"ordinary","baseRef":"<full 40-char SHA>","committedOnly":true}`
   and a fresh `idempotencyKey`.

The provider resolves the range itself (it reported its own internal `--base-ref`), freezes the
candidate, and continues to the ordinary reviewer slots. The workspace must be restored to its
branch afterwards; nothing in the provider's work touches the worktree.

**T6 is paid.** Lineage `review-42afa5987aa5f681`, tier `high`, 894 original changed lines over
four paths (`tools/spatial_units.py`, `tools/priority_schema.py`, `tools/composition_stats.py` and
this document), four lenses admitted, state **approved**, authority **burned**
(`gentle-ai.review-acknowledged/v1`, terminal consumption recorded under
`.git/gentle-ai/review-transactions/terminal-consumption/v1/`). Zero blocking findings. Four
informational findings, all in `tools/composition_stats.py`:

| Id | Lens | Location | Severity |
|---|---|---|---|
| `R2-duplicated-f3-error-msg` | readability | `:143-149` | WARNING |
| `R3-001` | reliability | `:577-580` | WARNING |
| `R3-002` | reliability | `:600-603` | SUGGESTION |
| `R3-003` | reliability | `:289-291` | SUGGESTION |

This covers `tools/spatial_units.py` and `tools/priority_schema.py` at their current content (no
commit after `9b243b0` touched either), plus the T6 refactor delta of `composition_stats.py`.

**`a48cb6c` attempted and escalated — terminal, not approved.** Lineage
`review-44bdd3a6300aecc9`, 49 lines, one path. One reviewer slot was refused at admission
("no complete JSON object ... scan ended at byte 1": the payload truncated to one byte, preserved
under `.git/gentle-ai/rejected-results/`); the refused bytes were **not** resent. On the retry of
the re-offered slots two were admitted and the third returned an ambiguous `partial_unknown`, which
was reconciled with exactly one fresh STATUS. STATUS then reported `state: escalated`,
`action: stop`, `reason_code: native_stop_required`, `cause: unknown_causality`, naming two
findings:

| Id | Lens | Location | Severity | Evidence | Causality |
|---|---|---|---|---|---|
| `R4-JSON-SHAPE-BREAK-NO-GUARD` | resilience | `:568-592` | CRITICAL | deterministic | unknown |
| `R3-missing-coverage-v2-shape` | reliability | `:565-589` | CRITICAL | insufficient | unknown |

Both were downgraded at admission for `unverified_location`, and the provider escalates instead of
deciding whether the risk is candidate-caused or pre-existing. Per the stop table this is terminal:
**the maintainer inspects and the lineage is never resumed.** The second finding is the substantive
one: the v2 shape change recorded as resolved in 14.3 had no assertion anchoring it, so a refactor
that flattened the years back to the top level would satisfy every existing check. That gap is
T10.

**T4 was not attempted, and the reason is structural.** Its committed range is 4525 changed lines,
of which **3854 are the generated CSV and JSON artifacts**. That is the candidate-sizing trap this
document already recorded in section 11, and 85 % generated tabular data is dilution rather than
review. The T4-era lines of `composition_stats.py` that neither T6 nor `a48cb6c` touched therefore
remain unreviewed, and that residual is recorded rather than labelled as reviewed.

**Method lesson, worth more than the fix.** A pendency recorded as "not payable" decays. Section
12.2 recorded it from one malformed attempt and the README repeated it as a limitation. Before
accepting a waiver, the route has to be retried with the form the facade documents **today**.

## 13. Class 33 (water) gain: what was verified and what was not

T4 measured class 33 (Río, lago u océano) growing from 4,280,192 ha (1985) to
4,469,291 ha (2024), +4.42 %. An aggregate number cannot distinguish a real water
body from a classification artifact, so `tools/class_change_probe.py` was written to
answer *where* the gain is and *what temporal signature* it has. The two competing
explanations have different signatures: a reservoir fills as a step change in one
year and persists; an artifact flickers diffusely across many small cells.

**Measured** (cell grid 0.1°, class 33, 1985 → 2024):

| Metric | Value |
|---|---|
| Total net gain | 2,123,147 pixels = **189,001.33 ha** (1,890 km²) |
| Cells with positive net gain | **4,472** |
| Share of net gain in the top 10 cells | **19.4 %** |
| Peak RSS of the probe | 5,189 MB (see the fragility note below) |

**The top clusters are real, and externally corroborated.** A single year explains
91.5–99.9 % of each top cell's net gain, which is step behaviour, not flicker:

| Rank | Cell centre | Net gain | Jump | Jump year | Jump share | Municipality (Nominatim) | Identification |
|---|---|---|---|---|---|---|---|
| 1 | 8.05 N, 62.95 W | 63,075 px | 57,735 px | **2003** | 0.915 | Parroquia Pozo Verde, Mun. Caroní, Bolívar | Caruachi reservoir, upstream reach |
| 2 | 9.05 N, 69.95 W | 54,016 px | 53,950 px | **1990** | 0.999 | Parroquia Boconoíto, Mun. San Genaro de Boconoíto, Portuguesa | Embalse Boconó–Tucupido (La Coromoto) |
| 3 | 8.15 N, 62.85 W | 43,848 px | 40,609 px | **2003** | 0.926 | Parroquia Unare, Mun. Caroní, Bolívar | Caruachi reservoir, at the dam |
| 4 | 8.85 N, 70.15 W | 41,867 px | 41,360 px | **1990** | 0.988 | Parroquia Barrancas, Mun. Cruz Paredes, Barinas | Boconó–Tucupido system, southern reach |
| 5 | 7.15 N, 63.15 W | 40,968 px | 21,932 px | 2017 | 0.535 | — | not identified |

External corroboration, from secondary sources:

- **Caruachi** (Central Hidroeléctrica Francisco de Miranda): dam at 8.160 N,
  62.799 W — cells 1 and 3 sit at the dam and immediately upstream along the Caroní.
  Reservoir surface 238 km², first generating unit in commercial operation **2003**.
  Sources: Wikidata/Wikipedia (coordinates), Global Energy Monitor (commissioning
  2003), COVENPRE technical sheet (reservoir surface, first quarter 2003).
- **Embalse Boconó–Tucupido**, later named Nuestra Señora de La Coromoto: built
  1975–1988 and **inaugurated in 1988**, surface ~12,465 ha, purpose irrigation,
  hydroelectric and flood control, located in Municipio San Genaro de Boconoíto —
  the municipality of cell 2. A 1990 step is consistent with the reservoir reaching
  operating level after the 1988 inauguration. Sources: Wikimedia Commons file
  description, an "Embalses de Venezuela" inventory listing construction 1975–1988 and
  12,465.52 ha, and a ReliefWeb piece giving 12,886 ha of water surface.

**Verdict, stated at its true strength.** Two step changes totalling ~9.6 % of the net
gain are corroborated real reservoirs, with the step year matching the documented
commissioning or inauguration year and the coordinates matching the documented
municipality. That is strong circumstantial agreement, not per-pixel validation.

**What is NOT verified**: the remaining majority of the gain. Only 19.4 % of it sits in
the top 10 cells, and 4,472 cells gained water. A diffuse long tail across thousands of
cells is not what a handful of reservoirs predicts, and no cause is claimed for it. It
could be river and floodplain dynamics, many small impoundments, or classification
behaviour around shorelines and seasonal water. **No water-related claim should be
published beyond the two identified reservoirs until the tail is characterised.**

**Fragility found, worth fixing before this probe is reused**: peak RSS was 5,189 MB,
roughly nine times the composition tool. The cause is the profile phase: it reads the
*union* bounding box of the top cells, and because the top cells sit 7.3° apart
(Portuguesa to Bolívar) that window is ~27,088 x 3,710 pixels, about 100 M pixels per
year. On a 16 GB machine with a browser open this is an OOM risk. The fix is to cluster
the top cells and profile one cluster window at a time instead of one country-wide
window.

**Provenance of the external claims**: Nominatim reverse geocoding for the
municipality names, and secondary sources for the reservoir facts. These are not
primary engineering documents, and the coordinates were matched to the cells by eye at
0.1° resolution. Anyone publishing the reservoir attribution should confirm it against
the operator's or the ministry's own records.

## 14. Follow-up backlog

Ordered by the risk of leaving it undone.

### 14.1 Open review findings (34, all non-blocking)

Neither review envelope carried the body text of its findings, only the id, lens,
location, severity and disposition. The T3 index is in section 11. The T5 review
(lineage `review-905ea42b8047deff`, approved, authority burned) added 17 more:

WARNING level, all in `tools/class_change_probe.py`:

| Id | Lens | Location | Note |
|---|---|---|---|
| `R1-pixelid-uint8-wrap` | risk | :276-277 | uint8 wrap risk in pixel-id handling — **the most substantive open item, missed by hand review** |
| `R1-profile-union-bbox-rss` | risk | :494 | union bounding box memory |
| `R4-uint8-wrap` | resilience | :279 | same uint8 wrap risk |
| `R4-union-bbox-oom` | resilience | :460-497 | union bounding box memory |
| `R2-1` | readability | :470-590 | |
| `R3-1` | reliability | :478-497 | |
| `R3-2` | reliability | :279-280 | |
| `R3-3` | reliability | :301-303 | |

Two of these independently reproduce the union-bbox memory fragility that was found by
hand and documented in section 13, which is useful corroboration. The uint8 wrap risk
was **not** found by hand and is the one worth fixing first.

SUGGESTION level: `R2-2` (:600-632), `R2-3` (:370-376), `R2-4` (:586-589), `R2-5`
(:545-550), `R2-6` (:927), `R3-4` (:558-560), `R3-5` (:714-722), `R3-6` (:529-571),
`R4-no-checkpoint` (:730-732).

**Additions from the 2026-10-08 payment run.** The T6 approval added four informational findings,
all in `tools/composition_stats.py` (`R2-duplicated-f3-error-msg` WARNING :143-149, `R3-001`
WARNING :577-580, `R3-002` SUGGESTION :600-603, `R3-003` SUGGESTION :289-291). The `a48cb6c`
review escalated terminally with two CRITICAL findings of unknown causality
(`R4-JSON-SHAPE-BREAK-NO-GUARD` :568-592, `R3-missing-coverage-v2-shape` :565-589); the second is
closed by T10 and the first is recorded in section 12.3. Body text for every finding above lives
in the native store, not in the closing envelopes: read
`.git/gentle-ai/review-transactions/v2/<lineage>/review-state.json` under
`state.admitted_role_results[N].value.result.findings[]`.

### 14.2 Geodesic area duplicated in the probe

`AUTHALIC_RADIUS_M` and a cell-grid geodesic area function remain in
`tools/class_change_probe.py` after T6 established `tools/spatial_units.py` as the
single source of truth. The T6 writer could not fix it because that file was outside
its allowed edit surfaces, and the two functions are not interchangeable today (raster
row versus configurable cell grid). Converging them is a real refactor, not a rename.

### 14.3 Smaller items

- `tools/class_change_probe.py` carries mode `100755` while the other tools are `644`.
  Inconsistent, harmless, worth normalising.
- ~~The composition summary JSON keys years at the top level~~ **RESOLVED before T8**: the
  summary JSON is now schema version 2 with every per-year record nested under `per_year`, and
  `schema_version` lets a consumer detect the old shape instead of misreading it. Verified against
  the committed v1 file: all 40 years match field by field with 0 numeric differences, the level-1
  CSV is byte-identical, and the level-2 CSV differs on exactly the same single row (2002,
  pixel_id 81, 1e-6 ha) that T6 already identified as float64 accumulation noise. The committed
  data now matches what the current code produces.
- The composition summary JSON still does not carry per-class **areas**: it carries per-class
  pixel counts and presence, while areas live only in the CSV. A per-class area regression
  therefore cannot be detected from the JSON alone.
- The tile manifest names its year list `totals.years_requested` even in `--scan-only` mode, where
  nothing was requested and the years were discovered on disk. Rename or add a mode-aware key.
- In `--scan-only` mode `source_dir` is `null` and each entry's COG fields are `null` by design,
  since no COG directory is needed to scan an existing pyramid. Consumers must tolerate nulls there.
- Unit inconsistency in the tile reporting: the log prints MiB and the manifest stores raw bytes,
  so the same pyramid reads as 4,756 MB and 4,987 MB depending on the unit convention. Pick one
  and state it. A T7 review finding reproduced this independently.
- The viewer's tile layer produces browser console noise from legitimate 404s for transparent
  tiles (roughly a third of z6 at a typical view). That is correct behaviour and must not be
  changed to a 200, because the map client relies on 404 meaning "no tile". Worth a note in the
  README so it is not mistaken for a bug.
- `tools/serve_viewer.py` parses the COG extent from the BigTIFF header by hand rather than using
  GDAL, to avoid a GDAL dependency in the service. It was tested against the real file only, not
  against a range of malformed or exotic COG layouts. If it ever misparses, `/api/meta` fails
  loudly rather than silently centring the map in the wrong place, but the parser deserves
  hardening or replacement with `gdalinfo -json` when T9 packages the service. T9 did not touch it.

### 14.4 Country hardcoded in `run.sh`, overriding the multi-country expression (D5)

The T9 review reported `R2-run-sh-duplicate-codebook-pdf-path` — readability, `run.sh:55-61`,
WARNING, disposition informational. The label understates it.

```bash
CODEBOOK_PDF="$LEGEND_DIR/source/MB-${COUNTRY^}-Col-${COLLECTION}-Legend-Code.pdf"   # line 53
# ...a comment explaining that ${COUNTRY^} yields "Venezuela" for "venezuela"...
CODEBOOK_PDF="$LEGEND_DIR/source/MB-Venezuela-Col-${COLLECTION}-Legend-Code.pdf"    # line 57
```

Line 57 reassigns the variable line 53 has just computed from `COUNTRY`, so the expansion the
comment defends is dead code. For every country other than Venezuela the codebook PDF path is
wrong, and this is exactly the hardcoding D5 forbids: no country name literal inside a code path.

The fix is to delete line 57, keep the expression on line 53, and move the comment directly
beneath it.

**Why it is recorded instead of fixed, which is a decision and not an oversight.** T9 was reviewed
and approved, `7aca576` was committed from exactly the bytes that review covered, and the exact
acknowledgement burned the authority. Editing afterwards would have made the commit differ from the
approved candidate and silently invalidated the receipt. The user chose to leave it noted. Whoever
picks it up should treat it as its own work unit with its own review pass, never as a footnote to
T9.

**The general lesson, which is worth more than the fix.** Nothing observed this defect before the
review: the three T9 verifications that ran — `check`, `serve` and the container — all ran with
`COUNTRY=venezuela`, and that is precisely the value that makes the wrong line produce the right
path. A default-valued variable hides its own hardcoded override, so any check of a multi-country
code path has to use a non-default country value, or it is only re-testing the default.
