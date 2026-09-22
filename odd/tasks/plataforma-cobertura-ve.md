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

## 4. Domain correction (binding for all artifacts)

The rasters are **land cover and land use** (`cobertura y uso del suelo`), **not soil
classification**. All artifact names, UI copy, table columns and docs must say
coverage/cover/use. This is a correctness issue, not a naming preference.

## 5. Inputs (verified)

| Input | Role |
|---|---|
| `mapasBases/coverage-venezuela_classification_1985..2024.tif` (40 files, 2.9 GB) | Source rasters. EPSG:4326, 30 m, Byte, 57605×45000, nodata=0, **no overviews** |
| `MB-Venezuela-Col-3-Legend-Code.pdf` | **Authoritative** legend: class hierarchy (level 1 + level 2), names ES/EN, hex colors |
| `QGIS_Leyenda_col3.qml` | QGIS paletted style. Color source of truth **only where it agrees with the PDF** |

Known PDF vs QML color conflicts to preserve as documented discrepancies:
class 9 (`#7a6c00` vs `#7a5900`), class 12 (`#d6bc74` vs `#b8af4f`),
class 27 (`#ffffff` vs `#d5d5e5`).

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

### T3 — COG normalization + integrity manifest
- Convert all 40 rasters to COG with internal overviews.
- `manifest.json`: country, collection, year, source path, SHA-256, size, class set.
- **Evidence**: 40/40 converted, oversized-read benchmark before/after, manifest complete.

### T4 — Composition statistics
- Exact class counts per year at native resolution: hectares, % of valid area,
  % of land area, at level 1 and level 2.
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

## 9. Commit log (evidence)

_Filled in as tasks close._
