# Feature: the catalogue's figures show what produced them

**Status**: in progress · **Branch**: `fix/procedencia-catalogo` (from `origin/main`) · **Commit**: `<pending>` ·
**Unit**: the debt left by `odd/tasks/procedencia-panel.md`, which gave the composition panel's two figures their
provenance and closed with: *"the studies catalogue's own figures still carry no provenance"*.

## 1. Why, and what is different from the panel's unit

The catalogue panel's figures are the congress metrics (the drawn area's talks, species and institutions) and the
catalogue's own class counts. They come from a **different artefact** than the composition panel's: the studies artifact,
built from the congress Parquet, with two hand-curated tables behind its institution and granularity figures. Today a
number read from that panel cannot be traced to what produced it any more than the composition panel's could before the
previous unit.

**The difference that shapes this unit**: the studies artifact is **not per year**. It is one corpus, so its provenance
does not change when the slider moves. Nothing here should be wired to `currentYear`.

## 2. The provenance that actually exists (read it, do not invent it)

**`data/derived/venezuela/congresos/catalogo-estudios.json`** — the artifact the catalogue panel and the metrics are
rendered from. Its top-level provenance fields, today:

| Field | Value today |
|---|---|
| `schema_version` | `4` |
| `generated_utc` | `2026-10-15T04:18:01.203025+00:00` |
| `source_parquet` | the source file's name |
| `source_sha256` | `55cc3091d2d06353a48ee7d07edd1fc380da42ec00b365d4955c3eef8e3266d8` |
| `source_bytes` | `364549` |
| `source_rows` | `255` |
| `study_count` | the corpus size |
| `ror_instituciones` | the curated institution map the institution figures are built from |

**`data/curated/congresos/ror-instituciones.json`** (11,135 bytes) and
**`data/curated/congresos/granularidad-ubicaciones.json`** (46,186 bytes) — the two hand-curated tables. The institution
figures depend on the first and the granularity band on the second: a change in either changes what the metrics say
without any data changing.

**The Parquet is a gitignored input and may not exist in a deployment.** Its identity must be read from the artifact's
recorded fields (`source_sha256`, `source_bytes`, `source_rows`) and **never by hashing the file**: the recorded digest is
the point of the field, and a missing input must not turn into a missing provenance line.

The recompute path is the one the endpoint already serves (`./run.sh pipeline`), read from the repository's own entry
point in the previous unit: reuse it, do not type a second copy.

## 3. What to build

Mirror the model the previous unit established, for the studies artifact.

1. **`tools/serve_viewer.py`**: extend the existing `GET /api/provenance` document with a **`studies`** object:
   - the artefact: its file name, `schema_version`, `generated_utc`, `study_count`, `country`, and the length of
     `ror_instituciones` as the curated institution count;
   - the source as recorded: `source_parquet`, `source_sha256`, `source_bytes`, `source_rows`;
   - the two curated tables: file name, byte size and `sha256`, computed **once at import** like the composition CSVs;
   - the artefact's own `sha256`, also once at import;
   - reuse the per-source error slots: a file that cannot be read is reported in the same shape the existing blocks use,
     never fatal, and never replaced by an invented value.
2. **`viewer/index.html`**: a provenance block as the **catalogue panel's footer** — a summary line plus a real
   disclosure button (`aria-expanded`, `aria-controls`, a glyph with `aria-hidden`) — placed after the panel's list and
   detail region, so it is visible whether or not the metrics block is expanded. The metrics block is collapsed by
   default, and the promise is that a figure can be traced, so the block must not live inside it.
3. **`viewer/catalog.js`**: fetch `/api/provenance` (the endpoint and `api.fetchProvenance` already exist), render the
   summary and the details, and say so plainly when a source could not be read. Keep the small digest-shortening helper
   local to this file rather than inventing a shared module.
4. **`viewer/style.css`**: the block's styles, reusing the 12px role and the disclosure family the panel's block already
   uses (its own class names, the same rules).

**The summary line** must fit **one line at 1600x1000** and carry, in the project's Spanish: the artefact with its
version and build date, the corpus size, and a shortened digest of the source Parquet with its byte size. The
**details** carry the full `source_sha256`, the source's name, bytes and rows, the two curated tables with their sizes
and digests, the artefact's own digest, and the recompute command.

## 4. Acceptance criteria

1. The catalogue panel's footer shows the summary, and **every value in it is read from section 2's sources** — no
   literal date, digest, size or version typed into the viewer.
2. **The summary is one line at 1600x1000**, and the block does not break the catalogue's layout: the list keeps its
   internal scroll and the panel keeps its two-column shape.
3. **The block does not change with the year**: moving the slider leaves it byte-identical, because the corpus is not
   per year.
4. The details expand and collapse by mouse and by keyboard (Tab, Enter, Space) with `aria-expanded` following.
5. **The digests on screen equal the artifacts'**: the source digest equals the artifact's recorded `source_sha256`, and
   the two curated tables' digests equal `sha256sum` of those files — checked against the files, not against the viewer.
6. A missing or malformed source is reported and never fatal: the catalogue, the metrics, the map and the clip keep
   working.
7. No new `font-size`, `line-height`, `font-weight`, colour or background declaration; the in-page detector stays at 0;
   suite `387 OK`; `node --check` and `python3 -m py_compile` clean.

## 5. Risks

- **The Parquet is not hashable at serving time.** It is gitignored and may be absent: read its recorded identity and
  never hash the file.
- **A provenance line inside the metrics block would be invisible by default**, because that block starts collapsed.
- **The catalogue's layout is capped** (the list scrolls internally, the panel is a two-column split): the footer must
  sit outside that box or it will fight it.
- **Do not wire it to the year.** The corpus does not change with the slider, and a re-render on the year change would
  suggest it does.

## 6. Verification

The viewer has **no persisted automated test**, so the verification of record is the parent's browser pass at 1600x1000
and 960x700: every value against the artifact and the two curated files read independently, the year change (the block
must not move), the line and the layout, the disclosure by mouse and by keyboard, a missing source, and the in-page
detector. The Python suite is the control.
