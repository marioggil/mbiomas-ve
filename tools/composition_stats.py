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

with the WGS84 authalic radius R = 6371007.181 m. The actual computation
lives in ``tools.spatial_units.compute_row_areas_m2`` (single source of
truth, derived from each file's own geotransform, with an orientation
guard that works for both north-up and south-up rasters). Each row's
area is divided by the raster width to give the per-pixel area for that
row. The geotransform is read from every file (gdal GetGeoTransform) so
the formula is never hardcoded for a single extent.

Pixel counts use a VECTORISED BLOCK-WIDE BINARY KEY. With 45000 rows per
year, a Python loop over rows calling np.bincount would be prohibitively
slow. Instead, for each row-block we build a single int32 key shaped
like the block where each cell encodes (row_in_block * unit_count * 256 +
unit_index * 256 + class_value); a single np.bincount call with
minlength=block_rows * unit_count * 256 reshaped to (block_rows,
unit_count, 256) gives every per-row per-unit histogram in one call.
Class values are Byte, so 256 buckets per row are sufficient. For the
shipped ExtentUnit (unit_count=1) the key collapses to the original
two-dimensional form, so counts are bit-identical to the pre-refactor
output.

Nodata is reported SEPARATELY from classes, not silently dropped. Nodata
conflates "outside the mapped extent" with "not observed" and that
ambiguity must be visible in the output for honest reporting; downstream
consumers need both numbers to interpret any area figure.

The summary JSON carries the mandatory MapBiomas labelling (project
decision D7): every area figure covers the MapBiomas mapping extent
rather than internationally recognized borders, which includes disputed
territory. The ``extent_label`` and ``boundary_note`` fields are written
at the top level of the JSON so no downstream consumer can miss them.

SUMMARY JSON SHAPE (schema_version)
-----------------------------------
The summary JSON is versioned through a top-level ``schema_version``
integer. The current value is ``2``; version 1 was the flat shape where
year keys (``"1985"`` ... ``"2024"``) lived alongside the metadata keys
at the top level, forcing every consumer to iterate the top level and
guess which keys were years (40 year keys plus 9 metadata keys for the
Venezuelan collection-3 file at the time of the bump). Version 2
nests every per-year record under a single ``per_year`` object keyed by
the year as a string. The metadata keys (``extent_label``,
``boundary_note``, ``country``, ``collection``, ``generated_utc``,
``years``, ``area_method``, ``authalic_radius_m``, ``nodata_value``,
``spatial_unit``, ``spatial_unit_metadata``, ``schema_version``) are
the only non-``per_year`` top-level keys; no year key may remain at
the top level. The ``per_year`` payload for each year is unchanged:
the same fields (``valid_area_ha``, ``nodata_area_ha``,
``total_extent_ha``, ``nodata_pixels``, ``total_pixels``,
``valid_pixels``, ``class_pixels``, ``class_presence``) with the same
numeric values and the same D7 labelling context above them. The
version exists so a consumer can detect this shape change rather than
silently misread an old file; this tool only writes schema version 2,
and CSVs are unaffected by schema bumps - this is a JSON-only
contract. Bump ``SCHEMA_VERSION`` and update this section when the
top-level JSON contract changes again.

SPATIAL UNITS
-------------
The counting loop is parameterised by a ``SpatialUnit`` from
``tools.spatial_units``. The shipped default is ``ExtentUnit``, which
treats the whole raster as a single unit and reproduces today's numbers
exactly. Hexagonal aggregation via ``H3Unit`` is scheduled for phase F3
(decision D4); requesting ``--unit h3`` exits non-zero with an F3-bound
message instead of silently falling back to extent.

Usage:
    tools/composition_stats.py --country <c> --collection <n> \\
        --cog-dir <dir> --codebook <json> --outdir <dir> \\
        [--row-block 256] [--unit extent|h3] [--years 2024 1985]
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

# tools/ is a flat scripts directory, not a Python package. Add its
# absolute path to sys.path so we can import our siblings (spatial_units)
# when the script is launched as `python3 tools/composition_stats.py`.
# This stays inside the tools/ surface and never touches the repo layout.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from spatial_units import (  # noqa: E402  (after sys.path tweak)
    AUTHALIC_RADIUS_M,
    ExtentUnit,
    H3Unit,
    SpatialUnit,
    compute_row_areas_m2,
)


# First 19xx/20xx year token in the filename. A file without such a token is
# treated as a recorded failure, not a crash.
YEAR_RE = re.compile(r"(19|20)\d{2}")

# Tolerance for the internal consistency checks. Total extent ==
# sum(class areas) + nodata area should hold exactly because everything is
# derived from the same row-area vector. 1e-6 ha is ~1e-2 m^2, well below
# any single pixel area.
HA_EPSILON = 1e-6

# Top-level ``schema_version`` written into the composition-summary JSON.
# Version 1 mixed metadata keys and per-year records at the top level, so
# a consumer had to iterate the top level and guess which keys were years
# (40 year keys plus 9 metadata keys for venezuela-collection-3 at the
# time of the bump). Version 2 nests every per-year record under a
# single ``per_year`` object keyed by the year as a string; the metadata
# keys (plus ``schema_version`` itself) are the only non-``per_year``
# top-level keys. The per-year payload is byte-identical to v1 apart
# from its new location, so this constant governs only the JSON shape -
# the CSVs are unchanged. Bump this when the top-level JSON contract
# changes again and update the SUMMARY JSON SHAPE section of the
# docstring to match.
SCHEMA_VERSION = 2

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

# Single source of truth for the F3-bound error string, kept here verbatim
# so the error path does not silently drift from ``tools/spatial_units.py``.
F3_H3_NOT_IMPLEMENTED_MSG = (
    "h3 aggregation is declared in tools/spatial_units.H3Unit but not "
    "implemented in this build; hexagonal aggregation is scheduled for "
    "phase F3 of the plataforma-cobertura-ve rollout (decision D4). "
    "Re-run with --unit extent to keep using the committed extent-based "
    "composition pipeline; do not request --unit h3 against this build."
)

# Unit name -> SpatialUnit factory. Mapping to callable so the CLI
# dispatcher exits BEFORE constructing the H3Unit stub (whose __init__
# raises loudly by contract). New spatial units register here.
UNIT_FACTORIES: dict[str, Any] = {
    "extent": ExtentUnit,
    "h3": H3Unit,
}


def extract_year(name: str) -> int | None:
    """Return the first 19xx/20xx year token in the filename, or None."""
    m = YEAR_RE.search(name)
    return int(m.group(0)) if m else None


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


def _extent_histogram_and_pixel_area(
    arr: np.ndarray,
    pixel_area_per_row_m2: np.ndarray,
    yoff: int,
    block_h: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Specialised per-block pass for ``ExtentUnit``.

    Every pixel lives in unit 0 with row area = full row area, so the
    per-row per-unit pixel area is just ``pixel_area_per_row_m2`` for
    the rows of the block (reshaped to (block_h, 1)). The histogram
    collapses to the original 2-D (row x class) form; the returned
    shape (block_h, 1, 256) keeps the downstream code-uniform with the
    general path, where the singleton unit dimension carries no
    additional information.

    Skipping the per-pixel assignment matrix keeps peak RSS in line
    with the pre-refactor baseline; that allocation alone costs ~50 MB
    per block at the Venezuela width of ~57500 pixels.
    """
    unit_pixel_area = pixel_area_per_row_m2[yoff:yoff + block_h].reshape(
        block_h, 1,
    )
    row_idx_arr = (
        np.arange(block_h, dtype=np.int32).reshape(-1, 1) * 256
    )
    arr_int = arr.astype(np.int32)
    keyed = (row_idx_arr + arr_int).ravel()
    hist2 = np.bincount(keyed, minlength=block_h * 256).reshape(
        block_h, 256,
    )
    return unit_pixel_area, hist2.reshape(block_h, 1, 256)


def process_year(
    path: Path,
    valid_pixel_ids: set[int],
    aggregator_ids: set[int],
    row_block: int,
    fallback_nodata: int | None,
    unit: SpatialUnit,
) -> tuple[YearTotals, list[int], list[int]]:
    """Stream one COG at native resolution and return per-year totals.

    Returns ``(totals, unknown_pixel_ids, aggregator_ids_found)`` where the
    latter two are sorted lists of offending values for this year (empty in
    clean data). The bincount-based histogram runs at native resolution
    inside each row block, so no full-raster array is ever held in memory.

    The partition is driven by ``unit``: it assigns every pixel of a row
    block to a unit index (or the spatial_units.OUTSIDE_UNIT sentinel)
    and supplies each unit's area in m^2 for those rows. ExtentUnit
    reproduces the pre-refactor counts and areas exactly; H3Unit is a
    stub that fails loudly when constructed.
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

        unit_count = unit.unit_count

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

            # Branch on partition triviality. ExtentUnit is the whole
            # raster as a single unit, so every pixel lives in unit 0;
            # the general per-pixel assignment + per-row per-unit pixel
            # count is unnecessary and would cost a ~50 MB allocation
            # per block at the Venezuela width of ~57500 pixels. We
            # route H3Unit and any future non-trivial partition through
            # the general path; the H3Unit stub fails loudly on
            # construction so a future contributor cannot land here
            # accidentally.
            if isinstance(unit, ExtentUnit):
                unit_pixel_area, hist3 = _extent_histogram_and_pixel_area(
                    arr, pixel_area_per_row_m2, yoff, block_h,
                )
            else:
                # 1. Per-pixel unit assignment for this block.
                assign = unit.assign_row_block(gt, width, yoff, block_h)

                # 2. Per-row, per-unit area in m^2 for this block.
                unit_row_areas = unit.unit_areas_m2_row_block(
                    area_per_row_m2, yoff, block_h,
                )
                if unit_row_areas.shape != (block_h, unit_count):
                    raise RuntimeError(
                        f"unit {unit.name!r} returned unit_areas shape "
                        f"{unit_row_areas.shape!r}, expected "
                        f"{(block_h, unit_count)}"
                    )

                # 3. Per-row, per-unit pixel counts for this block.
                unit_pixel_count = np.zeros(
                    (block_h, unit_count), dtype=np.int64,
                )
                for u in range(unit_count):
                    unit_pixel_count[:, u] = (assign == u).sum(axis=1)

                # 4. Per-row, per-unit pixel area in m^2. Rows where
                #    the unit has zero pixels (including OUTSIDE_UNIT
                #    rows) keep a zero denominator; we guard against
                #    divide-by-zero here by leaving 0 in those slots.
                with np.errstate(divide="ignore", invalid="ignore"):
                    unit_pixel_area = np.where(
                        unit_pixel_count > 0,
                        unit_row_areas / unit_pixel_count,
                        0.0,
                    )

                # 5. Build the (row, unit, class) histogram. The base
                #    for the row index is unit_count * 256, so a single
                #    bincount call covers every row x unit x class in
                #    one shot. int32 is wide enough for any plausible
                #    unit_count (block_h=256, unit_count<=100000 keeps
                #    the max key under 2**31).
                stride = unit_count * 256
                row_idx_arr = (
                    np.arange(block_h, dtype=np.int32).reshape(-1, 1) * stride
                )
                unit_byte = assign.astype(np.int32) * 256
                arr_int = arr.astype(np.int32)
                keyed = (row_idx_arr + unit_byte + arr_int).ravel()
                hist3 = np.bincount(
                    keyed, minlength=block_h * unit_count * 256,
                ).reshape(block_h, unit_count, 256)

            # Nodata column (when present) holds the per-row nodata
            # count. We sum across units because nodata is a class-level
            # signal, not a per-unit signal in the shipped ExtentUnit;
            # for future H3 partitioning the output JSON will need to
            # attribute nodata per-unit and that rework is part of F3.
            if nodata_val is not None and 0 <= nodata_val < 256:
                nodata_row = hist3[:, :, nodata_val].sum(axis=1).astype(
                    np.int64,
                )
                nodata_count_per_row[yoff:yoff + block_h] = nodata_row

            for pid in valid_pixel_ids:
                col_unit = hist3[:, :, pid].astype(np.int64)
                class_pixels[pid] += int(col_unit.sum())
                class_area_m2[pid] += float((col_unit * unit_pixel_area).sum())

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
    unit: SpatialUnit,
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

    # Summary JSON with the D7 labelling at the top level so no
    # consumer can miss it. The active spatial unit is recorded by
    # name and by its self-description so downstream readers can pin
    # the partition the numbers came from without parsing tool
    # version history.
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
        "spatial_unit": unit.name,
        "spatial_unit_metadata": unit.describe(),
        "schema_version": SCHEMA_VERSION,
    }
    # Schema version 2: per-year records are nested under ``per_year`` so
    # the top level only carries metadata (plus ``schema_version``). A
    # consumer no longer has to guess which top-level keys are years.
    # The per-year payload (field set, field order, numeric values) is
    # unchanged from schema version 1; only its location moves.
    per_year: dict[str, dict[str, Any]] = {}
    for t in year_totals:
        valid_area_m2 = t.total_extent_m2 - t.nodata_area_m2
        class_presence = sorted(pid for pid, c in t.class_pixels.items() if c > 0)
        per_year[str(t.year)] = {
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
    summary["per_year"] = per_year

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
    parser.add_argument(
        "--unit",
        choices=sorted(UNIT_FACTORIES.keys()),
        default="extent",
        help=(
            "Spatial partition to aggregate over. 'extent' (default) "
            "treats the whole raster as one unit and reproduces the "
            "committed numbers exactly. 'h3' is scheduled for phase F3 "
            "and exits non-zero against this build."
        ),
    )
    args = parser.parse_args(argv)

    if args.row_block <= 0:
        print(f"error: --row-block must be positive (got {args.row_block})", file=sys.stderr)
        return 1

    # --unit h3 must exit non-zero with an F3-bound message BEFORE any
    # H3Unit construction (the class itself raises on __init__ as a
    # safety net, but the dispatcher exits earlier by design).
    if args.unit == "h3":
        print(f"error: {F3_H3_NOT_IMPLEMENTED_MSG}", file=sys.stderr)
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

    # Construct the spatial unit AFTER the dispatcher short-circuit so
    # a valid --unit value produces a usable partition.
    unit = UNIT_FACTORIES[args.unit]()
    if not isinstance(unit, SpatialUnit):
        raise RuntimeError(
            f"unit {unit!r} does not satisfy the SpatialUnit contract"
        )

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
            path, valid_pixel_ids, aggregator_ids, args.row_block,
            fallback_nodata, unit,
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
    write_outputs(args, codebook, year_totals, args.outdir, unit)

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
