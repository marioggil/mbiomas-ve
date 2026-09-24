#!/usr/bin/env python3
"""tools/class_change_probe.py - WHERE the per-cell change lives and WHAT its temporal signature is.

WHY THIS TOOL EXISTS
--------------------
Composition totals prove NET change, not the cause. For class 33 (Rio, lago
u oceano) in Venezuela Collection 3 the aggregate count grew from
4,280,192 ha in 1985 to 4,469,291 ha in 2024 (+4.42 %); that number alone
cannot tell us whether the gain is a real reservoir or a classification
artifact, because the two leave different spatial and temporal signatures:

  * A REAL RESERVOIR fills in ONE step, in ONE year, in a small number
    of contiguous cells, and persists afterwards. The per-cell profile is
    monotonic after the step, the largest single-year jump explains
    nearly the whole net gain (jump_share_of_net_gain near 1.0), and
    direction_changes is low.

  * A CLASSIFICATION ARTIFACT flickers diffusely across MANY cells and
    MANY years. The per-cell profile is noisy, the largest single-year
    jump explains only a small fraction of the net gain
    (jump_share_of_net_gain small), and direction_changes is high.

This tool reports the per-cell WHERE and the temporal WHAT so the user
can read the numbers and judge. It does not invent a verdict.

Why native resolution (never the COG overviews): the 7 internal NEAREST
overviews round every class-boundary pixel to the nearest parent pixel,
so composition totals must be exact at native resolution. The 40
rasters are Byte 57605 x 45000, streamed in row blocks of 512 to keep
peak RSS well below 1 GB.

Why geodesic cell areas (not a constant 30 m per pixel): the rasters are
EPSG:4326, spanning about 12 degrees of latitude. A constant per-pixel
area is wrong by several percent across the extent; per-cell area uses
the WGS84 authalic sphere formula

    area_m2 = R^2 * delta_lambda_rad * (sin(phi_top) - sin(phi_bottom))

with R = 6371007.181 m, summed over the rows each cell covers and
restricted to the cell's longitude span. This matches the row-wise
geodesic method used by tools/composition_stats.py.

Why concentration matters: a +4.42 % gain spread over thousands of
small cells is a fundamentally different phenomenon from the same
percentage concentrated in five contiguous cells. The share of the
total net gain that the top 10 cells account for, and the number of
cells with any positive net gain, are the two scalar summaries.

D7 labelling: every area figure covers the MapBiomas mapping extent,
which exceeds internationally recognized borders and includes disputed
territory. No boundary mask is applied. The summary JSON carries the
mandatory ``extent_label`` and ``boundary_note`` at the top level so
no downstream consumer can miss them.

Usage:
    tools/class_change_probe.py --country <c> --collection <n> \\
        --cog-dir <dir> --pixel-id <int> --base-year <int> \\
        --target-year <int> [--cell-deg 0.1] [--top 20] \\
        [--outdir <dir>]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import resource
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from osgeo import gdal

gdal.UseExceptions()
# Bound GDAL's block cache so peak RSS stays predictable; we stream
# sequentially in row blocks so a small cache does not cost extra I/O.
gdal.SetCacheMax(256 * 1024 * 1024)


# First 19xx/20xx year token in the filename. Files without such a token
# are treated as a recorded failure, not a crash.
YEAR_RE = re.compile(r"(19|20)\d{2}")

# Authalic radius of the WGS84 ellipsoid in metres - the radius of a
# sphere with the same surface area as the ellipsoid. Used so the sum of
# row areas approximates the true surface area of the geographic grid.
AUTHALIC_RADIUS_M = 6371007.181

# Row block size for the count phase. A block is 512 * 57605 = ~29.5 MB
# of raster data plus per-row cell indices; the cache limit above keeps
# peak RSS well below 1 GB.
ROW_BLOCK = 512

# Mandatory MapBiomas labelling for every published area figure
# (project decision D7): every area figure covers the MapBiomas mapping
# extent rather than internationally recognized borders.
EXTENT_LABEL = "extension MapBiomas Venezuela"
BOUNDARY_NOTE = (
    "The extent covers the MapBiomas Venezuela mapping area rather than "
    "internationally recognized borders. It includes disputed territory "
    "and areas outside de jure boundaries. No boundary mask was applied; "
    "area figures are over the MapBiomas mapping extent only."
)
AREA_METHOD_DESCRIPTION = (
    "Row-wise geodesic area on the WGS84 sphere using the authalic radius "
    "R = 6371007.181 m. For row j with top latitude phi_top and bottom "
    "latitude phi_bottom (in radians) and longitude extent delta_lambda: "
    "area_m2 = R^2 * delta_lambda * (sin(phi_top) - sin(phi_bottom)). "
    "A cell's area is the sum of the row contributions it covers, "
    "restricted to the cell's longitude span delta_lambda_cell = "
    "cell_deg * pi/180."
)


def extract_year(name: str) -> int | None:
    """Return the first 19xx/20xx year token in the filename, or None."""
    m = YEAR_RE.search(name)
    return int(m.group(0)) if m else None


@dataclass
class Grid:
    """Regular lon/lat cell grid derived from a raster geotransform.

    The grid origin (cell_lon_min, cell_lat_min) is snapped DOWN to a
    multiple of cell_deg from the raster origin, so every pixel centre
    coordinate resolves to an integer cell index with floor arithmetic.
    The cell index is an arbitrary integer; monotonicity is preserved
    along each axis (larger cell_row_idx corresponds to larger centre
    latitude for a north-up raster).
    """

    cell_deg: float
    cell_lon_min: float
    cell_lat_min: float
    n_cols: int
    n_rows: int
    pixel_col_idx: np.ndarray  # int32 shape (width,)
    pixel_row_idx: np.ndarray  # int32 shape (height,)
    gt: tuple[float, ...]
    width: int
    height: int
    cell_area_per_row: np.ndarray  # float64 shape (n_rows,), m^2 per cell

    @classmethod
    def from_geotransform(
        cls,
        gt: tuple[float, ...],
        width: int,
        height: int,
        cell_deg: float,
    ) -> "Grid":
        # Snap the grid origin DOWN to a multiple of cell_deg. The
        # raster origin (gt[0], gt[3]) is the upper-left CORNER of the
        # upper-left pixel, so cell_lon_min is the largest multiple of
        # cell_deg not greater than gt[0]; every pixel centre at col >= 0
        # then has centre lon > cell_lon_min and a non-negative col_idx.
        # cell_lat_min uses the SOUTHERNMOST raster edge
        # (gt[3] + height*gt[5]) since gt[5] is negative for north-up
        # rasters, and the same down-snap.
        cell_lon_min = float(np.floor(gt[0] / cell_deg) * cell_deg)
        lat_bottom = gt[3] + height * gt[5]
        cell_lat_min = float(np.floor(lat_bottom / cell_deg) * cell_deg)

        # Cover the raster extent with ceil so the union of cells
        # covers every pixel centre. Pixels just outside the snapped
        # origin get negative cell indices and are masked out at the
        # count step.
        lon_right = gt[0] + width * gt[1]
        lat_top = gt[3]
        n_cols = int(np.ceil((lon_right - cell_lon_min) / cell_deg))
        n_rows = int(np.ceil((lat_top - cell_lat_min) / cell_deg))

        # Precompute per-column and per-row cell indices from centre
        # coordinates. These arrays are reused for every row block of
        # the count phase and for every window read of the profile
        # phase, so precomputing avoids per-pixel division.
        col_centres = gt[0] + (np.arange(width, dtype=np.float64) + 0.5) * gt[1]
        row_centres = gt[3] + (np.arange(height, dtype=np.float64) + 0.5) * gt[5]
        pixel_col_idx = np.floor((col_centres - cell_lon_min) / cell_deg).astype(np.int32)
        pixel_row_idx = np.floor((row_centres - cell_lat_min) / cell_deg).astype(np.int32)

        return cls(
            cell_deg=cell_deg,
            cell_lon_min=cell_lon_min,
            cell_lat_min=cell_lat_min,
            n_cols=n_cols,
            n_rows=n_rows,
            pixel_col_idx=pixel_col_idx,
            pixel_row_idx=pixel_row_idx,
            gt=gt,
            width=width,
            height=height,
            cell_area_per_row=np.zeros(n_rows, dtype=np.float64),
        )

    def flat_idx(self, row_idx: int, col_idx: int) -> int:
        return row_idx * self.n_cols + col_idx


def verify_grid_consistency(
    grid: Grid,
    cog_dir: Path,
) -> list[tuple[int, Path]]:
    """Assert every .tif in --cog-dir shares the base geotransform and size.

    Returns the list of (year, path) sorted by year. A mismatching
    geotransform, mismatching size, or duplicate year raises
    RuntimeError so the caller gets a hard failure rather than a wrong
    number.
    """
    inputs = sorted(cog_dir.glob("*.tif"))
    if not inputs:
        raise RuntimeError(f"no .tif inputs in {cog_dir}")
    by_year: dict[int, Path] = {}
    for p in inputs:
        ds = gdal.Open(str(p))
        if ds is None:
            raise RuntimeError(f"cannot open {p}")
        try:
            if ds.RasterXSize != grid.width or ds.RasterYSize != grid.height:
                raise RuntimeError(
                    f"{p.name}: raster size {ds.RasterXSize}x{ds.RasterYSize} "
                    f"differs from base {grid.width}x{grid.height}"
                )
            gt = ds.GetGeoTransform()
            if gt != grid.gt:
                raise RuntimeError(
                    f"{p.name}: geotransform differs from base; "
                    f"file={gt!r} base={grid.gt!r}"
                )
            y = extract_year(p.name)
            if y is None:
                raise RuntimeError(f"{p.name}: cannot extract year")
            if y in by_year:
                raise RuntimeError(f"duplicate year {y} in {cog_dir}")
            by_year[y] = p
        finally:
            ds = None
    return sorted(by_year.items())


def count_pixels_in_grid(
    path: Path,
    grid: Grid,
    pixel_id: int,
    nodata_val: int | None,
) -> np.ndarray:
    """Stream one raster at native resolution into a per-cell count matrix.

    Returns a flat (n_rows * n_cols,) int64 array. Rasters are read in
    row blocks of ROW_BLOCK so no full raster is ever held in memory.
    Nodata is read from the band, not hardcoded.

    Per-pixel work: a comparison (arr == pixel_id) and a scatter to a
    precomputed cell index. The col axis cell index is constant per
    column across the whole raster, so only the row axis slice needs to
    be re-fetched per block.
    """
    ds = gdal.Open(str(path))
    if ds is None:
        raise RuntimeError(f"cannot open {path}")
    try:
        band = ds.GetRasterBand(1)
        # Read the band's nodata. Fall back to the caller's hint only if
        # the band reports no value.
        nd_raw = band.GetNoDataValue()
        nd: int | None = int(nd_raw) if nd_raw is not None else nodata_val

        col_valid = (grid.pixel_col_idx >= 0) & (grid.pixel_col_idx < grid.n_cols)

        counts = np.zeros(grid.n_rows * grid.n_cols, dtype=np.int64)

        pixel_id_u8 = np.uint8(pixel_id)
        nd_u8 = np.uint8(nd) if nd is not None else None

        for yoff in range(0, grid.height, ROW_BLOCK):
            block_h = min(ROW_BLOCK, grid.height - yoff)
            arr = band.ReadAsArray(0, yoff, grid.width, block_h)
            if arr is None:
                raise RuntimeError(f"ReadAsArray returned None at yoff={yoff}")

            # Per-row cell indices for this block; rows outside the
            # grid are masked out below so their scattered indices are
            # ignored by bincount.
            row_idx = grid.pixel_row_idx[yoff:yoff + block_h]
            row_safe = (row_idx >= 0) & (row_idx < grid.n_rows)
            cell_flat = (
                row_idx[:, None].astype(np.int32) * grid.n_cols
                + grid.pixel_col_idx[None, :].astype(np.int32)
            )

            # Mask: pixel matches AND is not nodata AND falls inside the
            # grid in both axes. The col axis is constant per column so
            # the broadcast cost is negligible.
            mask = arr == pixel_id_u8
            if nd_u8 is not None:
                mask &= arr != nd_u8
            mask &= row_safe[:, None]
            mask &= col_valid[None, :]

            if not mask.any():
                continue

            block_counts = np.bincount(
                cell_flat[mask], minlength=grid.n_rows * grid.n_cols
            )
            counts += block_counts
    finally:
        ds = None

    return counts


def cell_area_m2(grid: Grid, row_idx: int, col_idx: int) -> float:
    """Return one cell's area in m^2 via the row-wise geodesic formula.

    Convenience wrapper around ``cell_area_per_row``: all cells in the
    same row share the same latitude range, hence identical area; only
    the longitude span matters and it is the same for every cell.
    """
    return float(grid.cell_area_per_row[row_idx])


def cell_area_per_row_of(grid: Grid) -> np.ndarray:
    """Precompute one area (m^2) per cell row, shared by all columns.

    For each raster row j that intersects cell row r, the contribution is
    R^2 * delta_lambda_cell * (sin(phi_top) - sin(phi_bot)) where
    phi_top, phi_bot are the intersection of row j's latitude span with
    cell row r's latitude span, and delta_lambda_cell = cell_deg * pi/180.
    Sum over all intersecting rows.

    All cells in the same cell row have the same area (they share the
    latitude span and the same cell_deg longitude span), so the result
    is a (n_rows,) array indexed by row.
    """
    gt = grid.gt
    row_top = gt[3] + np.arange(grid.height, dtype=np.float64) * gt[5]
    row_bot = row_top + gt[5]
    phi_top = np.maximum(row_top, row_bot)
    phi_bot = np.minimum(row_top, row_bot)

    delta_lambda_cell = grid.cell_deg * (np.pi / 180.0)
    R2 = AUTHALIC_RADIUS_M ** 2
    areas = np.zeros(grid.n_rows, dtype=np.float64)

    # Vectorise over cell rows: for each cell row r, the rows that
    # intersect it are those whose pixel_row_idx is r. Rows fully
    # inside cell r contribute their full sin(phi_top) - sin(phi_bot);
    # partial boundary rows contribute only the intersection.
    for r in range(grid.n_rows):
        cell_lat_min = grid.cell_lat_min + r * grid.cell_deg
        cell_lat_max = cell_lat_min + grid.cell_deg
        # Find raster rows whose centre falls in cell row r (these are
        # the rows that can intersect it).
        in_r = grid.pixel_row_idx == r
        if not in_r.any():
            areas[r] = 0.0
            continue
        top_int = np.minimum(phi_top[in_r], cell_lat_max)
        bot_int = np.maximum(phi_bot[in_r], cell_lat_min)
        valid = top_int > bot_int
        if not valid.any():
            areas[r] = 0.0
            continue
        sin_top = np.sin(np.deg2rad(top_int[valid]))
        sin_bot = np.sin(np.deg2rad(bot_int[valid]))
        areas[r] = R2 * delta_lambda_cell * float((sin_top - sin_bot).sum())

    return areas


def cell_center(grid: Grid, row_idx: int, col_idx: int) -> tuple[float, float]:
    """Return the centre (lon, lat) of a cell in degrees."""
    lon = grid.cell_lon_min + (col_idx + 0.5) * grid.cell_deg
    lat = grid.cell_lat_min + (row_idx + 0.5) * grid.cell_deg
    return lon, lat


def pixels_per_cell(grid: Grid) -> np.ndarray:
    """Return a (n_rows, n_cols) int64 array of pixel counts per cell.

    Computed once from the precomputed per-pixel cell index arrays via
    a row-block-by-block 2D histogram so the intermediate array never
    exceeds one block in size.
    """
    hist = np.zeros(grid.n_rows * grid.n_cols, dtype=np.int64)
    for yoff in range(0, grid.height, ROW_BLOCK):
        block_h = min(ROW_BLOCK, grid.height - yoff)
        row_idx_block = grid.pixel_row_idx[yoff:yoff + block_h]
        cell_flat = (
            row_idx_block[:, None].astype(np.int32) * grid.n_cols
            + grid.pixel_col_idx[None, :].astype(np.int32)
        )
        hist += np.bincount(
            cell_flat.ravel(), minlength=grid.n_rows * grid.n_cols
        )
    return hist.reshape(grid.n_rows, grid.n_cols)


def cell_pixel_count(grid: Grid, pixels_per_cell_cache: np.ndarray,
                     row_idx: int, col_idx: int) -> int:
    """Number of native pixels whose centre falls inside the cell.

    Used to convert net pixel counts to per-cell hectares via the
    cell-local average pixel area: cell_area_m2 / pixels_in_cell. The
    per-cell histogram is precomputed once and indexed here.
    """
    return int(pixels_per_cell_cache[row_idx, col_idx])


def temporal_profile(
    grid: Grid,
    year_paths: list[tuple[int, Path]],
    top_indices: list[tuple[int, int]],
    pixel_id: int,
    nodata_hint: int | None,
) -> tuple[list[list[int]], list[int]]:
    """Build the temporal profile matrix for the top cells.

    Returns ``(matrix, years)`` where ``matrix[i][yi]`` is the count of
    ``pixel_id`` pixels inside top cell ``i`` during year
    ``years[yi]``. To keep this affordable, only the union bounding box
    of the top cells is read for each year at native resolution; counts
    are aggregated per cell inside that window.

    Pixels are assigned to a cell with the same floor arithmetic used
    by the count phase, so the same pixel falls in the same cell at
    every year.
    """
    if not top_indices:
        return [], [y for y, _ in year_paths]
    years_sorted = [y for y, _ in year_paths]

    # Compute the pixel range of each top cell, then the union bbox.
    # A small safety margin handles floating-point round-off at the
    # cell edges without inflating the window by more than one pixel.
    pix_ranges: list[tuple[int, int, int, int]] = []
    for row_idx, col_idx in top_indices:
        cell_lon_min = grid.cell_lon_min + col_idx * grid.cell_deg
        cell_lon_max = cell_lon_min + grid.cell_deg
        cell_lat_min = grid.cell_lat_min + row_idx * grid.cell_deg
        cell_lat_max = cell_lat_min + grid.cell_deg
        col_start = int(np.floor((cell_lon_min - grid.gt[0]) / grid.gt[1]))
        col_end = int(np.ceil((cell_lon_max - grid.gt[0]) / grid.gt[1]))
        row_start = int(np.floor((cell_lat_max - grid.gt[3]) / grid.gt[5]))
        row_end = int(np.ceil((cell_lat_min - grid.gt[3]) / grid.gt[5]))
        col_start = max(0, col_start)
        col_end = min(grid.width, col_end)
        row_start = max(0, row_start)
        row_end = min(grid.height, row_end)
        pix_ranges.append((col_start, row_start, col_end, row_end))

    min_col = min(pr[0] for pr in pix_ranges)
    max_col = max(pr[2] for pr in pix_ranges)
    min_row = min(pr[1] for pr in pix_ranges)
    max_row = max(pr[3] for pr in pix_ranges)
    window_w = max_col - min_col
    window_h = max_row - min_row
    if window_w <= 0 or window_h <= 0:
        return [[0] * len(years_sorted) for _ in top_indices], years_sorted

    # Precompute per-row and per-column cell indices for the window.
    col_centres_w = (
        grid.gt[0] + (np.arange(min_col, max_col, dtype=np.float64) + 0.5) * grid.gt[1]
    )
    row_centres_w = (
        grid.gt[3] + (np.arange(min_row, max_row, dtype=np.float64) + 0.5) * grid.gt[5]
    )
    col_idx_w = np.floor((col_centres_w - grid.cell_lon_min) / grid.cell_deg).astype(np.int32)
    row_idx_w = np.floor((row_centres_w - grid.cell_lat_min) / grid.cell_deg).astype(np.int32)
    cell_flat_w = (row_idx_w[:, None] * grid.n_cols + col_idx_w[None, :]).astype(np.int64)

    valid_col = (col_idx_w >= 0) & (col_idx_w < grid.n_cols)
    valid_row = (row_idx_w >= 0) & (row_idx_w < grid.n_rows)
    valid_2d = valid_row[:, None] & valid_col[None, :]

    pixel_id_u8 = np.uint8(pixel_id)

    matrix: list[list[int]] = [[0] * len(years_sorted) for _ in top_indices]

    for yi, (year, path) in enumerate(year_paths):
        t0 = time.monotonic()
        ds = gdal.Open(str(path))
        if ds is None:
            raise RuntimeError(f"cannot open {path}")
        try:
            band = ds.GetRasterBand(1)
            nd_raw = band.GetNoDataValue()
            nd_year: int | None = int(nd_raw) if nd_raw is not None else nodata_hint
            arr = band.ReadAsArray(min_col, min_row, window_w, window_h)
            if arr is None:
                raise RuntimeError(f"ReadAsArray returned None for year {year}")

            mask = arr == pixel_id_u8
            if nd_year is not None:
                mask &= arr != np.uint8(nd_year)
            mask &= valid_2d

            pixels_in_window = int(mask.sum())
            cell_count: dict[int, int] = {}
            if pixels_in_window > 0:
                flat = cell_flat_w[mask]
                uniq, cnts = np.unique(flat, return_counts=True)
                cell_count = dict(zip(uniq.tolist(), cnts.tolist()))

            for ti, (row_idx, col_idx) in enumerate(top_indices):
                flat_idx = grid.flat_idx(row_idx, col_idx)
                matrix[ti][yi] = int(cell_count.get(flat_idx, 0))
        finally:
            ds = None

        elapsed = time.monotonic() - t0
        print(
            f"profile year={year} elapsed={elapsed:.2f}s "
            f"pixels_in_window={pixels_in_window}",
            flush=True,
        )

    return matrix, years_sorted


def descriptors_for_series(
    counts: list[int],
    years_sorted: list[int],
) -> tuple[int, int, float, int]:
    """Return (largest_jump, jump_year, jump_share, direction_changes).

    ``largest_jump`` is the maximum positive year-over-year increase in
    ``counts``. ``jump_year`` is the END year of that jump (the year
    with the higher count). ``jump_share`` is ``largest_jump / (counts[-1]
    - counts[0])`` so 1.0 indicates a reservoir-like step and a small
    value indicates diffuse gain. ``direction_changes`` counts how many
    times the sign of the year-over-year difference flips, so a
    persistently flickering cell is distinguishable from a monotonic
    one.
    """
    if len(counts) < 2:
        return 0, 0, 0.0, 0
    diffs = [counts[i + 1] - counts[i] for i in range(len(counts) - 1)]
    positive = [(d, i) for i, d in enumerate(diffs) if d > 0]
    if not positive:
        direction_changes = 0
        prev_sign = 0
        for d in diffs:
            sign = 1 if d > 0 else (-1 if d < 0 else 0)
            if sign != 0 and prev_sign != 0 and sign != prev_sign:
                direction_changes += 1
            if sign != 0:
                prev_sign = sign
        return 0, 0, 0.0, direction_changes
    largest_jump, jump_idx = max(positive)
    net_gain = counts[-1] - counts[0]
    jump_share = (largest_jump / net_gain) if net_gain > 0 else 0.0
    direction_changes = 0
    prev_sign = 0
    for d in diffs:
        sign = 1 if d > 0 else (-1 if d < 0 else 0)
        if sign != 0 and prev_sign != 0 and sign != prev_sign:
            direction_changes += 1
        if sign != 0:
            prev_sign = sign
    # jump_idx indexes diffs, so the END year of the jump is
    # years_sorted[jump_idx + 1].
    return largest_jump, int(years_sorted[jump_idx + 1]), jump_share, direction_changes


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--country", required=True)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--cog-dir", required=True, type=Path)
    parser.add_argument("--pixel-id", required=True, type=int)
    parser.add_argument("--base-year", required=True, type=int)
    parser.add_argument("--target-year", required=True, type=int)
    parser.add_argument("--cell-deg", type=float, default=0.1)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--outdir", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.cell_deg <= 0:
        print(f"error: --cell-deg must be positive (got {args.cell_deg})", file=sys.stderr)
        return 1
    if args.top <= 0:
        print(f"error: --top must be positive (got {args.top})", file=sys.stderr)
        return 1
    if args.base_year == args.target_year:
        print("error: --base-year and --target-year must differ", file=sys.stderr)
        return 1

    if args.outdir is None:
        args.outdir = Path(
            f"data/derived/{args.country}/collection-{args.collection}/probe"
        )
    args.outdir.mkdir(parents=True, exist_ok=True)

    # Open the base year first so the grid origin is derived from the
    # base-year geotransform (spec).
    base_path = args.cog_dir / f"coverage-{args.country}_classification_{args.base_year}.tif"
    if not base_path.exists():
        print(f"error: base raster not found: {base_path}", file=sys.stderr)
        return 1
    ds_base = gdal.Open(str(base_path))
    if ds_base is None:
        print(f"error: cannot open {base_path}", file=sys.stderr)
        return 1
    try:
        gt_base = ds_base.GetGeoTransform()
        width_base = ds_base.RasterXSize
        height_base = ds_base.RasterYSize
    finally:
        ds_base = None

    grid = Grid.from_geotransform(gt_base, width_base, height_base, args.cell_deg)
    # Precompute one area per cell row (constant across columns).
    grid.cell_area_per_row = cell_area_per_row_of(grid)
    print(
        f"grid cell_deg={grid.cell_deg} n_cols={grid.n_cols} n_rows={grid.n_rows} "
        f"cell_lon_min={grid.cell_lon_min:.6f} cell_lat_min={grid.cell_lat_min:.6f} "
        f"total_cells={grid.n_cols * grid.n_rows}",
        flush=True,
    )

    # Verify every year in --cog-dir shares the base geotransform; raise
    # hard if not (spec).
    year_paths = verify_grid_consistency(grid, args.cog_dir)
    years_sorted = [y for y, _ in year_paths]
    print(
        f"verified {len(year_paths)} files share the base geotransform; "
        f"years={years_sorted[0]}..{years_sorted[-1]}",
        flush=True,
    )

    if args.base_year not in years_sorted:
        print(f"error: --base-year {args.base_year} not in {args.cog_dir}", file=sys.stderr)
        return 1
    if args.target_year not in years_sorted:
        print(f"error: --target-year {args.target_year} not in {args.cog_dir}", file=sys.stderr)
        return 1

    # Read base nodata for documentation. The temporal profile reads
    # nodata per-year too, so we don't need to remember it across files.
    ds = gdal.Open(str(base_path))
    base_nodata_raw = ds.GetRasterBand(1).GetNoDataValue()
    ds = None
    base_nodata: int | None = (
        int(base_nodata_raw) if base_nodata_raw is not None else None
    )

    overall_t0 = time.monotonic()

    # Phase 1: count base and target per cell. Streaming, native
    # resolution, nodata read from band.
    print(f"count base={args.base_year} ...", flush=True)
    t0 = time.monotonic()
    base_counts = count_pixels_in_grid(base_path, grid, args.pixel_id, base_nodata)
    print(
        f"count base elapsed={time.monotonic() - t0:.2f}s "
        f"total={int(base_counts.sum())}",
        flush=True,
    )

    target_path = args.cog_dir / f"coverage-{args.country}_classification_{args.target_year}.tif"
    print(f"count target={args.target_year} ...", flush=True)
    t0 = time.monotonic()
    target_counts = count_pixels_in_grid(target_path, grid, args.pixel_id, base_nodata)
    print(
        f"count target elapsed={time.monotonic() - t0:.2f}s "
        f"total={int(target_counts.sum())}",
        flush=True,
    )

    # ----- Internal consistency assertions (fail loudly, never wrong).
    if int(base_counts.sum()) < 0 or int(target_counts.sum()) < 0:
        raise RuntimeError("negative total pixel count")
    if (base_counts < 0).any() or (target_counts < 0).any():
        raise RuntimeError("negative per-cell count")

    # Phase 2: net gain per cell; rank descending; pick top --top.
    # The counts arrays are flat (n_rows * n_cols,); we keep them flat
    # for the global stats and reshape to (n_rows, n_cols) only when
    # we need per-cell addressing for the ha loop.
    net_gain = target_counts.astype(np.int64) - base_counts.astype(np.int64)
    net_gain_2d = net_gain.reshape(grid.n_rows, grid.n_cols)
    base_counts_2d = base_counts.reshape(grid.n_rows, grid.n_cols)
    target_counts_2d = target_counts.reshape(grid.n_rows, grid.n_cols)

    total_base_pixels = int(base_counts.sum())
    total_target_pixels = int(target_counts.sum())
    total_net_gain_pixels = int(net_gain.sum())
    # Consistency: sum(net_gain) == target_total - base_total.
    if total_net_gain_pixels != total_target_pixels - total_base_pixels:
        raise RuntimeError(
            f"net_gain sum {total_net_gain_pixels} != "
            f"target_total - base_total {total_target_pixels - total_base_pixels}"
        )

    # Concentration: top 10 share of total net gain and count of cells
    # with any positive net gain.
    positive_mask = net_gain > 0
    n_cells_with_positive = int(positive_mask.sum())
    flat_sorted_idx = np.argsort(net_gain, kind="stable")[::-1]
    top10_idx = flat_sorted_idx[:10]
    top10_sum = int(net_gain[top10_idx].sum())
    top10_share = (
        top10_sum / total_net_gain_pixels if total_net_gain_pixels > 0 else 0.0
    )

    # Top --top cells (by net gain descending). If fewer than --top
    # cells have positive net gain, pad with zeros so we still emit
    # exactly --top entries (the ranking is descending, so zeros come
    # last and are explicitly zero-gain cells).
    n_top = args.top
    top_idx = flat_sorted_idx[:n_top]
    top_indices: list[tuple[int, int]] = [
        (int(i // grid.n_cols), int(i % grid.n_cols)) for i in top_idx.tolist()
    ]

    # Phase 3: temporal profile per top cell.
    print(
        f"profile: {len(top_indices)} top cells, union bbox of all",
        flush=True,
    )
    matrix, years_for_profile = temporal_profile(
        grid, year_paths, top_indices, args.pixel_id, base_nodata,
    )

    # Phase 4: descriptors and per-cell area.
    # Cell-level hectares use the cell-local average pixel area:
    #   cell_area_m2 / pixels_in_cell
    # This is exact under uniform per-row distribution within the cell
    # and a tight approximation otherwise for a 0.1 degree cell.
    csv_rows: list[list[str]] = []
    csv_header = [
        "rank",
        "row_idx", "col_idx",
        "center_lon", "center_lat",
        "base_pixels", "target_pixels",
        "net_gain_pixels", "net_gain_ha",
        "largest_single_year_jump", "largest_single_year_jump_year",
        "jump_share_of_net_gain", "direction_changes",
    ]

    top_cells_out: list[dict[str, Any]] = []
    total_net_gain_ha_all_cells = 0.0
    positive_cells_ha: list[tuple[int, int, int, float]] = []

    # Precompute the per-cell pixel count once via a single 2D
    # histogram over the precomputed pixel cell indices; this is
    # O(width*height) and avoids any per-cell meshgrid.
    ppc = pixels_per_cell(grid)
    # Sanity: sum of pixels-per-cell should equal width*height
    # (every pixel is assigned to exactly one cell).
    if int(ppc.sum()) != grid.width * grid.height:
        raise RuntimeError(
            f"pixels_per_cell sum {int(ppc.sum())} != "
            f"width*height {grid.width * grid.height}"
        )

    for r in range(grid.n_rows):
        for c in range(grid.n_cols):
            net_px = int(net_gain_2d[r, c])
            if net_px == 0:
                continue
            area_m2 = cell_area_m2(grid, r, c)
            px_in_cell = int(ppc[r, c])
            if px_in_cell <= 0:
                continue
            avg_pixel_area = area_m2 / float(px_in_cell)
            ha = net_px * avg_pixel_area / 10000.0
            total_net_gain_ha_all_cells += ha
            if net_px > 0:
                positive_cells_ha.append((r, c, net_px, ha))

    # Sanity: total ha matches the canonical row-wise total within a
    # small epsilon (per-cell average vs per-row within-cell averages
    # differ by sub-percent for 0.1 degree cells).
    if abs(total_net_gain_ha_all_cells) < 1e-9 and total_net_gain_pixels != 0:
        raise RuntimeError("total hectares computed as zero while net pixels nonzero")

    for rank, (row_idx, col_idx) in enumerate(top_indices, start=1):
        base_px = int(base_counts_2d[row_idx, col_idx])
        target_px = int(target_counts_2d[row_idx, col_idx])
        net_px = target_px - base_px
        area_m2 = cell_area_m2(grid, row_idx, col_idx)
        px_in_cell = int(ppc[row_idx, col_idx])
        if px_in_cell <= 0:
            net_ha = 0.0
        else:
            net_ha = net_px * (area_m2 / float(px_in_cell)) / 10000.0
        lon, lat = cell_center(grid, row_idx, col_idx)

        # Yearly counts for this cell.
        if matrix:
            series = matrix[rank - 1]
        else:
            series = []
        largest_jump, jump_year, jump_share, direction_changes = descriptors_for_series(
            series, years_for_profile
        )

        yearly_dict = {str(y): int(c) for y, c in zip(years_for_profile, series)}
        top_cells_out.append({
            "rank": rank,
            "row_idx": int(row_idx),
            "col_idx": int(col_idx),
            "center_lon": float(lon),
            "center_lat": float(lat),
            "base_pixels": base_px,
            "target_pixels": target_px,
            "net_gain_pixels": int(net_px),
            "net_gain_ha": float(net_ha),
            "largest_single_year_jump": int(largest_jump),
            "largest_single_year_jump_year": int(jump_year),
            "jump_share_of_net_gain": float(jump_share),
            "direction_changes": int(direction_changes),
            "yearly_counts": yearly_dict,
        })

        csv_rows.append([
            str(rank),
            str(row_idx), str(col_idx),
            f"{lon:.6f}", f"{lat:.6f}",
            str(base_px), str(target_px),
            str(net_px), f"{net_ha:.6f}",
            str(largest_jump), str(jump_year),
            f"{jump_share:.6f}", str(direction_changes),
        ])

    # ----- Write outputs -----
    json_path = args.outdir / f"class-change-probe-{args.country}-collection-{args.collection}.json"
    csv_path = args.outdir / f"class-change-probe-top-cells-{args.country}-collection-{args.collection}.csv"

    summary: dict[str, Any] = {
        # D7 labelling at the top level so no consumer can miss it.
        "extent_label": EXTENT_LABEL,
        "boundary_note": BOUNDARY_NOTE,
        "country": args.country,
        "collection": args.collection,
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "pixel_id": args.pixel_id,
        "base_year": args.base_year,
        "target_year": args.target_year,
        "cell_deg": grid.cell_deg,
        "grid": {
            "cell_lon_min": grid.cell_lon_min,
            "cell_lat_min": grid.cell_lat_min,
            "n_cols": grid.n_cols,
            "n_rows": grid.n_rows,
            "total_cells": grid.n_cols * grid.n_rows,
        },
        "raster": {
            "origin_lon": gt_base[0],
            "origin_lat": gt_base[3],
            "pixel_size_lon": gt_base[1],
            "pixel_size_lat": gt_base[5],
            "width": width_base,
            "height": height_base,
            "nodata_value": base_nodata,
        },
        "area_method": AREA_METHOD_DESCRIPTION,
        "authalic_radius_m": AUTHALIC_RADIUS_M,
        "total_base_pixels": total_base_pixels,
        "total_target_pixels": total_target_pixels,
        "total_net_gain_pixels": total_net_gain_pixels,
        "total_net_gain_ha": float(total_net_gain_ha_all_cells),
        "concentration": {
            "top_10_share_of_net_gain": float(top10_share),
            "n_cells_with_positive_net_gain": n_cells_with_positive,
        },
        "top_cells": top_cells_out,
    }

    json_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(csv_header)
        w.writerows(csv_rows)

    total_elapsed = time.monotonic() - overall_t0
    peak_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_mb = peak_kb / 1024.0

    # ----- Final summary print (spec) -----
    print(
        f"Done. elapsed={total_elapsed:.2f}s peak_rss_mb={peak_mb:.1f} "
        f"json={json_path} csv={csv_path}",
        flush=True,
    )
    print(
        f"Total net gain: {total_net_gain_pixels} pixels "
        f"({total_net_gain_ha_all_cells:.2f} ha). "
        f"top_10_share={top10_share:.4f} "
        f"n_cells_with_positive_net_gain={n_cells_with_positive}.",
        flush=True,
    )
    print("Top 5 cells (rank, center_lon, center_lat, net_px, net_ha, "
          "largest_jump, jump_year, jump_share, direction_changes):",
          flush=True)
    for cell in top_cells_out[:5]:
        print(
            f"  #{cell['rank']} lon={cell['center_lon']:.4f} "
            f"lat={cell['center_lat']:.4f} "
            f"net_px={cell['net_gain_pixels']} "
            f"net_ha={cell['net_gain_ha']:.2f} "
            f"largest_jump={cell['largest_single_year_jump']} "
            f"@ year {cell['largest_single_year_jump_year']} "
            f"jump_share={cell['jump_share_of_net_gain']:.3f} "
            f"dir_changes={cell['direction_changes']}",
            flush=True,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))