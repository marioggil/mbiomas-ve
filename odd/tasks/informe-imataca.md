# Case study: Imataca — coverage across the congress years

**Status**: planning · **Owner's frame**: *"seleccionar un cuadrado en una región que contenga los puntos con coordenadas de
Imataca… primero poder ver cómo evolucionan las distintas coberturas cuando se realizaron los congresos."*

## 1. The case, measured

**The box** (the tightest one that still holds every study of the zone, and inside the clip's pixel bound):

```
w = -61.746314, s = 6.60103, e = -60.246314, n = 8.00103     165 x 156 km, 25,764 km²
```

**Why this zone.** Imataca is the corpus's most shared coordinate: **28 studies sit on one point** (`-60.996314,
7.30103`, the reserve's centroid) because the reserve is a *named place* in the curated taxonomy. The box around it holds
**30 studies, all with a usable coordinate (T2), across 8 editions**, and it is the richest zone in the corpus. It is also
the case that makes the corpus's provenance limits visible, which is §3.

| | Value |
|---|---|
| Studies in the box | **30** of 255 (all `placeable`, all T2) |
| Editions present | **8**: 1999 (2), 2001 (3), 2003 (6), **2005 (9)**, 2007 (2), **2011 (1)**, 2013 (2), 2019 (5) |
| With parsed species | 14 |
| Talk-institution pairs | **39** across **10** institutions |
| The clip for 2024 | 13 level-2 classes, **Bosque 88.05 %**, water (5.1) 0.43 %, **`nodata_area_ha = 0.0`** |
| The clip's cost | ~0.7 s for a full request |

## 2. The question this phase answers

**How did the coverage of that box change between the congress editions?** Concretely: for each of the 8 edition years —
and, as anchors, 1985 (the series' first year) and 2024 (the present) — the level-1 and level-2 composition of the box,
with the shared classes' deltas across the decade.

## 3. The study's frame: an observation window, and one declared assumption

### 3.1 The assumption (declared, not hidden)

The owner's decision: **for this study, a talk reviewed by the machine is treated as being on the same footing as one reviewed by a person.**

That is an assumption, and a published piece states it in the text rather than leaving the reader to discover the split:

- **24 of the 30** studies in the box carry the machine flag (`mario` 6, `IA` 24), against 43 of 255 corpus-wide.
- The flag **stays in the data** (`human_reviewer` per study), so a reader who disagrees with the assumption can recompute any figure excluding those 24 — the assumption is defensible because it is checkable, not because it is convenient.
- The concentration is worth knowing even under the assumption: **8 of the 9 talks of 2005 are machine-reviewed**, 5 of 5 in 2019, 5 of 6 in 2003. With the assumption these counts are usable as counts; without it they would be unusable as a trend. Both statements belong in the piece, one as the assumption and one as context.

**Not covered by this assumption**: the **doubtful ROR assignments** are a different question (whether the institution the identifier resolves to is the one the abstract names). **5 of this box's 39 talk-institution pairs** come from the corpus's 16 doubtful institutions. That decision is taken separately (§7.4a).

### 3.2 The thesis: we were watching, not causing

The owner's decision: **nothing in this study claims that the congresses produced the changes.** The congresses were the **observation window**: each edition is a moment at which somebody looked at this zone and wrote down what was there — the species, the place, the institutions. The coverage series is what the land did over the same period.

So the study has **two parallel series**, and the piece says so in its own words:

| | What it is | Where it comes from |
|---|---|---|
| **A. What the land did** | the box's composition across 10 years (8 edition years + 1985 + 2024) | the clip API, one call per year |
| **B. What was observed and recorded** | the talks about that zone, per edition: how many, what species, which institutions | the studies artifact |

The rules that follow from this framing, and that the piece must respect:

1. **The two series are never merged into one figure** and never placed on one axis. A single chart of "coverage vs talks" would invite exactly the causal reading this study refuses.
2. **The coverage curve does not depend on the editions at all.** The edition years are samples of a continuous series — a window the owner chose — so their labels are a frame, not a driver.
3. **The talk counts are counts of a record, not of interest.** "More talks about Imataca in 2005" describes who recorded what and when; it is not a statement about the congress's interest in the zone.

### 3.3 What the numbers already say

| Class | 1985 | 2024 | Change |
|---|---|---|---|
| **1.1 Bosque** | 89.91 % | **88.05 %** | **−1.86 pts (−47,844 ha)** |
| **3.1 Uso pecuario** | 1.70 % | **2.79 %** | **+1.10 pts (+28,275 ha)** |
| **4.3 Uso Minero** | 0.04 % | **0.42 %** | **×10 (+9,932 ha)**, accelerating after 2013 |
| 2.2 Sabana/Herbazal | 3.60 % | 3.78 % | +0.19 pts (+4,822 ha) |
| 5.1 Río, lago u océano | 0.36 % | 0.43 % | +0.07 pts (+1,742 ha) — inside the class-33 caveat of `README.md`: no water claim beyond the two corroborated cases |

The mining class's shape — 0.04 (1985), 0.08 (2005), 0.12 (2011), 0.16 (2013), **0.28 (2019), 0.42 (2024)** — is the strongest single figure the study produces, and it is a measured change in the official classification inside a declared box.

**And one product gap the case exposes**: the composition chart's series covers the whole mapped extent and does not
follow a drawn window, so **the box's evolution cannot be read off the chart** — it has to be assembled from one clip per
year. That is the "open work" item in `KNOWN-GAPS.md` §4.7, now with a concrete user need behind it.

## 4. Method: where each number comes from

- **The numbers: the API.** `GET /api/clip-stats?year=<Y>&bbox=-61.746314,6.60103,-60.246314,8.00103` returns the box's
  level-1 and level-2 composition for that year with `total_window_area_ha`, `valid_area_ha` and `nodata_area_ha`. One
  call per year (10 for this phase), reproducible, and it is the same computation the viewer performs. The viewer's own
  UI has no export (`KNOWN-GAPS.md` §3), so transcribing the panel would be neither reproducible nor cheap.
- **The visual: the viewer.** The coordinate field commits the same box (so the screenshots and the API share one
  identity), the map shows the box at each year, and the composition panel shows the same breakdown the API returns —
  useful as an independent cross-check of one year.
- **The traceability: the provenance blocks.** Each year's figure comes from that year's COG: the panel's footer serves the
  year's `output_sha256`, the composition artefact's `schema_version` and `generated_utc`, and the recompute path. The
  report carries those, plus the consultation date and the repository commit.
- **The cross-layer part (phase 2, if wanted): the catalogue's metrics block** for the same box — the talks per edition,
  the species, the institutions — with the granularity flag, the review split and the doubtful-pair watermark.

## 5. The report's structure (from the reader's template, with this case's specifics)

1. **The frame**: the box's coordinates, its size, the year(s), and **why this zone** (§1).
2. **The caveats, before any figure**: the mapping extent is 1,086,229.52 km² vs the 916,445 km² recognised
   internationally → **~18 %** difference from official figures; the areas are geodesic (WGS84, authalic radius
   6,371,007.181 m); and the two findings of §3 that bound what the reader may conclude.
3. **The evolution table**: per year, the level-2 classes with their share **of the box** (the window = the valid area here,
   because `nodata` is 0 — and that equality is itself a finding to state), plus the deltas for the classes that matter.
4. **The reading of the trend**, with the confound of §3.2 stated in the same paragraph as the trend itself.
5. **The cross-layer section** (phase 2): what the congresses said about that zone, by edition, with its own caveats.
6. **The provenance**: the box, the years, the digests, the consultation date, the repository commit, and the fact that
   no automated test guards the viewer (`KNOWN-GAPS.md` §1).
7. **The licence line**: CC BY 4.0 attribution in the terms' own format, plus the "adapted" statement — mandatory if the
   report republishes the figures.

## 6. Tasks this plan implies

| # | Task | Verification |
|---|---|---|
| 1 | Fix the box and the year list (10 years: the 8 editions + 1985 + 2024) | The box inside the clip's pixel bound and holding all 30 studies, checked against the artifact |
| 2 | Collect the API's responses for those 10 years | Every response carries `schema_version`, the bbox echoes the request, and `window = valid + nodata` |
| 3 | Assemble the table and the deltas | Recompute two years independently by hand from the CSV/summary artifacts and compare |
| 4 | Reconcile one year against the panel in the browser | The panel's breakdown for the same box and year matches the API's, field by field |
| 5 | Collect the provenance for each year's COG | The digests on screen equal the manifest's, checked against the JSON, not against the viewer |
| 6 | Write §3 (the confound) with its numbers | The per-edition review split recomputed from the artifact |
| 7 | Phase 2: the cross-layer section | The metrics block for the same box, with the doubtful pairs identified by name |

## 7. Decisions taken by the owner (frozen)

1. **The box**: the tight one, `-61.746314, 6.60103, -60.246314, 8.00103` — 165 x 156 km. The 200 x 178 km candidate is
   not viable: the clip refuses it.
2. **The years**: the eight editions with studies **plus 1985 and 2024** as anchors — **ten**. They are what lets the
   report say what happened before and after the congress period, which is the context that gives the evolution meaning.
3. **The scope of this phase**: the coverage evolution **and the cross-layer reading** (what the congresses said about
   that zone, per edition).
4. **A published piece.** This is the decision that adds obligations, and they are not optional:
   - the **CC BY 4.0 citation in the exact format the terms prescribe** (collection, series, consultation date, link) plus
     the statement that the product is **adapted** — the filled-in sentence is in `NOTICE.md`;
   - **no water claim beyond the two externally corroborated step changes** (`README.md` § Limitations, class 33);
   - the extent caveat with its number (**1,086,229.52 km²** vs **916,445 km²**, **~18 %**) stated where figures are read;
   - the consultation date, the repository commit and each year's COG digest, because a published figure has to be
     traceable;
   - and, if the piece republishes any figure, the fact that **the viewer has no automated test** (`KNOWN-GAPS.md` §1):
     the figures are measured, not guarded.

**Consequence for the writing**: the three findings of §3 are part of the published piece, not an internal annex. A
published trend over this zone without the review confound is a claim the repository cannot defend — and defending the
figures is what this product is for.

## 8. Evidence and assembly

The collection lives in `odd/informes/imataca/` beside this plan: `evidencia/clip-<year>.json` with the ten raw API
responses, `evidencia/procedencia.json` with each year's COG identity, and the assembled table. That directory is the
report's evidence; a published piece cites it.
