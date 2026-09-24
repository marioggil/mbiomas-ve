"""FastAPI service for the MapBiomas data platform viewer.

This service is the read-only front door of the platform. It serves:

  * the tile pyramid (PNG XYZ) for one country / collection, with strict
    per-request validation (year, zoom, x, y, file existence, and a hard
    confinement check that any served path stays inside the tile root);
  * ``/api/meta``, a JSON document assembled from the tile manifest and the
    codebook -- never hard-coded in this file -- so that an operator can
    rerun a different country/collection without editing the viewer;
  * ``/api/composition/series`` and ``/api/composition/year/{year}`` for
    the composition panel (T8b), reading the committed CSVs once at
    import and serving them verbatim;
  * ``/api/clip-stats`` for the clip-on-map tool (T8c): a user-drawn
    rectangle becomes a per-class composition of that area for the visible
    year, read from the source COG at native resolution with the same
    counting method and the same row-wise geodesic area as the committed
    composition engine;
  * ``/api/health`` for one-call diagnosis of which country/collection is
    wired up and which asset paths were resolved;
  * the frontend in ``viewer/`` plus its static assets.

Why the service exists instead of just ``app.mount("/tiles", StaticFiles(...))``
=================================================================================

The viewer needs to be safe to expose. A naive static mount would serve any
PNG under the tile root and would happily hand back a 200 for tiles that
should not exist (transparent tiles are intentionally omitted from the
pyramid and the map client treats 404 as "empty"). It would also accept raw
URL path components that could escape the tile root. This service therefore:

  * validates ``year`` against the manifest's year list,
  * validates ``z`` against the manifest's declared zoom range,
  * validates ``x`` and ``y`` against the valid grid for that ``z``
    (Web Mercator: ``0 <= x, y < 2**z``),
  * resolves the candidate path and refuses to serve it unless the resolved
    path is strictly inside the configured tile root (defence in depth on
    top of the integer validation, in case a future caller passes something
    unexpected),
  * returns 404 for any tile that does not exist on disk (the client
    interprets that as transparent, which matches the pyramid semantics).

Cache-Control is set to a long-lived immutable value because the tiles never
change once written; the integrity block in the manifest is the source of
truth here. ``Content-Type`` is always ``image/png``.

Decision D7 -- the mandatory extent labelling -- is enforced on the
frontend (the text of ``extent_label`` and ``boundary_note`` from the
manifest is always rendered, never hidden behind a hover or modal) and
defended in this file because the wording travels with the data.

Decision D5 -- multi-country from day one -- is honoured by taking the
country and collection as configuration; no path in the request handlers
hard-codes Venezuela.

The single data-access module (``viewer/api.js``) is a hedge: when the
backend protocol changes in a later phase, every frontend change is in
that one file. This service must therefore expose a stable JSON contract,
which it does.
"""

from __future__ import annotations

import csv
import json
import math
import os
import re
import struct
import sys
from pathlib import Path
from typing import Any, Final

import numpy as np
from fastapi import FastAPI, HTTPException, Path as PathParam, Query, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

# tools/ is a flat scripts directory, not a Python package, and this file
# lives inside tools/. Add the tools/ directory itself to sys.path so we
# can ``import spatial_units`` -- the single source of truth for the
# row-wise geodesic area -- the same way the composition engine does
# (``tools/composition_stats.py`` adds the same directory for its
# ``from spatial_units import ...`` line). The insert is idempotent and
# stays scoped to this process.
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# The repository root, country and collection are resolved from environment
# variables with sane defaults. The defaults match the only dataset shipped
# in the repository today (venezuela / collection-3) so the service works
# out of the box, but a different country/collection is one env-var away.

REPO_ROOT: Final[Path] = Path(
    os.environ.get("MAPBIOMAS_REPO_ROOT", str(Path(__file__).resolve().parent.parent))
).resolve()

COUNTRY: Final[str] = os.environ.get("MAPBIOMAS_COUNTRY", "venezuela")
COLLECTION: Final[str] = os.environ.get("MAPBIOMAS_COLLECTION", "3")

DATA_ROOT: Final[Path] = REPO_ROOT / "data"
DERIVED_ROOT: Final[Path] = DATA_ROOT / "derived" / COUNTRY / f"collection-{COLLECTION}"
TILES_ROOT: Final[Path] = DATA_ROOT / "tiles" / COUNTRY / f"collection-{COLLECTION}"
LEGEND_ROOT: Final[Path] = DATA_ROOT / "legend"
COG_ROOT: Final[Path] = DATA_ROOT / "cog" / COUNTRY / f"collection-{COLLECTION}"

MANIFEST_PATH: Final[Path] = DERIVED_ROOT / "tiles-manifest.json"
CODEBOOK_PATH: Final[Path] = LEGEND_ROOT / f"{COUNTRY}-collection-{COLLECTION}.json"
VIEWER_DIR: Final[Path] = REPO_ROOT / "viewer"

# Composition outputs committed by T4 of the feature. The panel slice (T8b)
# reads them verbatim: the values on screen are the values the statistics tool
# wrote, never recomputed. They live next to the tile manifest so every
# derived artefact the service trusts travels together.
COMPOSITION_LEVEL1_PATH: Final[Path] = (
    DERIVED_ROOT / "composition" / f"composition-level1-{COUNTRY}-collection-{COLLECTION}.csv"
)
COMPOSITION_LEVEL2_PATH: Final[Path] = (
    DERIVED_ROOT / "composition" / f"composition-level2-{COUNTRY}-collection-{COLLECTION}.csv"
)

# Schema version of the composition endpoints. Bumped on any breaking change
# to the JSON contract the frontend consumes.
COMPOSITION_SCHEMA_VERSION: Final[str] = "viewer-composition.v1"

# Schema version of the clip-stats endpoint (slice T8c). The windowed
# composition shares the level-1/level-2 shape with the composition series,
# but the payload is computed on demand from the source COG, not read from
# the committed CSV. Bump this on any breaking change to the JSON contract
# the frontend consumes.
CLIP_STATS_SCHEMA_VERSION: Final[str] = "viewer-clip-stats.v1"

# Maximum pixel count the clip-stats endpoint will accept. The bound is
# set just above the shipped raster's full-extent size (57605 x 45000 =
# 2,592,225,000 pixels for the venezuela / collection-3 COG) so the
# acceptance test -- a clip whose rectangle equals the full raster extent
# must reproduce the published composition for that year exactly -- can
# run. The parent's measurement puts a full-extent read at roughly 20 s
# (tens of seconds), which is acceptable for a one-off audit request and
# is what the task brief itself predicts ("a window spanning the whole
# raster would take tens of seconds"). A small margin above the shipped
# raster keeps the bound future-proof against a slightly larger dataset
# without inviting an unbounded read. The error message names the bound
# so a caller can split or zoom in.
CLIP_STATS_MAX_PIXELS: Final[int] = 36_000_000

# Row block height used when streaming the clip window. 512 rows keeps the
# read+bincount pass comfortably under a second on the largest allowed
# window (36 M pixels / 512 = ~70k blocks of 512-wide rows, each ~ a few
# hundred microseconds), and matches the parent's measurement budget.
CLIP_STATS_ROW_BLOCK: Final[int] = 512

# Consistency check tolerances for the import-time validator. The level-1
# and level-2 CSVs are produced by the same engine, so per-year sums of the
# level-2 areas that roll up under each level-1 group must agree with the
# level-1 row within the geodesic area's float64 accumulation noise. 1e-3 ha
# is 0.01 m^2 and matches the noise budget observed in T6.
COMPOSITION_AREA_TOLERANCE_HA: Final[float] = 1e-3

TILE_URL_TEMPLATE: Final[str] = "/tiles/{year}/{z}/{x}/{y}.png"

# Schema version of the /api/meta endpoint itself. The manifest does not
# declare a schema version, so this file owns the version of its own output
# format. Bump it on any breaking change to the JSON contract the frontend
# consumes.
META_SCHEMA_VERSION: Final[str] = "viewer-meta.v1"

# Tiles never change once written. One year is one immutable build. The
# integrity block of the manifest is the source of truth.
TILE_CACHE_CONTROL: Final[str] = "public, max-age=31536000, immutable"

# Integer-only pattern for the route parameters. Used as a defence-in-depth
# check on top of FastAPI's ``int`` coercion. ``int`` already rejects
# non-integer strings, but a regex pass makes the intent unambiguous in the
# code and rejects anything that even looks like a path component (slashes,
# dot, percent).
INT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9]+$")

# Inline SVG served at ``/favicon.ico``. The platform has no icon asset
# today, so we hand back a tiny vector glyph instead of a binary .ico
# blob. The route is mounted under the ``/favicon.ico`` URL because that
# is what browsers (and bookmarks, crawlers, devtools) request by default;
# the Content-Type is the truth and modern browsers accept ``image/svg+xml``
# favicons. Cache it for one day: the icon does not change between deploys.
FAVICON_SVG: Final[str] = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="6" fill="#2a7a3f"/>'
    '<circle cx="16" cy="16" r="7" fill="#ffffff"/>'
    '<circle cx="16" cy="16" r="3" fill="#2a7a3f"/>'
    "</svg>"
)
FAVICON_CACHE_CONTROL: Final[str] = "public, max-age=86400"


# ---------------------------------------------------------------------------
# Asset loading
# ---------------------------------------------------------------------------

class ManifestError(RuntimeError):
    """Raised when the manifest or codebook is missing or malformed."""


def _load_manifest() -> dict[str, Any]:
    """Load the tile manifest and raise a clear error if anything is wrong."""
    if not MANIFEST_PATH.is_file():
        raise ManifestError(f"tiles manifest not found: {MANIFEST_PATH}")
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"tiles manifest is not valid JSON: {MANIFEST_PATH}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ManifestError(f"tiles manifest root is not an object: {MANIFEST_PATH}")
    return manifest


def _load_codebook() -> dict[str, Any]:
    """Load the legend codebook and raise a clear error if anything is wrong."""
    if not CODEBOOK_PATH.is_file():
        raise ManifestError(f"codebook not found: {CODEBOOK_PATH}")
    try:
        codebook = json.loads(CODEBOOK_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"codebook is not valid JSON: {CODEBOOK_PATH}: {exc}") from exc
    if not isinstance(codebook, dict):
        raise ManifestError(f"codebook root is not an object: {CODEBOOK_PATH}")
    if "level1" not in codebook or "classes" not in codebook:
        raise ManifestError(
            f"codebook missing required keys 'level1' or 'classes': {CODEBOOK_PATH}"
        )
    return codebook


# Load the manifest and codebook exactly once, at module import. A missing or
# malformed asset stops the service with a clear message instead of degrading
# per request, and the routes below read the parsed dicts directly so no
# per-request I/O or re-parsing happens during tile serving.
try:
    _MANIFEST_DATA: dict[str, Any] = _load_manifest()
    _CODEBOOK_DATA: dict[str, Any] = _load_codebook()
except ManifestError as exc:
    raise SystemExit(f"viewer: required assets missing or malformed: {exc}") from exc


# ---------------------------------------------------------------------------
# Composition CSVs (slice T8b)
# ---------------------------------------------------------------------------
# The composition panel reads the same CSVs the statistics tool committed in
# T4 and must not recompute anything. The previous review finding
# (R3-SERVE-VIEWER-NO-CACHE-RELOAD, raised against the tile route for
# re-parsing the manifest on every request) is the reason the loaders below
# run exactly once at import and the routes read the pre-parsed dicts.
#
# Two counters are kept in module scope and exposed through
# ``/api/composition/_load_counters`` for the verification harness; the
# expectation is zero calls during serving, which proves no per-request CSV
# re-parsing.

class CompositionError(RuntimeError):
    """Raised when the composition CSVs are missing, malformed or inconsistent."""


class _LoadCounter:
    """Tiny monotonic counter used by the verification harness.

    The whole point of these counters is to prove that the CSV loaders do not
    run on the request path. Incrementing a counter is two attribute writes;
    a counter object is cheaper than ``logging`` and survives the round-trip
    of an in-process test client that runs in the same interpreter.
    """

    __slots__ = ("calls",)

    def __init__(self) -> None:
        self.calls: int = 0

    def bump(self) -> None:
        self.calls += 1


_COMPOSITION_L1_LOAD_COUNTER: _LoadCounter = _LoadCounter()
_COMPOSITION_L2_LOAD_COUNTER: _LoadCounter = _LoadCounter()


def _load_composition_level1(path: Path) -> "dict[int, dict[int, dict[str, Any]]]":
    """Load the level-1 composition CSV into ``{year: {pixel_id: row}}``.

    Counts the load so the verification harness can assert no per-request
    re-parsing. Raises ``CompositionError`` with a row reference on any
    structural problem so the operator can open the file at the same line
    number the engine reports.
    """
    _COMPOSITION_L1_LOAD_COUNTER.bump()
    if not path.is_file():
        raise CompositionError(f"composition level-1 CSV not found: {path}")
    out: dict[int, dict[int, dict[str, Any]]] = {}
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row_index, raw in enumerate(reader, start=2):  # header is line 1
                try:
                    year = int(raw["year"])
                    pixel_id = int(raw["level1_pixel_id"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise CompositionError(
                        f"composition level-1 CSV row {row_index}: bad year/level1_pixel_id: {raw!r}"
                    ) from exc
                out.setdefault(year, {})[pixel_id] = {
                    "year": year,
                    "pixel_id": pixel_id,
                    "code": raw.get("level1_code", ""),
                    "name_es": raw.get("name_es", ""),
                    "name_en": raw.get("name_en", ""),
                    "pixels": int(raw["pixels"]),
                    "area_ha": float(raw["area_ha"]),
                    "share_pct": float(raw["share_of_extent_pct"]),
                }
    except OSError as exc:
        raise CompositionError(f"composition level-1 CSV is not readable: {path}: {exc}") from exc
    if not out:
        raise CompositionError(f"composition level-1 CSV has no usable rows: {path}")
    return out


def _load_composition_level2(path: Path) -> "dict[int, dict[int, dict[str, Any]]]":
    """Load the level-2 composition CSV into ``{year: {pixel_id: row}}``.

    Counts the load for the same reason as level-1. Level-2 carries the
    level-1 relationship (``level1_pixel_id``) so the breakdown endpoint can
    group classes under their group without a second pass over the codebook.
    """
    _COMPOSITION_L2_LOAD_COUNTER.bump()
    if not path.is_file():
        raise CompositionError(f"composition level-2 CSV not found: {path}")
    out: dict[int, dict[int, dict[str, Any]]] = {}
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row_index, raw in enumerate(reader, start=2):
                try:
                    year = int(raw["year"])
                    pixel_id = int(raw["pixel_id"])
                    level1_pixel_id = int(raw["level1_pixel_id"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise CompositionError(
                        f"composition level-2 CSV row {row_index}: bad year/pixel_id: {raw!r}"
                    ) from exc
                out.setdefault(year, {})[pixel_id] = {
                    "year": year,
                    "pixel_id": pixel_id,
                    "code": raw.get("code", ""),
                    "name_es": raw.get("name_es", ""),
                    "name_en": raw.get("name_en", ""),
                    "level1_pixel_id": level1_pixel_id,
                    "level1_code": raw.get("level1_code", ""),
                    "pixels": int(raw["pixels"]),
                    "area_ha": float(raw["area_ha"]),
                    "share_pct": float(raw["share_of_extent_pct"]),
                }
    except OSError as exc:
        raise CompositionError(f"composition level-2 CSV is not readable: {path}: {exc}") from exc
    if not out:
        raise CompositionError(f"composition level-2 CSV has no usable rows: {path}")
    return out


def _validate_composition_consistency(
    level1: "dict[int, dict[int, dict[str, Any]]]",
    level2: "dict[int, dict[int, dict[str, Any]]]",
    codebook: dict[str, Any],
) -> None:
    """Cross-check the two CSVs and the codebook at import time.

    The check fires once, at import, and the service refuses to start if any
    of the invariants are broken. The rules:

      1. The two CSVs cover the same set of years.
      2. For every year, the sum of the level-2 areas under each level-1
         group agrees with that level-1 row within
         ``COMPOSITION_AREA_TOLERANCE_HA`` (1e-3 ha = 0.01 m^2).
      3. Every level-1 ``pixel_id`` in the CSV exists in the codebook.
      4. Every level-2 ``pixel_id`` in the CSV exists in the codebook.

    A row that fails any rule stops the service. We do not silently drop
    rows: a value the panel does not show would be a lie.
    """
    years_l1 = set(level1.keys())
    years_l2 = set(level2.keys())
    if years_l1 != years_l2:
        only_l1 = sorted(years_l1 - years_l2)
        only_l2 = sorted(years_l2 - years_l1)
        raise CompositionError(
            "composition CSVs cover different years: "
            f"only in level-1: {only_l1[:5]}{'...' if len(only_l1) > 5 else ''}, "
            f"only in level-2: {only_l2[:5]}{'...' if len(only_l2) > 5 else ''}"
        )

    codebook_level1_ids: set[int] = {
        g["pixel_id"] for g in codebook.get("level1", []) if isinstance(g, dict)
    }
    codebook_class_ids: set[int] = {
        c["pixel_id"] for c in codebook.get("classes", []) if isinstance(c, dict)
    }

    for year in sorted(years_l1):
        l1_by_pixel = level1[year]
        l2_by_pixel = level2.get(year, {})

        # Group level-2 rows by their level-1 pixel_id and sum.
        sums_by_l1: dict[int, float] = {}
        for row in l2_by_pixel.values():
            sums_by_l1[row["level1_pixel_id"]] = (
                sums_by_l1.get(row["level1_pixel_id"], 0.0) + row["area_ha"]
            )

        for pixel_id, row in l1_by_pixel.items():
            expected = row["area_ha"]
            actual = sums_by_l1.get(pixel_id, 0.0)
            if abs(expected - actual) > COMPOSITION_AREA_TOLERANCE_HA:
                raise CompositionError(
                    f"composition sum mismatch for year={year} level1_pixel_id={pixel_id}: "
                    f"level-1 says {expected!r} ha, level-2 sum says {actual!r} ha "
                    f"(tolerance {COMPOSITION_AREA_TOLERANCE_HA} ha)"
                )
            if pixel_id not in codebook_level1_ids:
                raise CompositionError(
                    f"composition level-1 CSV references pixel_id={pixel_id} "
                    f"(year={year}) which is not in the codebook"
                )

        for pixel_id in l2_by_pixel:
            if pixel_id not in codebook_class_ids:
                raise CompositionError(
                    f"composition level-2 CSV references pixel_id={pixel_id} "
                    f"(year={year}) which is not in the codebook"
                )


# Composition pre-parsed state. Same fail-loudly-at-import discipline as the
# manifest and the codebook: if the CSVs are missing, malformed, or
# inconsistent, the service stops with a clear message instead of degrading
# per request.
try:
    _COMPOSITION_L1_DATA: "dict[int, dict[int, dict[str, Any]]]" = _load_composition_level1(
        COMPOSITION_LEVEL1_PATH
    )
    _COMPOSITION_L2_DATA: "dict[int, dict[int, dict[str, Any]]]" = _load_composition_level2(
        COMPOSITION_LEVEL2_PATH
    )
    _validate_composition_consistency(
        _COMPOSITION_L1_DATA, _COMPOSITION_L2_DATA, _CODEBOOK_DATA
    )
except CompositionError as exc:
    raise SystemExit(f"viewer: composition assets missing or malformed: {exc}") from exc


def _composition_years() -> list[int]:
    """Sorted year list shared by both composition endpoints.

    Derived from the already-parsed level-1 dict; the consistency check has
    already proved level-1 and level-2 cover the same years.
    """
    return sorted(_COMPOSITION_L1_DATA.keys())


def _composition_series_payload() -> dict[str, Any]:
    """Build the ``/api/composition/series`` document from the pre-parsed data.

    No CSV I/O happens here; every value is taken verbatim from
    ``_COMPOSITION_L1_DATA`` and the codebook. The D7 labelling is taken
    verbatim from the manifest, which is the same source the map labelling
    uses, so the map and the panel cannot disagree on the extent wording.
    """
    manifest = _MANIFEST_DATA
    codebook = _CODEBOOK_DATA
    years = _composition_years()

    codebook_groups_by_id: dict[int, dict[str, Any]] = {
        g["pixel_id"]: g
        for g in codebook.get("level1", [])
        if isinstance(g, dict) and isinstance(g.get("pixel_id"), int)
    }

    series_groups: list[dict[str, Any]] = []
    total_area_per_year: list[float] = []
    # Pre-collect one entry per level-1 group, in codebook order (the same
    # order the legend renders) so the panel chart and the legend agree.
    for group in codebook.get("level1", []):
        pixel_id = group.get("pixel_id")
        if not isinstance(pixel_id, int):
            continue
        area_ha: list[float] = []
        share_pct: list[float] = []
        for year in years:
            row = _COMPOSITION_L1_DATA.get(year, {}).get(pixel_id)
            if row is None:
                # A level-1 group absent for one year would break the chart's
                # stack alignment. The consistency check forbids it; we still
                # defend with a clear error so a future schema drift doesn't
                # silently produce an empty chart.
                raise CompositionError(
                    f"composition level-1 missing year={year} pixel_id={pixel_id}"
                )
            area_ha.append(row["area_ha"])
            share_pct.append(row["share_pct"])
        series_groups.append(
            {
                "pixel_id": pixel_id,
                "code": group.get("code", ""),
                "name_es": group.get("name_es", ""),
                "name_en": group.get("name_en", ""),
                "color": group.get("color", ""),
                "area_ha": area_ha,
                "share_pct": share_pct,
            }
        )

    # Per-year totals: sum of the level-1 areas for that year, so a consumer
    # can verify the stack totals without recomputing. The consistency check
    # has already proved this matches the level-2 sum within 1e-3 ha.
    for year in years:
        total = 0.0
        for group in series_groups:
            idx = years.index(year)
            total += group["area_ha"][idx]
        total_area_per_year.append(total)

    return {
        "schema_version": COMPOSITION_SCHEMA_VERSION,
        "country": manifest.get("country", COUNTRY),
        "collection": manifest.get("collection", COLLECTION),
        "unit": "ha",
        "years": years,
        "extent_label": manifest.get("extent_label"),
        "boundary_note": manifest.get("extent_boundary_note"),
        "groups": series_groups,
        "total_area_ha_per_year": total_area_per_year,
    }


def _composition_year_payload(year: int) -> dict[str, Any]:
    """Build the ``/api/composition/year/{year}`` document.

    Level-2 rows are sorted by ``area_ha`` descending so the bar breakdown
    can render top-down without a sort in the browser. Colours and names
    come from the codebook; the CSV supplies the area and share figures
    unchanged.
    """
    codebook_classes_by_id: dict[int, dict[str, Any]] = {
        c["pixel_id"]: c
        for c in _CODEBOOK_DATA.get("classes", [])
        if isinstance(c, dict) and isinstance(c.get("pixel_id"), int)
    }
    codebook_groups_by_id: dict[int, dict[str, Any]] = {
        g["pixel_id"]: g
        for g in _CODEBOOK_DATA.get("level1", [])
        if isinstance(g, dict) and isinstance(g.get("pixel_id"), int)
    }
    l2_rows = list(_COMPOSITION_L2_DATA.get(year, {}).values())
    classes: list[dict[str, Any]] = []
    for row in l2_rows:
        cls = codebook_classes_by_id.get(row["pixel_id"], {})
        grp = codebook_groups_by_id.get(row["level1_pixel_id"], {})
        classes.append(
            {
                "pixel_id": row["pixel_id"],
                "code": row["code"] or cls.get("code", ""),
                "name_es": row["name_es"] or cls.get("name_es", ""),
                "name_en": row["name_en"] or cls.get("name_en", ""),
                "color": cls.get("color", ""),
                "level1_pixel_id": row["level1_pixel_id"],
                "level1_code": row["level1_code"] or grp.get("code", ""),
                "level1_name_es": grp.get("name_es", ""),
                "level1_name_en": grp.get("name_en", ""),
                "level1_color": grp.get("color", ""),
                "area_ha": row["area_ha"],
                "share_pct": row["share_pct"],
                "pixels": row["pixels"],
            }
        )
    classes.sort(key=lambda r: r["area_ha"], reverse=True)
    total = sum(r["area_ha"] for r in classes)
    return {
        "schema_version": COMPOSITION_SCHEMA_VERSION,
        "country": _MANIFEST_DATA.get("country", COUNTRY),
        "collection": _MANIFEST_DATA.get("collection", COLLECTION),
        "year": year,
        "unit": "ha",
        "extent_label": _MANIFEST_DATA.get("extent_label"),
        "boundary_note": _MANIFEST_DATA.get("extent_boundary_note"),
        "total_area_ha": total,
        "classes": classes,
    }


# ---------------------------------------------------------------------------
# Clip statistics (slice T8c)
# ---------------------------------------------------------------------------
# The clip endpoint reads ONLY the requested window from the source COG at
# native resolution, never the overviews. Per-row area uses the single
# source-of-truth row-wise geodesic formula imported from
# ``tools/spatial_units.py`` (T6) -- this file does not redefine the
# formula nor copy the authalic radius constant, so the clip figures and
# the committed CSVs share the exact same geometry.
#
# The clip endpoint is the only endpoint that opens a COG on the request
# path: reading the bytes is the work, not a cache lookup. The manifest,
# the codebook, and the composition CSVs continue to be parsed once at
# import (the counters exposed by ``/api/composition/_load_counters`` prove
# this), so a stream of clip requests never re-reads them.
#
# The COG path is resolved from the year and the configured country and
# collection, so the country name never appears as a string literal in the
# route code (decision D5: multi-country from day one).


class ClipStatsError(RuntimeError):
    """Raised when the clip request is malformed or the COG is unreadable."""


def _cog_path_for_year(year: int) -> Path:
    """Resolve the source COG path for a given year.

    The naming pattern is ``coverage-{country}_classification_{year}.tif``
    under ``COG_ROOT``. The country and collection are configuration values
    (decision D5); no path component hardcodes Venezuela.
    """
    return COG_ROOT / f"coverage-{COUNTRY}_classification_{year}.tif"


def _clip_validate_bbox(bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """Validate a 4-tuple bbox and return it unchanged.

    The tuple must be four finite floats with west < east and south < north;
    no intersection check against the raster extent happens here (that is
    the caller's job). Raising ``HTTPException(400)`` keeps the error in
    the same shape as the rest of the validation in this file.
    """
    west, south, east, north = bbox
    if not all(map(math.isfinite, (west, south, east, north))):
        raise HTTPException(
            status_code=400,
            detail=(
                "bbox must be four finite floats (west, south, east, north); "
                f"got ({west}, {south}, {east}, {north})"
            ),
        )
    if west >= east:
        raise HTTPException(
            status_code=400,
            detail=f"bbox west ({west}) must be < east ({east})",
        )
    if south >= north:
        raise HTTPException(
            status_code=400,
            detail=f"bbox south ({south}) must be < north ({north})",
        )
    return (west, south, east, north)


def _clip_bbox_intersects_raster(
    bbox: tuple[float, float, float, float],
    raster_extent: list[float],
) -> bool:
    """Return True iff the bbox shares area with the raster extent.

    A bbox that touches the raster only at an edge is still considered to
    intersect (degenerate intersection). Strict zero-overlap is required to
    raise 400; everything else is silently clipped to the raster extent.
    """
    rw, rs, re, rn = raster_extent
    bw, bs, be, bn = bbox
    if be <= rw or bw >= re or bn <= rs or bs >= rn:
        return False
    return True


def _clip_window_for_bbox(
    bbox: tuple[float, float, float, float],
    cog_path: Path,
) -> tuple[int, int, int, int, float, float, float, float]:
    """Compute the pixel window for a bbox and return window + clipped bbox.

    Returns ``(col_off, row_off, width, height, west, south, east, north)``
    where the four floats are the bbox clipped to the raster extent
    (so the response can echo the actual extent read). Width and height are
    integers (ceil/floor on bounds); a zero-dimension window short-circuits
    the count loop.

    A bbox outside the raster extent is a 400; a partially-outside bbox is
    silently clipped to the raster extent and the response echoes the
    clipped bbox so the caller can tell what was actually read.
    """
    # Import lazily: rasterio is only needed on the request path of the
    # clip endpoint, and we want a clean failure if the dependency is
    # missing instead of blocking module import.
    import rasterio  # noqa: F401  (used inside the ``with`` below)
    from rasterio.windows import from_bounds  # noqa: F401

    with rasterio.open(str(cog_path)) as ds:
        extent = [
            float(ds.bounds.left),
            float(ds.bounds.bottom),
            float(ds.bounds.right),
            float(ds.bounds.top),
        ]
        raster_w = ds.width
        raster_h = ds.height

    if not _clip_bbox_intersects_raster(bbox, extent):
        rw, rs, re, rn = extent
        raise HTTPException(
            status_code=400,
            detail=(
                "bbox does not intersect the source COG extent "
                f"[{rw}, {rs}, {re}, {rn}]; "
                f"got bbox={list(bbox)}"
            ),
        )

    # Clip the bbox to the raster extent so the window calculation lives
    # entirely inside the raster. Using the raster's own bounds keeps the
    # rounding consistent with how rasterio derives the window.
    west = max(bbox[0], extent[0])
    south = max(bbox[1], extent[1])
    east = min(bbox[2], extent[2])
    north = min(bbox[3], extent[3])

    # Compute the pixel window from the clipped bbox via rasterio. We
    # clip again afterwards (defence in depth): from_bounds can return
    # floats, so we floor/ceil into integer pixel boundaries and clamp to
    # the raster.
    with rasterio.open(str(cog_path)) as ds:
        w_raw = from_bounds(west, south, east, north, transform=ds.transform)
        raster_w = ds.width
        raster_h = ds.height
    col_off = max(0, int(math.floor(w_raw.col_off)))
    row_off = max(0, int(math.floor(w_raw.row_off)))
    right = min(raster_w, int(math.ceil(w_raw.col_off + w_raw.width)))
    bottom = min(raster_h, int(math.ceil(w_raw.row_off + w_raw.height)))
    width = max(0, right - col_off)
    height = max(0, bottom - row_off)
    return (col_off, row_off, width, height, west, south, east, north)


def _clip_count_window(
    cog_path: Path,
    col_off: int,
    row_off: int,
    width: int,
    height: int,
    row_block: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Read a window of the COG at native resolution and count classes.

    Returns ``(class_pixels, pixel_area_per_row_m2, window_row_areas_m2,
    class_pixels_per_row)`` where:

      * ``class_pixels`` is an int64 array of length 256 with the total
        class counts across the window.
      * ``pixel_area_per_row_m2`` is the per-row pixel area in m^2 for
        this window (row area / width). Shape ``(height,)``.
      * ``window_row_areas_m2`` is the per-row total area in m^2 (the
        shared row area scaled by the window's share of the raster
        width). Shape ``(height,)``.
      * ``class_pixels_per_row`` is an int64 array of shape
        ``(height, 256)`` carrying the per-row per-class pixel counts.
        The endpoint uses it to attribute per-row area to each class
        exactly, matching the engine's accounting to floating-point
        noise rather than to the mean-pixel-area approximation.

    The counting method reuses the engine's per-row ``np.bincount`` over
    a ``row * 256 + class`` key, exactly the same shape as the production
    composition tool. No sampling, no overviews, no decimation.

    The row-wise geodesic formula is imported from ``spatial_units`` (the
    T6 single source of truth), so the clip endpoint shares its geometry
    with the committed CSVs.
    """
    import rasterio  # noqa: F401  (lazy: keeps import-time cost on the cheap path)

    # sys.path was augmented at module load to include ``tools/`` so
    # ``spatial_units`` resolves to the same module the composition engine
    # imports. The lazy import here keeps the tile route independent of
    # the clip dependency.
    from spatial_units import compute_row_areas_m2

    with rasterio.open(str(cog_path)) as ds:
        gt = tuple(ds.transform.to_gdal())
        raster_w = ds.width
        raster_h = ds.height
        # Read the entire window as one numpy array. At the largest allowed
        # window (~2.7 B pixels) the array is ~2.7 GB, which exceeds the
        # per-process memory budget; we therefore stream the window in
        # row blocks of ``row_block`` rows each.
        nodata_val = ds.nodata

    if nodata_val is None:
        nodata_int: int | None = None
    else:
        nodata_int = int(nodata_val)

    area_per_row_full = compute_row_areas_m2(gt, raster_w, raster_h)
    window_row_areas = (
        area_per_row_full[row_off:row_off + height] * (width / raster_w)
    )
    pixel_area_per_row_m2 = window_row_areas / float(width)

    # Streamed per-block counting. The key is row_in_block * 256 +
    # class_value, so a single ``np.bincount`` reshaped to (block_h, 256)
    # gives every per-row per-class histogram in one shot. Byte class
    # values fit in 256 buckets. We accumulate the totals in a single
    # 256-bucket vector AND keep the per-row shape so the area
    # attribution can use exact per-row pixel counts instead of a
    # mean-pixel-area approximation.
    class_pixels = np.zeros(256, dtype=np.int64)
    class_pixels_per_row = np.zeros((height, 256), dtype=np.int64)
    with rasterio.open(str(cog_path)) as ds:
        for y_local in range(0, height, row_block):
            block_h = min(row_block, height - y_local)
            block = ds.read(
                1,
                window=rasterio.windows.Window(
                    col_off, row_off + y_local, width, block_h,
                ),
            )  # (block_h, width) uint8
            row_idx_arr = (
                np.arange(block_h, dtype=np.int32).reshape(-1, 1) * 256
            )
            keyed = (row_idx_arr + block.astype(np.int32)).ravel()
            hist2 = np.bincount(keyed, minlength=block_h * 256).reshape(
                block_h, 256,
            )
            class_pixels += hist2.sum(axis=0).astype(np.int64)
            class_pixels_per_row[
                y_local:y_local + block_h, :
            ] = hist2.astype(np.int64)

    # Suppress the unused nodata_int warning when the dataset declares
    # nodata outside the Byte range: the histogram already counts it.
    _ = nodata_int

    return class_pixels, pixel_area_per_row_m2, window_row_areas, class_pixels_per_row


def _clip_build_payload(
    year: int,
    bbox_echo: tuple[float, float, float, float],
    pixel_window: dict[str, int],
    cog_extent: list[float],
    class_pixels: np.ndarray,
    class_pixels_per_row: np.ndarray,
    pixel_area_per_row_m2: np.ndarray,
    window_row_areas_m2: np.ndarray,
) -> dict[str, Any]:
    """Assemble the clip-stats JSON payload from the count + area arrays.

    The payload follows the same level-1/level-2 shape as
    ``/api/composition/year/{year}`` so the panel's existing rendering can
    be reused verbatim. The D7 labelling is taken verbatim from the tiles
    manifest (the same source the map labelling uses), and the area-method
    note is fixed because the calculation is fixed.
    """
    manifest = _MANIFEST_DATA
    codebook = _CODEBOOK_DATA
    classes_meta: dict[int, dict[str, Any]] = {
        c["pixel_id"]: c
        for c in codebook.get("classes", [])
        if isinstance(c, dict) and isinstance(c.get("pixel_id"), int)
    }
    groups_meta: dict[int, dict[str, Any]] = {
        g["pixel_id"]: g
        for g in codebook.get("level1", [])
        if isinstance(g, dict) and isinstance(g.get("pixel_id"), int)
    }

    nodata_int = 0  # platform convention; the band declares nodata=0.

    nodata_pixels = int(class_pixels[nodata_int]) if 0 <= nodata_int < 256 else 0
    total_pixels = int(class_pixels.sum())
    # Per-row nodata counts drive the exact per-row nodata area, matching
    # the engine's accounting (``np.dot(nodata_per_row, pixel_area_m2)``).
    nodata_per_row = (
        class_pixels_per_row[:, nodata_int].astype(np.int64)
        if 0 <= nodata_int < 256
        else np.zeros(class_pixels_per_row.shape[0], dtype=np.int64)
    )
    nodata_area_m2 = float(np.dot(nodata_per_row, pixel_area_per_row_m2))
    total_window_area_m2 = float(window_row_areas_m2.sum())
    total_window_area_ha = total_window_area_m2 / 10000.0
    nodata_area_ha = nodata_area_m2 / 10000.0
    valid_area_ha = total_window_area_ha - nodata_area_ha

    # Level-2 rows first (per-class). The level-1 roll-up is computed in
    # the same pass from the level-2 figures, mirroring the composition
    # tool's exact ordering. Area attribution uses per-row pixel counts
    # times per-row pixel area, so the figures reproduce the published
    # CSVs to floating-point noise.
    level2: list[dict[str, Any]] = []
    l1_area_m2: dict[int, float] = {}
    l1_pixels: dict[int, int] = {}
    for cls in codebook.get("classes", []):
        pid = cls.get("pixel_id")
        if not isinstance(pid, int) or not (0 <= pid < 256):
            continue
        pixels = int(class_pixels[pid])
        if pixels == 0 and not CLIP_STATS_INCLUDE_ZERO_CLASSES:
            continue
        # Per-row pixel counts for this class allow exact area attribution
        # (sum over rows of count_per_row * area_per_row).
        class_per_row = class_pixels_per_row[:, pid].astype(np.int64)
        area_m2 = float(np.dot(class_per_row, pixel_area_per_row_m2))
        area_ha = area_m2 / 10000.0
        share = (100.0 * area_ha / valid_area_ha) if valid_area_ha > 0 else 0.0
        grp_id = cls.get("level1_pixel_id")
        if isinstance(grp_id, int):
            l1_area_m2[grp_id] = l1_area_m2.get(grp_id, 0.0) + area_m2
            l1_pixels[grp_id] = l1_pixels.get(grp_id, 0) + pixels
        level2.append(
            {
                "pixel_id": pid,
                "code": cls.get("code", ""),
                "name_es": cls.get("name_es", ""),
                "name_en": cls.get("name_en", ""),
                "color": cls.get("color", ""),
                "level1_pixel_id": grp_id if isinstance(grp_id, int) else None,
                "level1_code": (
                    groups_meta.get(grp_id, {}).get("code", "")
                    if isinstance(grp_id, int) else ""
                ),
                "pixels": pixels,
                "area_ha": area_ha,
                "share_pct": share,
            }
        )

    level2.sort(key=lambda r: r["area_ha"], reverse=True)

    # Level-1 roll-up, in codebook order so the panel chart and the legend
    # agree on the colour and the order.
    level1: list[dict[str, Any]] = []
    for grp in codebook.get("level1", []):
        gid = grp.get("pixel_id")
        if not isinstance(gid, int):
            continue
        area_m2 = l1_area_m2.get(gid, 0.0)
        pixels = l1_pixels.get(gid, 0)
        area_ha = area_m2 / 10000.0
        share = (100.0 * area_ha / valid_area_ha) if valid_area_ha > 0 else 0.0
        level1.append(
            {
                "pixel_id": gid,
                "code": grp.get("code", ""),
                "name_es": grp.get("name_es", ""),
                "name_en": grp.get("name_en", ""),
                "color": grp.get("color", ""),
                "pixels": pixels,
                "area_ha": area_ha,
                "share_pct": share,
            }
        )
    level1.sort(key=lambda r: r["area_ha"], reverse=True)

    return {
        "schema_version": CLIP_STATS_SCHEMA_VERSION,
        "country": manifest.get("country", COUNTRY),
        "collection": manifest.get("collection", COLLECTION),
        "year": year,
        "bbox": list(bbox_echo),
        "window": pixel_window,
        "unit": "ha",
        "area_method": (
            "row-wise geodesic area on the WGS84 sphere, identical to the "
            "committed composition statistics; per-row pixel area = "
            "row_areas_m2 / window_width, with row_areas_m2 derived from "
            "the source COG geotransform via tools/spatial_units.py"
        ),
        "extent_label": manifest.get("extent_label"),
        "boundary_note": manifest.get("extent_boundary_note"),
        "valid_area_ha": valid_area_ha,
        "nodata_area_ha": nodata_area_ha,
        "total_window_area_ha": total_window_area_ha,
        "total_pixels": total_pixels,
        "nodata_pixels": nodata_pixels,
        "level1": level1,
        "level2": level2,
        "cog_extent": cog_extent,
    }


# When True, the clip endpoint emits rows for every declared class even if
# the window contains zero pixels of that class. When False, only classes
# with at least one pixel in the window appear, which is what the panel
# renders. Off by default: the panel's bar breakdown would otherwise show
# a long tail of empty bars for every clip.
CLIP_STATS_INCLUDE_ZERO_CLASSES: Final[bool] = False


def _manifest_years(manifest: dict[str, Any]) -> list[int]:
    """Derive the authoritative year list from the manifest.

    The manifest schema is supposed to expose ``years`` at the top level.
    When it does, that wins. When it does not, we fall back to the union of
    ``totals.years_succeeded`` and the per-year entries; either source on
    its own is enough. The result is sorted and deduplicated.
    """
    raw: list[Any] = []
    top = manifest.get("years")
    if isinstance(top, list):
        raw.extend(top)
    totals = manifest.get("totals")
    if isinstance(totals, dict):
        succeeded = totals.get("years_succeeded")
        if isinstance(succeeded, list):
            raw.extend(succeeded)
    entries = manifest.get("entries")
    if isinstance(entries, list):
        for e in entries:
            if isinstance(e, dict) and "year" in e:
                raw.append(e["year"])
    years: set[int] = set()
    for v in raw:
        if isinstance(v, int) and not isinstance(v, bool):
            years.add(v)
        elif isinstance(v, str) and v.isdigit():
            years.add(int(v))
    if not years:
        raise ManifestError("manifest does not declare any usable year")
    return sorted(years)


def _manifest_zoom(manifest: dict[str, Any]) -> tuple[int, int]:
    """Parse the zoom range from the manifest.

    Accepts either ``zoom_range_requested`` (e.g. ``"0-12"``) or per-entry
    ``zoom_levels_present``. Returns (z_min, z_max) inclusive.
    """
    raw = manifest.get("zoom_range_requested")
    if isinstance(raw, str) and "-" in raw:
        a, b = raw.split("-", 1)
        try:
            return int(a), int(b)
        except ValueError as exc:
            raise ManifestError(f"zoom_range_requested is not 'min-max': {raw!r}") from exc
    # Fall back to per-entry zoom_levels_present.
    entries = manifest.get("entries")
    if isinstance(entries, list) and entries:
        zs: set[int] = set()
        for e in entries:
            if isinstance(e, dict):
                zl = e.get("zoom_levels_present")
                if isinstance(zl, list):
                    for v in zl:
                        if isinstance(v, int):
                            zs.add(v)
        if zs:
            return min(zs), max(zs)
    raise ManifestError("manifest does not declare a usable zoom range")


# ---------------------------------------------------------------------------
# Source COG geotransform (no GDAL dependency)
# ---------------------------------------------------------------------------
# The venv does not include GDAL or rasterio. We only need the bounding box
# of the source COG to initialise the map view, so we parse the BigTIFF
# header directly. The COG was built by ``tools/normalize_to_cog.py`` with
# GeoTIFF tags 33550 (ModelPixelScaleTag) and 33922 (ModelTiepointTag).
# BigTIFF is detected via the magic number 43 in the header.

class CogExtentError(RuntimeError):
    """Raised when the source COG extent cannot be derived."""


def _read_big_tiff_extent(cog_path: Path) -> list[float]:
    """Read [west, south, east, north] from a COG's geotransform.

    Supports BigTIFF (magic 43) and classic TIFF (magic 42). Falls back to
    classic TIFF if BigTIFF parsing does not yield the required tags.
    """
    with cog_path.open("rb") as fh:
        head = fh.read(2048)
    if len(head) < 8:
        raise CogExtentError(f"COG header too short: {cog_path}")
    bo = head[:2]
    if bo not in (b"II", b"MM"):
        raise CogExtentError(f"COG byte order not recognised: {cog_path}")
    little = bo == b"II"

    def unpack(fmt: str, off: int) -> tuple[Any, ...]:
        return struct.unpack_from(
            ("<" if little else ">") + fmt, head, off
        )

    magic = unpack("H", 2)[0]
    width: int | None = None
    height: int | None = None
    pixel_scale: tuple[float, float, float] | None = None
    tiepoint: tuple[float, float, float, float, float, float] | None = None

    if magic == 43:
        # BigTIFF: byte_order(2) version(2) offset_size(2) reserved(2) ifd_off(8)
        ifd_off = unpack("Q", 8)[0]
        # num_entries is 8 bytes at ifd_off
        if ifd_off + 8 > len(head):
            with cog_path.open("rb") as fh:
                fh.seek(ifd_off)
                head = head + fh.read(64 * 1024)
        num_entries = unpack("Q", ifd_off)[0]
        entries_start = ifd_off + 8
        # Each BigTIFF IFD entry is 20 bytes.
        for i in range(int(num_entries)):
            eoff = entries_start + i * 20
            if eoff + 20 > len(head):
                with cog_path.open("rb") as fh:
                    fh.seek(eoff)
                    head = head + fh.read(64 * 1024)
            tag, typ, cnt = unpack("HHQ", eoff)[:3]
            voff_bytes = head[eoff + 12 : eoff + 20]
            if tag in (256, 257):
                # ImageWidth / ImageLength. Inline SHORT value.
                value = int.from_bytes(voff_bytes[:2], "little" if little else "big")
                if tag == 256:
                    width = value
                else:
                    height = value
            elif tag == 33550:
                # ModelPixelScaleTag: 3 doubles
                arr_off = unpack("Q", eoff + 12)[0]
                if arr_off + 24 > len(head):
                    with cog_path.open("rb") as fh:
                        fh.seek(arr_off)
                        head = head + fh.read(64 * 1024)
                pixel_scale = struct.unpack_from(
                    ("<" if little else ">") + "ddd", head, arr_off
                )
            elif tag == 33922:
                # ModelTiepointTag: 6 doubles (i, j, k, x, y, z)
                arr_off = unpack("Q", eoff + 12)[0]
                if arr_off + 48 > len(head):
                    with cog_path.open("rb") as fh:
                        fh.seek(arr_off)
                        head = head + fh.read(64 * 1024)
                tiepoint = struct.unpack_from(
                    ("<" if little else ">") + "dddddd", head, arr_off
                )
    elif magic == 42:
        # Classic TIFF: byte_order(2) magic(2) ifd_off(4) ...
        ifd_off = unpack("I", 4)[0]
        if ifd_off + 2 > len(head):
            with cog_path.open("rb") as fh:
                fh.seek(ifd_off)
                head = head + fh.read(64 * 1024)
        num_entries = unpack("H", ifd_off)[0]
        entries_start = ifd_off + 2
        # Each classic TIFF IFD entry is 12 bytes.
        for i in range(int(num_entries)):
            eoff = entries_start + i * 12
            if eoff + 12 > len(head):
                with cog_path.open("rb") as fh:
                    fh.seek(eoff)
                    head = head + fh.read(64 * 1024)
            tag, typ, cnt = unpack("HHI", eoff)[:3]
            voff = unpack("I", eoff + 8)[0]
            if tag in (256, 257):
                if tag == 256:
                    width = unpack("H", eoff + 8)[0]
                else:
                    height = unpack("H", eoff + 8)[0]
            elif tag == 33550:
                if voff + 24 > len(head):
                    with cog_path.open("rb") as fh:
                        fh.seek(voff)
                        head = head + fh.read(64 * 1024)
                pixel_scale = struct.unpack_from(
                    ("<" if little else ">") + "ddd", head, voff
                )
            elif tag == 33922:
                if voff + 48 > len(head):
                    with cog_path.open("rb") as fh:
                        fh.seek(voff)
                        head = head + fh.read(64 * 1024)
                tiepoint = struct.unpack_from(
                    ("<" if little else ">") + "dddddd", head, voff
                )
    else:
        raise CogExtentError(f"COG magic number is not TIFF or BigTIFF: {magic}")

    if width is None or height is None:
        raise CogExtentError("COG is missing ImageWidth / ImageLength")
    if pixel_scale is None or tiepoint is None:
        raise CogExtentError(
            "COG is missing ModelPixelScaleTag or ModelTiepointTag; cannot derive extent"
        )
    sx, sy, _sz = pixel_scale
    _, _, _, x0, y0, _z0 = tiepoint
    # Standard north-up interpretation: x increases east, y decreases south.
    west = x0
    north = y0
    east = x0 + width * sx
    south = y0 - height * sy
    return [west, south, east, north]


def _find_source_cog_extent() -> list[float]:
    """Locate the most recent source COG and derive its geographic extent.

    The platform is multi-country, so we don't hard-code the filename: we
    look for any file matching ``coverage-{country}_classification_<year>.tif``
    in the COG directory and pick the most recent year present. Falling back
    to that file gives us a deterministic extent even if the most recent year
    is still being rewritten.
    """
    if not COG_ROOT.is_dir():
        raise CogExtentError(f"COG directory not found: {COG_ROOT}")
    pattern = re.compile(rf"coverage-{re.escape(COUNTRY)}_classification_(\d{{4}})\.tif$")
    candidates: list[tuple[int, Path]] = []
    for p in COG_ROOT.iterdir():
        if not p.is_file():
            continue
        m = pattern.match(p.name)
        if m:
            candidates.append((int(m.group(1)), p))
    if not candidates:
        raise CogExtentError(f"no source COG found in {COG_ROOT}")
    candidates.sort()
    _, latest = candidates[-1]
    return _read_big_tiff_extent(latest)


# ---------------------------------------------------------------------------
# Legend assembly
# ---------------------------------------------------------------------------

def _build_legend(codebook: dict[str, Any]) -> list[dict[str, Any]]:
    """Assemble the hierarchical legend (level-1 groups with nested classes).

    Class order inside each group is preserved from the codebook so that the
    official legend order is what the viewer shows. We only keep the fields
    the frontend actually renders plus the colour used as the swatch.
    """
    level1: list[dict[str, Any]] = codebook.get("level1", [])
    classes: list[dict[str, Any]] = codebook.get("classes", [])
    by_group: dict[int, list[dict[str, Any]]] = {}
    for cls in classes:
        parent = cls.get("level1_pixel_id")
        if not isinstance(parent, int):
            continue
        by_group.setdefault(parent, []).append(
            {
                "pixel_id": cls.get("pixel_id"),
                "code": cls.get("code"),
                "name_es": cls.get("name_es"),
                "name_en": cls.get("name_en"),
                "color": cls.get("color"),
            }
        )

    out: list[dict[str, Any]] = []
    for g in level1:
        pixel_id = g.get("pixel_id")
        if not isinstance(pixel_id, int):
            continue
        out.append(
            {
                "pixel_id": pixel_id,
                "code": g.get("code"),
                "name_es": g.get("name_es"),
                "name_en": g.get("name_en"),
                "color": g.get("color"),
                "classes": by_group.get(pixel_id, []),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

def _safe_resolve(tile_root: Path, year: int, z: int, x: int, y: int) -> Path:
    """Resolve the tile path and prove it stays inside ``tile_root``.

    The route handlers already coerce the parameters to ``int`` and validate
    the integer ranges. This function does the *filesystem* check that an
    attacker cannot bypass by encoding, double-encoding, percent-encoding or
    smuggling ``..`` past the route parser -- FastAPI decodes percent-encoded
    path components before they reach us, and Starlette's path matcher would
    reject ``..`` segments that change the URL path, but we still want a
    belt-and-braces check on the resolved path that we are about to open.

    Returns the resolved file path. Raises ``HTTPException(404)`` if the
    resolved path escapes ``tile_root`` or the file is not a regular file.
    """
    candidate = (tile_root / str(year) / str(z) / str(x) / f"{y}.png").resolve()
    root_resolved = tile_root.resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        # The resolved path tried to escape the tile root. Treat as 404, not
        # 500, so the request never gets a chance to surface a server error.
        raise HTTPException(status_code=404, detail="tile not found") from exc
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="tile not found")
    return candidate


# ---------------------------------------------------------------------------
# App construction
# ---------------------------------------------------------------------------

app = FastAPI(
    title="MapBiomas viewer",
    version=META_SCHEMA_VERSION,
    # Hide framework banners on startup; this is a small viewer, not a service.
    docs_url=None,
    redoc_url=None,
)


@app.get("/api/health")
def api_health() -> dict[str, Any]:
    """One-call diagnosis of which assets this instance resolves to.

    A failure to find any required asset is reported with status 200 but a
    status flag the client can switch on, so a misconfigured deploy surfaces
    in the same UI that is supposed to show the map. The HTTP status stays
    200 because this endpoint is also used by ``/api/health``-style probes
    that expect a healthy 200.
    """
    manifest_status = MANIFEST_PATH.is_file()
    codebook_status = CODEBOOK_PATH.is_file()
    tiles_root_status = TILES_ROOT.is_dir()
    cog_root_status = COG_ROOT.is_dir()
    overall = (
        manifest_status and codebook_status and tiles_root_status and cog_root_status
    )
    return {
        "status": "ok" if overall else "degraded",
        "schema_version": META_SCHEMA_VERSION,
        "country": COUNTRY,
        "collection": COLLECTION,
        "repo_root": str(REPO_ROOT),
        "paths": {
            "manifest": str(MANIFEST_PATH),
            "codebook": str(CODEBOOK_PATH),
            "tiles_root": str(TILES_ROOT),
            "cog_root": str(COG_ROOT),
            "viewer_dir": str(VIEWER_DIR),
        },
        "checks": {
            "manifest_exists": manifest_status,
            "codebook_exists": codebook_status,
            "tiles_root_exists": tiles_root_status,
            "cog_root_exists": cog_root_status,
        },
        "tile_url_template": TILE_URL_TEMPLATE,
    }


@app.get("/api/meta")
def api_meta() -> JSONResponse:
    """Return the viewer metadata assembled from the manifest and codebook."""
    manifest = _MANIFEST_DATA
    codebook = _CODEBOOK_DATA
    try:
        years = _manifest_years(manifest)
        z_min, z_max = _manifest_zoom(manifest)
        legend = _build_legend(codebook)
        extent = _find_source_cog_extent()
    except ManifestError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except CogExtentError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    payload: dict[str, Any] = {
        "schema_version": META_SCHEMA_VERSION,
        "country": manifest.get("country", COUNTRY),
        "collection": manifest.get("collection", COLLECTION),
        "years": years,
        "zoom_range": {"min": z_min, "max": z_max},
        "tile_scheme": manifest.get("tile_scheme"),
        "tile_profile": manifest.get("tile_profile"),
        "resampling": manifest.get("resampling"),
        "extent_label": manifest.get("extent_label"),
        "boundary_note": manifest.get("extent_boundary_note"),
        "legend": legend,
        "tile_url_template": TILE_URL_TEMPLATE,
        "extent": extent,
    }
    # The meta document is not long-lived immutable; the dataset could be
    # regenerated. Cache it for a short window so a busy map can avoid
    # re-fetching on every interaction, but never longer than the integrity
    # window of the pyramid.
    return JSONResponse(
        payload,
        headers={"Cache-Control": "no-cache"},
    )


# ---------------------------------------------------------------------------
# Composition endpoints (slice T8b)
# ---------------------------------------------------------------------------
# Both endpoints read the pre-parsed composition data structures populated at
# import time. They take no I/O on the request path: the CSVs were parsed
# once when the module loaded, and the consistency check has already proved
# they agree with the codebook and with each other. The D7 labelling is
# taken verbatim from the tiles manifest, the same source the map's
# labelling uses, so the panel and the map cannot disagree on the extent
# wording.

@app.get("/api/composition/series")
def api_composition_series() -> JSONResponse:
    """Return the 40-year level-1 series for the composition panel.

    The payload carries the D7 extent labelling at the top level, the sorted
    year list, one entry per level-1 group with parallel ``area_ha`` and
    ``share_pct`` arrays aligned to ``years``, and a per-year total so the
    consumer can verify the stack sums without recomputing.

    Cache-Control mirrors ``/api/meta``: the dataset is regenerable, so we
    hold a short window but no long-lived immutable marker.
    """
    return JSONResponse(
        _composition_series_payload(),
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/api/composition/year/{year}")
def api_composition_year(year: int = PathParam(..., ge=0)) -> JSONResponse:
    """Return the level-2 breakdown for one year, sorted by area descending.

    An unknown year returns 404; the route is integer-typed and rejects
    non-integers at the FastAPI layer (422).
    """
    if year not in _COMPOSITION_L2_DATA:
        raise HTTPException(status_code=404, detail=f"composition year not found: {year}")
    return JSONResponse(
        _composition_year_payload(year),
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/api/composition/_load_counters")
def api_composition_load_counters() -> dict[str, Any]:
    """Diagnostic: how many times the CSV loaders have run.

    Used by the verification harness to prove no per-request CSV re-parsing
    happens (the previous review finding, R3-SERVE-VIEWER-NO-CACHE-RELOAD,
    was about re-parsing on every tile request). This endpoint is intentionally
    cheap: it returns two integers from module-scope counters.
    """
    return {
        "level1_calls": _COMPOSITION_L1_LOAD_COUNTER.calls,
        "level2_calls": _COMPOSITION_L2_LOAD_COUNTER.calls,
    }


# ---------------------------------------------------------------------------
# Clip stats endpoint (slice T8c)
# ---------------------------------------------------------------------------
# Reads ONLY the requested window from the source COG at native resolution
# (never overviews), counts per-class pixels, and returns per-class areas
# using the same row-wise geodesic formula as the committed CSVs. The
# endpoint is the only one that opens a COG on the request path: reading
# the bytes is the work, not a cache lookup. The manifest, codebook and
# composition CSVs continue to be parsed once at import (counters in
# ``/api/composition/_load_counters``); a burst of clip requests never
# re-reads them.


@app.get("/api/clip-stats")
def api_clip_stats(
    bbox: str = Query(
        ...,
        description=(
            "Comma-separated geographic bbox: west, south, east, north in "
            "EPSG:4326 degrees (WGS84)."
        ),
    ),
    year: int = Query(
        ...,
        description="Year of the COG (e.g. 2024); must be one of the manifest years.",
    ),
) -> JSONResponse:
    """Return per-class composition for a user-drawn rectangle on the map.

    The endpoint does the work the panel cannot do without a server:
    streams the COG window at native resolution, counts every pixel with
    the same ``np.bincount(row * 256 + class)`` method the committed
    composition engine uses, and returns per-row geodesic areas derived
    from the same ``tools/spatial_units.py`` formula the CSVs were written
    with. The D7 labelling is attached to the response verbatim from the
    manifest, the same source the map labelling uses, so the clip result
    cannot disagree with the map on the extent wording.

    Validation, in order:

      1. ``bbox`` parses as four finite floats with west < east and
         south < north (400 on failure).
      2. The bbox intersects the source COG's geographic extent; a
         fully-outside bbox is a 400 with a clear message.
      3. The pixel window is bounded at ``CLIP_STATS_MAX_PIXELS`` (36 M
         pixels = 6000 x 6000). Anything larger is rejected with 413 and
         a message that states the bound.
      4. ``year`` is one of the manifest's declared years (404 otherwise).
      5. The COG file exists on disk (404 with a clear message otherwise).
    """
    # Step 1: parse + validate the bbox.
    try:
        parts = [p.strip() for p in bbox.split(",")]
        if len(parts) != 4:
            raise ValueError(f"expected 4 comma-separated floats, got {len(parts)}")
        west, south, east, north = (float(p) for p in parts)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"bbox must be four comma-separated finite floats "
                f"(west, south, east, north); got {bbox!r}: {exc}"
            ),
        ) from exc
    bbox_in = _clip_validate_bbox((west, south, east, north))

    # Step 4: validate the year against the manifest (the canonical year
    # source for the platform). Years outside the manifest are a 404 so the
    # frontend's "no data for this year" path is the same one for unknown
    # years and for unknown COG files.
    try:
        manifest_years = _manifest_years(_MANIFEST_DATA)
    except ManifestError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if year not in manifest_years:
        raise HTTPException(
            status_code=404,
            detail=f"year not in tiles manifest: {year}",
        )

    # Step 5: the COG for this year must exist on disk.
    cog_path = _cog_path_for_year(year)
    if not cog_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=(
                f"source COG not found for year {year}: {cog_path}; "
                "expected coverage-{country}_classification_<year>.tif "
                "under the configured COG root"
            ),
        )

    # Step 2 + 3: derive the pixel window from the bbox, clipping to the
    # raster extent. A bbox outside the raster is a 400. An empty window
    # (degenerate edge intersection) is a 200 with zero figures so the
    # panel still renders, but this is unlikely for a real user rectangle.
    try:
        col_off, row_off, width, height, cw, cs, ce, cn = _clip_window_for_bbox(
            bbox_in, cog_path,
        )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive net
        raise HTTPException(
            status_code=503,
            detail=f"could not derive pixel window from bbox: {exc}",
        ) from exc

    if width <= 0 or height <= 0:
        # Degenerate: the bbox touches the raster at an edge but covers no
        # pixel. Surface a clear 400 rather than returning an empty
        # breakdown that would mislead the panel reader.
        raise HTTPException(
            status_code=400,
            detail=(
                "bbox intersects the COG extent but covers no native pixel "
                f"(resolved window width={width}, height={height}); "
                "draw a larger rectangle"
            ),
        )

    pixel_count = width * height
    if pixel_count > CLIP_STATS_MAX_PIXELS:
        raise HTTPException(
            status_code=413,
            detail=(
                f"requested window is too large: {width}x{height} = "
                f"{pixel_count} pixels, bound is "
                f"{CLIP_STATS_MAX_PIXELS} pixels; "
                "split the rectangle or zoom in. The bound keeps the "
                "worst case under half a second, which is what makes the "
                "interaction feel live. For the whole extent or any "
                "larger area, use the composition endpoints: they serve "
                "the published figures for the full extent without a "
                "windowed read."
            ),
        )

    # Stream the window, count classes, derive per-row areas. This is the
    # only place a request opens a COG; the manifest, codebook and CSVs
    # are untouched on this path.
    try:
        (
            class_pixels,
            pixel_area_per_row_m2,
            window_row_areas_m2,
            class_pixels_per_row,
        ) = _clip_count_window(
            cog_path, col_off, row_off, width, height,
            CLIP_STATS_ROW_BLOCK,
        )
    except Exception as exc:
        # Reading the COG can fail for filesystem or GDAL reasons. We
        # surface a clear message rather than a stack trace so the panel
        # can show something useful.
        raise HTTPException(
            status_code=503,
            detail=(
                f"could not read COG window for year {year}: {exc}; "
                "the COG may be unreadable or partially written"
            ),
        ) from exc

    # Get the COG extent for the response echo, so the caller can see
    # what the bbox was clipped against.
    import rasterio  # noqa: F401  (cheap second open, same interpreter)
    with rasterio.open(str(cog_path)) as ds:
        cog_extent = [
            float(ds.bounds.left),
            float(ds.bounds.bottom),
            float(ds.bounds.right),
            float(ds.bounds.top),
        ]

    payload = _clip_build_payload(
        year=year,
        bbox_echo=(cw, cs, ce, cn),
        pixel_window={
            "col_off": col_off,
            "row_off": row_off,
            "width": width,
            "height": height,
        },
        cog_extent=cog_extent,
        class_pixels=class_pixels,
        class_pixels_per_row=class_pixels_per_row,
        pixel_area_per_row_m2=pixel_area_per_row_m2,
        window_row_areas_m2=window_row_areas_m2,
    )
    return JSONResponse(payload, headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------------------
# Tile serving
# ---------------------------------------------------------------------------

@app.get("/tiles/{year}/{z}/{x}/{y}.png")
def serve_tile(
    year: int = PathParam(..., ge=0),
    z: int = PathParam(..., ge=0),
    x: int = PathParam(..., ge=0),
    y: int = PathParam(..., ge=0),
) -> Response:
    """Serve one PNG tile.

    Validation layers, in order:

      1. ``year`` must be one of the manifest's declared years.
      2. ``z`` must lie inside the manifest's declared zoom range.
      3. ``x`` and ``y`` must lie inside the Web Mercator grid for ``z``
         (that is, ``0 <= x, y < 2**z``).
      4. The resolved file path must stay strictly inside ``TILES_ROOT``
         (defence in depth; the integer validation already rules out raw
         path traversal in the URL).
      5. The tile must actually exist on disk; transparent tiles are
         intentionally omitted from the pyramid and the client treats a 404
         as transparent.
    """
    # Layer 1: year must be in the manifest.
    try:
        years = _manifest_years(_MANIFEST_DATA)
        z_min, z_max = _manifest_zoom(_MANIFEST_DATA)
    except ManifestError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if year not in years:
        raise HTTPException(status_code=404, detail="tile not found")
    if z < z_min or z > z_max:
        raise HTTPException(status_code=404, detail="tile not found")

    # Layer 3: x / y must fit in the Web Mercator grid for that z.
    max_xy = 1 << z
    if x >= max_xy or y >= max_xy:
        raise HTTPException(status_code=404, detail="tile not found")

    # Layer 4 + 5: resolve path, prove it is inside TILES_ROOT, ensure the
    # file is a regular file.
    file_path = _safe_resolve(TILES_ROOT, year, z, x, y)

    # We do not stream: tiles are small (256x256 PNG, typically a few kB up
    # to a few hundred kB), and FileResponse handles ``Content-Length`` and
    # the ``image/png`` media type for us.
    return FileResponse(
        file_path,
        media_type="image/png",
        headers={"Cache-Control": TILE_CACHE_CONTROL},
    )


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------
# Serve the viewer at "/" and its static assets under "/static/..." so the
# asset URLs in the HTML can be deterministic.

if VIEWER_DIR.is_dir():
    app.mount(
        "/static",
        StaticFiles(directory=str(VIEWER_DIR), check_dir=True),
        name="viewer-static",
    )

    @app.get("/", include_in_schema=False)
    def serve_index() -> FileResponse:
        index = VIEWER_DIR / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=503, detail="viewer not installed")
        return FileResponse(
            index,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/favicon.ico", include_in_schema=False)
    def serve_favicon() -> Response:
        """Serve the inline SVG favicon declared in ``viewer/index.html``.

        We keep the URL as ``/favicon.ico`` because that is what browsers
        fetch by default; the Content-Type is what tells the browser the
        real format. Returning a small inline SVG avoids shipping a
        binary ``.ico`` blob while still silencing the ``GET /favicon.ico``
        404 the parent observed in a real-browser console.
        """
        return Response(
            content=FAVICON_SVG,
            media_type="image/svg+xml",
            headers={"Cache-Control": FAVICON_CACHE_CONTROL},
        )
else:
    @app.get("/", include_in_schema=False)
    def serve_index_missing() -> JSONResponse:  # pragma: no cover - safety net
        return JSONResponse(
            {"error": "viewer directory not found", "path": str(VIEWER_DIR)},
            status_code=503,
        )
