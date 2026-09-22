#!/usr/bin/env python3
"""Convert MapBiomas coverage rasters to analysis-grade Cloud-Optimized GeoTIFFs.

WHY THIS TOOL EXISTS
--------------------
MapBiomas coverage rasters (Venezuela Collection 3, 1985-2024) ship as plain
GeoTIFFs without internal overviews. A decimated 1/16 read on the raw raster
takes ~6.7 s per year on this dataset; the same read on the COG produced here
takes ~0.19 s. COG conversion itself costs ~25 s per year.

These rasters encode DISCRETE CLASS CODES, not continuous intensities. Both the
overview pyramid and any future tile resampling MUST therefore use NEAREST.
The COG driver's default overview resampler is AVERAGE, which would invent
non-existent class values in the pyramid (e.g. class 3 and class 4 averaging
to 3.5). That is the single most important correctness constraint in this file.

Palettes are intentionally NOT baked into the output. The COG stays
analysis-grade class codes; colour lives in the codebook and the viewer.

Usage:
    tools/normalize_to_cog.py --country <c> --collection <n> \\
        --input-dir <dir> --output-dir <dir> --manifest <path>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from osgeo import gdal

gdal.UseExceptions()


# Exact creation options for the COG driver. Do NOT add, drop or "improve" any
# of these without re-reading the spec. BLOCKSIZE/COMPRESS/LEVEL/PREDICTOR are
# tuned for class-code Byte rasters; OVERVIEW_RESAMPLING=NEAREST prevents the
# pyramid from inventing fractional class codes; OVERVIEWS=IGNORE_EXISTING
# combined with NOT calling gdaladdo keeps the COG driver as the sole overview
# builder.
CREATION_OPTIONS = [
    "BLOCKSIZE=512",
    "COMPRESS=ZSTD",
    "LEVEL=9",
    "PREDICTOR=2",
    "NUM_THREADS=ALL_CPUS",
    "BIGTIFF=IF_SAFER",
    "OVERVIEW_RESAMPLING=NEAREST",
    "OVERVIEWS=IGNORE_EXISTING",
]

# A file without a 19xx/20xx year in its name is a recorded failure, not a
# crash; the rest of the run continues.
YEAR_RE = re.compile(r"(19|20)\d{2}")

# Pixel-exact integrity check window size, read at full resolution on both
# source and output.
WINDOW = 2048

# Offsets (in WINDOW-sized blocks) sampled to stress the COG: corners, mid
# and several prime-like positions across the raster. Clamped to stay inside.
INTEGRITY_OFFSETS: list[tuple[int, int]] = [
    (0, 0), (1, 0), (0, 1), (1, 1),
    (7, 5), (13, 9), (23, 17), (31, 29),
]


def sha256_of(path: Path) -> str:
    """Stream a file through SHA-256 in 1 MiB chunks without loading it."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_year(name: str) -> int | None:
    """First 19xx/20xx year found in the filename, or None."""
    m = YEAR_RE.search(name)
    return int(m.group(0)) if m else None


def clamp_window(
    width: int, height: int, xoff: int, yoff: int, size: int
) -> tuple[int, int, int, int]:
    """Clamp a (xoff, yoff, size, size) request so the window stays inside the raster."""
    if width <= 0 or height <= 0:
        return 0, 0, 0, 0
    if width < size:
        xoff, xsize = 0, width
    else:
        xoff = max(0, min(xoff, width - size))
        xsize = size
    if height < size:
        yoff, ysize = 0, height
    else:
        yoff = max(0, min(yoff, height - size))
        ysize = size
    return xoff, yoff, xsize, ysize


@dataclass
class Entry:
    year: int | None
    input_name: str
    output_name: str
    input_bytes: int
    output_bytes: int
    input_sha256: str
    output_sha256: str
    output_overviews: list[int]
    output_compression: str
    output_block_size: list[int]
    nodata: float | int | None
    class_set_sampled: list[int]
    integrity_ok: bool
    integrity_windows_checked: int
    integrity_differences: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


def _error_entry(
    src_path: Path,
    dst_path: Path,
    year: int | None,
    error_msg: str,
    input_bytes: int = 0,
    input_sha: str = "",
) -> Entry:
    """Build a minimal failure entry when conversion cannot complete."""
    return Entry(
        year=year,
        input_name=src_path.name,
        output_name=dst_path.name,
        input_bytes=input_bytes,
        output_bytes=0,
        input_sha256=input_sha,
        output_sha256="",
        output_overviews=[],
        output_compression="",
        output_block_size=[],
        nodata=None,
        class_set_sampled=[],
        integrity_ok=False,
        integrity_windows_checked=0,
        integrity_differences=[],
        error=error_msg,
    )


def convert_one(src_path: Path, dst_path: Path, year: int | None) -> tuple[Entry, bool]:
    """Convert src to COG, verify integrity and return (entry, success)."""
    try:
        input_bytes = src_path.stat().st_size
    except OSError as exc:
        return _error_entry(src_path, dst_path, year, f"stat_error: {exc}"), False

    try:
        input_sha = sha256_of(src_path)
    except OSError as exc:
        return _error_entry(
            src_path, dst_path, year, f"input_sha256_error: {exc}",
            input_bytes=input_bytes,
        ), False

    if year is None:
        # Recorded failure, not a crash: the file has no 19xx/20xx year token.
        return _error_entry(
            src_path, dst_path, year, "no_year_in_filename",
            input_bytes=input_bytes, input_sha=input_sha,
        ), False

    # Convert with the COG driver. NEAREST overview resampling is critical:
    # class codes must not be averaged into fractional values in the pyramid.
    try:
        gdal.Translate(
            str(dst_path),
            str(src_path),
            format="COG",
            creationOptions=CREATION_OPTIONS,
        )
    except Exception as exc:  # conversion error → recorded failure, not crash
        return _error_entry(
            src_path, dst_path, year, f"convert_error: {exc}",
            input_bytes=input_bytes, input_sha=input_sha,
        ), False

    try:
        output_bytes = dst_path.stat().st_size
        output_sha = sha256_of(dst_path)
    except OSError as exc:
        return _error_entry(
            src_path, dst_path, year, f"output_stat_error: {exc}",
            input_bytes=input_bytes, input_sha=input_sha,
        ), False

    # Inspect the produced COG: overview factors, compression, block size, nodata.
    ds_out = gdal.Open(str(dst_path))
    try:
        band = ds_out.GetRasterBand(1)

        # Overview factor levels (2, 4, 8, ...). For a 57605 px wide raster the
        # COG driver typically stops before the next factor would drop below
        # ~256 px, so we record whatever levels it actually built.
        overview_count = band.GetOverviewCount()
        overview_factors: list[int] = []
        if overview_count > 0:
            w_out = ds_out.RasterXSize
            for i in range(overview_count):
                ov = band.GetOverview(i)
                # GetOverview returns a Band; its XSize attribute is the
                # overview width, not RasterXSize (which is Dataset-only).
                ov_w = ov.XSize
                factor = max(1, round(w_out / ov_w)) if ov_w > 0 else 1
                overview_factors.append(factor)

        compression = ds_out.GetMetadata("IMAGE_STRUCTURE").get("COMPRESSION", "")
        bsx, bsy = band.GetBlockSize()
        nodata = band.GetNoDataValue()

        # Class set sampled from the overview pyramid at the 1/8 decimation
        # level. NEAREST resampling keeps this discrete.
        w = ds_out.RasterXSize
        h = ds_out.RasterYSize
        sampled = band.ReadAsArray(buf_xsize=w // 8, buf_ysize=h // 8)
        class_set = sorted(int(v) for v in np.unique(sampled) if v != 0)

        # Bounded pixel-exact integrity check: 2048x2048 windows at full
        # resolution on both source and output, at eight clamped offsets.
        # Lossless conversion must never report differences.
        ds_src = gdal.Open(str(src_path))
        try:
            diffs: list[dict[str, Any]] = []
            for xi, yi in INTEGRITY_OFFSETS:
                xoff, yoff, xsize, ysize = clamp_window(
                    ds_src.RasterXSize, ds_src.RasterYSize,
                    xi * WINDOW, yi * WINDOW, WINDOW,
                )
                if xsize == 0 or ysize == 0:
                    continue
                a = ds_src.ReadAsArray(xoff, yoff, xsize, ysize)
                b = band.ReadAsArray(xoff, yoff, xsize, ysize)
                n_diff = int(np.sum(a != b))
                diffs.append({
                    "offset": [xoff, yoff],
                    "window": [xsize, ysize],
                    "diff_pixels": n_diff,
                })
        finally:
            ds_src = None
    finally:
        ds_out = None

    integrity_ok = all(d["diff_pixels"] == 0 for d in diffs)

    entry = Entry(
        year=year,
        input_name=src_path.name,
        output_name=dst_path.name,
        input_bytes=input_bytes,
        output_bytes=output_bytes,
        input_sha256=input_sha,
        output_sha256=output_sha,
        output_overviews=sorted(overview_factors),
        output_compression=compression,
        output_block_size=[int(bsx), int(bsy)],
        nodata=nodata,
        class_set_sampled=class_set,
        integrity_ok=integrity_ok,
        integrity_windows_checked=len(diffs),
        integrity_differences=diffs,
    )
    return entry, integrity_ok


def write_manifest(
    args: argparse.Namespace,
    entries: list[Entry],
    failures: list[Entry],
    manifest_path: Path,
) -> None:
    """Serialize the run into a UTF-8 JSON manifest with a trailing newline."""
    successful = [e for e in entries if e.error is None and e.integrity_ok]
    years_sorted = sorted({e.year for e in entries if e.year is not None})

    payload = {
        "country": args.country,
        "collection": args.collection,
        "kind": "cog-normalization",
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "creation_options": CREATION_OPTIONS,
        "source_dir": str(args.input_dir),
        "output_dir": str(args.output_dir),
        "years": years_sorted,
        "totals": {
            "inputs": len(entries),
            "converted": len(successful),
            "failed": len(failures),
            "output_bytes": sum(e.output_bytes for e in successful),
        },
        "failures": [asdict(e) for e in failures],
        "entries": [
            asdict(e)
            for e in sorted(entries, key=lambda x: (x.year is None, x.year or 0))
        ],
    }

    manifest_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--country", required=True)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args(argv)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)

    inputs = sorted(args.input_dir.glob("*.tif"))
    if not inputs:
        print(f"error: no .tif inputs in {args.input_dir}", file=sys.stderr)
        return 1

    total = len(inputs)
    entries: list[Entry] = []
    failures: list[Entry] = []

    for index, src in enumerate(inputs, start=1):
        year = extract_year(src.name)
        dst = args.output_dir / src.name
        entry, ok = convert_one(src, dst, year)
        entries.append(entry)
        if not ok:
            failures.append(entry)

        if entry.error is not None:
            status = "FAILED"
            detail = entry.error
        else:
            n_clean = sum(1 for d in entry.integrity_differences if d["diff_pixels"] == 0)
            n_total = len(entry.integrity_differences)
            if entry.integrity_ok:
                status = "ok"
            else:
                status = "INTEGRITY FAILED"
            detail = f"{n_clean}/{n_total} windows clean"

        out_mb = entry.output_bytes / (1024 * 1024) if entry.output_bytes else 0.0
        print(
            f"[{index}/{total}] {entry.year} {status} {out_mb:.2f} MB "
            f"overviews={entry.output_overviews} {detail}",
            flush=True,
        )

    write_manifest(args, entries, failures, args.manifest)

    converted = sum(1 for e in entries if e.error is None and e.integrity_ok)
    print(
        f"Manifest written: {converted}/{total} converted, {len(failures)} failed, "
        f"{args.manifest}",
        flush=True,
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
