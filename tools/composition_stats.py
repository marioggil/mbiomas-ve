#!/usr/bin/env python3
"""Compute MapBiomas Venezuela land cover composition statistics per year.

WHY THIS TOOL EXISTS
--------------------
The MapBiomas coverage rasters encode DISCRETE CLASS CODES, not continuous
intensities. Composition statistics must therefore be computed EXACTLY at
native resolution - never sampled, never decimated, never read from the COG
overview pyramid. A separate verifier counted exactly 18 native pixels of
class 34 (Glaciar) in the 2024 raster; any other number means the counting
logic is wrong, so every row block is read at native resolution and counted
in the native Uint8 grid.

Area is computed with a ROW-WISE GEODESIC formula. The rasters are
EPSG:4326 geographic (degrees), where a single constant per-pixel area is
wrong by several percent across the 12 degrees of latitude that the
Venezuela extent spans. For row j with top latitude phi_top and bottom
latitude phi_bottom (in radians) and longitude extent delta_lambda_rad,
the row area is

    R^2 * delta_lambda_rad * (sin(phi_top) - sin(phi_bottom))

with the WGS84 authalic radius R = 6371007.181 m. Each row's area is then
divided by the raster width to give the per-pixel area for that row. The
geotransform is read from every file (gdal GetGeoTransform) so the formula
is never hardcoded for a single extent.

Pixel counts use a VECTORISED BLOCK-WIDE BINARY KEY. With 45000 rows per
year, a Python loop over rows calling np.bincount would be prohibitively
slow. Instead, for each row-block we build a single int32 key shaped like
the block where each cell encodes (row_in_block * 256 + class_value); a
single np.bincount call with minlength=block_rows * 256 reshaped to
(block_rows, 256) gives every per-row histogram in one call. Class values
are Byte, so 256 buckets per row are sufficient.

Nodata is reported SEPARATELY from classes, not silently dropped. Nodata
conflates "outside the mapped extent" with "not observed" and that
ambiguity must be visible in the output for honest reporting; downstream
consumers need both numbers to interpret any area figure.

The summary JSON carries the mandatory MapBiomas labelling (project
decision D7): every area figure covers the MapBiomas mapping extent
rather than internationally recognized borders, which includes disputed
territory. The ``extent_label`` and ``boundary_note`` fields are written
at the top level of the JSON so no downstream consumer can miss them.

Usage:
    tools/composition_stats.py --country <c> --collection <n> \\
        --cog-dir <dir> --codebook <json> --outdir <dir> \\
        [--row-block 256] [--years 2024 1985]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import resource
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from osgeo import gdal

gdal.UseExceptions()

# Bound GDAL's block cache so peak RSS stays well below 1 GB even on
# machines with tens of GB of RAM. We read sequentially in row blocks, so
# a small cache does not cost us extra I/O.
gdal.SetCacheMax(256 * 1024 * 1024)


# First 19xx/20xx year token in the filename. A file without such a token is
# treated as a recorded failure, not a crash.
YEAR_RE = re.compile(r"(19|20)\d{2}")

# Authalic radius of the WGS84 ellipsoid in metres - the radius of a sphere
# with the same surface area as the ellipsoid. Used so the sum of row areas
# approximates the true surface area of the geographic grid.
AUTHALIC_RADIUS_M = 6371007.181

# Tolerance for the internal consistency checks. Total extent ==
# sum(class areas) + nodata area should hold exactly because everything is
# derived from the same row-area vector. 1e-6 ha is ~1e-2 m^2, well below
# any single pixel area.
HA_EPSILON = 1e-6

# Mandatory MapBiomas labelling for every published composition figure.
# Every area figure covers the MapBiomas mapping extent, NOT internationally
# recognized borders. The extent exceeds internationally recognized borders
# and includes disputed territory.
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
    "latitude phi_bottom (in radians) and longitude extent delta_lambda_rad: "
    "area_m2 = R^2 * delta_lambda_rad * (sin(phi_top) - sin(phi_bottom)). "
    "Pixel area in row j is area_m2 / RasterXSize."
)


def extract_year(name: str) -> int | None:
    """Return the first 19xx/20xx year token in the filename, or None."""
    m = YEAR_RE.search(name)
    return int(m.group(0)) if m else None


def compute_row_areas_m2(
    geotransform: tuple[float, ...],
    width: int,
    height: int,
) -> np.ndarray:
    """Return a (height,) array of geodesic row areas in m^2.

    For each row j we derive the top and bottom edge latitudes from the
    file's own geotransform (gdal GetGeoTransform), map them to radians,
    and apply the spherical-strip formula. We order phi_top >= phi_bot so
    sin(phi_top) - sin(phi_bot) stays positive for both north-up (negative
    pixel height) and south-up (positive pixel height) rasters. The
    longitude extent is RasterXSize * pixel width in radians.
    """
    gt = geotransform
    j = np.arange(height, dtype=np.float64)
    top_edge = gt[3] + j * gt[5]
    bot_edge = top_edge + gt[5]
    phi_top_deg = np.maximum(top_edge, bot_edge)
    phi_bot_deg = np.minimum(top_edge, bot_edge)

    delta_lambda_rad = width * gt[1] * (np.pi / 180.0)
    sin_top = np.sin(np.deg2rad(phi_top_deg))
    sin_bot = np.sin(np.deg2rad(phi_bot_deg))

    return (AUTHALIC_RADIUS_M ** 2) * delta_lambda_rad * (sin_top - sin_bot)


@dataclass
class YearTotals:
    """Per-year totals accumulated block by block at native resolution."""

    year: int
    class_pixels: dict[int, int] = field(default_factory=dict)
    class_area_m2: dict[int, float] = field(default_factory=dict)
    nodata_pixels: int = 0
    nodata_area_m2: float = 0.0
    total_extent_m2: float = 0.0
    width: int = 0
    height: int = 0


def process_year(
    path: Path,
    valid_pixel_ids: set[int],
    aggregator_ids: set[int],
    row_block: int,
    fallback_nodata: int | None,
) -> tuple[YearTotals, list[int], list[int]]:
    """Stream one COG at native resolution and return per-year totals.

    Returns ``(totals, unknown_pixel_ids, aggregator_ids_found)`` where the
    latter two are sorted lists of offending values for this year (empty in
    clean data). The bincount-based histogram runs at native resolution
    inside each row block, so no full-raster array is ever held in memory.
    """
    ds = gdal.Open(str(path))
    if ds is None:
        raise RuntimeError(f"cannot open {path}")
    try:
        band = ds.GetRasterBand(1)
        gt = ds.GetGeoTransform()
        width = ds.RasterXSize
        height = ds.RasterYSize

        # Read the band's NoDataValue; do not hardcode 0. Fall back to the
        # codebook's declared nodata only if the band reports no value.
        nodata_raw = band.GetNoDataValue()
        if nodata_raw is None:
            nodata_val: int | None = fallback_nodata
        else:
            nodata_val = int(nodata_raw)

        area_per_row_m2 = compute_row_areas_m2(gt, width, height)
        pixel_area_per_row_m2 = area_per_row_m2 / float(width)
        total_extent_m2 = float(area_per_row_m2.sum())

        class_pixels: dict[int, int] = {pid: 0 for pid in valid_pixel_ids}
        class_area_m2: dict[int, float] = {pid: 0.0 for pid in valid_pixel_ids}
        nodata_count_per_row = np.zeros(height, dtype=np.int64)

        unknown_seen: set[int] = set()
        aggregator_seen: set[int] = set()

        for yoff in range(0, height, row_block):
            block_h = min(row_block, height - yoff)
            arr = band.ReadAsArray(0, yoff, width, block_h)
            if arr is None:
                raise RuntimeError(f"ReadAsArray returned None at yoff={yoff}")

            # Vectorised per-row histogram via the binary-key trick.
            # key = row_in_block * 256 + class_value; a single np.bincount
            # with minlength=block_h * 256 reshaped to (block_h, 256) gives
            # every per-row count in one call. Class values are Byte so 256
            # buckets per row are sufficient.
            row_idx = np.arange(block_h, dtype=np.int32).reshape(-1, 1)
            key = (row_idx * 256 + arr.astype(np.int32)).ravel()
            hist = np.bincount(key, minlength=block_h * 256).reshape(block_h, 256)

            # Nodata column (when present) holds the per-row nodata count.
            if nodata_val is not None and 0 <= nodata_val < 256:
                nodata_row = hist[:, nodata_val].astype(np.int64)
                nodata_count_per_row[yoff:yoff + block_h] = nodata_row

            block_pixel_area = pixel_area_per_row_m2[yoff:yoff + block_h]
            for pid in valid_pixel_ids:
                col = hist[:, pid].astype(np.int64)
                class_pixels[pid] += int(col.sum())
                class_area_m2[pid] += float(np.dot(col, block_pixel_area))

            # Unknown / aggregator detection on non-nodata values.
            if nodata_val is None:
                vals = np.unique(arr)
            else:
                vals = np.unique(arr[arr != nodata_val])
            for v in vals.tolist():
                v_int = int(v)
                if v_int in aggregator_ids:
                    aggregator_seen.add(v_int)
                if v_int not in valid_pixel_ids:
                    unknown_seen.add(v_int)
    finally:
        ds = None

    nodata_pixels = int(nodata_count_per_row.sum())
    nodata_area_m2 = float(np.dot(nodata_count_per_row, pixel_area_per_row_m2))

    for pid, a in class_area_m2.items():
        if not np.isfinite(a) or a < 0:
            raise RuntimeError(f"class {pid} has invalid area: {a!r}")
    if any(c < 0 for c in class_pixels.values()):
        raise RuntimeError("negative class pixel count")
    if not np.isfinite(nodata_area_m2) or nodata_area_m2 < 0:
        raise RuntimeError(f"nodata area invalid: {nodata_area_m2!r}")

    return (
        YearTotals(
            year=extract_year(path.name) or 0,
            class_pixels=class_pixels,
            class_area_m2=class_area_m2,
            nodata_pixels=nodata_pixels,
            nodata_area_m2=nodata_area_m2,
            total_extent_m2=total_extent_m2,
            width=width,
            height=height,
        ),
        sorted(unknown_seen),
        sorted(aggregator_seen),
    )


def build_rows_and_assert(
    args: argparse.Namespace,
    codebook: dict[str, Any],
    year_totals: list[YearTotals],
) -> tuple[list[list[str]], list[list[str]]]:
    """Build level-2 and level-1 CSV rows and run consistency assertions.

    The three assertions, each failing loudly with a RuntimeError instead of
    silently writing a wrong number:
      (a) sum(level2 areas) == sum(level1 areas) for every year,
      (b) sum(all class areas) + nodata area == total_extent_ha for every year,
      (c) no class area is negative or non-finite.
    """
    country = args.country
    collection = args.collection
    classes = codebook["classes"]
    level1_list = codebook["level1"]

    level2_rows: list[list[str]] = []
    level1_rows: list[list[str]] = []

    # Level-1 aggregates (areas kept in m^2 for exact comparison).
    l1_area_m2: dict[int, dict[int, float]] = {t.year: {} for t in year_totals}
    l1_pixels: dict[int, dict[int, int]] = {t.year: {} for t in year_totals}

    for t in year_totals:
        valid_area_ha = (t.total_extent_m2 - t.nodata_area_m2) / 10000.0
        for cls in classes:
            pid = cls["pixel_id"]
            pixels = t.class_pixels.get(pid, 0)
            area_m2 = t.class_area_m2.get(pid, 0.0)
            area_ha = area_m2 / 10000.0
            share = 100.0 * area_ha / valid_area_ha if valid_area_ha > 0 else 0.0
            level2_rows.append([
                country, collection, str(t.year), str(pid), cls["code"],
                str(cls["level1_pixel_id"]), cls["level1_code"],
                cls["name_es"], cls["name_en"],
                str(pixels), f"{area_ha:.6f}", f"{share:.6f}",
            ])
            lv_id = cls["level1_pixel_id"]
            l1_area_m2[t.year][lv_id] = l1_area_m2[t.year].get(lv_id, 0.0) + area_m2
            l1_pixels[t.year][lv_id] = l1_pixels[t.year].get(lv_id, 0) + pixels

    for t in year_totals:
        valid_area_ha = (t.total_extent_m2 - t.nodata_area_m2) / 10000.0
        for lv in level1_list:
            lv_id = lv["pixel_id"]
            pixels = l1_pixels[t.year].get(lv_id, 0)
            area_m2 = l1_area_m2[t.year].get(lv_id, 0.0)
            area_ha = area_m2 / 10000.0
            share = 100.0 * area_ha / valid_area_ha if valid_area_ha > 0 else 0.0
            level1_rows.append([
                country, collection, str(t.year), str(lv_id), lv["code"],
                lv["name_es"], lv["name_en"],
                str(pixels), f"{area_ha:.6f}", f"{share:.6f}",
            ])

    # ----- Internal consistency assertions -----
    # HA_EPSILON (in ha) -> m^2 tolerance.
    eps_m2 = HA_EPSILON * 10000.0
    for t in year_totals:
        sum_l2_m2 = sum(t.class_area_m2.values())
        sum_l1_m2 = sum(l1_area_m2[t.year].values())
        if abs(sum_l2_m2 - sum_l1_m2) > eps_m2:
            raise RuntimeError(
                f"year {t.year}: level2 area sum {sum_l2_m2!r} m^2 "
                f"!= level1 area sum {sum_l1_m2!r} m^2"
            )
        expected_m2 = t.total_extent_m2
        actual_m2 = sum_l2_m2 + t.nodata_area_m2
        if abs(actual_m2 - expected_m2) > eps_m2:
            raise RuntimeError(
                f"year {t.year}: class areas + nodata area = {actual_m2!r} m^2, "
                f"total extent = {expected_m2!r} m^2"
            )
        for pid, a in t.class_area_m2.items():
            if not np.isfinite(a) or a < 0:
                raise RuntimeError(
                    f"year {t.year}: class {pid} area invalid: {a!r}"
                )

    return level2_rows, level1_rows


def write_outputs(
    args: argparse.Namespace,
    codebook: dict[str, Any],
    year_totals: list[YearTotals],
    outdir: Path,
) -> None:
    """Write the two CSVs and the summary JSON after assertions pass."""
    # Build CSV rows; this also runs the consistency assertions and raises
    # on failure, so no wrong-number outputs are written.
    level2_rows, level1_rows = build_rows_and_assert(args, codebook, year_totals)

    country = args.country
    collection = args.collection
    level2_path = outdir / f"composition-level2-{country}-collection-{collection}.csv"
    level1_path = outdir / f"composition-level1-{country}-collection-{collection}.csv"
    summary_path = outdir / f"composition-summary-{country}-collection-{collection}.json"

    l2_header = [
        "country", "collection", "year", "pixel_id", "code",
        "level1_pixel_id", "level1_code", "name_es", "name_en",
        "pixels", "area_ha", "share_of_extent_pct",
    ]
    l1_header = [
        "country", "collection", "year", "level1_pixel_id", "level1_code",
        "name_es", "name_en", "pixels", "area_ha", "share_of_extent_pct",
    ]

    # CSV: use the csv module so embedded commas in class names are
    # quoted correctly (e.g. "Río, lago u océano").
    with level2_path.open("w", encoding="utf-8", newline="") as f2:
        w2 = csv.writer(f2, lineterminator="\n")
        w2.writerow(l2_header)
        w2.writerows(level2_rows)

    with level1_path.open("w", encoding="utf-8", newline="") as f1:
        w1 = csv.writer(f1, lineterminator="\n")
        w1.writerow(l1_header)
        w1.writerows(level1_rows)

    # Summary JSON with the D7 labelling at the top level so no consumer
    # can miss it.
    summary: dict[str, Any] = {
        "extent_label": EXTENT_LABEL,
        "boundary_note": BOUNDARY_NOTE,
        "country": country,
        "collection": collection,
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "years": [t.year for t in year_totals],
        "area_method": AREA_METHOD_DESCRIPTION,
        "authalic_radius_m": AUTHALIC_RADIUS_M,
        "nodata_value": codebook.get("invariants", {}).get("nodata_value"),
    }
    for t in year_totals:
        valid_area_m2 = t.total_extent_m2 - t.nodata_area_m2
        class_presence = sorted(pid for pid, c in t.class_pixels.items() if c > 0)
        summary[str(t.year)] = {
            "valid_area_ha": valid_area_m2 / 10000.0,
            "nodata_area_ha": t.nodata_area_m2 / 10000.0,
            "total_extent_ha": t.total_extent_m2 / 10000.0,
            "nodata_pixels": t.nodata_pixels,
            "total_pixels": t.width * t.height,
            "valid_pixels": t.width * t.height - t.nodata_pixels,
            "class_pixels": {
                str(pid): t.class_pixels[pid] for pid in sorted(t.class_pixels)
            },
            "class_presence": class_presence,
        }

    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--country", required=True)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--cog-dir", required=True, type=Path)
    parser.add_argument("--codebook", required=True, type=Path)
    parser.add_argument("--outdir", required=True, type=Path)
    parser.add_argument("--row-block", type=int, default=256)
    parser.add_argument("--years", type=int, nargs="*", default=None)
    args = parser.parse_args(argv)

    if args.row_block <= 0:
        print(f"error: --row-block must be positive (got {args.row_block})", file=sys.stderr)
        return 1

    codebook = json.loads(args.codebook.read_text(encoding="utf-8"))
    classes = codebook.get("classes", [])
    invariants = codebook.get("invariants", {})

    valid_pixel_ids: set[int] = {c["pixel_id"] for c in classes}
    aggregator_ids: set[int] = set(
        invariants.get("aggregator_pixel_ids_must_not_appear_in_rasters", [])
    )
    declared_nodata_raw = invariants.get("nodata_value")
    fallback_nodata: int | None = (
        int(declared_nodata_raw) if declared_nodata_raw is not None else None
    )

    args.outdir.mkdir(parents=True, exist_ok=True)

    inputs = sorted(args.cog_dir.glob("*.tif"))
    if not inputs:
        print(f"error: no .tif inputs in {args.cog_dir}", file=sys.stderr)
        return 1

    by_year: dict[int, Path] = {}
    for p in inputs:
        y = extract_year(p.name)
        if y is None:
            print(f"warning: cannot extract year from {p.name}; skipping", file=sys.stderr)
            continue
        by_year[y] = p

    if args.years:
        missing = [y for y in args.years if y not in by_year]
        if missing:
            print(
                f"error: requested years not found in {args.cog_dir}: {missing}",
                file=sys.stderr,
            )
            return 1
        # Preserve user order; final output is sorted by year below.
        selected = [(y, by_year[y]) for y in args.years]
    else:
        selected = sorted(by_year.items())

    year_totals: list[YearTotals] = []
    all_unknown: set[int] = set()
    all_aggregator: set[int] = set()

    overall_t0 = time.monotonic()

    for i, (year, path) in enumerate(selected, start=1):
        t0 = time.monotonic()
        totals, unknown, aggregator = process_year(
            path, valid_pixel_ids, aggregator_ids, args.row_block, fallback_nodata,
        )
        elapsed = time.monotonic() - t0
        valid_area_ha = (totals.total_extent_m2 - totals.nodata_area_m2) / 10000.0
        n_classes = sum(1 for c in totals.class_pixels.values() if c > 0)
        print(
            f"[{i}/{len(selected)}] year={year} elapsed={elapsed:.2f}s "
            f"valid_area_km2={valid_area_ha / 100.0:.4f} "
            f"classes_present={n_classes}",
            flush=True,
        )
        year_totals.append(totals)
        all_unknown.update(unknown)
        all_aggregator.update(aggregator)

    # Stable output ordering regardless of --years order.
    year_totals.sort(key=lambda t: t.year)

    total_elapsed = time.monotonic() - overall_t0
    write_outputs(args, codebook, year_totals, args.outdir)

    # Peak RSS for this process, in MB (ru_maxrss is kilobytes on Linux).
    peak_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_mb = peak_kb / 1024.0

    print(
        f"Done. years={len(year_totals)} elapsed={total_elapsed:.2f}s "
        f"peak_rss_mb={peak_mb:.1f} outdir={args.outdir}",
        flush=True,
    )

    if all_unknown or all_aggregator:
        if all_unknown:
            print(f"unknown_pixel_ids: {sorted(all_unknown)}", file=sys.stderr)
        if all_aggregator:
            print(f"aggregator_ids_found: {sorted(all_aggregator)}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
