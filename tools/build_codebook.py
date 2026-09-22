#!/usr/bin/env python3
"""Build a machine-readable codebook for a MapBiomas coverage collection.

The official PDF codebook is the source of truth for class names, hierarchy and
colors. The QGIS paletted style (``.qml``) is used only as a cross-check: where
the two disagree, the PDF wins and the disagreement is recorded in the output so
the divergence is never silently resolved.

Usage:
    tools/build_codebook.py --country venezuela --collection 3 \
        --pdf data/legend/source/MB-Venezuela-Col-3-Legend-Code.pdf \
        --qml data/legend/source/QGIS_Leyenda_col3.qml \
        --outdir data/legend

The script is strict on purpose: any structural surprise in the PDF aborts with a
non-zero exit status instead of emitting a quietly incomplete codebook.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

# A legend row looks like:
#   " 1.1. Forest      1.1. Bosque      3       #1f8d49"
# The PDF is not consistent about spacing ("3.Agricultural areas") or about the
# period after a code ("5.3 Acuicultura"), so both are optional and the split is
# anchored on the trailing "<pixel id> <#hex>" pair.
ROW_WITH_COLOR = re.compile(
    r"^(?P<head>.*?)\s+(?P<pixel_id>\d+)\s+(?P<color>#[0-9a-fA-F]{6})\s*$"
)
HEAD_SPLIT = re.compile(
    r"^\s*(?P<code>\d+(?:\.\d+)*)\.?\s*(?P<name_en>.+?)\s{2,}"
    r"(?P<code_es>\d+(?:\.\d+)*)\.?\s*(?P<name_es>.+?)\s*$"
)
QML_ENTRY = re.compile(r"<paletteEntry\b[^>]*/>")
QML_ATTR = re.compile(r'(\w+)="([^"]*)"')

EXPECTED_LEVEL1 = 6
EXPECTED_LEVEL2 = 25


class CodebookError(RuntimeError):
    """Raised when a source file cannot be read as expected."""


def pdf_rows(pdf_path: Path) -> list[dict]:
    """Extract legend rows from the official PDF codebook."""
    try:
        text = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except FileNotFoundError as exc:
        raise CodebookError("pdftotext is required (poppler-utils)") from exc
    except subprocess.CalledProcessError as exc:
        raise CodebookError(f"pdftotext failed on {pdf_path}: {exc.stderr}") from exc

    rows: list[dict] = []
    for line in text.splitlines():
        row_match = ROW_WITH_COLOR.match(line)
        if not row_match:
            continue
        head_match = HEAD_SPLIT.match(row_match.group("head"))
        if not head_match:
            raise CodebookError(f"could not split legend row: {line!r}")
        if head_match.group("code") != head_match.group("code_es"):
            raise CodebookError(
                f"code mismatch between columns in row: {line!r}"
            )
        code = head_match.group("code")
        rows.append(
            {
                "code": code,
                "name_en": head_match.group("name_en").strip(),
                "name_es": head_match.group("name_es").strip(),
                "pixel_id": int(row_match.group("pixel_id")),
                "color": row_match.group("color").lower(),
            }
        )

    if not rows:
        raise CodebookError(f"no legend rows found in {pdf_path}")
    return rows


def qml_entries(qml_path: Path) -> dict[int, dict]:
    """Read the QGIS paletted style, keyed by pixel value."""
    text = qml_path.read_text(encoding="utf-8")
    entries: dict[int, dict] = {}
    for tag in QML_ENTRY.findall(text):
        attrs = dict(QML_ATTR.findall(tag))
        if "value" not in attrs or "color" not in attrs:
            continue
        # QGIS labels are occasionally missing the space after the code
        # ("11.Herbazal/Arbustal inundable").
        label = re.sub(r"^\s*\d+(?:\.\d+)*\.?\s*", "", attrs.get("label", "")).strip()
        entries[int(attrs["value"])] = {
            "color": attrs["color"].lower(),
            "label": label,
            "alpha": int(attrs.get("alpha", "255")),
        }
    if not entries:
        raise CodebookError(f"no palette entries found in {qml_path}")
    return entries


def build(country: str, collection: str, pdf_path: Path, qml_path: Path) -> dict:
    rows = pdf_rows(pdf_path)

    level1_rows = [r for r in rows if "." not in r["code"]]
    level2_rows = [r for r in rows if "." in r["code"]]

    if len(level1_rows) != EXPECTED_LEVEL1:
        raise CodebookError(
            f"expected {EXPECTED_LEVEL1} level-1 groups, found {len(level1_rows)}"
        )
    if len(level2_rows) != EXPECTED_LEVEL2:
        raise CodebookError(
            f"expected {EXPECTED_LEVEL2} level-2 classes, found {len(level2_rows)}"
        )

    level1_by_code = {r["code"]: r for r in level1_rows}
    parents = {r["code"].split(".")[0] for r in level2_rows}

    # Level-1 ids are aggregation codes. They must never appear as pixel values in
    # the rasters, so they are exported separately as a validation invariant.
    aggregator_ids = sorted(
        level1_by_code[c]["pixel_id"] for c in parents if c in level1_by_code
    )

    # Leaf class = every detailed class, plus any level-1 group with no children
    # of its own (in Collection 3 that is "6. No observado" -> id 27).
    leaf_rows = list(level2_rows) + [
        r for r in level1_rows if r["code"] not in parents
    ]

    level1_out = [
        {
            "pixel_id": r["pixel_id"],
            "code": r["code"],
            "name_es": r["name_es"],
            "name_en": r["name_en"],
            "color": r["color"],
            "has_children": r["code"] in parents,
        }
        for r in level1_rows
    ]

    classes_out = []
    for r in leaf_rows:
        major = r["code"].split(".")[0]
        parent = level1_by_code.get(major)
        if parent is None:
            raise CodebookError(f"no level-1 parent for class {r['code']}")
        classes_out.append(
            {
                "pixel_id": r["pixel_id"],
                "code": r["code"],
                "level1_pixel_id": parent["pixel_id"],
                "level1_code": parent["code"],
                "name_es": r["name_es"],
                "name_en": r["name_en"],
                "color": r["color"],
            }
        )
    classes_out.sort(key=lambda c: c["pixel_id"])

    qml = qml_entries(qml_path)
    discrepancies = []
    for entry in classes_out:
        pid = entry["pixel_id"]
        if pid not in qml:
            discrepancies.append(
                {
                    "pixel_id": pid,
                    "name_es": entry["name_es"],
                    "field": "presence",
                    "pdf": "present",
                    "qml": "absent",
                }
            )
            continue
        if qml[pid]["color"] != entry["color"]:
            discrepancies.append(
                {
                    "pixel_id": pid,
                    "name_es": entry["name_es"],
                    "field": "color",
                    "pdf": entry["color"],
                    "qml": qml[pid]["color"],
                }
            )
        if qml[pid]["label"].casefold() != entry["name_es"].casefold():
            discrepancies.append(
                {
                    "pixel_id": pid,
                    "name_es": entry["name_es"],
                    "field": "name_es",
                    "pdf": entry["name_es"],
                    "qml": qml[pid]["label"],
                }
            )

    extra_qml_ids = sorted(set(qml) - {c["pixel_id"] for c in classes_out})
    if extra_qml_ids:
        discrepancies.append(
            {
                "pixel_id": None,
                "name_es": None,
                "field": "extra_qml_ids",
                "pdf": None,
                "qml": extra_qml_ids,
            }
        )

    return {
        "country": country,
        "collection": str(collection),
        "legend_name": f"MapBiomas {country.capitalize()} Colección {collection}",
        "source_of_truth": {
            "file": pdf_path.name,
            "kind": "official PDF codebook",
            "note": "Names, hierarchy and colors come from the PDF. The QGIS "
            "style is a cross-check only.",
        },
        "cross_check": {
            "file": qml_path.name,
            "kind": "QGIS paletted style",
            "discrepancies": discrepancies,
        },
        "level1": level1_out,
        "classes": classes_out,
        "invariants": {
            "aggregator_pixel_ids_must_not_appear_in_rasters": aggregator_ids,
            "nodata_value": 0,
        },
    }


def write_csv(codebook: dict, path: Path) -> None:
    fields = [
        "pixel_id",
        "code",
        "level1_code",
        "level1_pixel_id",
        "name_es",
        "name_en",
        "color",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(codebook["classes"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", required=True)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--qml", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        codebook = build(args.country, args.collection, args.pdf, args.qml)
    except CodebookError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    args.outdir.mkdir(parents=True, exist_ok=True)
    stem = f"{args.country}-collection-{args.collection}"
    json_path = args.outdir / f"{stem}.json"
    csv_path = args.outdir / f"{stem}.csv"

    json_path.write_text(
        json.dumps(codebook, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_csv(codebook, csv_path)

    classes = codebook["classes"]
    print(f"codebook: {len(codebook['level1'])} level-1 groups, {len(classes)} classes")
    print(f"  wrote {json_path}")
    print(f"  wrote {csv_path}")
    print(
        "  aggregator ids excluded from rasters: "
        f"{codebook['invariants']['aggregator_pixel_ids_must_not_appear_in_rasters']}"
    )

    discrepancies = codebook["cross_check"]["discrepancies"]
    print(f"  PDF vs QGIS discrepancies: {len(discrepancies)}")
    for item in discrepancies:
        print(
            f"    - id={item['pixel_id']} {item['field']}: "
            f"pdf={item['pdf']!r} qml={item['qml']!r}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
