#!/usr/bin/env python3
"""Build the static XYZ tile pyramid (Web Mercator) that the viewer consumes.

WHY THIS TOOL EXISTS
--------------------
The viewer needs an XYZ raster pyramid in Web Mercator so a browser can fetch a
PNG per (z, x, y) and paint it over the basemap. The COGs in
``data/cog/<country>/collection-<n>/`` are EPSG:4326 with Byte class codes;
the viewer cannot read them directly. This tool is the bridge.

Design choices the rest of this file rests on:

1. The codebook is the SINGLE source of colour. Each year gets the same
   ``#rrggbb`` from ``data/legend/<country>-collection-<n>.json`` and the
   palette is rebuilt from it on every run. The COG stays analysis-grade
   (class codes only) and the colour lives in one place. We record the
   codebook path and its SHA-256 in the manifest so that a palette change
   is detectable after the fact, not silently.

2. NEAREST resampling, not average/bilinear. These rasters encode DISCRETE
   CLASS CODES (0, 3, 4, 5, 6, ...). An averaged 3.5 pixel is not a class
   and would corrupt both the pyramid and any downstream area statistic
   that accidentally read it. ``gdal2tiles``'s default ``average`` is a
   correctness bug here, which is why ``-r near`` is non-negotiable.

3. Two cheap VRTs instead of one expensive raster per year. Writing a 57605 x
   45000 Byte RGBA raster per year (~2.6 GB of pixels) just to give it a
   colour would burn ~100 GB across the 40-year series and buy nothing.
   A paletted VRT references the COG's bytes unchanged; the RGBA VRT
   (``gdal_translate -of vrt -expand rgba``) only reinterprets them at
   read time. Both VRTs together cost a few kilobytes on disk.

4. ``gdal2tiles`` refuses a paletted input; the working route is
   paletted VRT -> ``gdal_translate -of vrt -expand rgba`` -> RGBA VRT.
   Anything else produces zero tiles and a confusing log.

5. Each VRT must carry BOTH ``<SRS>`` and ``<GeoTransform>`` taken from the
   source COG's own metadata. ``gdal2tiles`` silently produces zero tiles
   when either is missing, which is the failure we have already paid to
   discover: a year that produced zero tiles must be impossible to miss.

6. ``-x`` excludes fully transparent tiles, which keeps ocean tiles out of
   the pyramid and halves the file count for a country dataset. ``--xyz``
   uses OSM/MapLibre-style tile numbering. ``-w none`` skips the bundled
   HTML viewer; we ship our own.

7. Measured sizing (parent has the numbers): one full year z0-z12 is
   ~15 332 tiles and ~141 MB at ~6.7 KB/tile, so 40 years is
   ~613 000 tiles and ~5.5 GB. Disk has plenty.

Usage::

    tools/build_tiles.py --country <c> --collection <n> \\
        --cog-dir <dir> --codebook <json> \\
        --outdir <dir> --manifest <path> \\
        [--years 2024 1985] [--zoom 0-12] [--processes N] [--resume]

    tools/build_tiles.py --country <c> --collection <n> \\
        --codebook <json> \\
        --outdir <dir> --manifest <path> \\
        --scan-only

WHY SCAN-ONLY EXISTS (manifest as pyramid provenance, not run provenance)
--------------------------------------------------------------------------
A build run writes the manifest for whatever years it actually processed.
When a build is interrupted (machine reboot, killed process, out-of-disk)
and resumed with ``--years <window>``, the resulting manifest describes
that WINDOW, not the full pyramid. That is misleading provenance: every
downstream consumer of the manifest (the viewer, the composition stats,
any external auditor) reads ``years_succeeded`` and trusts it as the
pyramid's contents. A resume window of 27 years silently told the world
the pyramid was 27 years old when it was 40.

``--scan-only`` rebuilds the manifest from the pyramid already on disk.
It never invokes ``gdal_translate`` or ``gdal2tiles``: it just walks
every ``<outdir>/<year>/`` directory, counts tiles, sums bytes, lists
zoom levels and computes per-zoom tile counts, and writes a manifest
whose contents are equivalent to a successful full build. The pyramid
is the source of truth; the manifest follows the pyramid, not the run.

WHY TILES ARE VERIFIED, NOT JUST COUNTED (the resume-skips-existing trap)
--------------------------------------------------------------------------
``gdal2tiles -e`` (``--resume`` here) preserves files that already exist.
If a tile is left truncated on disk (size 0, partial PNG, no IEND)
because the process that wrote it died mid-write, a subsequent ``--resume``
will see the file and SKIP it. The zero-tile-guard in this tool catches
a whole year producing no tiles; it cannot catch one truncated tile
among ~16 565. A pyramid that ``looks`` 662 600 tiles wide but contains
a single 0-byte PNG is a broken pyramid the viewer will fetch and fail
to decode.

Tile integrity is therefore mandatory, in BOTH modes. Every PNG is
checked for non-zero size, the 8-byte PNG signature, and a trailing
``IEND`` chunk with zero length. Per-year and totals records carry
``tiles_verified``, ``zero_byte_count``, ``malformed_count``,
``malformed_examples`` and an ``integrity_verified`` boolean; any
non-zero integrity finding makes the process exit non-zero AFTER the
manifest has been written, so a broken pyramid cannot be reported as a
success.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from osgeo import gdal

gdal.UseExceptions()


# --- Constants ---------------------------------------------------------------

YEAR_RE = re.compile(r"(19|20)\d{2}")

# 256-entry palette; every codebook pixel_id is mapped, every other index
# (including nodata 0) is fully transparent so it can be excluded by ``-x``.
PALETTE_SIZE = 256

# Default zoom range when the caller does not pin one. Matches the maximum
# the parent has measured. z0 covers the world in 1 tile and z12 is the
# deepest level where Venezuela still has meaningful coverage on a single
# tile pyramid (~150 m/pixel at the equator).
DEFAULT_ZOOM = "0-12"

# Default parallelism; matches the verification invocation in the spec.
DEFAULT_PROCESSES = 1

# PNG file-format constants used by the integrity check. A valid PNG starts
# with the 8-byte signature and ends with a 12-byte IEND chunk (length=0,
# type="IEND", plus a 4-byte CRC). Anything else is malformed for the
# purposes of this tool.
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_IEND_TYPE = b"IEND"
PNG_IEND_LENGTH = b"\x00\x00\x00\x00"
# Smallest legal PNG body size in this verification: 8 (sig) + 12 (IEND)
# = 20 bytes. We use it as a fast reject before opening the file again.
PNG_MIN_BYTES = 20
# Maximum number of malformed-tile example paths recorded per scope.
INTEGRITY_EXAMPLES_LIMIT = 20


# --- Custom errors -----------------------------------------------------------


class BuildTilesError(RuntimeError):
    """Raised when anything inside this tool cannot proceed cleanly."""


class CodebookError(BuildTilesError):
    """Raised when the codebook is structurally invalid."""


class CogError(BuildTilesError):
    """Raised when a source COG cannot be opened or has missing metadata."""


class TileError(BuildTilesError):
    """Raised when ``gdal_translate`` / ``gdal2tiles`` exits non-zero or
    when a year produces zero tiles."""


# --- Per-year result ---------------------------------------------------------


@dataclass
class IntegrityVerdict:
    """Tile-integrity summary for one scope (one year or the whole pyramid).

    ``tiles_verified`` is the count of PNGs that passed all three checks
    (non-zero size, PNG signature, trailing IEND). ``zero_byte_count`` and
    ``malformed_count`` partition the failing tiles. ``malformed_examples``
    keeps up to ``INTEGRITY_EXAMPLES_LIMIT`` example paths so an operator
    can find them on disk without re-scanning. ``integrity_verified`` is
    the boolean the manifest carries and the one this tool exits on.
    """
    tiles_verified: int
    zero_byte_count: int
    malformed_count: int
    malformed_examples: list[str]
    integrity_verified: bool


@dataclass
class YearEntry:
    year: int
    # COG fields are populated by the build path; in --scan-only they are
    # null because nobody scanned an existing pyramid should have to point
    # at the source rasters.
    cog_filename: str | None
    cog_path: str | None
    cog_bytes: int | None
    tilemap_dir: str
    tiles_written: int
    total_bytes: int
    elapsed_seconds: float
    zoom_levels_present: list[int]
    zoom_tiles: dict[str, int]
    # Integrity block; always populated, both modes verify every PNG.
    tiles_verified: int = 0
    zero_byte_count: int = 0
    malformed_count: int = 0
    malformed_examples: list[str] = field(default_factory=list)
    integrity_verified: bool = True
    error: str | None = None


# --- Codebook ----------------------------------------------------------------


def load_codebook(codebook_path: Path) -> dict:
    """Read the codebook JSON and validate it is a MapBiomas colour codebook.

    The spec is strict on purpose: a codebook with a duplicate ``pixel_id``
    or with a ``pixel_id`` referenced but missing its ``color`` (or vice
    versa) must abort the run, never silently produce a half-coloured
    pyramid.
    """
    try:
        text = codebook_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CodebookError(f"cannot read codebook {codebook_path}: {exc}") from exc

    try:
        cb = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CodebookError(f"codebook {codebook_path} is not valid JSON: {exc}") from exc

    classes = cb.get("classes")
    if not isinstance(classes, list) or not classes:
        raise CodebookError(
            f"codebook {codebook_path} has no 'classes' array or it is empty"
        )

    seen: dict[int, int] = {}
    for index, entry in enumerate(classes):
        if not isinstance(entry, dict):
            raise CodebookError(
                f"codebook {codebook_path}: classes[{index}] is not an object"
            )
        if "pixel_id" not in entry or "color" not in entry:
            raise CodebookError(
                f"codebook {codebook_path}: classes[{index}] is missing "
                f"'pixel_id' or 'color'"
            )
        pid = entry["pixel_id"]
        if not isinstance(pid, int):
            raise CodebookError(
                f"codebook {codebook_path}: classes[{index}].pixel_id "
                f"is not an integer (got {type(pid).__name__})"
            )
        if pid < 0 or pid >= PALETTE_SIZE:
            raise CodebookError(
                f"codebook {codebook_path}: classes[{index}].pixel_id={pid} "
                f"is outside 0..{PALETTE_SIZE - 1}"
            )
        if pid in seen:
            raise CodebookError(
                f"codebook {codebook_path}: duplicate pixel_id={pid} "
                f"(first at index {seen[pid]}, again at index {index})"
            )
        seen[pid] = index

    return cb


def build_color_table(cb: dict) -> np.ndarray:
    """Build the (256, 4) RGBA ColorTable for the paletted VRT.

    Every index i in 0..255 is set to (0, 0, 0, 0) by default, which means
    it is fully transparent and excluded by ``gdal2tiles -x``. ``i=0``
    (the raster's nodata) is therefore transparent by construction. Each
    codebook pixel_id gets its declared ``#rrggbb`` colour and alpha=255.

    The output is a numpy array shaped ``(PALETTE_SIZE, 4)`` with dtype
    ``uint8``, the shape GDAL's ``ColorTable.SetRGB`` / XML ``Entry``
    expects.
    """
    table = np.zeros((PALETTE_SIZE, 4), dtype=np.uint8)
    for entry in cb["classes"]:
        pid = entry["pixel_id"]
        rgb = _hex_to_rgb(entry["color"])
        table[pid] = (rgb[0], rgb[1], rgb[2], 255)
    return table


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    """Parse ``#rrggbb`` (case-insensitive) into ``(r, g, b)`` bytes."""
    s = value.strip()
    if s.startswith("#"):
        s = s[1:]
    if len(s) != 6:
        raise CodebookError(f"color {value!r} is not in #rrggbb form")
    try:
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError as exc:
        raise CodebookError(f"color {value!r} is not valid hex: {exc}") from exc
    return (r, g, b)


def codebook_sha256(codebook_path: Path) -> str:
    """Stream the codebook through SHA-256, never load it whole."""
    h = hashlib.sha256()
    with codebook_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --- Source COG metadata -----------------------------------------------------


@dataclass
class CogInfo:
    """The bits we read off each source COG up front."""
    path: Path
    year: int
    width: int
    height: int
    crs_wkt: str
    geo_transform: tuple[float, float, float, float, float, float]
    block_size: tuple[int, int]


def extract_year(name: str) -> int | None:
    """First 19xx/20xx year found in the filename, or None."""
    m = YEAR_RE.search(name)
    return int(m.group(0)) if m else None


def open_cog(cog_path: Path) -> CogInfo:
    """Open the COG and capture everything the VRTs need.

    Raises ``CogError`` with a precise message when the file is unreadable,
    when the dataset has no geotransform, or when the CRS is missing. Both
    of the latter two are the silent-zero-tile failure mode gdal2tiles
    exhibits when the VRT input is malformed.
    """
    try:
        ds = gdal.Open(str(cog_path))
    except Exception as exc:
        raise CogError(f"cannot open COG {cog_path}: {exc}") from exc
    if ds is None:
        raise CogError(f"cannot open COG {cog_path}: gdal.Open returned None")

    try:
        gt = ds.GetGeoTransform()
        crs = ds.GetProjection()
        width = ds.RasterXSize
        height = ds.RasterYSize
        band = ds.GetRasterBand(1)
        bsx, bsy = band.GetBlockSize()
    finally:
        ds = None

    if not crs:
        raise CogError(
            f"COG {cog_path} has no projection (CRS missing); a VRT without "
            f"<SRS> makes gdal2tiles silently produce zero tiles"
        )
    if gt is None or gt == (0.0, 1.0, 0.0, 0.0, 0.0, 1.0):
        raise CogError(
            f"COG {cog_path} has no GeoTransform; a VRT without "
            f"<GeoTransform> makes gdal2tiles silently produce zero tiles"
        )

    year = extract_year(cog_path.name)
    if year is None:
        raise CogError(
            f"COG filename {cog_path.name} has no 19xx/20xx year token"
        )

    return CogInfo(
        path=cog_path,
        year=year,
        width=width,
        height=height,
        crs_wkt=crs,
        geo_transform=tuple(gt),
        block_size=(int(bsx), int(bsy)),
    )


# --- VRT construction --------------------------------------------------------


def write_paletted_vrt(paletted_path: Path, info: CogInfo, table: np.ndarray) -> None:
    """Write the 256-entry paletted VRT that references the COG unchanged.

    Both ``<SRS>`` and ``<GeoTransform>`` are taken verbatim from the source
    COG's own metadata. The default colour table is (0,0,0,0) which is then
    overwritten by ``<ColorTable>`` whose every entry is also (0,0,0,0)
    EXCEPT the codebook pixel_ids, which carry their declared ``#rrggbb``.
    """
    crs_xml = _xml_escape(info.crs_wkt)
    gt = info.geo_transform
    geo = (
        f"{gt[0]}, {gt[1]}, {gt[2]}, "
        f"{gt[3]}, {gt[4]}, {gt[5]}"
    )
    src = info.path.as_posix()
    bsx, bsy = info.block_size

    lines: list[str] = [
        f'<VRTDataset rasterXSize="{info.width}" rasterYSize="{info.height}">',
        f"  <SRS>{crs_xml}</SRS>",
        f"  <GeoTransform>{geo}</GeoTransform>",
        '  <VRTRasterBand dataType="Byte" band="1">',
        "    <ColorInterp>Palette</ColorInterp>",
        "    <ColorTable>",
    ]
    for i in range(PALETTE_SIZE):
        r, g, b, a = int(table[i, 0]), int(table[i, 1]), int(table[i, 2]), int(table[i, 3])
        lines.append(f'      <Entry c1="{r}" c2="{g}" c3="{b}" c4="{a}"/>')
    lines.extend(
        [
            "    </ColorTable>",
            "    <SimpleSource>",
            f'      <SourceFilename relativeToVRT="0">{_xml_escape(src)}</SourceFilename>',
            "      <SourceBand>1</SourceBand>",
            f'      <SourceProperties RasterXSize="{info.width}" '
            f'RasterYSize="{info.height}" DataType="Byte" '
            f'BlockXSize="{bsx}" BlockYSize="{bsy}"/>',
            f'      <SrcRect xOff="0" yOff="0" xSize="{info.width}" '
            f'ySize="{info.height}"/>',
            f'      <DstRect xOff="0" yOff="0" xSize="{info.width}" '
            f'ySize="{info.height}"/>',
            "    </SimpleSource>",
            "  </VRTRasterBand>",
            "</VRTDataset>",
            "",
        ]
    )
    paletted_path.write_text("\n".join(lines), encoding="utf-8")


def _xml_escape(text: str) -> str:
    """Escape the characters that would break a VRT/XML text node."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# --- subprocess wrappers -----------------------------------------------------


_STDERR_TAIL = 20  # lines of stderr to include in error messages


def _format_stderr_tail(stderr: str) -> str:
    lines = [ln for ln in stderr.splitlines() if ln.strip()]
    if not lines:
        return "(no stderr)"
    tail = lines[-_STDERR_TAIL:]
    return "\n".join(f"    | {ln}" for ln in tail)


def run_checked(cmd: list[str], what: str) -> None:
    """Run a subprocess; raise ``TileError`` on a non-zero exit.

    We deliberately call ``subprocess.run`` with explicit ``check=True``
    so the failure path is in this tool, not buried in CPython. The
    captured stderr tail is included so the operator can see why without
    rerunning the command by hand.
    """
    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise TileError(f"{what}: executable not found: {exc}") from exc

    if result.returncode != 0:
        raise TileError(
            f"{what}: exit={result.returncode}; command={cmd!r}\n"
            f"stderr tail:\n{_format_stderr_tail(result.stderr)}"
        )


# --- Tile counting / sizing / integrity --------------------------------------


def os_scandir(path: Path):  # tiny shim so the helper is testable on its own
    import os
    return os.scandir(str(path))


def verify_tile(path: Path, size: int) -> str | None:
    """Return None if the tile is OK, else a short reason string.

    The check is intentionally cheap: non-zero size, the 8-byte PNG
    signature at offset 0, and a 12-byte IEND chunk (length=0, type="IEND",
    plus a 4-byte CRC) at the end of the file. We do not decode the chunk
    stream and we do not validate the CRC; the spec is to catch a
    truncated tile (size 0, partial write, no trailing IEND), not to
    re-implement libpng.

    ``size`` is passed in so the caller can avoid a second ``stat()``
    on a ~600 000-file tree.
    """
    if size == 0:
        return "zero-byte tile"
    if size < PNG_MIN_BYTES:
        # Smaller than the signature plus the IEND chunk: cannot be valid.
        return f"too small ({size} bytes < {PNG_MIN_BYTES})"
    try:
        with path.open("rb") as fh:
            head = fh.read(8)
            if head != PNG_SIGNATURE:
                return "missing PNG signature"
            fh.seek(-12, 2)
            tail = fh.read(12)
    except OSError as exc:
        return f"read failed: {exc}"

    if tail[:4] != PNG_IEND_LENGTH:
        return (
            f"IEND chunk length not zero "
            f"({int.from_bytes(tail[:4], 'big')})"
        )
    if tail[4:8] != PNG_IEND_TYPE:
        return f"missing IEND marker (got {tail[4:8]!r})"
    return None


def scan_year_dir(year_dir: Path) -> tuple[int, int, list[int], dict[str, int], IntegrityVerdict]:
    """Walk ``year_dir/<z>/<x>/<y>.png`` once; return counts AND integrity.

    A single tree walk feeds both the count and the integrity check so the
    662 600-tile real pyramid is traversed exactly once in --scan-only.
    Returns ``(tile_count, total_bytes, sorted_zoom_levels,
    {zoom_str: count}, IntegrityVerdict)``.
    """
    empty = (0, 0, [], {}, IntegrityVerdict(0, 0, 0, [], True))
    if not year_dir.is_dir():
        return empty

    total = 0
    total_bytes = 0
    per_zoom: dict[int, int] = {}
    verified = 0
    zero_byte = 0
    malformed = 0
    examples: list[str] = []

    # Walk <year>/<z>/<x>/<y>.png, three deep. Restrict to .png so the
    # sibling tilemap-resource.xml and friends do not pollute the count.
    with os_scandir(year_dir) as it:
        for zoom_entry in it:
            if not zoom_entry.is_dir():
                continue
            try:
                z = int(zoom_entry.name)
            except ValueError:
                continue
            with os_scandir(zoom_entry.path) as xit:
                for x_entry in xit:
                    if not x_entry.is_dir():
                        continue
                    with os_scandir(x_entry.path) as yit:
                        for y_entry in yit:
                            if not y_entry.is_file():
                                continue
                            if not y_entry.name.endswith(".png"):
                                continue
                            try:
                                st = y_entry.stat()
                            except OSError:
                                continue
                            total += 1
                            total_bytes += st.st_size
                            per_zoom[z] = per_zoom.get(z, 0) + 1

                            reason = verify_tile(Path(y_entry.path), st.st_size)
                            if reason is None:
                                verified += 1
                            elif reason == "zero-byte tile":
                                zero_byte += 1
                                if len(examples) < INTEGRITY_EXAMPLES_LIMIT:
                                    examples.append(str(y_entry.path))
                            else:
                                malformed += 1
                                if len(examples) < INTEGRITY_EXAMPLES_LIMIT:
                                    examples.append(str(y_entry.path))

    zooms = sorted(per_zoom.keys())
    per_zoom_str = {str(z): per_zoom[z] for z in zooms}
    integrity = IntegrityVerdict(
        tiles_verified=verified,
        zero_byte_count=zero_byte,
        malformed_count=malformed,
        malformed_examples=examples,
        integrity_verified=(zero_byte + malformed == 0),
    )
    return (total, total_bytes, zooms, per_zoom_str, integrity)


def count_tiles(tilemap_dir: Path) -> tuple[int, int, list[int], dict[str, int]]:
    """Backwards-compatible thin wrapper around ``scan_year_dir``.

    Used by callers that only want the count, but kept so the existing
    public-ish surface does not break.
    """
    tiles, total_bytes, zooms, per_zoom, _verdict = scan_year_dir(tilemap_dir)
    return (tiles, total_bytes, zooms, per_zoom)


def find_year_dirs(outdir: Path) -> list[tuple[int, Path]]:
    """Find every direct child of ``outdir`` whose name is exactly a year.

    Returns ``[(year, year_dir), ...]`` sorted by year ascending. Used by
    --scan-only so the manifest covers the pyramid on disk, not the years
    requested in a previous build invocation. Non-year sibling files
    (e.g. a stray README) are ignored, not fatal.
    """
    if not outdir.is_dir():
        return []
    found: list[tuple[int, Path]] = []
    for child in outdir.iterdir():
        if not child.is_dir():
            continue
        m = YEAR_RE.fullmatch(child.name)
        if not m:
            continue
        found.append((int(m.group(0)), child))
    found.sort(key=lambda pair: pair[0])
    return found


# --- Per-year driver ---------------------------------------------------------


def build_year(
    info: CogInfo,
    table: np.ndarray,
    outdir_year: Path,
    zoom: str,
    processes: int,
    resume: bool,
) -> YearEntry:
    """Build the tiles for one year: paletted VRT -> RGBA VRT -> gdal2tiles.

    Returns a populated ``YearEntry``. Raises ``TileError`` when the subprocess
    chain exits non-zero or when the resulting tile directory is empty. The
    latter is precisely the silent failure mode that a VRT-without-geotransform
    produces; it must never slip through.
    """
    outdir_year.mkdir(parents=True, exist_ok=True)
    paletted_vrt = outdir_year / "paletted.vrt"
    rgba_vrt = outdir_year / "rgba.vrt"

    write_paletted_vrt(paletted_vrt, info, table)

    run_checked(
        [
            "gdal_translate",
            "-of",
            "vrt",
            "-expand",
            "rgba",
            str(paletted_vrt),
            str(rgba_vrt),
        ],
        what=f"gdal_translate -> rgba vrt for year {info.year}",
    )

    cmd: list[str] = [
        "gdal2tiles.py",
        "-p",
        "mercator",
        "-r",
        "near",
        "--xyz",
        "-x",
        "-w",
        "none",
        "-z",
        zoom,
        "--processes",
        str(processes),
    ]
    if resume:
        cmd.append("-e")
    cmd.extend([str(rgba_vrt), str(outdir_year)])

    start = time.monotonic()
    run_checked(cmd, what=f"gdal2tiles for year {info.year}")
    elapsed = time.monotonic() - start

    tiles, total_bytes, zooms, per_zoom, integrity = scan_year_dir(outdir_year)
    if tiles == 0:
        raise TileError(
            f"year {info.year} produced ZERO tiles under {outdir_year}. "
            f"This is the exact failure mode the missing-<GeoTransform> bug "
            f"caused: the RGBA VRT was accepted but gdal2tiles found nothing "
            f"to tile. Inspect {rgba_vrt} and the source COG."
        )

    return YearEntry(
        year=info.year,
        cog_filename=info.path.name,
        cog_path=str(info.path),
        cog_bytes=info.path.stat().st_size,
        tilemap_dir=str(outdir_year),
        tiles_written=tiles,
        total_bytes=total_bytes,
        elapsed_seconds=round(elapsed, 3),
        zoom_levels_present=zooms,
        zoom_tiles=per_zoom,
        tiles_verified=integrity.tiles_verified,
        zero_byte_count=integrity.zero_byte_count,
        malformed_count=integrity.malformed_count,
        malformed_examples=list(integrity.malformed_examples),
        integrity_verified=integrity.integrity_verified,
    )


# --- Manifest writer ---------------------------------------------------------


def integrity_label(entry: YearEntry) -> str:
    """One-line integrity verdict for the per-year log line."""
    if entry.integrity_verified:
        return "integrity=OK"
    return (
        f"integrity=BROKEN(zero={entry.zero_byte_count}, "
        f"malformed={entry.malformed_count})"
    )


def aggregate_integrity_examples(entries: list[YearEntry]) -> list[str]:
    """Up to ``INTEGRITY_EXAMPLES_LIMIT`` malformed-tile paths across entries.

    Preserves per-year order: examples from earlier years come first, so
    the operator scanning top-to-bottom reads in chronological order.
    """
    out: list[str] = []
    for entry in entries:
        for path in entry.malformed_examples:
            if len(out) >= INTEGRITY_EXAMPLES_LIMIT:
                return out
            out.append(path)
    return out


def write_manifest(
    args: argparse.Namespace,
    codebook_path: Path,
    codebook_sha: str,
    zoom_range: str,
    entries: list[YearEntry],
    failures: list[YearEntry],
    manifest_path: Path,
) -> None:
    """Serialize the run into a UTF-8 JSON manifest, with a trailing newline.

    Includes the zoom levels requested, the tile scheme, the resampling,
    the D7 ``extent_label`` / boundary note the downstream composition tool
    relies on, and per-year zoom tile counts so the operator can spot a
    tier that lost tiles.
    """
    successful = [e for e in entries if e.error is None]
    failures_only = [e for e in entries if e.error is not None]

    total_zero = sum(e.zero_byte_count for e in successful)
    total_malformed = sum(e.malformed_count for e in successful)

    totals = {
        "years_requested": sorted({e.year for e in entries}),
        "years_succeeded": sorted(e.year for e in successful),
        "years_failed": sorted(e.year for e in failures_only),
        "tiles_total": sum(e.tiles_written for e in successful),
        "bytes_total": sum(e.total_bytes for e in successful),
        "seconds_total": round(sum(e.elapsed_seconds for e in successful), 3),
        "integrity": {
            "tiles_verified": sum(e.tiles_verified for e in successful),
            "zero_byte_count": total_zero,
            "malformed_count": total_malformed,
            "malformed_examples": aggregate_integrity_examples(successful),
            "integrity_verified": (total_zero + total_malformed == 0),
        },
    }

    # ``vars(args)`` carries Path objects (not JSON-serializable). Coerce
    # every value through ``str`` so the manifest can be replayed verbatim.
    raw_args = vars(args)
    args_jsonable: dict[str, Any] = {
        k: (str(v) if isinstance(v, Path) else v)
        for k, v in raw_args.items()
    }

    # In --scan-only the source COG directory is optional; record null
    # instead of an empty placeholder so a manifest consumer can tell
    # "scan, no source" apart from "build with a real cog-dir".
    source_dir_value: str | None = (
        str(args.cog_dir) if args.cog_dir is not None else None
    )

    payload: dict[str, Any] = {
        "country": args.country,
        "collection": args.collection,
        "kind": "tile-pyramid",
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source_dir": source_dir_value,
        "output_dir": str(args.outdir),
        "zoom_range_requested": zoom_range,
        "tile_scheme": "xyz",
        "tile_profile": "mercator",
        "resampling": "near",
        "exclude_transparent": True,
        "webviewer": "none",
        "codebook": {
            "path": str(codebook_path),
            "sha256": codebook_sha,
        },
        "d7_labelling_note": (
            "The XYZ tile pyramid here is a rendering for the viewer. Any "
            "area, percent or histogram figure produced by the viewer or "
            "the composition outputs must come from the composition "
            "outputs, NOT from counting pixels in these tiles. Tiles are "
            "filtered, resampled to 256x256 and exclude transparency; they "
            "are not an audit-grade source."
        ),
        "extent_label": "extension MapBiomas Venezuela",
        "extent_boundary_note": (
            "The pixel extent in the source COGs exceeds internationally "
            "recognised borders and includes disputed territory. No "
            "boundary mask has been applied to the pyramid."
        ),
        "command": {
            "args": args_jsonable,
            "argv": sys.argv,
        },
        "totals": totals,
        "entries": [asdict(e) for e in entries],
        "failures": [asdict(e) for e in failures_only],
    }

    manifest_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# --- main --------------------------------------------------------------------


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the static XYZ tile pyramid (Web Mercator) the viewer "
            "consumes, one MapBiomas year at a time. Use --scan-only to "
            "rebuild the manifest from a pyramid already on disk without "
            "invoking gdal_translate or gdal2tiles."
        )
    )
    parser.add_argument("--country", required=True,
                        help="country id (used in the manifest only)")
    parser.add_argument("--collection", required=True,
                        help="collection id (used in the manifest only)")
    parser.add_argument("--cog-dir", required=False, type=Path, default=None,
                        help="directory containing one COG per year, named "
                             "with a 19xx/20xx year token. Required for "
                             "build mode; optional in --scan-only "
                             "(omit when you only have the pyramid).")
    parser.add_argument("--codebook", required=True, type=Path,
                        help="machine-readable MapBiomas codebook JSON")
    parser.add_argument("--outdir", required=True, type=Path,
                        help="output root; one <outdir>/<year>/ per year")
    parser.add_argument("--manifest", required=True, type=Path,
                        help="path to the JSON manifest to write")
    parser.add_argument(
        "--scan-only",
        action="store_true",
        help="rebuild the manifest from the pyramid on disk; never invokes "
             "gdal_translate or gdal2tiles. --cog-dir becomes optional.",
    )
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        default=None,
        help="explicit subset of years to build (default: every year "
             "present in the cog-dir). Ignored in --scan-only, which "
             "discovers years from <outdir>/<year>/ on disk.",
    )
    parser.add_argument(
        "--zoom",
        default=DEFAULT_ZOOM,
        help="zoom range passed to gdal2tiles.py as-is "
             f"(default: {DEFAULT_ZOOM})",
    )
    parser.add_argument(
        "--processes",
        type=int,
        default=DEFAULT_PROCESSES,
        help=f"parallel workers for gdal2tiles.py (default: {DEFAULT_PROCESSES})",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="pass -e to gdal2tiles.py so repeated runs only fill gaps",
    )

    args = parser.parse_args(argv)

    # Build mode still requires --cog-dir; --scan-only does not.
    if not args.scan_only and args.cog_dir is None:
        parser.error(
            "--cog-dir is required unless --scan-only is set "
            "(nobody scanning an existing pyramid should have to point "
            "at the source rasters)"
        )
    if args.scan_only and args.years is not None:
        # --years is a build-mode construct; a scan covers every year on
        # disk. Reject up front so the surprise is loud, not silent.
        parser.error(
            "--years cannot be combined with --scan-only; scan mode "
            "discovers years from <outdir>."
        )
    return args


def select_cogs(cog_dir: Path, years: list[int] | None) -> list[Path]:
    """Pick which COG files to process, in deterministic order."""
    cogs = sorted(cog_dir.glob("*.tif"))
    if not cogs:
        raise BuildTilesError(f"no .tif files in {cog_dir}")
    if years is None:
        return cogs
    wanted = set(years)
    selected = [c for c in cogs if extract_year(c.name) in wanted]
    missing = sorted(wanted - {extract_year(c.name) for c in selected})
    if missing:
        raise BuildTilesError(
            f"--years requested years with no matching COG in {cog_dir}: "
            f"{missing}"
        )
    return selected


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.scan_only:
        return run_scan(args)
    return run_build(args)


def run_build(args: argparse.Namespace) -> int:
    """Build the pyramid (the original behaviour) and verify on the way out."""
    # 1. Codebook first: if the colour source is broken, no colour goes out.
    try:
        load_codebook(args.codebook)  # raises CodebookError on a bad one
        codebook_sha = codebook_sha256(args.codebook)
    except BuildTilesError as exc:
        print(f"error: {exc}", file=sys.stderr, flush=True)
        return 2

    table = build_color_table(load_codebook(args.codebook))

    # 2. Pick the years to process and open every COG before we start tiling,
    #    so a bad COG fails the run cleanly instead of half-completing.
    try:
        cog_paths = select_cogs(args.cog_dir, args.years)
    except BuildTilesError as exc:
        print(f"error: {exc}", file=sys.stderr, flush=True)
        return 2

    cog_infos: list[CogInfo] = []
    open_failures: list[YearEntry] = []
    for p in cog_paths:
        try:
            cog_infos.append(open_cog(p))
        except CogError as exc:
            # The spec: a year whose COG cannot be opened is a hard failure.
            # Failures are recorded per-year in the manifest for traceability,
            # but we still abort the run so we don't ship a partial pyramid.
            print(f"error: {exc}", file=sys.stderr, flush=True)
            return 2

    if not cog_infos:
        print(f"error: no usable COGs in {args.cog_dir}", file=sys.stderr, flush=True)
        return 2

    args.outdir.mkdir(parents=True, exist_ok=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)

    entries: list[YearEntry] = []
    successes = 0
    failures = 0
    total = len(cog_infos)
    overall_start = time.monotonic()

    for index, info in enumerate(cog_infos, start=1):
        year_outdir = args.outdir / str(info.year)
        try:
            entry = build_year(
                info,
                table,
                year_outdir,
                zoom=args.zoom,
                processes=args.processes,
                resume=args.resume,
            )
        except BuildTilesError as exc:
            failure = YearEntry(
                year=info.year,
                cog_filename=info.path.name,
                cog_path=str(info.path),
                cog_bytes=info.path.stat().st_size,
                tilemap_dir=str(year_outdir),
                tiles_written=0,
                total_bytes=0,
                elapsed_seconds=0.0,
                zoom_levels_present=[],
                zoom_tiles={},
                error=str(exc),
            )
            entries.append(failure)
            failures += 1
            print(
                f"[{index}/{total}] year={info.year} FAILED {exc}",
                file=sys.stderr,
                flush=True,
            )
            print(
                f"error: year {info.year} failed; aborting the run. "
                f"No partial pyramid is shipped.",
                file=sys.stderr,
                flush=True,
            )
            write_manifest(
                args,
                args.codebook,
                codebook_sha,
                zoom_range=args.zoom,
                entries=entries,
                failures=[failure],
                manifest_path=args.manifest,
            )
            return 1

        entries.append(entry)
        successes += 1

        mb = entry.total_bytes / (1024 * 1024)
        zoom_summary = ",".join(str(z) for z in entry.zoom_levels_present) or "-"
        per_zoom_summary = " ".join(
            f"z{z}={entry.zoom_tiles.get(str(z), 0)}"
            for z in entry.zoom_levels_present
        )
        print(
            f"[{index}/{total}] year={info.year} tiles={entry.tiles_written} "
            f"size={mb:.2f} MB elapsed={entry.elapsed_seconds:.2f}s "
            f"zooms=[{zoom_summary}] [{per_zoom_summary}] "
            f"{integrity_label(entry)}",
            flush=True,
        )

    overall_seconds = time.monotonic() - overall_start

    write_manifest(
        args,
        args.codebook,
        codebook_sha,
        zoom_range=args.zoom,
        entries=entries,
        failures=[],
        manifest_path=args.manifest,
    )

    successful_entries = [e for e in entries if e.error is None]
    total_tiles = sum(e.tiles_written for e in successful_entries)
    total_bytes = sum(e.total_bytes for e in successful_entries)
    total_zero = sum(e.zero_byte_count for e in successful_entries)
    total_malformed = sum(e.malformed_count for e in successful_entries)
    integrity_verified = (total_zero + total_malformed == 0)

    # The "extrapolation the parent cares about": 40 years of coverage from
    # this run. We report a measured scaling only when we have at least one
    # successful year, otherwise the number would be meaningless.
    if successful_entries:
        avg_tiles = total_tiles / len(successful_entries)
        avg_bytes = total_bytes / len(successful_entries)
        extrapolated_tiles = int(round(avg_tiles * 40))
        extrapolated_bytes = int(round(avg_bytes * 40))
        extrapolated_minutes = (overall_seconds * 40) / 60.0
        extrapolation = (
            f"extrapolation(40 years) ~{extrapolated_tiles:,} tiles, "
            f"~{extrapolated_bytes / (1024 ** 3):.2f} GB, "
            f"~{extrapolated_minutes:.1f} min"
        )
    else:
        extrapolation = "extrapolation(40 years) unavailable (0 successful years)"

    overall_mb = total_bytes / (1024 * 1024)
    print(
        f"summary: {successes}/{total} years succeeded, {failures} failed; "
        f"total tiles={total_tiles:,}, total size={overall_mb:.2f} MB, "
        f"wall clock={overall_seconds:.2f}s, "
        f"integrity verified={total_tiles - total_zero - total_malformed:,} "
        f"zero={total_zero} malformed={total_malformed} "
        f"verified={'OK' if integrity_verified else 'BROKEN'}",
        flush=True,
    )
    print(extrapolation, flush=True)
    print(f"manifest: {args.manifest}", flush=True)

    if failures > 0:
        return 1
    if not integrity_verified:
        # The manifest is on disk so the operator can inspect what failed;
        # the run is a failure regardless of how many years succeeded.
        return 1
    return 0


def run_scan(args: argparse.Namespace) -> int:
    """Rebuild the manifest from the pyramid on disk; never invoke GDAL.

    Discovers year directories under ``args.outdir``, walks each one,
    counts tiles and bytes, lists zoom levels and per-zoom counts, and
    verifies every PNG. Writes a manifest whose contents are equivalent
    in shape to a successful build manifest; per-year COG fields are
    ``null`` because nobody scanning a pyramid has to point at the
    source rasters.
    """
    # 1. Codebook is still required: palette provenance is part of the
    #    manifest so a future colour change is detectable after the fact.
    try:
        load_codebook(args.codebook)
        codebook_sha = codebook_sha256(args.codebook)
    except BuildTilesError as exc:
        print(f"error: {exc}", file=sys.stderr, flush=True)
        return 2

    args.manifest.parent.mkdir(parents=True, exist_ok=True)

    # 2. Discover years from disk; an empty outdir is a hard failure
    #    because a "scan" of nothing is a misleading provenance statement.
    year_dirs = find_year_dirs(args.outdir)
    if not year_dirs:
        print(
            f"error: no year directories found under {args.outdir}; "
            f"a scan with nothing to describe is not a valid provenance "
            f"statement",
            file=sys.stderr,
            flush=True,
        )
        return 2

    entries: list[YearEntry] = []
    total = len(year_dirs)
    overall_start = time.monotonic()

    for index, (year, year_dir) in enumerate(year_dirs, start=1):
        year_start = time.monotonic()
        tiles, total_bytes, zooms, per_zoom, integrity = scan_year_dir(year_dir)
        elapsed = time.monotonic() - year_start

        entry = YearEntry(
            year=year,
            # COG fields are null in scan mode: the source rasters are
            # not required to read a pyramid already on disk.
            cog_filename=None,
            cog_path=None,
            cog_bytes=None,
            tilemap_dir=str(year_dir),
            tiles_written=tiles,
            total_bytes=total_bytes,
            elapsed_seconds=round(elapsed, 3),
            zoom_levels_present=zooms,
            zoom_tiles=per_zoom,
            tiles_verified=integrity.tiles_verified,
            zero_byte_count=integrity.zero_byte_count,
            malformed_count=integrity.malformed_count,
            malformed_examples=list(integrity.malformed_examples),
            integrity_verified=integrity.integrity_verified,
        )
        entries.append(entry)

        mb = total_bytes / (1024 * 1024)
        zoom_summary = ",".join(str(z) for z in zooms) or "-"
        per_zoom_summary = " ".join(
            f"z{z}={per_zoom.get(str(z), 0)}" for z in zooms
        )
        print(
            f"[{index}/{total}] year={year} tiles={tiles} "
            f"size={mb:.2f} MB zooms=[{zoom_summary}] "
            f"[{per_zoom_summary}] {integrity_label(entry)}",
            flush=True,
        )

    overall_seconds = time.monotonic() - overall_start

    write_manifest(
        args,
        args.codebook,
        codebook_sha,
        zoom_range=args.zoom,
        entries=entries,
        failures=[],
        manifest_path=args.manifest,
    )

    total_tiles = sum(e.tiles_written for e in entries)
    total_bytes = sum(e.total_bytes for e in entries)
    total_verified = sum(e.tiles_verified for e in entries)
    total_zero = sum(e.zero_byte_count for e in entries)
    total_malformed = sum(e.malformed_count for e in entries)
    integrity_verified = total_zero + total_malformed == 0
    overall_mb = total_bytes / (1024 * 1024)

    print(
        f"summary: scanned {total} years under {args.outdir}; "
        f"total tiles={total_tiles:,}, total size={overall_mb:.2f} MB, "
        f"wall clock={overall_seconds:.2f}s, "
        f"integrity verified={total_verified:,} "
        f"zero={total_zero} malformed={total_malformed} "
        f"verified={'OK' if integrity_verified else 'BROKEN'}",
        flush=True,
    )
    print(f"manifest: {args.manifest}", flush=True)

    # Always 0 on success, 1 if anything is broken. The manifest has
    # already been written either way, so the operator can inspect what
    # failed without re-running.
    return 0 if integrity_verified else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
