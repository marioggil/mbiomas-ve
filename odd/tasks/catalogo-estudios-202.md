# Feature: the CVE study catalog at the real corpus size (202 studies)

**Status**: implementation authorized — T1 **DONE**, T2 next
**Branch**: `feat/catalogo-estudios-202`, **stacked on `feat/catalogo-estudios-cve`** (F4, not merged;
`tools/build_study_catalog.py` exists only there)
**Parent record**: [`catalogo-estudios-cve.md`](catalogo-estudios-cve.md) — F4, decisions D9–D11,
the original display contract, its measured evidence and its open items C1–C4. This document
continues the decision sequence at D12 and does not repeat the parent's evidence.

**Scope authorized**: bring the derived study catalog up to the corpus the repository actually
holds (202 studies); replace the collision exclusion with a curated location-granularity taxonomy;
record provenance of the derived artifact; adapt the API, the catalog panel and the map to that
volume; and close the packaging F4 left pending (its T5). This is stage E0 + E1 of the roadmap.

**Explicitly NOT authorized**: the point table (`congresos_revisados_puntos.parquet`, 204 points)
and multi-point conferences; the KDE hotspot map (stage E3); enabling the `study_gap` priority
term; re-geocoding or editing any coordinate (D11); rich search facets and pagination (stage E2);
any change to the `Congresos_CVE_V2` ETL or corpus.

---

## 1. Goal

The repository already contains the current export of the reviewed conferences — 202 studies — and
serves a derived catalog built from a 31-study snapshot of the same file. The goal is that the
catalog the viewer serves **is** the corpus the repository holds, that its exclusions are justified
by *granularity* rather than by *coincidence of coordinates*, and that a future silent drift
between the raw input and the derived artifact is impossible.

## 2. Non-goals

- **Using the point table or multi-point conferences.** `congresos_revisados_puntos.parquet` carries
  11 hand-curated additional points across 5 multi-point conferences that the viewer ignores today.
  Consuming it requires an explicit decision against D9's "one marker = exactly one study", and it
  is not taken here.
- **The hotspot map (D14 of `Congresos_CVE_V2`).** KDE at 15 km, the `1/n` fractional weight and the
  peak extraction are stage E3. They need the taxonomy this feature builds, which is why they wait.
- **Enabling `study_gap`.** Section 6 of the parent document still governs, and 202 studies across
  twelve editions do not populate an H3 res 8–9 gap index. See decision D12's note and item C4.
- **Touching any coordinate** (D11) and **re-geocoding** anything.
- **Rich search**: facets, pagination, virtualised lists. Stage E2. T5 delivers a bounded, usable
  panel, not a search product.

## 3. Decisions

### D12 — Collision of coordinates stops being an exclusion and becomes an attribute

**Context.** The F4 contract classified a study as `shared_coordinate` whenever another study
resolved to the *exact same* `(lat, lon)`, and excluded it from the map. It was written for a single
collision: four edition-I studies whose own location text names four different granularities
(`Barinas, Turen y Yaritagua`, `estado Barinas`, `Jardín Botánico de la ULA, Barinas`, `Barinas`).
One marker would have asserted that four different places are one.

Applied to the 202 real rows, that rule excludes **69 studies** — and among them are the **6 studies
at the Mérida centroid** (`8.5060738, -71.2649632`), which in `Congresos_CVE_V2`'s D14 is the
**number-one hotspot of the country** (weight 10.00). The rule stopped protecting an honest map and
started deleting the strongest signal in the corpus.

**Decision.** Collision and coarseness are different things and must be judged separately.

1. The exclusion classes are `no_coordinate`, `coarse_location`, `outside_extent`, evaluated **in
   that order**, with `placeable` as the remainder. `shared_coordinate` is no longer a class.
2. `coarse_location` comes from the **curated taxonomy** (section 6): T0 (country, multi-national
   region, or an enumeration of separate regions) and T1 (first-level administrative unit, or a
   natural region at state scale without a locality) are excluded. T2 (locality, named site, park,
   named watershed) is placeable.
3. The collision becomes a **per-study attribute**: `coordinate_group_size` (total studies at the
   exact same coordinate, including this one; `null` when the study has no coordinate) and
   `coordinate_group_ids` (the *other* `study_id`s in that group, sorted ascending; `[]` when alone).
   It is computed by the builder from coordinates alone, **independently of class** — in the Barinas
   group one member is T1 and three are T2, and that is correct.
4. The map must **show** the collision instead of hiding it: a study in a group larger than one is
   drawn with a distinguishing halo, and the map note states how many studies share a coordinate
   while the panel stays the authoritative view (D9).

**Consequence.** The map stops excluding rows for sharing a coordinate and starts declaring the
collision where it happens. The placeable count is no longer derivable from a formula: it is what
the curated taxonomy leaves, and it closes against `study_count` in the artifact.

### D13 — Sequencing: provenance plumbing first, the freshness assertion with the rebuild

The plan originally put "provenance" and "the freshness check" in one task, before the rebuild.
Planning the first commit showed that is impossible to land green: the committed artifact was built
from a 31-row file that no longer exists on disk, so any assertion comparing the two must fail until
the artifact is regenerated — and regenerating it before the taxonomy exists would land the 202 rows
under the **old** contract and break the pinned contract tests.

**Decision.** T1 adds provenance *plumbing* to the builder (fields written, unit-tested on synthetic
fixtures, committed artifact untouched, suite green). The **freshness assertion** over the committed
artifact lands in T3, where it can be green, together with the rebuild that makes it true.

### D14 — Undated studies get an explicit `study_id` segment and sort last

**Context.** Running the builder against the real 202-row Parquet for the first time (see 4.6) fails
before writing anything: `make_study_id(int(row["anio"]), ...)` raises `TypeError` on the 16 Vol XI
rows whose `anio` is null. Changing the id is not free — the id is a URL path segment and an existing
test anchors `^[a-z0-9-]+$` — so the shape is decided here rather than improvised inside T3.

**Decision.**

1. When `anio` is known the id keeps its current shape, `cve-{anio}-{slug of the source stem}`: no
existing id changes, so no published URL churns.
2. When `anio` is null the year segment becomes the literal `sin-anio`: `cve-sin-anio-pagina-607-1`.
   The volume does not enter the id; `congreso` already carries it as its own field, and the builder
   hard-fails on duplicates, so ambiguity cannot pass silently.
3. The study sort key stops being `(anio, congreso, pagina, indice)`, which raises `TypeError` when
   comparing `None` with an `int`. Undated studies sort **last**, ordered among themselves by
   `(congreso, pagina, indice)`, so the artifact order stays total and deterministic.

## 4. Measured facts (verified, not assumed)

Everything in this section was measured on 2026-10-13/14 against the repository as it stands.

### 4.1 The drift

| Item | Value |
|---|---|
| `data/raw/congresos/congresos_revisados.parquet` | **202 rows**, 288.7 KB, sha256 `111a0d0526b46e7022f7b10967cd79fdaf1f37edb861012b322b1a85fcd4fde8` |
| same file in `Congresos_CVE_V2/exports/` | **byte-identical** (same sha256) |
| `congresos_revisados_puntos.parquet` | 204 points, sha256 `fe62aac412dba30db4da53fa855e9090e0d5af463044d4629236ce1c86c865f9`, identical upstream |
| committed derived artifact | `study_count` **31**, classes `{placeable 24, shared_coordinate 4, outside_extent 1, no_coordinate 2}`, `map_visible_count` 24, `excluded_count` 7, `generated_utc` `2026-10-09T03:10:50Z` |
| artifact `source_parquet` | `data/raw/congresos/congresos_revisados.parquet` — **the same path**, different content |

The artifact records the *path* of its input, never its identity, so nothing in the repository can
detect that the two no longer match. That is the defect T1/T3 exist to close.

### 4.2 The F4 contract applied to the 202 real rows (measured, same logic as `display_class_for`)

| Class | Artifact (31) | Real (202) |
|---|---|---|
| `placeable` | 24 | **107** |
| `shared_coordinate` | 4 | **69** |
| `outside_extent` | 1 | **17** |
| `no_coordinate` | 2 | **9** |

Sum 202. The map would go from 24 of 31 visible to 107 of 202, and exclusions from 7 (23%) to
**95 (47%)**. See D12 for why that is unacceptable.

### 4.3 The corpus

| Measurement | Value |
|---|---|
| Rows | **202**, all `evento = cve` |
| Editions | **12** (I 14, II 16, III 12, IV 15, V 16, VI 31, VII 17, VIII 15, IX 16, X 17, XI 16, XII 17) |
| Years | 1991 → 2019, and **`anio` is null in 16 rows** (Vol XI, legacy CSV ETL) |
| Congress cities | 8: Porlamar 48, Mérida 32, Sartenejas 31, Maracaibo 31, Ciudad Guayana 17, Guanare 16, Coro 15, Puerto Ordaz 12 |
| Rows with a coordinate | **193**; without: 9 |
| Distinct coordinates | **145** |
| `palabrasclaves` non-empty | **82 of 202** |
| Authors | **559** |
| `especiesmencionadas` non-empty | **162** |
| `ubicaciontemporal` present | 89 (absent in 113) |
| `direccion` | 193 non-empty, **181 distinct values**; equal to `ubicaciongeografica` in 201 of 202 rows |
| Extent (from the 2024 COG) | west −73.51785335775641, south 0.5274009033065727, east −57.9936177752449, north 12.654657238920112 |

C3 of the parent document ("`palabrasclaves` is empty in all 31 rows, so keyword search cannot be
offered") **is no longer true**: 82 rows carry keywords.

### 4.4 Collision groups (exact `(lat, lon)`, top of the distribution)

| Coordinate | Studies | Note |
|---|---|---|
| `8.0018709, -66.1109318` | **11** | Venezuela centroid; all mentions are the country itself (T0) |
| `8.5060738, -71.2649632` | **6** | Mérida centroid — D14's hotspot #1 |
| `10.0251111, -71.6163131` | 5 | |
| `8.1450535, -69.8567392` | 4 | the Barinas collision of the parent document |
| `10.5942021, -63.834001` | 3 | |
| `9.8910697, -72.087479` | 3 | |

### 4.5 The 17 rows outside the extent are not homogeneous

- **4** are generic mentions that must be classified T0: `Caribbean`, `Neotrópico`, `Pan-Amazonía`,
  `América Latina`.
- **14** are legitimate foreign sites (El Yunque PR, Kwakwani Guyana, Río Lozoya Spain, Lagoa dos
  Patos Brazil, Costa de Brasil, Chile central, Lima, Sierra de Neiba DR, Isla de Aves ×2, Sierra
  Nevada de Santa Marta ×2, Pan-Amazonía aside).
- **1** is a geocode bug: `XII/curatedwithgeo/pagina_227_1.json` says `La Florida, Piedra de
  Cachimbo, Colonia Tovar, Edo. Aragua, Venezuela` and sits at `(-33.52, -70.60)` — Santiago de
  Chile. Recorded with a note; the coordinate is not touched (D11).

### 4.6 The builder cannot build the 202-row corpus at all

The F4 builder was only ever exercised against the 31 rows of volumes I–III. Run against the real
Parquet — same command the tool documents, on the rebuild interpreter of section 9 — it **fails
before writing anything**:

```
File "tools/build_study_catalog.py", line 489, in build_study
    study_id = make_study_id(int(row["anio"]), row["source_path"])
TypeError: int() argument must be a string, a bytes-like object or a real number, not 'NoneType'
```

The 16 Vol XI rows with `anio` null (C6) reach `int(None)`. A second failure waits immediately behind
it: `build_catalog` sorts with `key=lambda s: (s["anio"], ...)`, which raises `TypeError` on the same
rows because `None` cannot be compared with an `int`. Both are the subject of D14, and both are fixed
inside T3 before the artifact is regenerated.

This is why the end-to-end proof of T1's plumbing is deferred to T3: the JSON is never written today,
so the provenance block cannot be observed in a real artifact until the corpus builds at all.

## 5. The new display contract

**Evaluation order**, first match wins:

1. `latitud` or `longitud` is null → **`no_coordinate`**
2. the curated taxonomy says T0 or T1 → **`coarse_location`** (reason names the level and carries the
   verbatim location text)
3. the coordinate falls outside the COG extent → **`outside_extent`**
4. otherwise → **`placeable`**

Only `placeable` is on the map (`on_map == (display_class == "placeable")`, unchanged from F4).

**Artifact shape changes:**

- New classes: `coarse_location` replaces `shared_coordinate` in `classes[]` (key, count, on_map,
  `label_es`, reason).
- New per-study fields: `coordinate_group_size`, `coordinate_group_ids`, `granularidad_nivel`
  (`T0`/`T1`/`T2`), `granularidad_razon`, and **`palabrasclaves`** (`list[str]`) so the panel can
  search it without a second artifact.
- `source_sha256`, `source_rows`, `source_bytes` next to `source_parquet` (T1).
- `schema_version` is **bumped** and anchored by a test, following the project's existing convention
  (the composition summary is anchored the same way).

`serve_viewer.py`'s import-time validator is **contract-driven**, not nominal: it checks invariants
(`sum(class counts) == study_count`, `on_map ⟺ placeable`, a non-empty reason for every non-placeable
row, the real per-class tally) and does not know the four class names. Adding a class therefore needs
**no change** to its class logic; T4 only adds the new invariants for the collision attributes.

## 6. The curated granularity taxonomy

**File**: `data/curated/congresos/granularidad-ubicaciones.json` (verified: **not** gitignored —
`data/raw/`, `data/cog/` and `data/tiles/` are, `data/curated/` is not).

**Shape**: `schema_version`, `levels` (the definition of T0/T1/T2 in prose), and `entries`, one per
`source_path`, each `{nivel, razon?, nota?}`. Complete: all 202 rows. `razon` is required for T0 and
T1 — those are assertions that need justification in the diff — and optional for T2.

**Pre-fill, and the result.** Mechanical, from the rules below applied to the corpus's own location
texts, with every T0/T1 decision written out in the file next to its reason:

| Rule | Level |
|---|---|
| **A** no usable location text | T0 |
| **B** supra-national or multi-country mention | T0 |
| **C** enumeration of two or more named *sites* with no name that subsumes them | T0 |
| **D** country-only, an enumeration of regions, or a broad natural region spanning several states (an appended state name does not localize it) | T0 |
| **E** an enumeration of states with no named site | T0 |
| **F** an administrative unit with no locality, site or natural feature named inside it (state, municipio) | T1 |
| **G** a regional-scale feature with no locality (gulf, delta, plain, coastline stretch) | T1 |
| **H** otherwise: a named locality, site, park, watershed, island or water body | T2 |

A named site wins over an appended list of states: the states are not the anchor.

Result over the 202-row corpus: **T0 61, T1 31, T2 110**, which under the D12 evaluation order
leaves **100 placeable / 83 coarse_location / 10 outside_extent / 9 no_coordinate**. The F4 contract
on the same rows gave 107 placeable — a similar *number*, for entirely different reasons: it
excluded studies for sharing a coordinate, including the Mérida and Lago de Maracaibo clusters,
while the taxonomy excludes the mentions that name no place and keeps those clusters on the map.

**Every entry records the location text it classifies** (`texto`). Without it the file would be a
list of opaque `source_path` keys that no reviewer could judge from the diff, which would defeat the
whole point of a curated file. The text is not decoration: `check_granularity_coverage` fails when
the recorded text no longer matches the corpus row, so an upstream extraction fix stops the build
until a human re-judges the level.

**43 entries carry a `nota`** recording a boundary call and the alternative; **27 of them would move
at least one study on or off the map**. They are grouped into five decisions in T2's evidence below.

**Fail-loud**: a parquet row with no entry aborts the build; an entry matching no row aborts; a level
outside T0/T1/T2 aborts; a T0/T1 entry without `razon` aborts.

**Known holes closed here**, both named in D14 upstream: `I/curatedwithgeo/pagina_6_2.json`
(`Territorio Amazonas, Edo. Bolívar, Edo. Apure, Edo. Lara` — multi-state enumeration) → **T0**, and
`XII/curatedwithgeo/pagina_223_1.json` (`Bosques urbanos, Venezuela, América Latina`) → **T0**.

**Human checkpoint**: the pre-filled file and the doubt list are shown to the user **before** T3, and
the rebuild is not treated as truth until they are reviewed.

## 7. Tasks

Each task closes with one work-unit commit carrying code, its tests and its documentation together.

### T1 — Provenance plumbing in the builder — **DONE**

**Commit**: `7b47474` — work unit carrying the builder, its tests and this document.

- `read_rows` reads the Parquet **once** into memory, hashes those bytes and parses them from the same
  buffer, returning `(rows, source_identity)` with exactly `source_sha256`, `source_rows` and
  `source_bytes`. There is no second read of the path, so the digest cannot describe a different
  revision than the one parsed. `build_catalog` takes that identity as a trailing parameter and
  writes the three fields immediately after `source_parquet`; the CSV is untouched (provenance is
  document-level). The module docstring gained a `PROVENANCE` section.
- **Evidence**: suite went from 162 to **178 tests, OK** on the bare interpreter (`python3 -m
  unittest discover -s tests -q`, 0.144 s); the artifact was **not** regenerated (`git diff --stat --
  data/derived/... ` empty; `git status --short` shows only the two intended source files plus the
  untracked feature document). The file still contains **zero** bare `assertRaises`.
- **Controls, verified by mutation and reverted byte-identical** (`diff -q` against a pre-mutation
  copy): hashing the path instead of the payload makes the different-digest control fail
  (`9454269… != e174582…`); taking the row count from the parsed list instead of the Parquet's
  `num_rows` makes the row-count control fail (`1 != 7`); and moving `source_sha256` before
  `source_parquet` makes the key-order control report
  `['source_rows', 'source_bytes', 'extent_label']` and fail.
- **Independently verified by the parent**, because the writer could not: the real end-to-end run
  needed the rebuild interpreter of section 9, and it is what exposed 4.6. The parent reproduced the
  suite at 178 tests and confirmed the diff parses the bytes it hashes. The **real-artifact proof of
  the provenance block moves to T3**, since the JSON cannot be written until the corpus builds.

### T2 — Curated granularity taxonomy — **DONE**

**Commit**: `89d456b` (the curated data, alone) and `f482b42` (the loader, its tests and this
document).

- Lands the file of section 6 (202 entries), `load_granularity`, `row_location_text` and
  `check_granularity_coverage`. It deliberately does **not** wire the taxonomy into the
  classification or into `main`: that is T3.3.
- **Evidence**: suite **178 → 222 tests, OK** on the bare interpreter. Verified by the parent with
  the rebuild interpreter, because the tests cannot read Parquet: the curated file covers the real
  corpus exactly — **202 rows ↔ 202 entries, no orphans, every T0/T1 entry justified, every recorded
  text equal to its corpus row** — and a deliberately corrupted text makes the coverage check fire
  with `... location text no longer matches the parquet row it classifies; re-judge the level before
  shipping`.
- The loader was verified **by mutation and reverted byte-identically** (sha256 before and after):
  removing the missing-`texto` guard, and neutralising the text comparison each make the intended
  control fail. Zero bare `assertRaises` remain (79 `assertRaisesRegex` sites).
- **Deviations the writer reported and the parent accepted**: `tmp_path` is a pytest fixture and
  this file is pure `unittest`, so temp files come from `tempfile`; `diff -q` would have required
  writing outside the allowed edit surfaces, so byte-identical restoration is proven by `sha256sum`
  equality instead (strictly stronger); and it added a dependency-free test that loads the real
  curated document and pins its 202 entries.
- **The contract change, measured study by study** (F4 class → D12 class over the 202 rows):

| F4 | D12 | Studies |
|---|---|---|
| placeable | placeable | 64 |
| placeable | coarse_location | **43** |
| shared_coordinate | placeable | **36** |
| shared_coordinate | coarse_location | 33 |
| outside_extent | outside_extent | 10 |
| outside_extent | coarse_location | 7 |
| no_coordinate | no_coordinate | 9 |

  The two bold cells are the whole argument: **36 studies come back to the map** that the collision
  rule was deleting, and **43 leave it** that the old rule admitted although they name no place. The
  three clusters that matter: Mérida keeps **4 of 6** (the other two are `Estado Mérida, Venezuela`,
  which names a state and nothing inside it), the Lago de Maracaibo group keeps **all 5**, and the
  original Barinas collision of F4 keeps **2 of 4** (`Barinas` and `Jardín Botánico de la ULA,
  Barinas`; the multi-site mention and `estado Barinas` correctly lose their marker).
- **Human review is the gate before T3**, owed on five grouped decisions:

| Group | Mentions | Effect if flipped |
|---|---|---|
| Regional-scale features held as T1 (Golfo de Venezuela, Golfo Triste, Delta del Orinoco, Planicie de Maracaibo, desembocadura del estuario, Mar Caribe) | 6 | +1 each back onto the map |
| `Lago de Maracaibo, Venezuela` (+ the beaches variant) held as T2 | 2 | **−4** if moved to T1; it is D14's 4th hotspot |
| Administrative apparatus beside a named site (Municipio Campo Elías/Jají, parroquia Canoabo, Valle de Caracas, Maracay + estado, Carora, Aguas Calientes, Capitán Chico, IVIC, PNALR, laguna de Guanoco) | 10 | ±1 each |
| Multi-site mentions holding a name that subsumes them (3-river basin, 2 páramos, Henri Pittier + 2 cities, Isla la Tortuga archipelago, Sierra Nevada + 2 quebradas, Sierra Maigualida) | 6 | ±1 each |
| `Isla de Margarita, Venezuela` held as T2 while `Nueva Esparta` is T1 | 1 | −1; the Margarita/Porlamar cluster is 5 studies |

Whatever the review changes lands as a **data-only commit** on top of this one.

### T3 — Builder at 202, new contract, artifact regenerated

Three work-unit commits inside one task, in this order:

**T3.1 — Undated studies (D14).** `make_study_id` handles a null `anio` (`cve-sin-anio-…`) and the
artifact sort key becomes total instead of raising on `None`. Builder and tests only: the committed
artifact is still not regenerated, so the pinned contract tests stay green. Evidence: a control for
each branch (null year, and a null-year row interleaved with dated ones proving the order is total
and deterministic), plus the suite green.

**T3.2 — Regenerated artifact (data commit).** The artifact is regenerated in its **own commit
before** the tool commit, per the project rule that the review candidate is the tool and never
generated data.

**T3.3 — Tool and contract.** Taxonomy replaces the collision classification; collision attributes;
reasons naming the level; class labels; `palabrasclaves` added; `schema_version` bumped; provenance
fields populated; and the freshness assertion that consumes T1's plumbing.
- Tests: pinned constants at `tests/test_study_catalog_contract.py:73-82` recomputed; the six
  mutation controls at `:512-513, :578, :641-642, :657-658, :662-663` re-anchored;
  `EXPECTED_ESPECIES_NON_NULL` 21 → 162; new controls for every new branch; a `schema_version`
  anchor test; and the **freshness assertion** (committed artifact vs parquet on disk) with a control
  that mutates a fixture copy and sees it fail.
- Evidence: two consecutive rebuilds differ **only** in `generated_utc` and the CSV is
  byte-identical; class counts close against `study_count`; the taxonomy's own T0/T1 tally equals the
  artifact's `coarse_location` count.

### T4 — API invariants and packaging
- New hard invariants in `tools/serve_viewer.py`: `coordinate_group_size` is `null` exactly for rows
  without coordinates and an int ≥ 1 otherwise; `coordinate_group_ids` is sorted, unique, free of
  self-reference, references existing `study_id`s, and `len(ids) + 1 == size`. The group is **not**
  asserted to share a display class (the Barinas group mixes T1 and T2).
- `run.sh`: the `stage_studies` stage F4 left pending, and the parquet named in `check` as a
  rebuild-only prerequisite.
- Evidence: `/api/studies/catalog` 200 with 202 studies; `_load_counters` unchanged across N
  requests; unknown id 404; the service refusing to start on a deliberately inconsistent artifact;
  the other endpoints unaffected.

### T5 — Panel at 202
- Bounded, scrollable list container (today `.catalog-list` has no `max-height`/`overflow`, so 202
  rows make the whole document scroll); a compact reason badge with the full builder-produced reason
  in the detail view (today the full text is printed inline on every excluded row); selection without
  re-querying every row; and a text search over title, author names and `palabrasclaves`.
- The edition filter is already derived from the data and needs no change (12 values).
- Evidence: 202 rows rendered, search narrows the list, selection works, no document-level scroll
  trap; measured in a real browser.

### T6 — Map: the collision becomes visible
- A distinguishing halo for studies whose `coordinate_group_size > 1`, plus the note stating how many
  studies share a coordinate and that the panel is the authoritative view.
- Evidence, in a real browser with the MapLibre constructor intercepted (the technique recorded after
  F4's T4): marker count read from the live `studies-points` source, halo count read from the live
  halo source, a click on a shared-coordinate marker selects the right study, and no overlap between
  the D7 boundary note, the studies note/legend and the attribution strip at two viewport widths.

### T7 — Closing
- `README.md`: the new contract and the standing `study_gap` warning.
- Open items C1–C6 below brought up to date, including C3's reversal.
- This document's evidence sections filled with the observed results.

## 8. Open items

| # | Item | Blocks |
|---|---|---|
| C1 | `data/raw/` is gitignored, so the parquet is not versioned and a fresh clone cannot rebuild the catalog | Rebuild only. T1 records the input's identity, which detects drift but does not make the input available |
| C2 | Four studies share one coordinate and one study is mislocated in Puerto Rico | **Superseded by D12**: the collision is now an exposed attribute, and the Puerto Rico study is `outside_extent`. The coordinate is still never edited (D11) |
| C3 | `palabrasclaves` empty, so keyword search cannot be offered | **Closed, reversed**: 82 of 202 rows carry keywords. T5 can offer search |
| C4 | The `study_gap` rationale in `tools/priority_schema.py` names D2 and reads as stale | Nothing yet. Section 6 of the parent document is the answer; with 202 studies the term is still insufficient for an H3 res 8–9 index. Do not flip it |
| C5 | **New**: decide whether the raw parquet is versioned in this repository or the sync from `Congresos_CVE_V2` becomes a documented, hash-checked mandatory step | A fresh clone's rebuild. A decision, not a task |
| C6 | **New**: 16 Vol XI rows have `anio` null (legacy CSV ETL) | Any per-year study layer (stage E2) will have 16 undated studies |

## 9. Rebuild environment

`pyarrow` (to read Parquet) and GDAL (to read the COG geotransform) are **rebuild-only**
dependencies. They stay out of the service, out of the image and out of any requirements file.

No interpreter on this machine has both: the repository `.venv` has neither, the system `python3`
(3.13.5) has GDAL + numpy but no pyarrow, and the `Congresos_CVE_V2` `.venv` has pyarrow but no
GDAL. The throwaway environment used in F4's T1 (`/tmp/pq2`) no longer exists.

**Verified working (2026-10-14):**

```
uv venv --python 3.13 --system-site-packages /tmp/pq-catalog
uv pip install --python /tmp/pq-catalog/bin/python pyarrow
```

gives `pyarrow 26.0.0` + `GDAL 3.10.3` (inherited from the system), and reads the 2024 COG
geotransform reproducing the committed extent **to the last digit**:
`-73.5178533578 / -57.9936177752 / 12.6546572389 / 0.5274009033`.

The tests themselves stay dependency-free: they run on a bare interpreter (`python3 -m unittest
discover -s tests`), which is the whole point of the lazy imports T2 of F4 introduced.

## 10. Risks

1. **The taxonomy is a domain judgement.** If the pre-fill classifies a row wrongly and the human
   review is cursory, the error enters the map looking like data. Mitigated by: a complete file, a
   reason per T0/T1 row, doubtful cases flagged and listed separately, and a review gate before T3.
2. **T3 is the biggest candidate in this feature** (artifact of 202 studies + builder + tests). The
   data/tool commit split is mandatory, not optional.
3. **Rebuild interpreter version drift.** The original artifact was built with `pyarrow 25.0.1`; the
   environment available today gives `26.0.0`. T3 verifies that the output does not depend on it by
   rebuilding and diffing (only `generated_utc` and the new provenance fields may differ).
4. **A 202-row catalog is a computation, not a list.** The panel must stay usable, and the map must
   stay readable with several markers stacked on one coordinate — that is what T5 and T6 are for,
   with browser evidence rather than code reading.
5. **The builder had never run on the real corpus** (4.6). Expect more of the same class of defect:
   every code path only ever exercised by 31 dated, well-behaved rows is suspect until the rebuild in
   T3 walks it. This is an argument for running the real rebuild at every step, not only at the end.
