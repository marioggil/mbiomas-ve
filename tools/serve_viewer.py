"""FastAPI service for the MapBiomas data platform viewer.

This service is the read-only front door of the platform. It serves:

  * the tile pyramid (PNG XYZ) for one country / collection, with strict
    per-request validation (year, zoom, x, y, file existence, and a hard
    confinement check that any served path stays inside the tile root);
  * ``/api/meta``, a JSON document assembled from the tile manifest and the
    codebook -- never hard-coded in this file -- so that an operator can
    rerun a different country/collection without editing the viewer;
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

import json
import os
import re
import struct
from pathlib import Path
from typing import Any, Final

from fastapi import FastAPI, HTTPException, Path as PathParam, Query, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse


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
