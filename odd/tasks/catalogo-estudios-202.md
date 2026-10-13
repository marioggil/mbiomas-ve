# Feature: the CVE study catalog at the real corpus size (202 studies)

**Status**: **CLOSED** — T1–T7 done, each with its commit recorded below; open items C1–C7 remain,
with their blockers stated and nothing left implicit.
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
4. The map must **show** the collision instead of hiding it: **one ring per coordinate that carries
   more than one marker**, added behind the markers, while the panel stays the authoritative view
   (D9). **Corrected after T6**: the note states what the ring *means* and carries **no number**,
   because the artifact exposes no builder-produced collision tally and D9 forbids the frontend from
   deriving one. Making the count visible needs a builder-side field, recorded as open item C7.

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

### D15 — How the artifact/tool commit split stays green

**Context.** The project rule is that a regenerated artifact lands in its **own commit before** the
tool that produces it, so the review candidate is the tool and never the data. The naive split is
impossible for T3: the pinned shipped-artifact expectations (`31` studies, `{24,4,1,2}`, `21` species)
live in the same test file as the fixture tests, so regenerating the artifact under the old contract
would either leave the shipped tests failing or drag the whole contract change into the data commit.

**Decision.** Split by **what each test reads**, not by file:

- **T3.2 (data commit)** carries the regenerated `catalogo-estudios.{json,csv}` **and** the
  shipped-artifact expectations — the pinned constants, their mutation controls and
  `EXPECTED_ESPECIES_NON_NULL`. Those assertions only read the committed JSON, so this commit is green
  while the fixture tests still exercise the old tool.
- **T3.3 (tool commit)** carries the contract rewrite, the new fixture tests, the `schema_version`
  anchor and the freshness assertion, and it is green because the artifact already matches it.

No commit in the sequence is red, and the contract change's review candidate is still the tool.

**Mechanics, so it is not improvised at commit time.** The two groups live in one file, so the split is
built deliberately: the writer implements the whole change (tool + both test groups) **without
touching the shipped-artifact expectations**, which stay at the old 31-row values and therefore still
pass against the still-old committed artifact. The parent then:

1. regenerates the artifact with the rebuild interpreter and verifies it against the taxonomy;
2. restores **HEAD's** version of the test file, re-anchors only the shipped-artifact expectations to
   the new artifact, and commits **T3.2 = artifact + those expectations**, green against the old tool;
3. restores the writer's version and commits **T3.3 = tool + fixture tests + anchors + docs**, green
   against the new artifact.

The parent also asks the writer to **report** every shipped-artifact assertion the new artifact
invalidates (`file:line`) instead of changing it, so the re-anchoring is done once, in one place, and
cannot silently miss an assertion.

**Revised by execution: the split is impossible, and T3 lands atomically.** The plan above assumed
the shipped-artifact expectations could be re-anchored on their own. They cannot, because they live
inside `assert_catalog_contract` — the same function the new contract *must* change, since it is what
asserts the class order, the new per-study fields and the provenance block. There is no partition in
which that function is green before the artifact is regenerated, and the freshness assertion could
never pass against the old artifact at all: it carries no `source_sha256` to compare.

So **T3.2 and T3.3 are one atomic commit** — artifact, tool, tests and this document together. The
data/tool separation exists to keep generated data out of the review candidate; here the artifact *is*
part of the deliverable and its contract is asserted by the very code that changed, so splitting would
only produce a red commit. Review focus for that commit is the tool and the tests; the artifact's
numbers are tabulated in 4.7 instead of read off the diff.

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

### 4.7 The regenerated artifact (T3), measured

`catalogo-estudios.json` 749.7 KB, `catalogo-estudios.csv` 147.2 KB, both versioned. Rebuilt twice in
a row: the runs differ **only** in `generated_utc` and the **CSV is byte-identical**.

| Quantity | Value |
|---|---|
| `study_count` / `schema_version` | 202 / **2** |
| `classes` | `placeable` **103** · `coarse_location` **80** · `outside_extent` **10** · `no_coordinate` **9** |
| `display_contract` | `map_visible_count` 103, `excluded_count` 99 |
| Provenance | `source_sha256` `111a0d05…`, `source_rows` 202, `source_bytes` 295 581 |
| Granularity levels | T2 113 · T0 60 · T1 29 |
| Collision groups | 23 coordinates shared by more than one study, the largest with **11** |
| `palabrasclaves` non-empty | 82 of 202, byte-for-byte the Parquet column |
| Undated studies | 16, all with a `cve-sin-anio-…` id, all sorted last |
| CSV | 1 header + 202 rows |

**Every one of those numbers was recomputed independently by the parent** from the Parquet and the
curated taxonomy, not read from the tool's own output: the class counts, the granularity tally, the
collision attributes of all 202 studies (size, ids, self-exclusion, `len(ids) + 1 == size`), the
exclusion reasons (each carrying its level, its verbatim text and its curated reason), the keyword
lists against the source column, and the CSV line count. All matched.

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

**The evaluation order has a consequence that must be stated, not discovered.** A study can be coarse
*by its text* and still have no coordinate — the 9 rows whose location text is empty are classified
`T0` by rule A of section 6 and carry no `latitud`/`longitud`. For those, the class is
**`no_coordinate`**, because coordinate absence is decided first, and the taxonomy level is still
recorded as `T0` alongside them. So the invariant is not "`coarse_location` iff T0/T1" but the
coordinate-conditional form: with coordinates, T0/T1 means `coarse_location`; without them, T0/T1
means `no_coordinate` with the level preserved. Measured in the shipped artifact: `coarse_location`
80 (51 T0 + 29 T1), `no_coordinate` 9 (all T0), `outside_extent` 10 and `placeable` 103 (all T2).

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

Result, **after the human review**: **T0 60, T1 29, T2 113**, which under the D12 evaluation order
leaves **103 placeable / 80 coarse_location / 10 outside_extent / 9 no_coordinate**. The F4 contract
on the same rows gave 107 placeable — a similar *number*, for entirely different reasons: it
excluded studies for sharing a coordinate, including the Mérida and Lago de Maracaibo clusters,
while the taxonomy excludes the mentions that name no place and keeps those clusters on the map.

**Every entry records the location text it classifies** (`texto`). Without it the file would be a
list of opaque `source_path` keys that no reviewer could judge from the diff, which would defeat the
whole point of a curated file. The text is not decoration: `check_granularity_coverage` fails when
the recorded text no longer matches the corpus row, so an upstream extraction fix stops the build
until a human re-judges the level.

**43 entries carry a `nota`** recording a boundary call that was argued; **28 of them concern a
mention with at least one study inside the map extent**. The file states its own convention: a `nota`
marks a case that was discussed, the `nivel` is the decision.

**The human review of 2026-10-14** walked the consequential cases one by one and changed **four
levels and no location text**: `Golfo de Venezuela`, `Golfo Triste` and the `Desembocadura del
estuario de Maracaibo` moved T1 → T2 (each a bounded feature whose own row already sits on or beside
a mapped point), and `Mar Caribe, Venezuela` moved T0 → T1, which does not move the map because both
levels are excluded. The outcome is recorded in the file's top-level `reviewed` block.

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
  control fail. At that point the file carried **zero bare `assertRaises`** and 79 `assertRaisesRegex`
  sites.
  - **Correction, at close.** The file now has **87 `assertRaisesRegex`** sites and **exactly one**
    bare `assertRaises`, added by T3.3 in
    `test_control_a_missing_required_argument_is_a_usage_error`. It is deliberate and not a vacuous
    check: it captures the `SystemExit` object in order to assert `caught.exception.code == 2`, which
    is the branch's pin, and a mutation that made `--granularidad` optional would fail it. The T2
    sentence above is left as it was written and correct **for that moment**; the claim about the
    file as a whole is no longer true, which is why it is corrected here rather than silently.
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

**Review outcome (2026-10-14), commit `05359af`.**

- **The effect was +3 studies, not +15.** Eight of the mentions I flagged as boundary calls were
  **already T2**, so accepting them changed nothing; only `Golfo de Venezuela`, `Golfo Triste` and the
  `Desembocadura del estuario de Maracaibo` were actually outside and moved inside (T1 → T2), and
  `Mar Caribe, Venezuela` moved T0 → T1 without moving the map. **100 → 103 markers of 202**, measured
  after the edit with the rebuild interpreter, which also re-ran `load_granularity` and
  `check_granularity_coverage` over the real Parquet: 202 rows ↔ 202 entries, no orphans, every text
  matching its corpus row.
- **Two errors of mine, both in the summary and neither in the artifact.** The first was arithmetic:
  I reported the review's effect as "+15 → 115 markers" by counting entries that were already
  placeable as if they were gains. The second was reading the pending list wrong: I presented
  `Laguna de Asfalto Guanoco` as a default I was correcting from T0 to T2, when the entry had always
  been T2 — the reasoning was right, the "correction" framing was false. The classification now
  encodes exactly the seventeen recommendations presented; what was wrong was how I added them up.
- The review also settled `Guanoco` in writing: its coordinate falls in Mérida state, 38 km from
  Lagunillas, and `Sucre` is also a municipality of Mérida, so the multi-state reading had followed
  the text rather than the place. Its `nota` is now a decision record instead of an open question.
- **Group decisions accepted as defaults**: a named site wins over the administrative apparatus that
  contains it (Municipio Campo Elías + Parroquia Jají, parroquia Canoabo, Valle de Caracas, Maracay +
  Estado Aragua, Isla de Margarita, and the rest); and the four mentions that name only
  administration — `Municipio Caroní`, `Municipio El Hatillo`, `Municipio Libertador del Distrito
  Capital`, `Estado Portuguesa, municipio Ospino`, `Programa Colorido` — stay outside the map.

### T3 — Builder at 202, new contract, artifact regenerated

Three work-unit commits inside one task, in this order:

**T3.1 — Undated studies (D14). — DONE.** `make_study_id` handles a null `anio`
(`cve-sin-anio-pagina-5-1`) and the artifact order became a total `study_sort_key` instead of a
lambda that raised on `None`; dated studies keep their existing relative order and undated ones sort
last. Builder and tests only: the committed artifact was **not** regenerated, so the pinned contract
tests stayed green.

- **Evidence, run end to end by the parent with the rebuild interpreter** (the writer could not: no
  `pyarrow`, and the artifact must not move in this commit): the builder now completes over the real
  202-row corpus, twice in a row. `study_count` 202; **16 studies with `anio` null and 16 ids carrying
  the `sin-anio` segment**, all ids unique; **the last 16 studies are exactly the undated ones**; the
  two runs differ **only** in `generated_utc` and the **CSV is byte-identical**.
- **T1's deferred proof is closed here**: the emitted `source_sha256` equals the real
  `sha256` of the input (`111a0d05…`), with `source_rows` 202 and `source_bytes` 295 581.
- **Cross-validation**: this run, still on the **old** contract, produced exactly
  `107 placeable / 69 shared_coordinate / 17 outside_extent / 9 no_coordinate` — the same numbers
  measured independently by hand in 4.2, reproduced this time by the builder itself.
- Suite 222 → **232 tests OK**; zero bare `assertRaises` (79 `assertRaisesRegex`); two mutations
  reverted byte-identically, one showing that `str(None)` in the id is caught by the `^[a-z0-9-]+$`
  guard (`cve-None-pagina-607-1`), the other showing that flipping the sort flag breaks the order
  tests. The artifact's bytes are unchanged (`fee40a59…` JSON, `a8955935…` CSV).

**T3.2 / T3.3 — one atomic commit (D15 revised). — DONE**

- One commit carries the contract rewrite, the regenerated artifact, the tests and this document,
  because the shipped-artifact expectations live inside the function the contract change must modify
  (D15, revised).
- **The writer stalled mid-task and delivered no handoff.** Its working tree was recovered and
  verified by the parent instead of taken on trust, and that verification paid: `assert_catalog_contract`
  asserted `schema_version == 1` while the tool emits `2`. That one stale literal fired before every
  other branch and made **27 unrelated mutation controls report the schema-version mismatch instead of
  their own target branch** — a green-looking suite with a whole layer of controls silently
  miscalibrated. Fixed, and the controls now derive their numbers from the constants (`f"study_count
  is {EXPECTED_STUDY_COUNT - 1}"`) instead of hardcoded literals, so the next refresh cannot desync
  them in silence.
- **Evidence**: **281 tests, OK** on the bare interpreter (1 skip, `pyarrow`-gated) and **281 tests,
  OK, zero skips** on the rebuild interpreter, which exercises the freshness checks including their
  mutation control. Independent recomputation of every number in 4.7 against the source data, all
  matching.
- **Seen red**: disabling the taxonomy exclusion in the tool (`if False:`) produces **7 failures**,
  and the file was restored **byte-identical** (sha256 `505664a9…` before and after). A green suite
  that has never been shown to fail is not evidence.
- Tests: pinned constants at `tests/test_study_catalog_contract.py:73-82` recomputed; the six
  mutation controls at `:512-513, :578, :641-642, :657-658, :662-663` re-anchored;
  `EXPECTED_ESPECIES_NON_NULL` 21 → 162; new controls for every new branch; a `schema_version`
  anchor test; and the **freshness assertion** (committed artifact vs parquet on disk) with a control
  that mutates a fixture copy and sees it fail.
- Evidence: two consecutive rebuilds differ **only** in `generated_utc` and the CSV is
  byte-identical; class counts close against `study_count`; the taxonomy's own T0/T1 tally equals the
  artifact's `coarse_location` count.

### T4 — API invariants and packaging — **DONE**

**Commit**: `f0a8bc4`.

- Eight new import-time invariants in `tools/serve_viewer.py`, each naming the offending study:
  the level is `T0`/`T1`/`T2`; the coordinate-conditional class rule (section 5);
  `granularidad_razon` non-empty exactly for T0/T1; `palabrasclaves` a list of strings;
  `coordinate_group_size` null exactly without coordinates and an int ≥ 1 otherwise;
  `coordinate_group_ids` sorted, unique, self-free, referencing existing ids, with
  `len(ids) + 1 == size`; every referenced study at the same coordinate; and **symmetric membership**,
  so if A lists B then B lists A. The group is deliberately **not** asserted to share a display class:
  the four Barinas studies mix T1 and T2.
- `run.sh`: `stage_studies` (rebuild-only, wired after the tiles stage, refusing with the actionable
  hint that the rebuild needs an environment carrying `pyarrow` — the system interpreter has GDAL but
  not pyarrow), and two new `cmd_check` items: the studies catalog as `[serve]` and the congress
  Parquet as `[rebuild]`, since `data/raw/` is gitignored and a fresh clone will not have it.
- **A contradiction in this document's plan, caught by the writer before it wrote any code.** The T4
  brief asserted "`coarse_location` iff T0/T1". That is false against the real artifact: the 9 studies
  with no coordinate carry level `T0` (rule A of the taxonomy classifies an unusable location text as
  T0) while their class is `no_coordinate`, because coordinate absence is decided first. The writer
  stopped instead of inventing a semantics. The resolution is the coordinate-conditional form now
  written in section 5, and it was verified independently before being adopted: 0 violations of
  `coords is False ⟺ no_coordinate`, of "T0/T1 with coordinates ⇒ coarse_location" and of
  "placeable/outside_extent ⇒ T2" across all 202 rows.
- **Evidence — tests.** 308 tests OK on the system interpreter (with **28 skips**: the 27 new ones need
  `fastapi` and the freshness row-count check needs `pyarrow`), 27/27 OK under the repository `.venv`,
  and **308 tests OK with zero skips in a single interpreter** carrying GDAL, `pyarrow` and `fastapi`.
  That last run is the honest statement of the project's dependency split: **no documented runner
  executes the whole suite**, because the dependencies are deliberately disjoint (T7 documents this).
  The `.venv` additionally errors on `test_composition_summary_schema`, which needs `osgeo` —
  pre-existing, documented in that file's own docstring, and unrelated to this task.
- **Evidence — the service.** Every endpoint returns 200 (`/api/health`, `/api/meta`,
  `/api/composition/series`, `/api/composition/year/2024`, `/api/studies/catalog` at 664 630 bytes,
  `/api/studies/_load_counters`, and a real tile `/tiles/1985/0/0/0.png`); an unknown id returns **404**
  with `study not found: no-existe`; the catalog serves **202 studies, `schema_version` 2**, contract
  `103/99` and the four classes; and the parse-once invariant is **measured, not asserted**:
  `catalog_calls` reads 1 before and 1 after 24 requests.
- **Evidence — the refusal, with its exit status.** With one group's symmetry broken the service
  exits **1** with
  `viewer: studies catalog missing or malformed: studies catalog study 'cve-1991-pagina-8-2' has coordinate_group_size 4 but 2 coordinate_group_ids (expected 3)`,
  and returns to exit 0 once the artifact is restored **byte-identically** (sha256 `78159412…`).

### T5 — Panel at 202 — **DONE**

**Commit**: `8233387`.

- **Bounded list.** `.catalog-list` is capped with `min-height == max-height = min(70vh, 720px)` and
  `overflow-y: auto`. Measured at 1280x900: a **630 px window over 13 015 px of content**, with the
  document at 4 250 px where the uncapped list alone would be ~13 000. The detail column keeps
  `max-height: none`.
- **This reverses an earlier deliberate decision, and the record says so.** F4's `catalog.js`
  documented "no inner scroll region and no max-height: the document scrolls when the list grows, so
  no study row ... can be trapped inside a fixed-height cap". That was written for 31 rows; with 202
  the panel became tens of screens tall and the detail column was lost while scrolling. What the old
  comment protected is preserved **by measurement**: every row is a native `<button>`, Tab reaches all
  202, and focusing row 181 scrolls the **list**, not the document.
- **Density.** The first cut showed **4.5 rows** (496 ÷ 114 px) — about 44 screens for 202 studies —
  because the title wrapped to three lines. The title now clamps to two lines with the full text kept
  in a `title` attribute (202 rows carry it; **16 are actually clamped**) and meta + author + badge
  share one line: rowHeight **63.8 px**, **9.2 rows visible** at 1280x900 and 5.8 at 1042x569, with
  **zero wrapped meta lines** at the wide viewport.
- **Search** over title, author names and `palabrasclaves`, accent- and case-insensitive and combined
  with the edition filter: `merida` = `Mérida` = 10 rows, `RIO ORINOCO` = 5, `gavidia` = 1, a nonsense
  query = 0 with the empty state, clearing restores 202. Document height and `scrollY` do not change
  while narrowing (4066 → 4066, 1200 → 1200), which the `min-height == max-height` equality is what
  guarantees. **An earlier reading of mine that showed a 703 px jump was my test's fault**: `page.fill`
  focuses the input and the browser scrolls it into view.
- **Badge**: 99, exactly the excluded rows, tally 80/10/9 matching the artifact's classes, all inside
  the meta line, **none with the placeable label**. The text is the builder's `classes[].label_es`
  verbatim (D9). It first shipped on all 202 rows with `Ubicable` on 103 of them — noise, not
  information, and my brief's fault for listing that label — and the original placement was restored.
- **The first author went back into the row** (`Peterson, George · 1 autor` on all 202 rows, 0
  count-only) after my brief dropped it by asking for "the author count". The name is a strong scan key
  in a catalog of one's own field, and the count alone is not a substitute.
- **Detail**: the full `exclusion_reason` renders **verbatim** — checked in the browser against the
  artifact's own string (153 characters for `cve-1991-pagina-5-2`).
- **Selection**: exactly one `.is-selected` after a click, and exactly one after clicking another.
- 13 filter buttons (`Todas (202)` plus the twelve editions, `XI · sin año (16)` last); the 16 undated
  studies render `sin año`, are the last 16 in order, and no row contains `null` or `NaN`.
- Console: **0 errors, 0 warnings**.
- **Residual gap, stated rather than implied**: the panel has **no persisted automated test**. Its
  logic was checked with a throwaway headless DOM stub (not committed) and its layout evidence is this
  browser pass, which no CI run reproduces. T7 records it as a known hole.

### T6 — Map: the collision becomes visible — **DONE**

**Commit**: `e944e38`.

- New `studies-halos` source and `studies-halos-ring` layer, added **before** the marker layer so
  MapLibre paints it underneath, with **one ring per coordinate** and never one per study — otherwise
  the rings would stack exactly like the markers do. Measured in the live sources: **103 markers,
  12 rings**, a `marker_count` multiset of `{5, 4, 3, 3, 3, 2×7}` summing **32** drawn studies, and 12
  distinct ring coordinates.
- The ring interpolates its radius 9 → 18 against the marker's 4 → 8, so the annulus is ~2.2x the
  marker's diameter at the default zoom. Probed on the canvas: 12 px from the centre hits the ring and
  **not** the marker.
- **The trap the brief named, confirmed against the data**: two rings carry a
  `coordinate_group_size` that differs from what is drawn — Barinas 4 in the catalog and 2 drawn,
  Mérida 6 and 4 — because the artifact counts every study at that coordinate regardless of class.
  The ring is driven by the **drawn** markers; the catalog number travels on the feature and is
  deliberately **not rendered**.
- **One ring per coordinate, one marker per study.** The ring is an annotation, not an aggregate and
  not a counter marker, so D9's rule 1 still holds.
- **Clicking a stacked marker**: `queryRenderedFeatures` at the Lago de Maracaibo coordinate returns
  **5 features**, and clicking there selects exactly one study (`.is-selected` count 1) whose detail
  reads `Lago de Maracaibo, Venezuela`. Which member of the stack wins is MapLibre's own order, not
  our code — that was already true before this change.
- **Overlays**: a third child inside F4's content-sized column, so it inherits the no-overlap
  guarantee instead of re-tuning offsets. Measured bounding boxes at 1280x900 and 1042x569 give
  **zero overlaps** among the legend, the ring note, the D7 note and the MapLibre attribution. The
  toolbar clearance is clear in the 1280 view; at 1042 the column sits at the map's bottom edge and
  the toolbar at its top, which is F4's `bottom: 40px` structure and not a new offset. **The toolbar
  distance was eyeballed, not measured pixel by pixel**, and it is stated as such.
- **A contradiction the writer caught, and my own text was at fault.** D12 point 4 said the note
  "states how many studies share a coordinate", while my T6 item 3 forbade frontend-derived counts.
  Both cannot hold: no builder-produced collision tally exists. The writer followed the more specific
  instruction and refused to improvise. D12's wording is corrected above and the missing count is
  item **C7**.

### T7 — Closing — **DONE**

**Commit**: `1a57427`.

- **`README.md` gained what F4 never wrote.** A **"The study catalog"** section: the corpus, the panel
  as the authoritative view with the map secondary, the contract and its four classes with counts,
  the ring, the provenance chain, the curated taxonomy and its text-verification rule, and the
  `study_gap` warning. Plus a bullet in "What the viewer shows", a ring bullet in "Behaviours that
  look like bugs but are not", the studies stage in "Rebuilding the data" with the `pyarrow`
  refusal, and three bullets in "Limitations": the **runner matrix**, the panel's missing automated
  test, and the `study_gap` pointer.
- **One stale enumeration fixed**: "What *is* versioned" listed the codebook, the composition CSVs and
  the manifests but not the study catalog, which is tracked.
- **One bullet checked and deliberately *not* changed**: "The page scrolls instead of the panel" is
  about the **composition** panel and is still true — T5 capped the *catalog list*, a different panel.
  The distinction is now stated once, in the catalog section, so a reader cannot conflate them.
- **Every number in the new prose traces to a measured value.** The writer was told not to compute or
  round anything and reported the source of each figure; it declined to add a row to the stage table
  because no cost had been measured for the studies stage, and said so instead of inventing one.
- `docs/` holds only `.gitkeep`, so nothing else in the repository described the viewer.
- **Open items are current**: C1–C7, including C3's reversal (the keywords exist) and C7 (the ring
  note carries no count, because no builder tally exists).

## 8. Open items

| # | Item | Blocks |
|---|---|---|
| C1 | `data/raw/` is gitignored, so the parquet is not versioned and a fresh clone cannot rebuild the catalog | Rebuild only. T1 records the input's identity, which detects drift but does not make the input available |
| C2 | Four studies share one coordinate and one study is mislocated in Puerto Rico | **Superseded by D12**: the collision is now an exposed attribute, and the Puerto Rico study is `outside_extent`. The coordinate is still never edited (D11) |
| C3 | `palabrasclaves` empty, so keyword search cannot be offered | **Closed, reversed**: 82 of 202 rows carry keywords. T5 can offer search |
| C4 | The `study_gap` rationale in `tools/priority_schema.py` names D2 and reads as stale | Nothing yet. Section 6 of the parent document is the answer; with 202 studies the term is still insufficient for an H3 res 8–9 index. Do not flip it |
| C5 | **New**: decide whether the raw parquet is versioned in this repository or the sync from `Congresos_CVE_V2` becomes a documented, hash-checked mandatory step | A fresh clone's rebuild. A decision, not a task |
| C6 | **New**: 16 Vol XI rows have `anio` null (legacy CSV ETL) | Any per-year study layer (stage E2) will have 16 undated studies |
| C7 | **New**: the map overlays carry no collision tally, so the ring note explains the ring without a number | A builder-side `display_contract` field (a coordinate count and a marker count) plus its API invariant would make the number visible. Recorded, not scheduled: it reopens the artifact, the validator and the pinned expectations for a figure of modest value |
| C8 | **New, measured**: the panel's search covers title, author names and `palabrasclaves` **only**, so a query by **place** or by **species** silently misses rows. Measured against the artifact: adding `ubicaciongeografica` and `especiesmencionadas` to the haystack finds far more — across 346 genera sampled from the 162 studies that carry a species list, **288 improve**, gaining **355 study matches** in total (`Reptiles` 0 → 4, `Atelopus` 0 → 3, `Aves` 8 → 14, `Peces` 6 → 12), and place names too (`morrocoy` 1 → 4, `merida` 10 → 14, `orinoco` 7 → 10). The artifact already carries both fields, so the fix is a two-field change in the panel plus its label copy | A product decision on what the search covers. **Recommended**, because a species query returning zero is the query an ecologist is most likely to make |
| C9 | **New**: `data/curated/congresos/granularidad-ubicaciones.json` was pre-filled by a **one-off script that is not committed**. The file states its own rules in section 6 and every T0/T1 row carries its reason, and the recorded text is verified against the corpus, so the artifact itself is sound — but the next corpus growth would have to redo the pre-fill by hand | Nothing today. A committed helper that only *proposes* entries for unclassified rows, never overwriting a reviewed one, would close it |

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
