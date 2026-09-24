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
- Year slider, hierarchical legend, composition panel, clip/download.
- **Evidence**: runs locally, slider switches years, panel matches T4 numbers.

### T9 — Local packaging and documentation
- Reproducible entrypoint (script/container) + README.
- License/attribution section left as an explicit **unresolved** placeholder.
- **Evidence**: clean-clone-to-running instructions executed once.

## 8. Open items (blocking, not yet resolved)

| # | Item | Blocks |
|---|---|---|
| O1 | License and attribution terms for MapBiomas data | Publication only |
| O2 | Final hosting target | Nothing yet (D6: local) |
| O3 | H3 term weights and "interesting zone" thresholds | F3 start |
| O4 | Host-side subagent launch defect (see section 10) | Every task that needs a delegated writer |

## 9. Commit log (evidence)

| Task | Commit | Evidence |
|---|---|---|
| T1 | `7bd98a5` | 40 rasters relocated to `data/raw/venezuela/collection-3/`; `git check-ignore` confirms no `.tif` is ever tracked; branch `feat/plataforma-cobertura-ve` created from unborn HEAD; 8 paths committed |
| T2 | `71d94c1` | `tools/build_codebook.py` emits `data/legend/venezuela-collection-3.{json,csv}`: 6 level-1 groups, 26 classes, unique pixel ids, colors taken from the PDF, 9 PDF-vs-QGIS discrepancies recorded instead of silently resolved |
| T3 | `84e786f` | 40/40 COG converted, 0 failed, 320 integrity windows with 0 differing pixels, 4.44 GB output, versioned manifest with 80 checksums; independent NEAREST verification PASS with a discriminating AVERAGE control (see section 7/T3) |
| T4 | `5961577` | 40/40 years of exact native-resolution composition, 1504 s, peak RSS 567 MB; level-2 vs level-1 = 0 pixel difference; class 34 in 2024 = exactly 18 pixels, matching the independent verifier; valid area 1,086,229.52 km² with the D7 label at the top level of the summary JSON; glacier series 989 → 18 pixels. **Committed without lens review** — see section 12 |
| T5 | `ba6b55f` | `tools/class_change_probe.py` plus the class-33 probe: 2,123,147 pixels (189,001.33 ha) of net water gain, of which the top two clusters are step changes externally corroborated as Caruachi (2003) and Boconó–Tucupido (1990); only 19.4 % of the gain sits in the top 10 cells, so the majority is unexplained. See section 13 |
| T6 | `9b243b0` | `tools/spatial_units.py` (single source of truth for units and geodesic area), `tools/priority_schema.py` (D2 and D3 as mechanical invariants, study_gap disabled at weight 0.0), and `composition_stats.py` parameterized by `--unit`. Full 40-year regression: level-1 CSV byte-identical, JSON numerics identical across all 40 years, level-2 CSV differs on 1 of 1040 rows by 1e-6 ha (float64 accumulation noise, relative 3.8e-15) |
| T7 | this commit | `tools/build_tiles.py` plus the 40-year pyramid: 662,600 tiles, 4,987 MB of PNG content, ~110 min. Every year 16,565 tiles, identical path set and identical per-zoom counts across all 40 years; all 662,600 PNGs integrity-verified with 0 zero-byte and 0 malformed; palette spot-check found 0 colours outside the official table. The mid-build reboot exposed two tool gaps (run-scoped manifest, unverified tiles) and both were fixed |

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

### 12.1 T6 review debt

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

### 14.2 Geodesic area duplicated in the probe

`AUTHALIC_RADIUS_M` and a cell-grid geodesic area function remain in
`tools/class_change_probe.py` after T6 established `tools/spatial_units.py` as the
single source of truth. The T6 writer could not fix it because that file was outside
its allowed edit surfaces, and the two functions are not interchangeable today (raster
row versus configurable cell grid). Converging them is a real refactor, not a rename.

### 14.3 Smaller items

- `tools/class_change_probe.py` carries mode `100755` while the other tools are `644`.
  Inconsistent, harmless, worth normalising.
- The composition summary JSON keys years at the top level (`"1985": {…}`) alongside
  metadata keys, mixing namespaces for consumers. Nest under `per_year`.
- The composition summary JSON still does not carry per-class **areas**, only per-class
  pixel counts, so a per-class area regression cannot be detected from the JSON alone.
  The CSV is currently the only place those numbers live.
- The tile manifest names its year list `totals.years_requested` even in `--scan-only`
  mode, where nothing was requested and the years were discovered on disk. Rename or
  add a mode-aware key.
- In `--scan-only` mode `source_dir` is `null` and each entry's COG fields are `null`
  by design, since no COG directory is needed to scan an existing pyramid. Consumers
  must tolerate nulls there.
- Unit inconsistency in the tile reporting: the log prints MiB and the manifest stores
  raw bytes, so the same pyramid reads as 4,756 MB and 4,987 MB depending on the unit
  convention. Pick one and state it.
