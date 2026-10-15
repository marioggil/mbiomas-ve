# Notice — data licence, attribution and changes

This repository builds derived products from **MapBiomas Venezuela** data. That data is not ours, and
its terms are not ours to choose. This file records the terms as published, the citation they require,
and what this repository changed, which the licence obliges us to state.

## The licence: CC BY 4.0

**Creative Commons Attribution 4.0 International — <https://creativecommons.org/licenses/by/4.0/>**

Read and recorded on **2026-10-15** from the MapBiomas Venezuela terms of use at
<https://venezuela.mapbiomas.org/terminos-de-uso/>, which states that the data are *"públicos, abiertos
y gratuitos bajo licencia Creative Commons CC-BY"* and links to the 4.0 deed. The same site's footer,
present on every page, states *"Los datos de MapBiomas son de uso público, abierto y gratuito, sujetos
a citación. CC BY 4.0"*.

What that means here, in plain terms:

- **Attribution is required**, in the format the terms specify (below).
- **Indicating changes is required.** Everything in this repository is an adaptation, so every
  published product must say so.
- **No additional restrictions may be applied.** Nobody may impose terms or technical measures that
  restrict what the licence permits, including on the copies redistributed here.
- **There is no ShareAlike condition.** Derivative works may be licensed as their author chooses.
- **Commercial use is permitted.**

### One discrepancy, resolved

A web search still indexes a FAQ page of the *previous* version of that site claiming **CC-BY-SA**
(share-alike). That page now returns **HTTP 404**, and the current site's own API returns **no page
containing "CC-BY-SA"** and exactly **one** page mentioning "licencia" — the terms page quoted above.
The stale page is therefore not the term of record; CC BY 4.0 is, and this repository implements CC BY
4.0. If MapBiomas Venezuela ever publishes a share-alike term, this file and the products built from
it must be revisited before further distribution.

## Required citation

The terms require referencing the source in this format, with their own placeholders:

> «MapBiomas – Colección **[versión]** de la Serie **[anual/mensual]** de Mapas de
> **[Cobertura y Uso del Suelo/Superficie del agua]** de Venezuela, consultada el **[fecha]** a través
> del enlace: **[ENLACE]**»

The products of this repository are **Collection 3**, **annual**, **Land Cover and Use**, so the
citation filled for them is:

> «MapBiomas – Colección **3** de la Serie **anual** de Mapas de **Cobertura y Uso del Suelo** de
> Venezuela, consultada el **[fecha]** a través del enlace: **[ENLACE]**»

Whoever publishes a product of this repository fills in the consultation date and the link where that
product can be reached, and states that it is adapted from the source. A ready-to-paste version:

> MapBiomas Venezuela. *Colección 3 de la Serie anual de Mapas de Cobertura y Uso del Suelo de
> Venezuela*, consultada el **[fecha]** a través del enlace: **[ENLACE]**. Datos de
> <https://venezuela.mapbiomas.org/> bajo licencia CC BY 4.0
> (<https://creativecommons.org/licenses/by/4.0/>); **adaptados** como se describe abajo.

## What this repository changed

CC BY 4.0 obliges us to indicate changes. None of the transformations below alters a class code, a
classification decision or a legend meaning; they repackage the published maps for analysis and for
the web:

| Product | What happens to it |
|---|---|
| `data/cog/` | The published GeoTIFFs (EPSG:4326, byte class codes) are rewritten as analysis-grade Cloud-Optimized GeoTIFFs with internal overviews. **Nearest-neighbour resampling**: the rasters encode discrete class codes, and an averaged pixel would invent a class that does not exist |
| `data/tiles/` | An XYZ Web Mercator PNG pyramid is built from the COGs for the browser, painting the official MapBiomas palette taken from the codebook. Also nearest-neighbour. The manifest records the codebook path and its SHA-256 so a palette change cannot pass silently |
| `data/derived/.../composition-*` | Per-year, per-class **pixel counts** (JSON) and per-class **geodesic areas** (CSV) computed from the COGs, with the class codes, the codebook checksum and the group structure as published. The geodesic area comes from this repository's own `tools/spatial_units.py`, not from MapBiomas |
| `data/legend/` | The codebook is derived from the published legend material; `data/legend/source/` holds MapBiomas's own code PDF and QGIS style **unmodified** |
| `viewer/` | An independent web viewer written for this repository. It is not MapBiomas's own site and shares no code with it |

Palettes are never baked into the COGs: the COG stays analysis-grade class codes and colour lives in
the codebook. Class codes are preserved end to end, so an area computed here is the area their
classification implies.

### What this repository redistributes, and what it does not

The **raw rasters are not redistributed here**: `data/raw/` is gitignored, and so are the COGs and
the tile pyramid (`data/cog/`, `data/tiles/`), which are built locally from the source and mounted
at deployment time. What this repository does carry is the derived statistics committed under
`data/derived/` and the legend material under `data/legend/` — so the attribution and the change
notice apply above all to those, and to the running viewer.

## What in this repository is not MapBiomas data

- **The congress study catalog** (`data/derived/venezuela/congresos/`, `data/raw/congresos/`,
  `data/curated/congresos/`) describes studies of the *Congreso Venezolano de Ecología*. It is a
  different source with its own provenance, recorded in `odd/tasks/catalogo-estudios-202.md`, and
  MapBiomas's licence does not cover it.
- **All source code** in this repository.

## Names and logos

"MapBiomas" and its marks belong to the MapBiomas network. This repository uses the name only to
attribute the source as the licence requires, and nothing here implies that MapBiomas endorses,
sponsors or reviewed it. **No logo or badge file from the MapBiomas site is copied into this
repository**: the licence is referenced by name and URL, which is what CC BY 4.0 requires.

## The source code has no licence yet

CC BY 4.0 governs **the data**, not the software that reads it. The code in this repository carries no
licence, which means the default applies: nobody may reuse it beyond what copyright law allows.
Choosing one is a separate decision and it is still open — this file deliberately does not make it,
and it does not claim a licence for the code by putting the data's terms over the whole repository.

## Sources

| What | Where | Read |
|---|---|---|
| Terms of use, licence and citation format | <https://venezuela.mapbiomas.org/terminos-de-uso/> | 2026-10-15 |
| The licence deed | <https://creativecommons.org/licenses/by/4.0/> | 2026-10-15 |
| The data | <https://venezuela.mapbiomas.org/> | 2026-10-15 |
