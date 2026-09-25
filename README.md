# MapBiomas Venezuela — cobertura y uso de la tierra, 1985–2024

An annual land cover and land use data platform for Venezuela, built to extend to the whole
MapBiomas region. It publishes the MapBiomas Venezuela Collection 3 rasters as a browsable
annual series, with composition statistics, a 40-year series panel and statistics for a drawn
area.

**The rasters are cover and land use, not soil classification.** The classes describe what
covers the ground (forest, savanna, pasture, cropland, water, urban, and so on), not soil
taxonomy. The legend is the MapBiomas Collection 3 legend: 26 classes in 6 level-1 groups, taken
from the official codebook and reproduced in `data/legend/venezuela-collection-3.json`.

## Read this before quoting any number

Every area figure this platform produces covers the **MapBiomas mapping extent**, not
internationally recognized borders. That extent is **1,086,229.52 km²** — about 169,600 km² more
than the 916,445 km² of Venezuela as internationally recognized, because it includes disputed
territory and border areas outside de jure boundaries. **No boundary mask has been applied.**
The user interface states this on the map and on the composition panel; anything derived from
this repository must state it too, or it will disagree with official figures by roughly 18 %.

## Where the data is

**The data is not in this repository.** Every geospatial input and output is gitignored, because
it is too large to version:

| Path | Content | Size |
|---|---|---|
| `data/raw/<country>/collection-<n>/` | The original annual GeoTIFFs from MapBiomas | 2.9 GB |
| `data/cog/<country>/collection-<n>/` | Cloud Optimized GeoTIFFs built from them | 4.4 GB |
| `data/tiles/<country>/collection-<n>/` | The XYZ tile pyramid used by the viewer | 6.1 GB |

What *is* versioned is the code and the small derived metadata: the codebook, the composition
CSVs and summary, and the manifests with their checksums. A fresh clone therefore has the code
and no data, and there are two ways forward:

1. **Rebuild it** from the raw rasters with `./run.sh pipeline`. This is honest work, not a
   quick step: see the measured costs below.
2. **Point the clone at an existing data tree**, which is far faster. Either set
   `MAPBIOMAS_REPO_ROOT` to that checkout, or symlink the directories as `./run.sh check`
   suggests:

   ```bash
   ln -s /path/to/other/checkout/data/raw     data/raw
   ln -s /path/to/other/checkout/data/cog     data/cog
   ln -s /path/to/other/checkout/data/tiles   data/tiles
   ln -s /path/to/other/checkout/data/derived data/derived
   ```

## Quickstart

```bash
git clone <this repository> && cd <repository>
./run.sh check     # says exactly what is present, what is missing, and how to produce it
# make the data available, per the section above
./run.sh serve     # creates .venv, installs the pinned dependencies, starts the viewer
```

Then open <http://127.0.0.1:8000>. `./run.sh serve 9000` uses another port, and `PORT=9000`
works too.

`./run.sh check` is the command to run first after cloning. It distinguishes what is needed to
**serve** from what is needed only to **rebuild**, and prints the producing command for every
missing item.

## Rebuilding the data

```bash
./run.sh pipeline --dry-run   # print each stage's command and run nothing; stages whose outputs already exist are skipped
./run.sh pipeline             # run the stages whose outputs are missing
./run.sh pipeline --force     # rebuild even where outputs already exist
```

| Stage | Tool | Measured cost |
|---|---|---|
| Codebook | `tools/build_codebook.py` | seconds |
| COG normalization | `tools/normalize_to_cog.py` | ~25 s per year, ~17–25 min total |
| Composition statistics | `tools/composition_stats.py` | ~38 s per year, ~25 min total |
| Tile pyramid | `tools/build_tiles.py` | ~140–164 s per year, ~110 min total |

`tools/class_change_probe.py` is a diagnostic on top of the composition outputs and is not part
of the pipeline.

## What the viewer shows

- **The annual map**, on a year slider over 1985–2024, with the official MapBiomas palette and a
  hierarchical legend whose groups expand to their classes.
- **The composition panel**: the 40-year level-1 series as a stacked area chart whose cursor
  follows the slider, and the level-2 breakdown for the selected year, sorted by area. Both read
  the committed composition CSVs verbatim, so the panel cannot disagree with the published
  statistics.
- **Clip statistics**: draw a rectangle on the map and get the exact composition of that area for
  the visible year, computed from the COG window at native resolution. The window is bounded at
  36 million pixels, roughly 180 × 180 km, which keeps the worst case around 250 ms; for a whole
  region use the composition panel instead.

## Deploying on a server with Dokploy

`docker-compose.yml` is ready for Dokploy. Create a service of type **Compose** pointing at this
repository, then set the domain in the **Domains** tab with service `viewer` and port `8000`;
Dokploy injects the Traefik routing. Manual Traefik labels are included commented out in the
compose file if you prefer them. The port is deliberately not published on the host.

Environment variables set in the Dokploy UI are written to a `.env` beside the compose file and
are picked up automatically by the `${MAPBIOMAS_COUNTRY:-venezuela}` style interpolation, so
nothing breaks when `.env` is absent.

**The data must be placed on the server.** The image carries the code and the small tracked
metadata, and nothing else:

```bash
rsync -a --info=progress2 data/cog/   server:/etc/dokploy/compose/<app>/files/data/cog/
rsync -a --info=progress2 data/tiles/ server:/etc/dokploy/compose/<app>/files/data/tiles/
```

Only those two subdirectories are mounted. Mounting over `/app/data` as a whole would shadow the
legend, the composition outputs and the manifests that the image already contains.

**The container serves; it cannot rebuild.** Every tool that produces data imports
`from osgeo import gdal`, which needs the GDAL Python bindings, and rasterio's wheels do not
provide them. So regeneration runs where GDAL is installed — normally the developer's machine —
and the result is synced. The image itself needs no system GDAL, because rasterio bundles one for
the clip endpoint.

## Behaviours that look like bugs but are not

- **Tiles return 404.** Transparent ocean tiles are excluded from the pyramid, and the map client
  relies on 404 meaning "no tile". This must never be turned into a 200 or an empty image: it is
  correct, and it is the reason the browser console shows 404s while panning.
- **Class 27 (`No observado`) has zero pixels.** The data encodes non-observed as nodata 0, so
  class 27 never appears in a raster. The composition CSV still carries it as a zero row so the
  schema stays stable, while the clip response omits it.
- **The page scrolls instead of the panel.** The composition panel grows to its content and the
  document scrolls, which is deliberate: an earlier version trapped 2,692 px of content in a
  360 px box and hid 57 % of the chart.
- **Two different denominators on screen.** The clip breakdown labels its shares "de la zona
  seleccionada" because they are of the drawn area, while the year breakdown labels them "de la
  extensión válida" because they are of the whole mapped extent. Both are correct; they are not
  the same denominator.

## Multi-country

The service takes country and collection from the environment, and every path is built from
them. `MAPBIOMAS_COUNTRY`, `MAPBIOMAS_COLLECTION` and `MAPBIOMAS_REPO_ROOT` are the three knobs.
Adding a country means adding its data tree and a codebook; no code path hardcodes Venezuela.

## Performance, measured

| Operation | Number |
|---|---|
| Decimated read of one year, original GeoTIFF | 6.7 s |
| Same read from the COG | 0.19 s |
| Serving tiles through the service | ~440–460 tiles/s |
| Clip statistics, ~15 × 15 km | 10 ms |
| Clip statistics, ~62 × 62 km | 34 ms |
| Clip statistics, ~177 × 177 km | 246 ms |
| Composition statistics, 40 years | 1,504 s |

## Licence and attribution — UNRESOLVED

**This is not settled and it blocks publishing.** MapBiomas data carries attribution obligations
and possibly share-alike terms that have not been verified. Do not publish derived products from
this repository, and do not add a licence file implying otherwise, until the terms have been read
and recorded. The intent is to state them here once they are confirmed.

## Limitations a reader should know

- **Three authored files have never been through lens review**: `tools/spatial_units.py` (the
  single source of truth for the geodesic area), `tools/priority_schema.py` (the weighted-score
  schema) and `tools/composition_stats.py`. The rest of the pipeline and the whole viewer have
  been reviewed, and several real defects were found and fixed that way. Two provider validation
  steps could not be executed either, because the review facade does not expose them. Do not
  assume the code is fully reviewed.
- The composition summary JSON carries per-class pixel counts and presence but not per-class
  **areas**; those live in the CSV.
- Class 33 (water) grows 4.42 % over the series. Two step changes are externally corroborated as
  real reservoirs, but roughly 80 % of the gain is a diffuse tail with no attributed cause, so no
  water claim should be published beyond those two.
- `odd/tasks/plataforma-cobertura-ve.md` is the working record: decisions, measured evidence, open
  items and the accumulated follow-up backlog. Read it before extending anything.
