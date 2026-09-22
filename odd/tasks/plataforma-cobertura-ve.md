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

**Independent verification (PASS)**: delegated to `gentle-ai-verify`, which refused to
take the tool's own reasoning as evidence and built a discriminating control — the
same window written twice as COG, once with NEAREST and once with AVERAGE. The
AVERAGE control fabricates 54 class codes that do not exist in the source, including
the forbidden aggregator ids `[10, 14, 22]`, with share errors up to +2879 %
relative. The NEAREST control fabricates 0. The COG under test, over 2,592,225,000
native pixels: **0 fabricated classes**, maximum absolute share deviation 0.0017 pp,
sampling rate 0.015624 against an exact 1/64. The pyramid is NEAREST with no
ambiguity.

### T4 — Composition statistics
- Exact class counts per year at native resolution: hectares, % of valid area,
  % of land area, at level 1 and level 2.
- Every output must carry the D7 label `extensión MapBiomas Venezuela` and the
  boundary note; no unlabelled "Venezuela" area figure is acceptable.
- Output: small versioned Parquet/CSV + JSON for the panel.
- **Evidence**: area totals stable and plausible; level-2 sums equal level-1 sums.

### T5 — Data integrity validation
- Class 34 (Glaciar) trend — expected monotonically shrinking to ~0 by 2024
  (Venezuela lost its last glacier; strong external validation of the series).
- Class 27 (`No observado`) presence or absence vs nodata=0 semantics.
- Legend drift across years (class 34 disappears by 2024).
- **Evidence**: per-year class 34 counts table + verdict on each check.

### T6 — Reusable statistics engine (shape for F3)
- Parameterized by spatial unit: country and collection now, H3 later.
- H3 term for "study gap" present in the schema with weight 0 (D2).
- **Evidence**: same numbers as T4 when unit=country; unit interface documented.

### T7 — Static tile pyramid
- Per-year z0–z12 pyramid with the official palette; storage estimate first.
- **Evidence**: tile counts, total size, spot-check of a rendered year.

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
| T3 | this commit | 40/40 COG converted, 0 failed, 320 integrity windows with 0 differing pixels, 4.44 GB output, versioned manifest with 80 checksums; independent NEAREST verification PASS with a discriminating AVERAGE control (see section 7/T3) |

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
