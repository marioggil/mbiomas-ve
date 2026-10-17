#!/usr/bin/env python3
"""Build the shipped artifact behind the Imataca case study page.

The study's research is done and its evidence is versioned under
``odd/informes/imataca/``: the report's prose (``informe.md``), the box's
level-2 composition for ten years (``tabla-coberturas.json``), the congress
table for the same box (``tabla-congresos.json``), the curation of the raw
species entries (``especies-curadas.json``) and the raw evidence (the ten
``evidencia/clip-<year>.json`` responses plus ``evidencia/procedencia.json``).

``odd/`` is not part of the deployed image: only ``tools/``, ``viewer/``,
``data/legend/`` and ``data/derived/`` travel. The page therefore cannot read
the evidence at runtime, and retyping the numbers into markup would give the
study a second source of truth. This tool exists to make the evidence into one
shipped artifact -- ``data/derived/venezuela/informes/imataca.json`` -- that
the service reads once at import and serves verbatim at
``GET /api/informe/imataca``. Every figure on the page comes from that
artifact, so a change in the evidence changes the page only by rebuilding it.

Usage::

    tools/build_informe_imataca.py

    tools/build_informe_imataca.py \\
        --evidence odd/informes/imataca \\
        --catalog data/derived/venezuela/congresos/catalogo-estudios.json \\
        --out data/derived/venezuela/informes/imataca.json

The script is strict on purpose. Before writing anything it cross-checks the
committed coverage table against the ten raw clip responses (same box, same
observed area, per-class areas equal to the last floating-point bit), the
congress editions against the coverage years, and the species curation against
the raw entries. A disagreement means one of the two files was rebuilt without
the other, which would put two different numbers behind the same sentence, so
the tool aborts with a non-zero exit status instead of emitting a quietly
inconsistent artifact.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
DEFAULT_EVIDENCE_DIR: Final[Path] = REPO_ROOT / "odd" / "informes" / "imataca"
DEFAULT_CATALOG_PATH: Final[Path] = (
    REPO_ROOT / "data" / "derived" / "venezuela" / "congresos" / "catalogo-estudios.json"
)
DEFAULT_OUT_PATH: Final[Path] = (
    REPO_ROOT / "data" / "derived" / "venezuela" / "informes" / "imataca.json"
)

# Schema version of the artifact's own JSON contract. Bumped on any breaking
# change to the shape ``tools/serve_viewer.py`` validates and ``viewer/
# informe-imataca.js`` reads.
SCHEMA_VERSION: Final[str] = "informe-imataca.v1"

# The two artefact identities the page's provenance section names. The
# composition artefact's schema version is recorded in the study's own
# provenance evidence and is asserted here rather than trusted: the box was
# measured against the committed composition engine's output.
EXPECTED_COMPOSITION_SCHEMA: Final[int] = 2
# The studies catalogue the congress table was extracted from. Its schema
# version is asserted for the same reason: a version 5 catalogue is a different
# curation and the congress numbers here were not built from it.
EXPECTED_CATALOG_SCHEMA: Final[int] = 4

# The six classes ``informe.md`` section 3 tabulates, in that section's order.
# The page's coverage figure draws exactly these; the remaining level-2 classes
# of the box travel in the artifact too, so the figure's subset is a documented
# choice of the study and not a silent filter in the frontend.
CLASSES_OF_THE_REPORT: Final[tuple[tuple[str, str], ...]] = (
    ("1.1", "Bosque"),
    ("3.1", "Uso pecuario/Tierras en descanso"),
    ("4.3", "Uso Minero"),
    ("2.2", "Sabana/Herbazal"),
    ("1.4", "Bosque inundable"),
    ("5.1", "Río, lago u océano"),
)

# Spanish month names, used only to render the consultation date and the two
# artefact dates as the prose writes them ("16 de octubre de 2026"). A date
# rendered by the frontend would need the browser's locale data; rendering it
# here keeps the string identical everywhere the page is opened.
MONTHS_ES: Final[dict[int, str]] = {
    1: "enero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "junio",
    7: "julio",
    8: "agosto",
    9: "septiembre",
    10: "octubre",
    11: "noviembre",
    12: "diciembre",
}

# The report's coverage table does not print a plain delta for every class.
# ``informe.md`` section 3 writes "×10" for the mining class and "estable" for
# the floodable forest, where a mechanical difference would print "+0,39
# puntos" and "−0,02 puntos". The page must print the report's own label, and
# that label must be derived instead of typed into the markup, so this tool
# computes one label per class and ships it in the artifact as
# ``cambio_etiqueta``:
#
#   * "estable"  -- the change rounds to 0,0 points at one decimal, the
#                   report's own resolution for "nothing moved": a delta below
#                   0,05 points in absolute value.
#   * "×N"       -- the ratio between the two shares as the report's table
#                   prints them (two decimals) is at least 10. N is that ratio
#                   truncated toward zero, so 0,42 / 0,04 = 10,5 prints "×10",
#                   the value ``informe.md`` carries.
#   * otherwise  -- the signed delta in points, with two decimals.
STABLE_CHANGE_LABEL: Final[str] = "estable"
STABLE_CHANGE_POINTS: Final[float] = 0.05
CHANGE_RATIO_THRESHOLD: Final[float] = 10.0
# The precision the report's coverage table prints its two shares with. The
# ratio is taken on the printed values because that is the ratio a reader can
# recompute from the row's own cells.
REPORT_SHARE_DECIMALS: Final[int] = 2

# The comparison tolerances. The committed table and the raw clips are the same
# float64 values (the table is the clip responses aggregated), so the only slack
# needed is the noise of a JSON round-trip. 1e-6 ha is 1 mm^2.
AREA_TOLERANCE_HA: Final[float] = 1e-6
SHARE_TOLERANCE_PCT: Final[float] = 1e-6


class InformeError(RuntimeError):
    """Raised when the study's evidence is missing, malformed or inconsistent."""


# ---------------------------------------------------------------------------
# Reading the evidence
# ---------------------------------------------------------------------------


def _read_json(path: Path, label: str) -> dict[str, Any]:
    """Read one JSON object, or raise naming the file and the problem."""
    if not path.is_file():
        raise InformeError(f"{label} not found: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InformeError(f"{label} is not readable: {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise InformeError(f"{label} is not valid UTF-8: {path}: {exc}") from exc
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InformeError(f"{label} is not valid JSON: {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise InformeError(f"{label} root is not an object: {path}")
    return document


def _require(condition: bool, message: str) -> None:
    """Fail loudly on a violated invariant, with the reason already written."""
    if not condition:
        raise InformeError(message)


def _number(value: Any, where: str) -> float:
    """Return ``value`` as a float, rejecting bools and non-numbers."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InformeError(f"{where} is not a number: {value!r}")
    return float(value)


def _int(value: Any, where: str) -> int:
    """Return ``value`` as an int, rejecting bools and non-integers."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise InformeError(f"{where} is not an integer: {value!r}")
    return value


def _date_es(iso_utc: Any, where: str) -> str:
    """Render an ISO-8601 UTC timestamp as the prose's Spanish date.

    Only the date part is used: the study's own sentences say "consultada el 16
    de octubre de 2026" and "generado el 2026-09-24", and a time of day would
    add a precision the report does not claim.
    """
    _require(isinstance(iso_utc, str) and len(iso_utc) >= 10, f"{where} is not an ISO date: {iso_utc!r}")
    date_part = iso_utc[:10]
    try:
        year_s, month_s, day_s = date_part.split("-")
        year, month, day = int(year_s), int(month_s), int(day_s)
    except (ValueError, AttributeError) as exc:
        raise InformeError(f"{where} is not an ISO date: {iso_utc!r}") from exc
    if month not in MONTHS_ES:
        raise InformeError(f"{where} has a month outside 1-12: {iso_utc!r}")
    return f"{day} de {MONTHS_ES[month]} de {year}"


def load_coverage_table(path: Path) -> dict[str, Any]:
    """Load ``tabla-coberturas.json`` and check its own internal shape."""
    table = _read_json(path, "coverage table")
    box = table.get("caja")
    _require(
        isinstance(box, list) and len(box) == 4,
        f"coverage table 'caja' is not four numbers: {path}",
    )
    years = table.get("anios")
    _require(
        isinstance(years, list) and years and all(isinstance(y, int) for y in years),
        f"coverage table 'anios' is not a non-empty list of integers: {path}",
    )
    classes = table.get("clases")
    _require(
        isinstance(classes, dict) and classes,
        f"coverage table 'clases' is not a non-empty object: {path}",
    )
    for key, series in classes.items():
        code, _, name = key.partition("|")
        _require(bool(code and name), f"coverage table class key is not 'code|name': {key!r}")
        _require(
            isinstance(series, dict),
            f"coverage table class {key!r} is not an object: {path}",
        )
        for year in years:
            entry = series.get(str(year))
            _require(
                isinstance(entry, list) and len(entry) == 2,
                f"coverage table class {key!r} has no [area_ha, share_pct] for {year}: {path}",
            )
            _number(entry[0], f"coverage table class {key!r} area for {year}")
            _number(entry[1], f"coverage table class {key!r} share for {year}")
    _number(table.get("ventana_ha"), "coverage table 'ventana_ha'")
    return table


def load_clips(evidence_dir: Path, years: list[int]) -> dict[int, dict[str, Any]]:
    """Load one raw clip response per year.

    The clips are the study's primary evidence: they are what the API answered
    for this box, and the coverage table is their aggregation. Reading them here
    is what lets the build prove the two agree instead of assuming it.
    """
    clips: dict[int, dict[str, Any]] = {}
    for year in years:
        path = evidence_dir / "evidencia" / f"clip-{year}.json"
        clip = _read_json(path, f"clip evidence for {year}")
        _require(
            _int(clip.get("year"), f"clip evidence for {year} 'year'") == year,
            f"clip evidence file clip-{year}.json records year {clip.get('year')!r}",
        )
        for field in ("bbox", "level1", "level2"):
            _require(field in clip, f"clip evidence for {year} has no {field!r}: {path}")
        _number(clip.get("valid_area_ha"), f"clip evidence for {year} 'valid_area_ha'")
        _number(clip.get("nodata_area_ha"), f"clip evidence for {year} 'nodata_area_ha'")
        _require(
            isinstance(clip["level2"], list) and clip["level2"],
            f"clip evidence for {year} has an empty 'level2': {path}",
        )
        clips[year] = clip
    return clips


def load_congress_table(path: Path) -> dict[str, Any]:
    """Load ``tabla-congresos.json`` and check its own internal shape."""
    table = _read_json(path, "congress table")
    editions = table.get("por_edicion")
    _require(
        isinstance(editions, dict) and editions,
        f"congress table 'por_edicion' is not a non-empty object: {path}",
    )
    for key, edition in editions.items():
        try:
            int(key)
        except (TypeError, ValueError) as exc:
            raise InformeError(f"congress table edition key is not a year: {key!r}") from exc
        _require(
            isinstance(edition, dict),
            f"congress table edition {key} is not an object: {path}",
        )
        for field in ("charlas", "especies_distintas", "revision_ia", "pares_ror", "instituciones"):
            _int(edition.get(field), f"congress table edition {key} {field!r}")
    institutions = table.get("instituciones")
    _require(
        isinstance(institutions, list) and institutions,
        f"congress table 'instituciones' is not a non-empty list: {path}",
    )
    for index, institution in enumerate(institutions):
        _require(
            isinstance(institution, dict),
            f"congress table institution {index} is not an object: {path}",
        )
        _require(
            isinstance(institution.get("nombre"), str) and institution["nombre"],
            f"congress table institution {index} has no name: {path}",
        )
        _int(institution.get("pares"), f"congress table institution {index} 'pares'")
        _require(
            institution.get("estado") in ("ok", "dudoso"),
            f"congress table institution {index} has an unknown state: "
            f"{institution.get('estado')!r}",
        )
    _int(table.get("charlas"), "congress table 'charlas'")
    return table


def load_species_curation(path: Path) -> dict[str, Any]:
    """Load ``especies-curadas.json`` and check its own internal shape."""
    curation = _read_json(path, "species curation")
    entries = curation.get("entradas")
    _require(
        isinstance(entries, dict) and entries,
        f"species curation 'entradas' is not a non-empty object: {path}",
    )
    for raw, entry in entries.items():
        _require(
            isinstance(entry, dict),
            f"species curation entry {raw!r} is not an object: {path}",
        )
        _require(
            isinstance(entry.get("clase"), str) and entry["clase"],
            f"species curation entry {raw!r} has no class: {path}",
        )
        _require(
            isinstance(entry.get("taxon"), str),
            f"species curation entry {raw!r} has no taxon string: {path}",
        )
        _require(
            isinstance(entry.get("nota"), str),
            f"species curation entry {raw!r} has no note string: {path}",
        )
    by_edition = curation.get("por_edicion")
    _require(
        isinstance(by_edition, dict) and by_edition,
        f"species curation 'por_edicion' is not a non-empty object: {path}",
    )
    for year, taxa in by_edition.items():
        _require(
            isinstance(taxa, list) and all(isinstance(t, str) for t in taxa),
            f"species curation edition {year} is not a list of names: {path}",
        )
    _int(curation.get("especies_distintas"), "species curation 'especies_distintas'")
    resumen = curation.get("resumen")
    _require(
        isinstance(resumen, dict) and resumen,
        f"species curation 'resumen' is not a non-empty object: {path}",
    )
    for key, count in resumen.items():
        _int(count, f"species curation 'resumen' entry {key!r}")
    return curation


# ---------------------------------------------------------------------------
# Cross-checks: the table against the raw evidence
# ---------------------------------------------------------------------------


def check_box(clip: dict[str, Any], box: list[float], year: int) -> None:
    """Prove one clip was measured on the study's box, whole and observed."""
    recorded = clip["bbox"]
    _require(
        isinstance(recorded, list) and len(recorded) == 4,
        f"clip evidence for {year} 'bbox' is not four numbers",
    )
    for got, expected in zip(recorded, box):
        _require(
            abs(_number(got, f"clip {year} bbox") - expected) < 1e-12,
            f"clip evidence for {year} was measured on bbox {recorded} but the "
            f"study's box is {box}",
        )


def check_coverage_against_clips(
    table: dict[str, Any], clips: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    """Cross-check the aggregated table against the ten raw responses.

    Three facts the page's prose asserts are proved here rather than repeated in
    the artifact as claims: the box is the same window in every year; the window
    is fully observed (no no-data pixel, so the shares are shares of the box);
    and every class's area and share in the table is the clip's own value.
    """
    box = [_number(v, "coverage table box coordinate") for v in table["caja"]]
    _require(
        box[0] < box[2] and box[1] < box[3],
        f"the study's box is not a rectangle with west < east and south < north: {box}",
    )
    window_ha = _number(table["ventana_ha"], "coverage table 'ventana_ha'")
    years = [int(y) for y in table["anios"]]
    classes = table["clases"]

    windows: set[tuple[Any, ...]] = set()
    cog_extents: set[tuple[Any, ...]] = set()
    clip_schemas: set[str] = set()
    area_methods: set[str] = set()
    country_collection: set[tuple[Any, Any]] = set()
    total_pixels: set[int] = set()
    nodata_total_ha = 0.0

    for year in years:
        clip = clips[year]
        _require(
            _int(clip.get("year"), f"clip {year} 'year'") == year,
            f"the clip response filed under {year} records year {clip.get('year')!r}",
        )
        check_box(clip, box, year)

        # The same observed window in every year. If a year's window differed,
        # its shares would be shares of a different area and the ten-year curve
        # would be comparing two boxes.
        windows.add(_window_key(clip, year))
        cog_extents.add(tuple(_number(v, f"clip {year} cog_extent") for v in clip.get("cog_extent", [])))
        clip_schemas.add(str(clip.get("schema_version")))
        area_methods.add(str(clip.get("area_method")))
        country_collection.add((clip.get("country"), clip.get("collection")))
        total_pixels.add(_int(clip.get("total_pixels"), f"clip {year} 'total_pixels'"))

        valid_ha = _number(clip["valid_area_ha"], f"clip {year} 'valid_area_ha'")
        nodata_ha = _number(clip["nodata_area_ha"], f"clip {year} 'nodata_area_ha'")
        _require(
            abs(valid_ha - window_ha) < AREA_TOLERANCE_HA,
            f"clip evidence for {year} observed {valid_ha} ha of the box but the "
            f"coverage table declares {window_ha} ha",
        )
        _require(
            nodata_ha == 0.0 and _int(clip.get("nodata_pixels"), f"clip {year} 'nodata_pixels'") == 0,
            f"clip evidence for {year} has {nodata_ha} ha of no-data inside the box; "
            "the prose claims the box is fully observed",
        )
        nodata_total_ha += nodata_ha

        # Per-class equality. The clips omit a class whose area is zero that
        # year, so a class missing from a clip must be zero in the table.
        measured = {entry["code"]: entry for entry in clip["level2"]}
        for key, series in classes.items():
            code, _, name = key.partition("|")
            area_ha, share_pct = series[str(year)]
            if code not in measured:
                _require(
                    area_ha == 0.0 and share_pct == 0.0,
                    f"class {key!r} is absent from clip evidence for {year} but the "
                    f"coverage table records {area_ha} ha / {share_pct} %",
                )
                continue
            entry = measured[code]
            _require(
                entry.get("name_es") == name,
                f"clip evidence for {year} names class {code} {entry.get('name_es')!r} "
                f"but the coverage table names it {name!r}",
            )
            _require(
                abs(_number(entry.get("area_ha"), f"clip {year} class {code} area") - area_ha)
                < AREA_TOLERANCE_HA,
                f"class {key!r} area for {year}: clip says {entry.get('area_ha')} ha, the "
                f"coverage table says {area_ha} ha",
            )
            _require(
                abs(_number(entry.get("share_pct"), f"clip {year} class {code} share") - share_pct)
                < SHARE_TOLERANCE_PCT,
                f"class {key!r} share for {year}: clip says {entry.get('share_pct')} %, the "
                f"coverage table says {share_pct} %",
            )

    _require(len(windows) == 1, f"the clip responses do not share one window: {sorted(windows)}")
    _require(len(clip_schemas) == 1, f"the clip responses disagree on their schema: {clip_schemas}")
    _require(
        len(area_methods) == 1,
        f"the clip responses disagree on the area method: {area_methods}",
    )
    _require(
        len(country_collection) == 1,
        f"the clip responses disagree on the country/collection: {country_collection}",
    )
    _require(len(total_pixels) == 1, f"the clip responses disagree on the window size: {total_pixels}")
    _require(
        len(cog_extents) == 1,
        "the clip responses were measured on different source extents",
    )
    return {
        "window": next(iter(windows)),
        "clip_schema": next(iter(clip_schemas)),
        "area_method": next(iter(area_methods)),
        "country": next(iter(country_collection))[0],
        "collection": next(iter(country_collection))[1],
        "cog_extent": list(next(iter(cog_extents))),
        "total_pixels": next(iter(total_pixels)),
        "nodata_ha": nodata_total_ha,
    }


def _window_key(clip: dict[str, Any], year: int) -> tuple[Any, ...]:
    """Return the clip's pixel window as a hashable, validated tuple."""
    window = clip.get("window")
    _require(isinstance(window, dict), f"clip evidence for {year} has no 'window' object")
    parts = []
    for field in ("col_off", "row_off", "width", "height"):
        parts.append(_int(window.get(field), f"clip {year} window {field!r}"))
    return tuple(parts)


# ---------------------------------------------------------------------------
# Cross-checks: the congress and curation tables against each other
# ---------------------------------------------------------------------------


def check_congress_and_curation(
    congress: dict[str, Any],
    curation: dict[str, Any],
    years: list[int],
) -> dict[str, Any]:
    """Join the congress table with the species curation and check the joins.

    The two tables describe the same eight editions. The edition set is the
    coverage years minus the two years the congress did not meet (1985, the
    first map, and 2024, the last): deriving it here means a coverage year
    added to the evidence cannot silently become a congress edition, and a
    congress edition without a coverage year is refused rather than charted
    against a missing point.
    """
    editions = sorted(int(key) for key in congress["por_edicion"])
    expected_editions = [year for year in years if year not in (min(years), max(years))]
    _require(
        editions == expected_editions,
        f"the congress editions {editions} are not the coverage years without "
        f"the first and the last ({expected_editions})",
    )

    curated_by_edition = curation["por_edicion"]
    _require(
        sorted(int(key) for key in curated_by_edition) == editions,
        f"the species curation covers editions {sorted(curated_by_edition)} but the "
        f"congress table covers {editions}",
    )

    rows: list[dict[str, Any]] = []
    talks = 0
    determinations = 0
    for year in editions:
        raw = congress["por_edicion"][str(year)]
        taxa = list(curated_by_edition[str(year)])
        talks += _int(raw["charlas"], f"congress table edition {year} 'charlas'")
        determinations += len(taxa)
        # The curated count can only be lower than the raw one: the curation
        # removes non-names and collapses a species counted twice. A curated
        # count above the raw count means one of the two tables was edited
        # alone, which is exactly the drift this build refuses.
        _require(
            len(taxa) <= _int(raw["especies_distintas"], f"congress edition {year} raw species"),
            f"edition {year} curates {len(taxa)} species but the raw extraction "
            f"counted {raw['especies_distintas']}",
        )
        _require(
            len(taxa) == len(set(taxa)),
            f"edition {year} lists a species twice after curation: {taxa}",
        )
        rows.append(
            {
                "anio": year,
                "charlas": _int(raw["charlas"], f"congress edition {year} 'charlas'"),
                "especies_distintas": len(taxa),
                "especies_sin_curar": _int(
                    raw["especies_distintas"], f"congress edition {year} raw species"
                ),
                "especies": taxa,
                "charlas_con_especies": _int(
                    raw.get("con_especies", 0), f"congress edition {year} 'con_especies'"
                ),
                "pares_ror": _int(raw["pares_ror"], f"congress edition {year} 'pares_ror'"),
                "instituciones": _int(
                    raw["instituciones"], f"congress edition {year} 'instituciones'"
                ),
                "pares_dudosos": _int(
                    raw.get("pares_dudosos", 0), f"congress edition {year} 'pares_dudosos'"
                ),
                "revision_ia": _int(
                    raw["revision_ia"], f"congress edition {year} 'revision_ia'"
                ),
            }
        )

    _require(
        talks == _int(congress["charlas"], "congress table 'charlas'"),
        f"the edition rows sum to {talks} talks but the congress table declares "
        f"{congress['charlas']}",
    )
    # The sum of the editions' curated species is NOT the study's distinct count:
    # one species (Harpia harpyja) is legitimately named in two editions, so the
    # sum over-counts it once. It is the number of species-level determinations in
    # the series, and it must equal the curation's species-level entry count (31
    # for 30 distinct taxa).
    _require(
        determinations == _int(curation["resumen"].get("especie"), "curation species-level count"),
        f"the editions list {determinations} species-level determinations but the "
        f"curation classifies {curation['resumen'].get('especie')} entries at species level",
    )
    return {"rows": rows, "talks": talks, "determinations": determinations}


def load_tile_zoom(derived_dir: Path) -> tuple[int, int]:
    """Read the tile pyramid's declared zoom range from its own manifest.

    The page's map draws the 2024 pyramid, so the range of zoom levels it may
    ask for is a fact about the deployed tiles, not a number to guess in the
    frontend: a zoom above the pyramid's ceiling would request tiles that do not
    exist and paint nothing.
    """
    manifest = _read_json(derived_dir / "tiles-manifest.json", "tiles manifest")
    raw = manifest.get("zoom_range_requested")
    _require(
        isinstance(raw, str) and raw.count("-") == 1,
        f"tiles manifest has no 'zoom_range_requested' range: {derived_dir / 'tiles-manifest.json'}",
    )
    low_s, _, high_s = raw.partition("-")
    try:
        low, high = int(low_s), int(high_s)
    except ValueError as exc:
        raise InformeError(f"tiles manifest zoom range is not numeric: {raw!r}") from exc
    _require(
        0 <= low <= high,
        f"tiles manifest zoom range is not ordered: {raw!r}",
    )
    return low, high


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build(
    evidence_dir: Path,
    catalog_path: Path,
) -> dict[str, Any]:
    """Assemble the artifact from the study's evidence."""
    coverage_table = load_coverage_table(evidence_dir / "tabla-coberturas.json")
    congress_table = load_congress_table(evidence_dir / "tabla-congresos.json")
    curation = load_species_curation(evidence_dir / "especies-curadas.json")
    provenance = _read_json(evidence_dir / "evidencia" / "procedencia.json", "procedure evidence")

    years = [int(y) for y in coverage_table["anios"]]
    clips = load_clips(evidence_dir, years)
    facts = check_coverage_against_clips(coverage_table, clips)

    # The provenance record must describe the same box and the same years as the
    # table it is attached to; otherwise the artifact would carry the identity of
    # an artifact that measured something else.
    box = [_number(v, "coverage table box coordinate") for v in coverage_table["caja"]]
    recorded_box = provenance.get("caja")
    _require(
        isinstance(recorded_box, list)
        and len(recorded_box) == 4
        and all(abs(_number(g, "procedure box coordinate") - e) < 1e-12 for g, e in zip(recorded_box, box)),
        f"the procedure evidence records box {recorded_box} but the coverage table "
        f"records {box}",
    )
    window_ha = _number(coverage_table["ventana_ha"], "coverage table 'ventana_ha'")
    _require(
        abs(_number(provenance.get("ventana_ha"), "procedure 'ventana_ha'") - window_ha)
        < AREA_TOLERANCE_HA,
        "the procedure evidence and the coverage table disagree on the box area",
    )

    cogs = provenance.get("cogs_por_anio")
    _require(isinstance(cogs, dict), "procedure evidence has no 'cogs_por_anio' object")
    _require(
        sorted(int(y) for y in cogs) == sorted(years),
        f"the procedure evidence digests years {sorted(cogs)} but the study measured "
        f"{sorted(years)}",
    )
    _require(
        str(provenance.get("schema_del_clip")) == facts["clip_schema"],
        f"the procedure evidence records clip schema {provenance.get('schema_del_clip')!r} "
        f"but the raw clips are {facts['clip_schema']!r}",
    )

    composition = provenance.get("artefacto_composicion")
    _require(
        isinstance(composition, dict),
        "procedure evidence has no 'artefacto_composicion' object",
    )
    _require(
        _int(composition.get("schema_version"), "composition 'schema_version'")
        == EXPECTED_COMPOSITION_SCHEMA,
        f"the composition artefact is schema {composition.get('schema_version')!r}, "
        f"expected {EXPECTED_COMPOSITION_SCHEMA}",
    )
    radius_m = _number(composition.get("authalic_radius_m"), "composition 'authalic_radius_m'")

    # The catalogue identity is read from the shipped catalogue itself rather
    # than typed here: the congress table was extracted from that artifact and a
    # rebuild of it must move this line with it.
    catalog = _read_json(catalog_path, "studies catalogue")
    _require(
        _int(catalog.get("schema_version"), "studies catalogue 'schema_version'")
        == EXPECTED_CATALOG_SCHEMA,
        f"the studies catalogue is schema {catalog.get('schema_version')!r}, expected "
        f"{EXPECTED_CATALOG_SCHEMA}",
    )

    congress_facts = check_congress_and_curation(congress_table, curation, years)
    coverage_classes = build_coverage_classes(coverage_table, years)
    derived_dir = (
        REPO_ROOT / "data" / "derived" / str(facts["country"]) / f"collection-{facts['collection']}"
    )
    zoom_min, zoom_max = load_tile_zoom(derived_dir)

    institutions = [
        {
            "nombre": institution["nombre"],
            "pares": _int(institution["pares"], "institution 'pares'"),
            "estado": institution["estado"],
        }
        for institution in congress_table["instituciones"]
    ]
    institution_pairs = sum(institution["pares"] for institution in institutions)
    doubtful_pairs = sum(
        institution["pares"] for institution in institutions if institution["estado"] == "dudoso"
    )
    _require(
        institution_pairs == sum(row["pares_ror"] for row in congress_facts["rows"]),
        "the institution pairs do not sum to the per-edition pair counts",
    )

    curated_entries = [
        {
            "crudo": raw,
            "clase": entry["clase"],
            "taxon": entry["taxon"],
            "nota": entry["nota"],
        }
        for raw, entry in sorted(curation["entradas"].items())
    ]
    clasified = {key: _int(value, f"curation resumen {key!r}") for key, value in curation["resumen"].items()}
    _require(
        sum(clasified.values()) == len(curated_entries),
        f"the curation's class counts sum to {sum(clasified.values())} but its entries "
        f"are {len(curated_entries)}",
    )
    species_level = [entry for entry in curated_entries if entry["clase"] == "especie"]
    distinct_taxa = sorted({entry["taxon"] for entry in species_level})
    _require(
        len(distinct_taxa) == _int(curation["especies_distintas"], "curation distinct species"),
        f"the curation's entries yield {len(distinct_taxa)} distinct species but it "
        f"declares {curation['especies_distintas']}",
    )
    _require(
        len(species_level) == _int(curation["resumen"].get("especie"), "curation species-level count"),
        "the curation's species-level entries do not match its own species count",
    )

    # A species named in more than one edition. The prose makes one of these a
    # point of the curation (Harpia harpyja, written two ways), so the artifact
    # records the whole set instead of letting the page infer it from a chart.
    editions_per_taxon: dict[str, list[int]] = {}
    for row in congress_facts["rows"]:
        for taxon in row["especies"]:
            editions_per_taxon.setdefault(taxon, []).append(row["anio"])
    repeated = [
        {"taxon": taxon, "ediciones": editions, "veces": len(editions)}
        for taxon, editions in sorted(editions_per_taxon.items())
        if len(editions) > 1
    ]
    # The two counts must reconcile: every determination is one distinct taxon,
    # plus one extra for each additional edition a repeated taxon appears in.
    _require(
        congress_facts["determinations"]
        == len(distinct_taxa) + sum(row["veces"] - 1 for row in repeated),
        f"the {congress_facts['determinations']} species-level determinations do not "
        f"reconcile with {len(distinct_taxa)} distinct taxa and {len(repeated)} "
        f"taxa named in more than one edition",
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "estudio": "imataca",
        # The country and the collection the box was measured in, taken from the
        # ten raw responses. The page's citation names both, so they are facts of
        # the study rather than constants of the template.
        "pais": facts["country"],
        "coleccion": facts["collection"],
        "caja": build_box(box, window_ha, facts, radius_m),
        "coberturas": {
            "unidad_area": "ha",
            "metodo_area": facts["area_method"],
            "anios": years,
            "clases": coverage_classes,
        },
        "congresos": {
            "charlas": congress_facts["talks"],
            "ediciones": congress_facts["rows"],
            "determinaciones_por_edicion": congress_facts["determinations"],
            "instituciones": institutions,
            "instituciones_distintas": len(institutions),
            "pares_institucion": institution_pairs,
            "pares_dudosos": doubtful_pairs,
            "revision_ia": sum(row["revision_ia"] for row in congress_facts["rows"]),
        },
        "especies": {
            "entradas_crudas": len(curated_entries),
            "clases": clasified,
            "especies_distintas": len(distinct_taxa),
            "determinaciones": congress_facts["determinations"],
            "taxones": distinct_taxa,
            "entradas": curated_entries,
            "repetidas": repeated,
        },
        "mapa": {
            "anio": max(years),
            "plantilla": "/tiles/{year}/{z}/{x}/{y}.png",
            "zoom_min": zoom_min,
            "zoom_max": zoom_max,
        },
        "procedencia": {
            "consulta_utc": provenance["consulta_utc"],
            "consulta_es": _date_es(provenance.get("consulta_utc"), "procedure 'consulta_utc'"),
            "composicion": {
                "artefacto": (
                    f"composition-summary-{facts['country']}-collection-{facts['collection']}.json"
                ),
                "schema_version": EXPECTED_COMPOSITION_SCHEMA,
                "generado_utc": composition["generated_utc"],
                "generado_es": _date_es(
                    composition.get("generated_utc"), "composition 'generated_utc'"
                ),
                "radio_autalico_m": radius_m,
            },
            "catalogo": {
                "artefacto": catalog_path.name,
                "schema_version": EXPECTED_CATALOG_SCHEMA,
                "generado_utc": catalog.get("generated_utc"),
                "generado_es": _date_es(catalog.get("generated_utc"), "catalogue 'generated_utc'"),
            },
            "clip_schema": facts["clip_schema"],
            "recomputar": provenance.get("recomputar"),
            "cogs": [
                {
                    "anio": year,
                    "sha256": cogs[str(year)].get("output_sha256"),
                    "bytes": _int(cogs[str(year)].get("output_bytes"), f"cog {year} 'output_bytes'"),
                }
                for year in years
            ],
        },
    }


def build_box(
    box: list[float],
    window_ha: float,
    facts: dict[str, Any],
    radius_m: float,
) -> dict[str, Any]:
    """Describe the study's box, including the size the prose quotes in km.

    ``informe.md`` says "165 × 156 km" next to the four coordinates. Those two
    numbers are derived here from the box and the authalic radius the areas were
    measured with -- the width on the box's central parallel, the height along
    the meridian -- so the km figures cannot drift from the degrees, and the page
    carries no number it did not receive.
    """
    west, south, east, north = box
    per_degree_m = 2.0 * math.pi * radius_m / 360.0
    width_km = (east - west) * per_degree_m * math.cos(math.radians((south + north) / 2.0)) / 1000.0
    height_km = (north - south) * per_degree_m / 1000.0
    window = facts["window"]
    return {
        "oeste": west,
        "sur": south,
        "este": east,
        "norte": north,
        "bbox": [west, south, east, north],
        "centro": [(west + east) / 2.0, (south + north) / 2.0],
        "ventana_ha": window_ha,
        "ventana_km2": window_ha / 100.0,
        "ancho_km": width_km,
        "alto_km": height_km,
        "radio_autalico_m": radius_m,
        "ventana_px": {
            "col_off": window[0],
            "row_off": window[1],
            "ancho": window[2],
            "alto": window[3],
            "pixeles": facts["total_pixels"],
        },
        "sin_dato_ha": facts["nodata_ha"],
        "observada_pct": 100.0 * (window_ha - facts["nodata_ha"]) / window_ha,
    }


def change_label(share_1985: float, share_2024: float, delta_puntos: float) -> str:
    """Derive the change label ``informe.md`` prints for one class.

    See the ``STABLE_CHANGE_LABEL`` block above for the rule. The result is a
    finished Spanish string, so the page never re-derives it and a rebuilt
    artifact moves the coverage table and the figure captions together.
    """
    if abs(delta_puntos) < STABLE_CHANGE_POINTS:
        return STABLE_CHANGE_LABEL
    displayed_1985 = round(share_1985, REPORT_SHARE_DECIMALS)
    displayed_2024 = round(share_2024, REPORT_SHARE_DECIMALS)
    if displayed_1985 > 0.0:
        ratio = displayed_2024 / displayed_1985
        if ratio >= CHANGE_RATIO_THRESHOLD:
            return f"\u00d7{int(ratio)}"
    return _signed_points(delta_puntos)


def _signed_points(value: float) -> str:
    """Render a change in points as the report's table writes it.

    Two decimals, a comma for the decimal mark and U+2212 for the minus sign,
    the same conventions the page formats its other numbers with. The plus sign
    on a positive change is the report's own.
    """
    text = f"{value:+.2f}".replace(".", ",")
    if text.startswith("-"):
        text = "\u2212" + text[1:]
    return text + " puntos"


def build_coverage_classes(table: dict[str, Any], years: list[int]) -> list[dict[str, Any]]:
    """Build the per-class series with the report's six classes first."""
    report_order = {code: index for index, (code, _name) in enumerate(CLASSES_OF_THE_REPORT)}
    for code, name in CLASSES_OF_THE_REPORT:
        _require(
            f"{code}|{name}" in table["clases"],
            f"informe.md section 3 tabulates class {code}|{name} but the coverage "
            "table does not carry it",
        )

    rows: list[dict[str, Any]] = []
    for key, series in table["clases"].items():
        code, _, name = key.partition("|")
        area_ha = [float(series[str(year)][0]) for year in years]
        share_pct = [float(series[str(year)][1]) for year in years]
        rows.append(
            {
                "codigo": code,
                "nombre_es": name,
                "en_informe": code in report_order,
                "area_ha": area_ha,
                "share_pct": share_pct,
                "share_1985": share_pct[0],
                "share_2024": share_pct[-1],
                "delta_puntos": share_pct[-1] - share_pct[0],
                "delta_ha": area_ha[-1] - area_ha[0],
                "cambio_etiqueta": change_label(
                    share_pct[0], share_pct[-1], share_pct[-1] - share_pct[0]
                ),
            }
        )
    rows.sort(
        key=lambda row: (
            report_order.get(row["codigo"], len(report_order)),
            -row["share_2024"],
            row["codigo"],
        )
    )
    return rows


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def write_artifact(artifact: dict[str, Any], path: Path) -> Path:
    """Write the artifact, pretty-printed and UTF-8, with a trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(artifact, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--evidence",
        type=Path,
        default=DEFAULT_EVIDENCE_DIR,
        help="directory holding the study's versioned evidence "
        f"(default: {DEFAULT_EVIDENCE_DIR.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG_PATH,
        help="the shipped studies catalogue whose identity the artifact records "
        f"(default: {DEFAULT_CATALOG_PATH.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT_PATH,
        help=f"artifact to write (default: {DEFAULT_OUT_PATH.relative_to(REPO_ROOT)})",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        artifact = build(args.evidence, args.catalog)
    except InformeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    write_artifact(artifact, args.out)

    box = artifact["caja"]
    coverage = artifact["coberturas"]
    congress = artifact["congresos"]
    species = artifact["especies"]
    print(
        f"informe imataca: box {box['oeste']}, {box['sur']}, {box['este']}, {box['norte']} "
        f"({box['ancho_km']:.0f} x {box['alto_km']:.0f} km, {box['ventana_ha']:.0f} ha)"
    )
    print(
        f"  coverage: {len(coverage['anios'])} years, {len(coverage['clases'])} classes, "
        f"{sum(1 for c in coverage['clases'] if c['en_informe'])} of them in the report"
    )
    print(
        f"  congress: {congress['charlas']} talks in {len(congress['ediciones'])} editions, "
        f"{congress['determinaciones_por_edicion']} species-level determinations, "
        f"{congress['pares_institucion']} institution pairs in "
        f"{congress['instituciones_distintas']} institutions "
        f"({congress['pares_dudosos']} doubtful)"
    )
    print(
        f"  species: {species['entradas_crudas']} raw entries, "
        f"{species['clases'].get('especie', 0)} at species level, "
        f"{species['especies_distintas']} distinct taxa, "
        f"{len(species['repetidas'])} taxa named in more than one edition"
    )
    print(f"  consultation: {artifact['procedencia']['consulta_es']}")
    print(f"  wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
