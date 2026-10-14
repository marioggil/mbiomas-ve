# Fix: Vol XI no longer carries a null year (`anio = 2015`), derived artifact rebuilt

**Status**: implemented — artifact regenerated, suite green, commit pending (section 6).
**Branch**: `fix/catalogo-anio-xi`, off `origin/main` at `876d9c0`.
**Parent record**: [`catalogo-estudios-202.md`](catalogo-estudios-202.md) — decisions D12–D15, the
display contract and its measured evidence. D14 still governs the undated path; this document
records only what changed upstream and the rebuild it forced.

**Scope**: rebuild `data/derived/venezuela/congresos/catalogo-estudios.{json,csv}` from the
regenerated raw export, prove the change is confined to the promised fields, and make the README and
the `viewer/catalog.js` comments true again. **Not authorized**: touching anything under `tests/`
(no re-pin, no weakening), touching `tools/build_study_catalog.py` or
`data/curated/congresos/granularidad-ubicaciones.json`, creating or switching branches, committing.

---

## 1. What changed upstream

The corpus owner regenerated the gitignored raw export
`data/raw/congresos/congresos_revisados.parquet`: now
`55cc3091d2d06353a48ee7d07edd1fc380da42ec00b365d4955c3eef8e3266d8`, **364549 bytes** (before
`576b6fe05d2be0ec72e4d5ede4532199a1f201967fd279c04f3265b780971618`, 364547 bytes). The only
semantic change: the **19** congreso **XI** rows that carried `anio = null` (legacy CSV) now carry
`anio = 2015`. Row count, `classes` and `display_contract` are unchanged — 255 rows / 255 studies;
placeable 145 / coarse_location 87 / outside_extent 13 / no_coordinate 10; map_visible 145,
excluded 110, 15 collision coordinates / 69 markers.

The versioned derived artifact had never been rebuilt, so the digest/size test in
`tests/test_study_catalog_contract.py` (`CommittedArtifactFreshnessTests`) failed: the artifact still
recorded the old parquet's `source_sha256`/`source_bytes`.

## 2. Decision

Rebuild with the **existing** builder and the **existing** curated taxonomy — no builder change, no
taxonomy change — so the freshness test goes green because the **artifact** changed, never because
the test did. The `tests/` tree was not touched.

## 3. Measured before / after

| | before (HEAD `876d9c0`) | after |
|---|---|---|
| `source_sha256` | `576b6fe0…1618` | `55cc3091…66d8` |
| `source_bytes` | 364547 | 364549 |
| `generated_utc` | `2026-10-14T05:27:42.095540+00:00` | `2026-10-14T16:20:30.009206+00:00` |
| studies with `anio = null` | 19 (all Vol XI) | 0 |
| `study_id` of those rows | `cve-sin-anio-pagina-N-I` (19) | `cve-2015-pagina-N-I` (19) |
| studies referencing them in `coordinate_group_ids` | 21 | 21 (ids repointed) |

Independent diff (my own, not the requester's): both artifacts indexed by the stable `source_path`,
then every field of all 255 studies compared. The complete set of differing **per-study** fields is
exactly `anio` (**19**, all `None → 2015`), `study_id` (**19**), `coordinate_group_ids` (**21**); the
only differing **top-level** fields are `source_sha256`, `source_bytes`, `generated_utc`. Nothing
else differs, so `classes` and `display_contract` are byte-identical.

The studies array also re-sorts, because the sort key `(anio, congreso, pagina, indice)` no longer
pushes those rows last: **43** studies change array position (the 19 plus 24 displaced). Position is
not a field; the field-level diff above is the whole semantic change.

## 4. Commands run

Rebuild — interpreter `/tmp/gm-rebuild/bin/python` (Python 3.13, system site packages with
`pyarrow`, `osgeo`, `fastapi`):

```sh
cd /home/mario/Documentos/Mambiomas_data
/tmp/gm-rebuild/bin/python tools/build_study_catalog.py \
  --parquet data/raw/congresos/congresos_revisados.parquet \
  --granularidad data/curated/congresos/granularidad-ubicaciones.json \
  --cog data/cog/venezuela/collection-3/coverage-venezuela_classification_2024.tif \
  --outdir data/derived/venezuela/congresos \
  --country venezuela \
  --labelling-json data/derived/venezuela/collection-3/tiles-manifest.json
```

Exit 0; stdout matched the committed counts exactly:

```
studies: 255 (map_visible=145, excluded=110, collisions=15 coords / 69 markers)
n_autores consistency: 255/255 rows matched, 0 mismatched
granularity levels: T0=66, T1=31, T2=158
  placeable: 145
  coarse_location: 87
  outside_extent: 13
  no_coordinate: 10
```

Focused checks, all green (all `/tmp/gm-rebuild/bin/python -m unittest discover -s tests -k …`):
`CommittedArtifactFreshnessTests -v` → `Ran 3, OK`; `study_catalog_contract` → `Ran 265, OK`;
`serve_viewer_studies` → `Ran 35, OK`. `git status --short` after the work: only the four allowed
files modified, plus this new document.

## 5. Suite state, before and after

At HEAD the freshness digest/size test was the only failure. Re-measured with the three interpreters:

- **combined** (`/tmp/gm-rebuild/bin/python`, GDAL + `pyarrow` + `fastapi`): `Ran 322 tests`, **zero
  skips**, green.
- **system** (`python3`): `Ran 322 tests`, green, `skipped=36` — 35 × `fastapi is a serve-only
  dependency` plus 1 × `pyarrow is a rebuild-only dependency`.
- **repo `.venv`**: `Ran 301 tests`, `skipped=1` (`pyarrow`), plus one import error:
  `test_composition_summary_schema` cannot import `osgeo` (no GDAL in the `.venv`), so its 22 tests
  are not discovered. The pre-existing "`.venv` cannot run the composition schema test" limit.

Docs updated to match, all values re-measured first. `README.md` "## The study catalog": the
"**19** … shown as \"sin año\"" sentence now says all 255 rows carry a year, Vol XI is dated 2015,
nothing renders as "sin año", and the `sin-anio` id segment plus the sort-last rule remain a live
contract exercised by synthetic fixtures (the behaviour is described, not deleted); the **98**
`palabrasclaves` count was verified and kept. `README.md` "## Limitations a reader should know": the
interpreter matrix went from `28 skips / 27 viewer tests / 308 total` to
`36 skips / 35 viewer tests / 322 total`, and the `.venv` bullet now states `Ran 301 tests` with one
import error and one `pyarrow` skip. The same bullet's `study_gap` sentence still said **202**
studies where the corpus has 255 — a survivor of the 202-row era, corrected to 255. `viewer/catalog.js`: the three comments asserting as fact that
the shipped corpus carries `anio: null` for Vol XI (edition ordering, list ordering, `yearLabel`
doc) were reworded to state the null-year path is still handled by contract and still sorts last,
without claiming an undated shipped edition. Comments only; no behaviour change.

## 6. Commit

**Commit**: `<pending — the parent commits the artifact + README + viewer/catalog.js + this
document>`.

## 7. Open items

| # | Item | Blocks |
|---|---|---|
| C1 | The 202-era records ([`catalogo-estudios-202.md`](catalogo-estudios-202.md) D14, §4.3, C6) say **16** undated Vol XI rows because they describe the 202-row corpus; the 255-row artifact carried **19** before this fix | Nothing. Recorded so the two counts are not read as a contradiction |
| C2 | `data/raw/congresos/congresos_revisados.parquet` stays gitignored | Rebuild only; the derived artifact is versioned and ships |
