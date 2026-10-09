#!/usr/bin/env python3
"""Build the human-reviewed CVE study catalog the viewer serves.

WHY THIS TOOL EXISTS
--------------------
The viewer needs the 31 human-reviewed abstracts of the Congreso Venezolano de
Ecologia editions, each tagged with whether the annual map can place it. The
service must NOT read Parquet: ``pyarrow`` is ~40 MB and the image is 108 MB
(project decision D10). So the raw Parquet is parsed once here and the service
later reads the small versioned JSON with the standard library.

This follows the project's established raster -> COG -> derived pattern: the raw
Parquet stays raw and unversioned, the derived CSV/JSON under ``data/derived/``
is versioned and ships.

REBUILD-ONLY DEPENDENCY
-----------------------
``pyarrow`` (to read Parquet) and ``osgeo``/GDAL (to read the COG geotransform)
are needed only to REBUILD the catalog. They are deliberately absent from the
service and the image, and must never be added to a requirements file. This tool
fails with an actionable message when either is missing.

The classification is computed here, at build time, so the service never
recomputes it and the exclusion reasons are reviewable in the derived artifact.

Usage:
    tools/build_study_catalog.py \\
        --parquet  data/raw/congresos/congresos_revisados.parquet \\
        --cog      data/cog/venezuela/collection-3/coverage-venezuela_classification_2024.tif \\
        --outdir   data/derived/venezuela/congresos \\
        --country  venezuela \\
        --labelling-json data/derived/venezuela/collection-3/tiles-manifest.json

The tool is strict on purpose: any missing column, non-labelable row or broken
labelling source aborts with a non-zero exit status and leaves NO partial
artifact behind.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover - exercised only on a bare interpreter
    sys.stderr.write(
        "error: pyarrow is required to REBUILD the study catalog. It is a "
        "rebuild-only dependency: install it in a build environment (for "
        "example `pip install 'pyarrow>=25'`), never in the viewer's "
        "requirements or the image. Nothing else in this project reads Parquet.\n"
    )
    raise SystemExit(1)

try:
    from osgeo import gdal
except ImportError:  # pragma: no cover - exercised only on a bare interpreter
    sys.stderr.write(
        "error: the GDAL Python bindings (osgeo) are required to REBUILD the "
        "study catalog, because the extent comes from the COG's own "
        "geotransform. They are a rebuild-only dependency: install GDAL in the "
        "build environment, never in the viewer's requirements or the image.\n"
    )
    raise SystemExit(1)

gdal.UseExceptions()


# Columns the source Parquet must carry. The first block is the contract's
# required set; the rest are the fields the catalog emits, so a missing one is
# still a hard error rather than a KeyError later.
REQUIRED_COLUMNS = [
    "source_path",
    "congreso",
    "anio",
    "ciudad",
    "pagina",
    "indice",
    "titulo",
    "resumen",
    "latitud",
    "longitud",
    "human_verified",
    "autores",
    "instituciones",
    "ubicaciongeografica",
    "ubicaciontemporal",
    "especiesmencionadas",
    "n_autores",
    "paises",
]

CLASS_ORDER = ["placeable", "shared_coordinate", "outside_extent", "no_coordinate"]

CLASS_LABELS = {
    "placeable": "Ubicable",
    "shared_coordinate": "Coordenada compartida",
    "outside_extent": "Fuera de la extensión",
    "no_coordinate": "Sin coordenada",
}

CLASS_REASONS = {
    "placeable": None,
    "shared_coordinate": (
        "Más de un estudio comparte exactamente la misma coordenada; el mapa no "
        "los dibuja para no afirmar una ubicación común que los datos no "
        "establecen."
    ),
    "outside_extent": (
        "La coordenada cae fuera del rectángulo de la extensión del COG; el mapa "
        "no puede dibujarla."
    ),
    "no_coordinate": "El estudio no trae latitud ni longitud.",
}

CSV_FIELDS = [
    "study_id",
    "anio",
    "congreso",
    "ciudad",
    "titulo",
    "autores",
    "n_autores",
    "paises",
    "instituciones",
    "ubicaciongeografica",
    "ubicaciontemporal",
    "especiesmencionadas",
    "latitud",
    "longitud",
    "display_class",
    "on_map",
    "exclusion_reason",
    "source_path",
    "pagina",
    "indice",
]


class StudyCatalogError(RuntimeError):
    """Raised when an input cannot be turned into a valid catalog."""


# --- inputs ------------------------------------------------------------------


def load_labelling(path: Path) -> tuple[str, str]:
    """Copy extent_label and extent_boundary_note verbatim from a manifest."""
    if not path.is_file():
        raise StudyCatalogError(f"--labelling-json not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StudyCatalogError(
            f"could not read --labelling-json {path}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise StudyCatalogError(
            f"--labelling-json {path} is not a JSON object"
        )
    missing = [
        key
        for key in ("extent_label", "extent_boundary_note")
        if key not in payload
    ]
    if missing:
        raise StudyCatalogError(
            f"--labelling-json {path} is missing required key(s): "
            f"{', '.join(missing)}"
        )
    return str(payload["extent_label"]), str(payload["extent_boundary_note"])


def cog_extent(path: Path) -> dict[str, float]:
    """Read the COG's real extent from its geotransform, never a constant."""
    if not path.is_file():
        raise StudyCatalogError(f"--cog not found: {path}")
    dataset = gdal.Open(str(path))
    if dataset is None:
        raise StudyCatalogError(f"GDAL could not open --cog: {path}")
    gt = dataset.GetGeoTransform()
    width = dataset.RasterXSize
    height = dataset.RasterYSize
    west = gt[0]
    north = gt[3]
    east = gt[0] + width * gt[1]
    south = gt[3] + height * gt[5]
    dataset = None
    return {
        "west": float(west),
        "south": float(south),
        "east": float(east),
        "north": float(north),
    }


def read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise StudyCatalogError(f"--parquet not found: {path}")
    try:
        table = pq.read_table(str(path))
    except Exception as exc:  # pyarrow raises its own hierarchy
        raise StudyCatalogError(f"could not read --parquet {path}: {exc}") from exc
    return table.to_pylist()


# --- validation ---------------------------------------------------------------


def row_name(row: dict[str, Any]) -> str:
    return (
        f"source_path={row.get('source_path')!r} "
        f"pagina={row.get('pagina')!r} indice={row.get('indice')!r}"
    )


def validate_rows(rows: list[dict[str, Any]]) -> None:
    """Fail loudly, naming the offending column or row, before anything is written."""
    if not rows:
        raise StudyCatalogError("the source Parquet has no rows")

    columns = set(rows[0].keys())
    missing = [c for c in REQUIRED_COLUMNS if c not in columns]
    if missing:
        raise StudyCatalogError(
            f"source Parquet is missing required column(s): {', '.join(missing)}"
        )

    for row in rows:
        where = row_name(row)

        if row["human_verified"] is not True:
            raise StudyCatalogError(
                f"row is not human-verified ({row['human_verified']!r}); the "
                f"catalog may only ship human-reviewed rows [{where}]"
            )

        lat = row["latitud"]
        lon = row["longitud"]
        if (lat is None) != (lon is None):
            raise StudyCatalogError(
                f"latitud/longitud must both be null or both present, got "
                f"latitud={lat!r}, longitud={lon!r} [{where}]"
            )
        if lat is not None and abs(lat) > 90:
            raise StudyCatalogError(
                f"latitud {lat!r} is outside the plausible range [-90, 90] [{where}]"
            )
        if lon is not None and abs(lon) > 180:
            raise StudyCatalogError(
                f"longitud {lon!r} is outside the plausible range [-180, 180] [{where}]"
            )

        _parse_json_list_column(row, "paises", where)
        _parse_autores(row, where)
        _parse_instituciones(row, where)


def _parse_json_list_column(
    row: dict[str, Any], column: str, where: str
) -> list[Any]:
    """Decode a JSON-array-encoded string column, failing loudly and naming the row."""
    value = row[column]
    if not isinstance(value, str):
        raise StudyCatalogError(
            f"{column} is not a JSON string (got {type(value).__name__}) [{where}]"
        )
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise StudyCatalogError(
            f"{column} does not parse as JSON ({value!r}): {exc} [{where}]"
        ) from exc
    if not isinstance(parsed, list):
        raise StudyCatalogError(
            f"{column} must decode to a JSON array, got {type(parsed).__name__} "
            f"[{where}]"
        )
    return parsed


AUTOR_FIELDS = ["nombre", "afiliacion", "ror", "pais", "orcid"]


def _parse_autores(row: dict[str, Any], where: str) -> list[dict[str, Any]]:
    """Decode ``autores`` into a list of objects, keeping the source fields in order."""
    entries = _parse_json_list_column(row, "autores", where)
    autores: list[dict[str, Any]] = []
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise StudyCatalogError(
                f"autores[{position}] is not a JSON object (got "
                f"{type(entry).__name__}); autores must decode to an array of "
                f"objects [{where}]"
            )
        missing = [field for field in AUTOR_FIELDS if field not in entry]
        if missing:
            raise StudyCatalogError(
                f"autores[{position}] is missing field(s) "
                f"{', '.join(missing)} [{where}]"
            )
        autores.append({field: entry[field] for field in AUTOR_FIELDS})
    return autores


def _parse_instituciones(row: dict[str, Any], where: str) -> list[str]:
    """Decode ``instituciones`` into a list of strings."""
    entries = _parse_json_list_column(row, "instituciones", where)
    for position, entry in enumerate(entries):
        if not isinstance(entry, str):
            raise StudyCatalogError(
                f"instituciones[{position}] is not a string (got "
                f"{type(entry).__name__}); instituciones must decode to an array "
                f"of strings [{where}]"
            )
    return entries


def check_n_autores(
    rows: list[dict[str, Any]],
) -> tuple[int, list[tuple[str, int, int]]]:
    """Compare len(autores) with the source's own ``n_autores`` column.

    Returns ``(matched, mismatches)`` where each mismatch is
    ``(where, n_autores, len(autores))``. The caller decides whether that is
    fatal; the check itself never tolerates or repairs a difference.
    """
    matched = 0
    mismatches: list[tuple[str, int, int]] = []
    for row in rows:
        where = row_name(row)
        autores = _parse_autores(row, where)
        declared = int(row["n_autores"])
        if len(autores) == declared:
            matched += 1
        else:
            mismatches.append((where, declared, len(autores)))
    return matched, mismatches


# --- identity -----------------------------------------------------------------


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def make_study_id(anio: int, source_path: str) -> str:
    """``cve-{anio}-{slug of the source_path stem}``, e.g. ``cve-1991-pagina-5-2``.

    The ``anio`` is part of the identity so the same stem in two editions cannot
    collide. ``slugify`` already drops ``<``, ``>``, ``_`` and ``.``, so the
    result matches ``^[a-z0-9-]+$``. No collision suffix is ever invented here:
    a duplicate is a hard error in ``build_catalog``.
    """
    stem = Path(source_path).stem
    stem_slug = slugify(stem)
    if not stem_slug:
        raise StudyCatalogError(
            f"source_path {source_path!r} has an empty slug; cannot build a study_id"
        )
    study_id = f"cve-{anio}-{stem_slug}"
    if not re.fullmatch(r"[a-z0-9-]+", study_id):
        raise StudyCatalogError(
            f"study_id {study_id!r} from source_path {source_path!r} does not "
            f"match ^[a-z0-9-]+$"
        )
    return study_id


# --- classification -----------------------------------------------------------


def classify(rows: list[dict[str, Any]], extent: dict[str, float]) -> dict[tuple, int]:
    """Return the multiplicity of every exact coordinate pair."""
    counts: Counter = Counter()
    for row in rows:
        lat = row["latitud"]
        lon = row["longitud"]
        if lat is not None and lon is not None:
            counts[(lat, lon)] += 1
    return dict(counts)


def display_class_for(
    row: dict[str, Any], extent: dict[str, float], coord_counts: dict[tuple, int]
) -> str:
    lat = row["latitud"]
    lon = row["longitud"]
    if lat is None or lon is None:
        return "no_coordinate"
    inside = (
        extent["west"] <= lon <= extent["east"]
        and extent["south"] <= lat <= extent["north"]
    )
    if not inside:
        return "outside_extent"
    if coord_counts.get((lat, lon), 0) > 1:
        return "shared_coordinate"
    return "placeable"


def exclusion_reason_for(
    row: dict[str, Any],
    display_class: str,
    extent: dict[str, float],
    coord_counts: dict[tuple, int],
) -> str | None:
    if display_class == "placeable":
        return None
    lat = row["latitud"]
    lon = row["longitud"]
    if display_class == "no_coordinate":
        return (
            "El estudio no tiene latitud ni longitud, así que no se puede "
            "situar en el mapa."
        )
    if display_class == "outside_extent":
        return (
            f"La latitud {lat!r} supera el límite norte de la extensión mapeada "
            f"({extent['north']!r}); el punto ({lat!r}, {lon!r}) queda fuera del "
            f"área del mapa."
        )
    n = coord_counts[(lat, lon)]
    return (
        f"{n} estudios comparten exactamente la misma coordenada "
        f"({lat!r}, {lon!r}); el mapa no los dibuja para no afirmar una "
        f"ubicación común que los datos no establecen."
    )


# --- build --------------------------------------------------------------------


def build_study(
    row: dict[str, Any],
    extent: dict[str, float],
    coord_counts: dict[tuple, int],
) -> dict[str, Any]:
    study_id = make_study_id(int(row["anio"]), row["source_path"])
    display_class = display_class_for(row, extent, coord_counts)
    on_map = display_class == "placeable"
    return {
        "study_id": study_id,
        "titulo": row["titulo"],
        "resumen": row["resumen"],
        "autores": _parse_autores(row, row_name(row)),
        "instituciones": _parse_instituciones(row, row_name(row)),
        "ubicaciongeografica": row["ubicaciongeografica"],
        "ubicaciontemporal": row["ubicaciontemporal"],
        "especiesmencionadas": row["especiesmencionadas"],
        "source_path": row["source_path"],
        "anio": int(row["anio"]),
        "congreso": row["congreso"],
        "ciudad": row["ciudad"],
        "pagina": int(row["pagina"]),
        "indice": int(row["indice"]),
        "n_autores": int(row["n_autores"]),
        "paises": _parse_json_list_column(row, "paises", row_name(row)),
        "latitud": row["latitud"],
        "longitud": row["longitud"],
        "display_class": display_class,
        "on_map": on_map,
        "exclusion_reason": exclusion_reason_for(
            row, display_class, extent, coord_counts
        ),
    }


def build_catalog(
    rows: list[dict[str, Any]],
    extent: dict[str, float],
    country: str,
    source_parquet: str,
    extent_label: str,
    extent_boundary_note: str,
) -> tuple[dict[str, Any], dict[str, int]]:
    coord_counts = classify(rows, extent)
    studies = [build_study(row, extent, coord_counts) for row in rows]
    studies.sort(key=lambda s: (s["anio"], s["congreso"], s["pagina"], s["indice"]))

    seen: set[str] = set()
    for study in studies:
        if study["study_id"] in seen:
            raise StudyCatalogError(
                f"duplicate study_id {study['study_id']!r}; identifiers must be "
                f"unique (source_path={study['source_path']!r})"
            )
        seen.add(study["study_id"])

    counts = {key: 0 for key in CLASS_ORDER}
    for study in studies:
        counts[study["display_class"]] += 1

    placeable = counts["placeable"]
    classes = []
    for key in CLASS_ORDER:
        classes.append(
            {
                "key": key,
                "count": counts[key],
                "on_map": key == "placeable",
                "label_es": CLASS_LABELS[key],
                "reason": CLASS_REASONS[key],
            }
        )

    catalog = {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "country": country,
        "source_parquet": source_parquet,
        "extent_label": extent_label,
        "extent_boundary_note": extent_boundary_note,
        "extent": extent,
        "study_count": len(studies),
        "display_contract": {
            "map_visible_count": placeable,
            "excluded_count": len(studies) - placeable,
        },
        "classes": classes,
        "studies": studies,
    }
    return catalog, counts


# --- output -------------------------------------------------------------------


def _csv_value(field: str, value: Any) -> Any:
    """Render one catalog value for the CSV.

    ``autores`` is a list of objects, so the CSV gets the author ``nombre``
    values joined with ``"; "``; other lists (``instituciones``, ``paises``)
    are already lists of strings. ``especiesmencionadas`` stays verbatim
    because it is free text, not a list.
    """
    if field == "autores":
        return "; ".join(str(author["nombre"]) for author in value)
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    return value


def write_outputs(catalog: dict[str, Any], outdir: Path) -> tuple[Path, Path]:
    """Write both artifacts atomically; never leave a partial file behind."""
    outdir.mkdir(parents=True, exist_ok=True)
    json_path = outdir / "catalogo-estudios.json"
    csv_path = outdir / "catalogo-estudios.csv"

    json_text = json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"

    json_tmp = csv_tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="",
            dir=outdir, prefix=".catalogo-", suffix=".json.tmp", delete=False,
        ) as handle:
            handle.write(json_text)
            json_tmp = Path(handle.name)

        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="",
            dir=outdir, prefix=".catalogo-", suffix=".csv.tmp", delete=False,
        ) as handle:
            writer = csv.DictWriter(
                handle, fieldnames=CSV_FIELDS, lineterminator="\n"
            )
            writer.writeheader()
            for study in catalog["studies"]:
                writer.writerow(
                    {key: _csv_value(key, study[key]) for key in CSV_FIELDS}
                )
            csv_tmp = Path(handle.name)

        os.replace(json_tmp, json_path)
        os.replace(csv_tmp, csv_path)
    except BaseException:
        for leftover in (json_tmp, csv_tmp):
            if leftover is not None and leftover.exists():
                leftover.unlink()
        raise

    return json_path, csv_path


# --- main ---------------------------------------------------------------------


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--parquet", type=Path, required=True,
                        help="raw source Parquet (unversioned, rebuild-only)")
    parser.add_argument("--cog", type=Path, required=True,
                        help="a COG whose geotransform defines the extent")
    parser.add_argument("--outdir", type=Path, required=True,
                        help="output directory for catalogo-estudios.json/.csv")
    parser.add_argument("--country", required=True,
                        help="country id recorded in the catalog")
    parser.add_argument(
        "--labelling-json",
        type=Path,
        default=Path("data/derived/venezuela/collection-3/tiles-manifest.json"),
        help="manifest to copy extent_label / extent_boundary_note from "
             "(default: data/derived/venezuela/collection-3/tiles-manifest.json)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        extent_label, extent_boundary_note = load_labelling(args.labelling_json)
        extent = cog_extent(args.cog)
        rows = read_rows(args.parquet)
        validate_rows(rows)
        matched, mismatches = check_n_autores(rows)
        if mismatches:
            detail = "; ".join(
                f"n_autores={declared} but len(autores)={actual} [{where}]"
                for where, declared, actual in mismatches
            )
            raise StudyCatalogError(
                f"len(autores) does not match the source n_autores column in "
                f"{len(mismatches)} of {len(rows)} rows; refusing to ship an "
                f"internally inconsistent catalog: {detail}"
            )
        catalog, counts = build_catalog(
            rows,
            extent,
            args.country,
            str(args.parquet),
            extent_label,
            extent_boundary_note,
        )
        json_path, csv_path = write_outputs(catalog, args.outdir)
    except StudyCatalogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"computed extent from {args.cog}:")
    print(
        f"  west={extent['west']!r} south={extent['south']!r} "
        f"east={extent['east']!r} north={extent['north']!r}"
    )
    print(
        f"studies: {catalog['study_count']} "
        f"(map_visible={catalog['display_contract']['map_visible_count']}, "
        f"excluded={catalog['display_contract']['excluded_count']})"
    )
    print(
        f"n_autores consistency: {matched}/{len(rows)} rows matched, "
        f"{len(mismatches)} mismatched"
    )
    for key in CLASS_ORDER:
        print(f"  {key}: {counts[key]}")
    print(f"  wrote {json_path}")
    print(f"  wrote {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
