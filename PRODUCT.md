# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

**Primary: the MapBiomas Venezuela team and the allies it answers to**, at a desk, in long
analytical sessions. They open the viewer to prepare figures, answer requests about land cover over
the 1985–2024 series, and show what changed inside a specific area.

Desktop is the target. The phone is **not** a declared context, so the disposition is optimised for
a large screen and no mobile requirement is pending. An audit on 2026-10-15 measured the mobile
stack — at 390×844 the map sits 1.75 screens down, the edition filters take five rows and the chart
text falls to 9 px with 6 px axis ticks. Those are recorded measurements, not a backlog, until
someone declares phone use a goal.

## Product Purpose

To publish the MapBiomas Venezuela Collection 3 cover-and-use rasters as a browsable annual series
with statistics the team can defend: the annual map on a 1985–2024 slider, a composition panel for
the whole series and for the selected year, statistics for a drawn area and — as a secondary layer —
the 255 studies of the Congreso Venezolano de Ecología placed over that coverage.

**Every area figure covers the MapBiomas mapping extent, not recognised borders.** The extent is
1,086,229.52 km², about 169,600 km² more than Venezuela's internationally recognised 916,445 km²,
because it includes disputed territory, and no boundary mask has been applied. The interface states
this on the map and on the composition panel, and anything derived from this repository must state
it too or it will disagree with official figures by roughly 18 %.

## Positioning

Two things a neighbouring product could not truthfully copy, both confirmed as the point:

- **The computation is ours and it is auditable.** Composition over the series, and the statistics
  for a drawn area, are calculated here from the MapBiomas GeoTIFFs, with versioned inputs, recorded
  digests and a freshness assertion that fails when the input changes without a rebuild. The
  official site publishes a map and its own figures; here the figure can be recomputed and traced
  to the artefact that produced it.
- **Coverage is crossed with the congress bibliography.** The 255 verified studies of the Congreso
  Venezolano de Ecología are geolocated over the coverage and carry metrics per drawn area — species
  mentioned, contributing institutions by ROR. That cross is a different source with its own
  provenance, not part of the MapBiomas dataset.

Two real capabilities are **not** the positioning, because they were not confirmed as such: running
without CDNs or third-party services, and the multi-country design aimed at the rest of the
MapBiomas region. They are facts of the implementation (below), not claims the product is sold on.

## Operating Context

- **The data is not in this repository.** The raw GeoTIFFs (2.9 GB), the COGs built from them
  (4.4 GB), the tile pyramid and the congress inputs live outside Git and are mounted at deployment.
  The derived statistics do travel, committed.
- **Rebuilding is one pipeline**: `./run.sh pipeline` runs the codebook, COG normalization
  (~25 s/year), composition statistics (~38 s/year) and the tile pyramid (~140–164 s/year). The
  studies stage needs an interpreter carrying both `pyarrow` and GDAL, which the service image
  deliberately does not have.
- **Serving is self-hosted**: uvicorn inside a container behind their own reverse proxy
  (Dokploy/Traefik compose, no published host port).
- **Publishing carries an obligation**: the data is CC BY 4.0, so any published product needs the
  citation in the format the terms specify, filled for Collection 3, plus the change notice —
  recorded with the date the terms were read in `NOTICE.md`.
- **The congress corpus arrives as an export**: a Parquet produced upstream in `Congresos_CVE_V2`,
  dropped into `data/raw/congresos/` and gitignored; the study catalog derived from it is rebuilt
  and committed.

## Capabilities and Constraints

Capabilities: the annual cover-and-use map over 1985–2024 with the official palette and a
hierarchical legend (26 classes in 6 level-1 groups) taken from the codebook; a composition panel
with the 40-year level-1 series and the level-2 breakdown of the selected year; statistics for a
rectangle drawn on the map; the congress study catalog panel with its drawn-area metrics block.

Constraints future work has to respect:

- The interface speaks **Spanish**, and class and group names come from the official codebook.
- **No CDN and no remote script or stylesheet dependency**: MapLibre is vendored, as the rest of the
  viewer's assets are.
- Raw inputs are never versioned; derived artefacts are, each recording the digest of its input and
  a freshness test that detects drift.
- The service image carries neither `pyarrow` nor GDAL: rebuilding is a separate environment.
- **The source code has no licence.** CC BY 4.0 governs the MapBiomas data, not the software.
  Choosing a code licence is an explicitly open decision.
- **The viewer has no persisted automated test.** Its logic is verified with throwaway harnesses and
  browser passes; no CI run covers it.
- The `study_gap` term of the priority index stays disabled at weight 0.0: 255 studies cannot
  populate an H3 res 8–9 gap index, and an invented gap would read as evidence.

## Brand Commitments

- **"MapBiomas" and its marks belong to the MapBiomas network.** The name is used to attribute the
  source, as CC BY 4.0 requires; nothing here implies endorsement, sponsorship or review, and no
  logo or badge file from their site is copied into this repository.
- The attribution and the citation are **not optional decoration**: they are the condition of using
  the data, and they live next to the data in the viewer, in `README.md` and in `NOTICE.md`.
- The incumbent voice **states limitations where the number is read** — the unmasked extent on the
  map and the composition panel, the classes the map cannot place in the catalog list, the doubtful
  institution assignments declared beside the chart. Recorded as the existing voice; not confirmed
  as a binding principle.

## Evidence on Hand

| What | Where |
|---|---|
| The class codebook: 26 classes, 6 groups | `data/legend/venezuela-collection-3.json`; the official PDF and QGIS style, unmodified, in `data/legend/source/` |
| Committed composition statistics | `data/derived/venezuela/collection-3/composition-*` (per-class CSV + summary JSON) |
| The 255-study congress catalog | `data/derived/venezuela/congresos/catalogo-estudios.json` (+ CSV); the curated location taxonomy and the curated ROR table in `data/curated/congresos/` |
| Measured numbers | `README.md`: answering latency, stage costs, and the structural findings (the +18 % extent, the class-33 water caveat, the collision counts) |
| Browser-pass records | `odd/tasks/plataforma-cobertura-ve.md`, `catalogo-estudios-202.md`, `metricas-congresos-area.md` |
| Licence evidence and citation format | `NOTICE.md`, read 2026-10-15 from the MapBiomas Venezuela terms of use |

Absences future work must not fill with invention: no testimonials, customers, press coverage or
benchmarks beyond the measured ones; no published figure that ignores the extent caveat or the
class-33 caveat; no claim of a code licence.

## Product Principles

1. **The panel is the authoritative view; the map is secondary.** The map can only place a study
   that has a usable coordinate; the panel lists all of them and states the class it assigns to
   each. The map never replaces the panel.
2. **The number is recomputable.** Anything the viewer says about area, composition or change has to
   be traceable to a committed artefact and reproducible from the inputs, or it does not belong in
   the interface.
3. **Two sources stay distinguishable.** MapBiomas coverage and the congress bibliography carry
   different provenance, different licences and different coverage rules: they cross in the UI, they
   do not merge into one number.
4. **Desktop-first.** The disposition is optimised for long analytical sessions on a large screen.
   No mobile requirement exists today, and effort spent there is effort not spent on the analytical
   surface.
