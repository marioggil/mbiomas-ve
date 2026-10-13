#!/usr/bin/env python3
"""Build the human-reviewed CVE study catalog the viewer serves.

WHY THIS TOOL EXISTS
--------------------
The viewer needs the 202 human-reviewed abstracts of the Congreso Venezolano de
Ecologia, across twelve editions, each tagged with whether the map can place it.
The service must NOT read Parquet: ``pyarrow`` is ~40 MB and the image is 108 MB
(project decision D10). So the raw Parquet is parsed once here and the service
later reads the small versioned JSON with the standard library.

This follows the project's established raster -> COG -> derived pattern: the raw
Parquet stays raw and unversioned, the derived CSV/JSON under ``data/derived/``
is versioned and ships.

PROVENANCE
----------
An unversioned input can change under a derived artifact without anything
noticing, so the JSON records the identity of the file it was built from
next to its path: ``source_sha256``, ``source_rows`` and ``source_bytes``.
The digest is computed from the exact bytes that were parsed, in a single
read, so the artifact cannot describe a different revision of the file than
the one it was built from. The CSV stays a flat per-study table: provenance
is document-level and lives only in the JSON.

IDENTITY
--------
Every study gets a ``study_id`` of the shape ``cve-{anio}-{slug of the
source_path stem}``, e.g. ``cve-1991-pagina-5-2``. A null ``anio`` (the legacy
Vol XI rows carry none) uses the literal year segment ``sin-anio``, giving
``cve-sin-anio-pagina-607-1``. The volume does not enter the id: ``congreso``
already carries it and ``build_catalog`` hard-fails on a duplicate. The artifact
sorts dated studies by ``(anio, congreso, pagina, indice)`` and undated studies
last by ``(congreso, pagina, indice)``, so the order is total and deterministic.

CURATED TAXONOMY
----------------
Coarseness, not collision of coordinates, decides what the map may draw. The
per-study level comes from ``data/curated/congresos/granularidad-ubicaciones.json``,
one entry per ``source_path``: T0 (country, supra-national region, or an
enumeration of separate places) and T1 (first-level administrative unit, or a
state-scale natural region without a locality) are not placeable; T2 (locality,
named site, park or watershed) is. ``load_granularity`` reads that file and
``check_granularity_coverage`` closes it against the rows. Each entry also
records the corpus location ``texto``, and ``check_granularity_coverage``
verifies that recorded text against ``row_location_text(row)`` so an upstream
re-extraction that changes a location text stops the build until a human
re-judges the level. The file is hand-edited and shipped complete, so the
loader fails loudly on a missing or unreadable file, malformed JSON, a
duplicate key anywhere in the document, an unknown level, a missing or
non-string ``texto``, or a T0/T1 entry without a ``razon``.

CLASSIFICATION
--------------
The display class is decided here, at build time, first match wins:

1. a null ``latitud`` or ``longitud`` -> ``no_coordinate``;
2. the curated level is T0 or T1 -> ``coarse_location``;
3. the coordinate falls outside the COG extent -> ``outside_extent``;
4. otherwise -> ``placeable``.

Only ``placeable`` sets ``on_map``. Collision of coordinates stopped being a
class: ``coordinate_group_size`` (how many studies sit at the exact same
``(latitud, longitud)`` pair, ``null`` without a coordinate) and
``coordinate_group_ids`` (the *other* study_ids there, sorted ascending, empty
when alone) expose it as a per-study attribute computed from the coordinates
alone and independently of the class, so a group may mix levels (the Barinas
group mixes T1 and T2). Every study also carries ``granularidad_nivel``
(``T0``/``T1``/``T2``), ``granularidad_razon`` (the curated justification,
``null`` when the entry has none) and ``palabrasclaves`` (the parquet list
column, so the panel can search it without a second artifact). Every
non-placeable study carries an ``exclusion_reason`` in Spanish: the
``coarse_location`` one names the level, quotes the corpus location text,
repeats the curated ``razon`` and glosses what the level means, and never
quotes the review-only ``nota``.

REBUILD-ONLY DEPENDENCY
-----------------------
``pyarrow`` (to read Parquet) and ``osgeo``/GDAL (to read the COG geotransform)
are needed only to REBUILD the catalog. They are deliberately absent from the
service and the image, and must never be added to a requirements file. This tool
fails with an actionable message when either is missing.

Both imports are lazy, inside the function that needs them. A library module
must never call ``sys.exit`` on import: ``slugify``, ``display_class_for`` and the
rest of the pure logic stay importable and testable on an interpreter with neither
dependency, and the CLI still fails with the same stderr line and exit status 1
because ``main`` reports the ``StudyCatalogError`` itself.

The classification is computed here, at build time, so the service never
recomputes it and the exclusion reasons are reviewable in the derived artifact.

Usage:
    tools/build_study_catalog.py \\
        --parquet      data/raw/congresos/congresos_revisados.parquet \\
        --granularidad data/curated/congresos/granularidad-ubicaciones.json \\
        --cog          data/cog/venezuela/collection-3/coverage-venezuela_classification_2024.tif \\
        --outdir       data/derived/venezuela/congresos \\
        --country      venezuela \\
        --labelling-json data/derived/venezuela/collection-3/tiles-manifest.json

The tool is strict on purpose: any missing column, non-labelable row or broken
labelling source aborts with a non-zero exit status and leaves NO partial
artifact behind.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# The two rebuild-only dependencies are imported inside the functions that use
# them (see the module docstring). The wording below is the message the CLI has
# always printed; only the delivery changed from an import-time exit to a
# StudyCatalogError that ``main`` prints and turns into exit status 1.
PYARROW_MISSING = (
    "pyarrow is required to REBUILD the study catalog. It is a "
    "rebuild-only dependency: install it in a build environment (for "
    "example `pip install 'pyarrow>=25'`), never in the viewer's "
    "requirements or the image. Nothing else in this project reads Parquet."
)

GDAL_MISSING = (
    "the GDAL Python bindings (osgeo) are required to REBUILD the "
    "study catalog, because the extent comes from the COG's own "
    "geotransform. They are a rebuild-only dependency: install GDAL in the "
    "build environment, never in the viewer's requirements or the image."
)


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
    "palabrasclaves",
    "n_autores",
    "paises",
]

# The schema version anchor, following the project's convention (the
# composition summary is anchored the same way). Bumped when the display
# contract changes in a way a reader must not mistake for the previous one.
# Version 3 adds the two builder-produced collision tallies the map note
# renders (``collision_coordinate_count`` / ``collision_marker_count``); a
# version 2 artifact carries no number for the ring, so the viewer refuses it.
SCHEMA_VERSION = 3

# The identity of the derived document: the taxonomy replaced the collision
# class, so ``coarse_location`` sits where ``shared_coordinate`` used to.
CLASS_ORDER = ["placeable", "coarse_location", "outside_extent", "no_coordinate"]

# The curated location-granularity levels. T0 and T1 are excluded from the map;
# the file repeats that exclusion list and ``load_granularity`` cross-checks it,
# so the taxonomy and the code cannot drift apart silently.
GRANULARITY_LEVELS = ("T0", "T1", "T2")
GRANULARITY_EXCLUDED_FROM_MAP = ["T0", "T1"]

# What each level means, in the words the exclusion reason uses. The curated
# file states the same definitions in its own ``levels`` block; this is the
# code-side gloss the per-study reason can quote without reading that block
# again.
GRANULARITY_LEVEL_GLOSSES = {
    "T0": (
        "mención que no identifica un lugar: el país, una región supra-nacional, "
        "una región natural amplia de varios estados, o una enumeración de "
        "lugares distintos"
    ),
    "T1": (
        "unidad administrativa sin localidad nombrada dentro, o accidente o "
        "región de escala estadal o regional sin localidad"
    ),
    "T2": (
        "localidad, sitio, parque, cuenca, isla o cuerpo de agua con nombre propio"
    ),
}

CLASS_LABELS = {
    "placeable": "Ubicable",
    "coarse_location": "Ubicación de grano grueso",
    "outside_extent": "Fuera de la extensión",
    "no_coordinate": "Sin coordenada",
}

CLASS_REASONS = {
    "placeable": None,
    "coarse_location": (
        "La mención de ubicación no identifica un lugar concreto: la taxonomía "
        "curada la clasifica en un nivel de grano grueso (T0 o T1). El mapa no "
        "la dibuja; el motivo detallado de cada estudio está en su "
        "exclusion_reason."
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
    "palabrasclaves",
    "latitud",
    "longitud",
    "display_class",
    "granularidad_nivel",
    "coordinate_group_size",
    "coordinate_group_ids",
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


def load_granularity(path: Path) -> dict[str, dict[str, Any]]:
    """Load the curated location-granularity taxonomy.

    Returns ``source_path -> {"nivel", "texto", "razon", "nota"}``, with
    ``razon`` and ``nota`` normalised to ``None`` when absent. ``texto`` is the
    location text as it appears in the corpus: it is required, must be a string
    (an empty string is valid, for rows with no usable location text), and
    ``check_granularity_coverage`` later verifies it against the row. Every
    failure names the offending key or the file: this is a hand-edited document,
    so a duplicated key (which ``json`` would otherwise resolve by keeping the
    last value), an unknown level or a T0/T1 entry without a justification would
    reach the map unless it is rejected here.
    """
    if not path.is_file():
        raise StudyCatalogError(f"granularity file not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise StudyCatalogError(
            f"could not read granularity file {path}: {exc}"
        ) from exc

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        # ``object_pairs_hook`` runs for every object in the document, so a
        # repeated key anywhere is caught before the last value silently wins.
        seen: set[str] = set()
        for key, _ in pairs:
            if key in seen:
                raise StudyCatalogError(
                    f"granularity file {path} has a duplicate key {key!r}; a "
                    f"repeated entry would silently overwrite the first"
                )
            seen.add(key)
        return dict(pairs)

    try:
        payload = json.loads(text, object_pairs_hook=reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise StudyCatalogError(
            f"granularity file {path} is not valid JSON: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise StudyCatalogError(
            f"granularity file {path} must be a JSON object, got "
            f"{type(payload).__name__}"
        )
    if "entries" not in payload:
        raise StudyCatalogError(f"granularity file {path} is missing 'entries'")
    entries = payload["entries"]
    if not isinstance(entries, dict):
        raise StudyCatalogError(
            f"granularity file {path} 'entries' must be a JSON object, got "
            f"{type(entries).__name__}"
        )
    if not entries:
        raise StudyCatalogError(
            f"granularity file {path} has an empty 'entries' object; a taxonomy "
            f"that classifies nothing cannot cover the corpus"
        )
    excluded = payload.get("levels_excluded_from_map")
    if excluded != GRANULARITY_EXCLUDED_FROM_MAP:
        raise StudyCatalogError(
            f"granularity file {path} must declare levels_excluded_from_map as "
            f"exactly {GRANULARITY_EXCLUDED_FROM_MAP!r}, got {excluded!r}"
        )

    granularity: dict[str, dict[str, Any]] = {}
    for source_path, entry in entries.items():
        where = f"granularity entry {source_path!r}"
        if not isinstance(entry, dict):
            raise StudyCatalogError(
                f"{where} must be a JSON object, got {type(entry).__name__}"
            )
        if "nivel" not in entry:
            raise StudyCatalogError(f"{where} is missing 'nivel'")
        nivel = entry["nivel"]
        if nivel not in GRANULARITY_LEVELS:
            raise StudyCatalogError(
                f"{where} has nivel {nivel!r}; expected one of "
                f"{', '.join(GRANULARITY_LEVELS)}"
            )
        if "texto" not in entry:
            raise StudyCatalogError(
                f"{where} is missing 'texto'; every entry records the corpus "
                f"location text it classifies"
            )
        texto = entry["texto"]
        if not isinstance(texto, str):
            raise StudyCatalogError(
                f"{where} has a 'texto' that is not a string: {texto!r}"
            )
        for field in ("razon", "nota"):
            if field in entry:
                value = entry[field]
                if not isinstance(value, str) or not value.strip():
                    raise StudyCatalogError(
                        f"{where} has a {field!r} that is not a non-empty "
                        f"string: {value!r}"
                    )
        if nivel in ("T0", "T1") and "razon" not in entry:
            raise StudyCatalogError(
                f"{where} is level {nivel} and must carry a 'razon'"
            )
        granularity[source_path] = {
            "nivel": nivel,
            "texto": texto,
            "razon": entry.get("razon"),
            "nota": entry.get("nota"),
        }
    return granularity


def row_location_text(row: dict[str, Any]) -> str:
    """Return the location text the corpus carries for one row.

    It prefers ``ubicaciongeografica`` and falls back to ``direccion``, then to
    the empty string, always stripped. This is the single derivation of the
    corpus side of the taxonomy's recorded ``texto``, so the loader and the
    coverage check cannot drift apart.
    """
    return (row.get("ubicaciongeografica") or row.get("direccion") or "").strip()


def check_granularity_coverage(
    granularity: dict[str, dict[str, Any]], rows: list[dict[str, Any]]
) -> None:
    """Fail unless the taxonomy and the rows cover each other exactly once.

    Both directions are checked: a row with no entry would be classified by
    accident, and an entry with no row is a taxonomy that has drifted away from
    the corpus it describes. The recorded ``texto`` is then checked against
    :func:`row_location_text` of its row, so a re-extraction that corrects a
    location text stops the build instead of shipping a stale judgement.
    ``rows`` is a parameter so the check stays dependency-free and testable
    without the Parquet.
    """
    row_paths = {row["source_path"] for row in rows}
    missing = sorted(path for path in row_paths if path not in granularity)
    if missing:
        raise StudyCatalogError(
            "granularity file has no entry for parquet source_path(s): "
            + ", ".join(repr(path) for path in missing)
        )
    orphans = sorted(key for key in granularity if key not in row_paths)
    if orphans:
        raise StudyCatalogError(
            "granularity entry matches no parquet row: "
            + ", ".join(repr(key) for key in orphans)
        )
    rows_by_path = {row["source_path"]: row for row in rows}
    mismatched = [
        (source_path, entry["texto"], row_location_text(rows_by_path[source_path]))
        for source_path, entry in sorted(granularity.items())
        if entry["texto"] != row_location_text(rows_by_path[source_path])
    ]
    if mismatched:
        detail = "; ".join(
            f"{source_path!r} records {recorded!r} but the row has {actual!r}"
            for source_path, recorded, actual in mismatched
        )
        raise StudyCatalogError(
            "granularity entry location text no longer matches the parquet row "
            "it classifies; re-judge the level before shipping: " + detail
        )


def cog_extent(path: Path) -> dict[str, float]:
    """Read the COG's real extent from its geotransform, never a constant."""
    # Lazy so importing this module does not require GDAL. Checked before the
    # path, exactly as the old module-level import was.
    try:
        from osgeo import gdal
    except ImportError as exc:  # pragma: no cover - bare interpreter only
        raise StudyCatalogError(GDAL_MISSING) from exc
    gdal.UseExceptions()
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


def read_rows(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Read the Parquet once and return its rows plus the input's identity.

    The bytes are read into memory first, hashed, and parsed from that same
    buffer. There is deliberately no second read of ``path``: a digest computed
    from a separate read could describe a different revision of the file than
    the one that was parsed.
    """
    # Lazy so importing this module does not require pyarrow. Checked before the
    # path, exactly as the old module-level import was.
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - bare interpreter only
        raise StudyCatalogError(PYARROW_MISSING) from exc
    if not path.is_file():
        raise StudyCatalogError(f"--parquet not found: {path}")
    try:
        data = path.read_bytes()
        table = pq.read_table(io.BytesIO(data))
    except Exception as exc:  # pyarrow raises its own hierarchy
        raise StudyCatalogError(f"could not read --parquet {path}: {exc}") from exc
    source_identity = {
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_rows": int(table.num_rows),
        "source_bytes": len(data),
    }
    return table.to_pylist(), source_identity


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
        _parse_palabrasclaves(row, where)


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


def _parse_palabrasclaves(row: dict[str, Any], where: str) -> list[str]:
    """Return the parquet ``palabrasclaves`` list column as a list of strings.

    This is a real PyArrow ``list<string>`` column, not a JSON-encoded string,
    so there is nothing to decode. An empty list is valid (the corpus has rows
    without keywords); anything that is not a list of strings aborts the build
    and names the offending row, exactly as the other column parsers do.
    """
    value = row["palabrasclaves"]
    if not isinstance(value, list) or any(
        not isinstance(keyword, str) for keyword in value
    ):
        raise StudyCatalogError(
            f"palabrasclaves must be a list of strings (got {value!r}); the "
            f"keyword column cannot be repaired here [{where}]"
        )
    return list(value)


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


def make_study_id(anio: int | None, source_path: str) -> str:
    """``cve-{anio}-{slug of the source_path stem}``, e.g. ``cve-1991-pagina-5-2``.

    The ``anio`` is part of the identity so the same stem in two editions cannot
    collide. A null ``anio`` (the legacy Vol XI rows have none) uses the literal
    year segment ``sin-anio``, giving ``cve-sin-anio-pagina-607-1``: the volume
    does not enter the id because ``congreso`` already carries it, and
    ``build_catalog`` hard-fails on a duplicate, so ambiguity cannot pass
    silently. ``slugify`` already drops ``<``, ``>``, ``_`` and ``.``, so the
    result matches ``^[a-z0-9-]+$``. No collision suffix is ever invented here:
    a duplicate is a hard error in ``build_catalog``.
    """
    stem = Path(source_path).stem
    stem_slug = slugify(stem)
    if not stem_slug:
        raise StudyCatalogError(
            f"source_path {source_path!r} has an empty slug; cannot build a study_id"
        )
    year_segment = "sin-anio" if anio is None else str(anio)
    study_id = f"cve-{year_segment}-{stem_slug}"
    if not re.fullmatch(r"[a-z0-9-]+", study_id):
        raise StudyCatalogError(
            f"study_id {study_id!r} from source_path {source_path!r} does not "
            f"match ^[a-z0-9-]+$"
        )
    return study_id


# --- classification -----------------------------------------------------------


def study_id_for(row: dict[str, Any]) -> str:
    """Return the ``study_id`` for one row.

    ``build_catalog`` needs every id *before* it can build a study, because the
    collision attributes relate ids to each other. ``build_study`` uses this same
    function, so the id the group holds and the id the study carries cannot
    drift apart.
    """
    anio = None if row["anio"] is None else int(row["anio"])
    return make_study_id(anio, row["source_path"])


def coordinate_groups(
    rows: list[dict[str, Any]], study_ids: list[str]
) -> dict[tuple, list[str]]:
    """Map every exact ``(latitud, longitud)`` pair to the ids sitting on it.

    ``study_ids`` is parallel to ``rows``. Rows without a coordinate are not a
    group: a null pair is the absence of a location, not a location. The ids of
    every group come back sorted ascending, so the artifact is deterministic and
    a consumer can compare two builds byte for byte.
    """
    if len(rows) != len(study_ids):
        raise StudyCatalogError(
            f"coordinate_groups needs one study_id per row, got {len(study_ids)} "
            f"ids for {len(rows)} rows"
        )
    groups: dict[tuple, list[str]] = {}
    for row, study_id in zip(rows, study_ids):
        lat = row["latitud"]
        lon = row["longitud"]
        if lat is None or lon is None:
            continue
        groups.setdefault((lat, lon), []).append(study_id)
    return {pair: sorted(ids) for pair, ids in groups.items()}


def granularity_entry_for(
    row: dict[str, Any], granularity: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Return the curated entry for one row, naming the row when it is missing.

    ``check_granularity_coverage`` closes the whole taxonomy against the whole
    row set in ``main``; this is the in-build guard, so ``build_catalog`` cannot
    classify a row by accident when it is called directly with a partial map.
    """
    source_path = row["source_path"]
    entry = granularity.get(source_path)
    if entry is None:
        raise StudyCatalogError(
            f"granularity file has no entry for {row_name(row)}; the curated "
            f"taxonomy must cover every row before the catalog is built"
        )
    return entry


def display_class_for(
    row: dict[str, Any],
    extent: dict[str, float],
    granularity_entry: dict[str, Any],
) -> str:
    """Classify one row, first match wins (see the module's CLASSIFICATION)."""
    lat = row["latitud"]
    lon = row["longitud"]
    if lat is None or lon is None:
        return "no_coordinate"
    if granularity_entry["nivel"] in GRANULARITY_EXCLUDED_FROM_MAP:
        return "coarse_location"
    inside = (
        extent["west"] <= lon <= extent["east"]
        and extent["south"] <= lat <= extent["north"]
    )
    if not inside:
        return "outside_extent"
    return "placeable"


def exclusion_reason_for(
    row: dict[str, Any],
    display_class: str,
    extent: dict[str, float],
    granularity_entry: dict[str, Any],
) -> str | None:
    """Build the Spanish reason a non-placeable study carries.

    The ``coarse_location`` reason is produced here, never by the frontend: it
    names the curated level, quotes the corpus location text verbatim, repeats
    the curated ``razon`` and glosses what that level means. It deliberately
    does not quote the entry's ``nota``, which records how a boundary call was
    argued and is review material, not a user-facing explanation.
    """
    if display_class == "placeable":
        return None
    lat = row["latitud"]
    lon = row["longitud"]
    if display_class == "no_coordinate":
        return (
            "El estudio no tiene latitud ni longitud, así que no se puede "
            "situar en el mapa."
        )
    if display_class == "coarse_location":
        nivel = granularity_entry["nivel"]
        texto = row_location_text(row)
        razon = granularity_entry["razon"]
        return (
            f"La ubicación {texto!r} no identifica un lugar concreto: la "
            f"taxonomía curada de granularidad la clasifica en el nivel {nivel} "
            f"({GRANULARITY_LEVEL_GLOSSES[nivel]}) porque {razon}. Un nivel "
            f"{nivel} no se puede dibujar como un punto del mapa."
        )
    return (
        f"La latitud {lat!r} supera el límite norte de la extensión mapeada "
        f"({extent['north']!r}); el punto ({lat!r}, {lon!r}) queda fuera del "
        f"área del mapa."
    )


# --- build --------------------------------------------------------------------


def build_study(
    row: dict[str, Any],
    extent: dict[str, float],
    granularity_entry: dict[str, Any],
    coordinate_group: list[str] | None,
) -> dict[str, Any]:
    """Assemble one study.

    ``coordinate_group`` is the sorted list of ids at the row's exact
    coordinate, including this study, or ``None`` when the row has no
    coordinate. The collision attributes are derived from it and are independent
    of the display class: a group may hold studies the map draws and studies it
    does not, and the Barinas group genuinely mixes T1 and T2.
    """
    study_id = study_id_for(row)
    display_class = display_class_for(row, extent, granularity_entry)
    if row["latitud"] is None or row["longitud"] is None:
        coordinate_group_size: int | None = None
        coordinate_group_ids: list[str] = []
    elif coordinate_group is None:
        raise StudyCatalogError(
            f"no coordinate group was computed for {row_name(row)}; the collision "
            f"attributes need the id map built before the studies"
        )
    else:
        coordinate_group_size = len(coordinate_group)
        coordinate_group_ids = sorted(
            other for other in coordinate_group if other != study_id
        )
    return {
        "study_id": study_id,
        "titulo": row["titulo"],
        "resumen": row["resumen"],
        "autores": _parse_autores(row, row_name(row)),
        "instituciones": _parse_instituciones(row, row_name(row)),
        "ubicaciongeografica": row["ubicaciongeografica"],
        "ubicaciontemporal": row["ubicaciontemporal"],
        "especiesmencionadas": row["especiesmencionadas"],
        "palabrasclaves": _parse_palabrasclaves(row, row_name(row)),
        "source_path": row["source_path"],
        "anio": None if row["anio"] is None else int(row["anio"]),
        "congreso": row["congreso"],
        "ciudad": row["ciudad"],
        "pagina": int(row["pagina"]),
        "indice": int(row["indice"]),
        "n_autores": int(row["n_autores"]),
        "paises": _parse_json_list_column(row, "paises", row_name(row)),
        "latitud": row["latitud"],
        "longitud": row["longitud"],
        "display_class": display_class,
        "on_map": display_class == "placeable",
        "granularidad_nivel": granularity_entry["nivel"],
        "granularidad_razon": granularity_entry["razon"],
        "exclusion_reason": exclusion_reason_for(
            row, display_class, extent, granularity_entry
        ),
        "coordinate_group_size": coordinate_group_size,
        "coordinate_group_ids": coordinate_group_ids,
    }


def study_sort_key(study: dict[str, Any]) -> tuple[Any, ...]:
    """Total order for the artifact's studies.

    Dated studies keep exactly the order ``(anio, congreso, pagina, indice)``
    produced. Undated studies sort last, ordered among themselves by
    ``(congreso, pagina, indice)``. The leading flag separates the two groups
    and the literal ``0`` fills the year slot of the undated group, so no key
    ever compares ``None`` with an ``int`` and the order stays deterministic.
    """
    if study["anio"] is None:
        return (1, 0, study["congreso"], study["pagina"], study["indice"])
    return (0, study["anio"], study["congreso"], study["pagina"], study["indice"])


def collision_display_counts(studies: list[dict[str, Any]]) -> tuple[int, int]:
    """Count the collisions the map actually draws.

    Returns ``(collision_coordinate_count, collision_marker_count)``: the
    distinct ``(latitud, longitud)`` pairs carrying **two or more** placeable
    studies, and the number of placeable studies sitting on those pairs.

    Only ``placeable`` studies reach the map, so only they can collide there.
    The grouping is by exact coordinate, the same equality the viewer's halo
    derivation uses, and this is deliberately NOT the catalog-wide
    ``coordinate_group_size``: that attribute counts every study at a
    coordinate regardless of display class, so a coordinate where one coarse
    study shares a marker's spot would inflate the number the ring asserts
    (Barinas: group size 4, two markers drawn).
    """
    drawn_by_coordinate: dict[tuple, int] = {}
    for study in studies:
        if study["display_class"] != "placeable":
            continue
        key = (study["latitud"], study["longitud"])
        drawn_by_coordinate[key] = drawn_by_coordinate.get(key, 0) + 1
    collision_sizes = [
        size for size in drawn_by_coordinate.values() if size > 1
    ]
    return len(collision_sizes), sum(collision_sizes)


def build_catalog(
    rows: list[dict[str, Any]],
    extent: dict[str, float],
    granularity: dict[str, dict[str, Any]],
    country: str,
    source_parquet: str,
    extent_label: str,
    extent_boundary_note: str,
    source_identity: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, int]]:
    """Assemble the catalog document.

    ``granularity`` is the curated taxonomy, keyed by ``source_path``.
    ``source_identity`` comes from :func:`read_rows` and carries the three
    provenance fields. It is written immediately after ``source_parquet`` so the
    document reads as one provenance block.

    The ids are computed first, in one pass parallel to ``rows``, because the
    collision attributes relate ids to each other: ``coordinate_group_size`` and
    ``coordinate_group_ids`` need the whole id map before any study is built.
    """
    study_ids = [study_id_for(row) for row in rows]
    groups = coordinate_groups(rows, study_ids)
    studies = []
    for row in rows:
        entry = granularity_entry_for(row, granularity)
        group = groups.get((row["latitud"], row["longitud"]))
        studies.append(build_study(row, extent, entry, group))
    studies.sort(key=study_sort_key)

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
    collision_coordinates, collision_markers = collision_display_counts(studies)
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
        "schema_version": SCHEMA_VERSION,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "country": country,
        "source_parquet": source_parquet,
        "source_sha256": source_identity["source_sha256"],
        "source_rows": source_identity["source_rows"],
        "source_bytes": source_identity["source_bytes"],
        "extent_label": extent_label,
        "extent_boundary_note": extent_boundary_note,
        "extent": extent,
        "study_count": len(studies),
        "display_contract": {
            "map_visible_count": placeable,
            "excluded_count": len(studies) - placeable,
            "collision_coordinate_count": collision_coordinates,
            "collision_marker_count": collision_markers,
        },
        "classes": classes,
        "studies": studies,
    }
    return catalog, counts


# --- output -------------------------------------------------------------------


def _csv_value(field: str, value: Any) -> Any:
    """Render one catalog value for the CSV.

    ``autores`` is a list of objects, so the CSV gets the author ``nombre``
    values joined with ``"; "``; the other list columns (``instituciones``,
    ``paises``, ``palabrasclaves``, ``coordinate_group_ids``) are already lists
    of strings and get the same treatment, so a spreadsheet stays readable.
    ``especiesmencionadas`` stays verbatim because it is free text, not a list.
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
    parser.add_argument("--granularidad", type=Path, required=True,
                        help="curated location-granularity taxonomy, one entry "
                             "per source_path")
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
        rows, source_identity = read_rows(args.parquet)
        validate_rows(rows)
        granularity = load_granularity(args.granularidad)
        check_granularity_coverage(granularity, rows)
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
            granularity,
            args.country,
            str(args.parquet),
            extent_label,
            extent_boundary_note,
            source_identity,
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
        f"excluded={catalog['display_contract']['excluded_count']}, "
        f"collisions={catalog['display_contract']['collision_coordinate_count']} "
        f"coords / {catalog['display_contract']['collision_marker_count']} markers)"
    )
    print(
        f"n_autores consistency: {matched}/{len(rows)} rows matched, "
        f"{len(mismatches)} mismatched"
    )
    level_tally = Counter(entry["nivel"] for entry in granularity.values())
    print(
        "granularity levels: "
        + ", ".join(f"{level}={level_tally.get(level, 0)}" for level in GRANULARITY_LEVELS)
    )
    for key in CLASS_ORDER:
        print(f"  {key}: {counts[key]}")
    print(f"  wrote {json_path}")
    print(f"  wrote {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
