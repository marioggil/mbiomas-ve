# Feature: every figure shows what produced it

**Status**: in progress · **Branch**: `fix/procedencia-panel` (from `origin/main`) · **Commit**: `<pending>` ·
**Unit**: 4, the last of the plan after the second critique (its P2: *the product's differentiator — auditable,
recomputable figures — has no interface*).

## 1. What the product promises and what the screen shows

`PRODUCT.md` § Positioning: **"The computation is ours and it is auditable.** Composition over the series, and the
statistics for a drawn area, are calculated here from the MapBiomas GeoTIFFs, with versioned inputs, recorded digests and
a freshness assertion that fails when the input changes without a rebuild. The official site publishes a map and its own
figures; here **the figure can be recomputed and traced to the artefact that produced it**."

The viewer shows none of that. A figure screenshotted from the composition panel is indistinguishable from one taken from
the official site. The second critique logged exactly this as a P2, and it is the half of the product's positioning that
lives nowhere on screen.

## 2. The provenance that actually exists (read it, do not invent it)

Everything below is committed and already in the repository. Do not add a digest, a date or a method that is not read
from one of these sources.

**`data/derived/venezuela/collection-3/composition/composition-summary-venezuela-collection-3.json`** (49,547 bytes) —
the artefact the composition panel reads verbatim:

| Field | Value today |
|---|---|
| `schema_version` | `2` |
| `generated_utc` | `2026-09-24T18:40:54+00:00` |
| `area_method` | the geodesic method behind every area figure |
| `authalic_radius_m` | the radius that method uses |
| `nodata_value`, `spatial_unit`, `spatial_unit_metadata`, `per_year`, `years` | as they are |

Its siblings, also committed, are the two CSVs the panel and the map read: `composition-level1-venezuela-collection-3.csv`
(22,059 bytes) and `composition-level2-venezuela-collection-3.csv` (105,802 bytes).

**`data/derived/venezuela/collection-3/cog-manifest.json`** (105,311 bytes) — the manifest of the COG set the clip
endpoint reads at request time. `entries` has **40** objects, one per year, each with `year`, `input_name`,
`input_sha256`, `input_bytes`, `output_name`, `output_sha256`, `output_bytes` and the conversion options; the batch
carries `generated_utc` (`2026-09-22T17:32:44+00:00`) and `totals`. **This is what "the artefact that produced the figure"
means for a drawn area**, and it is per year: the figure for 2024 comes from the 2024 entry, not from a batch.

The server already follows this pattern for the tiles manifest (`MANIFEST_PATH` and `_load_manifest()` at
`tools/serve_viewer.py:116` and `:220`): a path constant, a loader that raises a named error, and a module-level cache.

## 3. What to build

**A provenance block in the panel's footer**, under the D7 note that already lives in `.panel-labelling` — the panel's
own idiom, 12px, bordered, `margin-top: auto`.

1. **`tools/serve_viewer.py`**: a new read-only endpoint, e.g. `GET /api/provenance`, returning one document with:
   - the composition artefact's identity: the file name, `schema_version`, `generated_utc`, `area_method` and
     `authalic_radius_m`, plus the two CSVs' names and byte sizes (and their `sha256`, computed **once at import**, not
     per request);
   - the COG set: per year, `output_sha256`, `output_bytes`, `input_sha256`, `input_bytes`, `input_name`, `output_name`,
     with the batch's `generated_utc` and `totals`;
   - the command that recomputes it, read from the repository's own documented entry point (`./run.sh pipeline`) rather
     than typed twice.
   Follow `_load_manifest()`'s shape for the COG manifest (a path constant, a loader raising a named error, a
   module-level cache). A missing or malformed file must not take the viewer down: the endpoint reports what it has and
   says what it could not read.
2. **`viewer/api.js`**: the fetch, in that file's existing style.
3. **`viewer/index.html`**: the block's markup inside `.panel-labelling`, after the D7 note: one summary line plus a real
   disclosure button (`aria-expanded`, `aria-controls`, a glyph) for the details.
4. **`viewer/panel.js`**: render it, and **update the year-dependent parts when the year changes** — the digest and the
   file names of the year on screen, not of the year the page loaded with.
5. **`viewer/style.css`**: the styles, reusing the 12px role and the existing disclosure rules.

**The summary line** must fit **one line at 660px of panel width** and carry, in the project's Spanish: the composition
artefact with its version and build date, **the current year and a shortened digest of that year's COG output**, and the
fact that the figure is computed here. The **expanded details** carry the full `output_sha256` and `input_sha256`, the
byte sizes, the CSVs with their sizes and digests, the area method with its authalic radius, and the recompute command.
Digests are shown in a copyable, monospaced form, shortened only in the summary.

## 4. Acceptance criteria

1. The panel's footer shows the provenance summary for the year on screen, and **every value in it is read from the
   sources in section 2** — no literal date, digest or version typed into the viewer.
2. **The summary is one line at 1600x1000** and the panel's collapsed height stays **≤700px** (it is 660px today).
3. **Changing the year changes the digest and the file names** in both the summary and the details. Prove it with two
   years whose `output_sha256` differ.
4. The details expand and collapse by mouse and by keyboard (Tab, Enter, Space), with `aria-expanded` following.
5. **The digest on screen equals the manifest's**, checked against the JSON, not against the viewer's own rendering.
6. A missing COG manifest or composition summary does not break the panel, the map or the clip: the block says what it
   could not read.
7. No new `font-size`, `line-height`, `font-weight`, colour or background declaration; the in-page detector stays at 0;
   suite `387 OK`; `node --check` and `python3 -m py_compile` clean on every touched file.

## 5. Risks

- **A provenance line that is not true is worse than none.** Every string must come from section 2's sources; if a field
  is absent, say so rather than filling it in.
- **The panel's height budget is tight** (660px of a 700px ceiling): the summary is one line and the details are behind
  the disclosure for exactly this reason.
- **Per-year plumbing**: the COG identity is per year, so a render that only runs on load will show the wrong year after
  the first slider move. That is criterion 3.
- **Hashing at request time would be a self-inflicted latency**; the composition files are hashed once at import.

## 6. Verification

The viewer has **no persisted automated test**, so the verification of record is the parent's browser pass at 1600x1000:
the summary's content against the manifest and the summary JSON read independently, the year change (two years, two
digests), the panel's height, the disclosure by mouse and by keyboard, the missing-file behaviour if it can be forced,
and the in-page detector. The Python suite is the control.
