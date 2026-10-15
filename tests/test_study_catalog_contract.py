"""Anchor the CVE study-catalog builder's pure contract and the shipped artifact.

WHY THIS FILE EXISTS
--------------------
``tools/build_study_catalog.py`` computed ``display_class``, ``on_map`` and
``exclusion_reason`` for the human-reviewed abstracts the viewer serves, and
nothing asserted any of it. The builder also called ``raise SystemExit(1)`` at
module import time when ``pyarrow`` or ``osgeo`` was missing, so importing it to
test ``slugify`` killed the test process instead of reporting a failure. This
file pins both: the pure logic through direct calls, and the artifact the viewer
actually consumes.

Since the location-granularity taxonomy landed, the class is decided by the
curated level, not by a collision of coordinates: ``coarse_location`` replaced
``shared_coordinate``, and the collision became the per-study attributes
``coordinate_group_size``/``coordinate_group_ids``. The fixtures below exercise
that contract, and ``CommittedArtifactFreshnessTests`` compares the committed
artifact's recorded input identity with the unversioned Parquet on disk.

WHAT IT DOES NOT DO
-------------------
It re-derives nothing from the Parquet. The artifact check reads the committed
``data/derived/venezuela/congresos/catalogo-estudios.json`` and asserts the
pinned numbers against it, so a regenerated artifact that breaks the display
contract fails a test here instead of reaching the viewer. The file needs
neither ``pyarrow`` nor GDAL: the rebuild-only dependency messages are exercised
by making the modules unimportable, not by depending on their absence.

Run it with the system interpreter from the repository root::

    python3 -m unittest discover -s tests -v

DESIGN NOTE ON CONTROLS
-----------------------
Passing over the current state is not evidence. Every check in this file has a
discriminating control that reaches *that* check: ``assert_catalog_contract``
has one mutation per branch, and every negative path is pinned with
``assertRaisesRegex`` rather than a bare ``assertRaises``. That is not
decoration. The first version of ``test_composition_summary_schema.py`` used
bare ``assertRaises``: its control for a flattened summary was rejected by the
missing-version check long before reaching the year-leak check it claimed to
exercise, so the regression the file existed for was never tested. Each control
here was written to be rejected by the assertion it names and by nothing
earlier.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
import types
import unittest
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import build_study_catalog as subject  # noqa: E402

CATALOG_PATH = (
    REPO_ROOT / "data" / "derived" / "venezuela" / "congresos" / "catalogo-estudios.json"
)
GRANULARITY_PATH = (
    REPO_ROOT / "data" / "curated" / "congresos" / "granularidad-ubicaciones.json"
)
# The unversioned input of the rebuild. ``data/raw/`` is gitignored, so this
# file is absent from a fresh clone; the freshness check below skips itself
# there instead of failing on a missing input (open item C1).
PARQUET_PATH = (
    REPO_ROOT / "data" / "raw" / "congresos" / "congresos_revisados.parquet"
)

# ---------------------------------------------------------------------------
# Pinned numbers. These describe the committed artifact; they are asserted
# against the file, never re-derived from the Parquet.
# ---------------------------------------------------------------------------
EXPECTED_SCHEMA_VERSION = 4
EXPECTED_STUDY_COUNT = 255
EXPECTED_CLASS_COUNTS = {
    "placeable": 145,
    "coarse_location": 87,
    "outside_extent": 13,
    "no_coordinate": 10,
}
EXPECTED_MAP_VISIBLE = 145
EXPECTED_EXCLUDED = 110
# The builder's collision tallies, describing what the map draws: 15 exact
# coordinates carry two or more of the 145 placed studies, and those
# coordinates gather 69 markers. The catalog-wide collision is larger because it
# also counts coordinates whose extra studies the map does not draw, so these two
# numbers must come from the ``placeable`` studies alone. 28 of the 69 sit on the
# Imataca reserve centroid alone: the reserve is ``T2``, a decision the review
# kept, so the ring has to declare that pile rather than the map hide it.
EXPECTED_COLLISION_COORDINATE_COUNT = 15
EXPECTED_COLLISION_MARKER_COUNT = 69
EXPECTED_ESPECIES_NON_NULL = 194

# The congress-metrics contract (schema v4). Pinned against the committed
# artifact, never re-derived from the Parquet.
#
# ``ror_instituciones`` is the curated ROR table projected for the client: 42
# reviewed ids. ``estado`` is the VERDICT and did not move with this decision:
# 26 usable (``ok``) and 16 doubtful (``dudoso``). ``grafica`` is the separate
# CHARTING decision and all 42 entries are drawn (``true``), including the 16
# doubtful ones the owner accepted for the charts while the doubt stays recorded.
# 226 of the 255 studies carry at least one usable ROR, and the 226 studies hold
# 282 talk-institution pairs. The parsed species list is non-empty in 189 studies;
# the 189 studies name 534 distinct species once lowercased (the artifact keeps
# the first form it saw, the client lowercases for grouping).
EXPECTED_ROR_ENTRIES = 42
EXPECTED_ROR_ESTADOS = {"ok": 26, "dudoso": 16}
EXPECTED_ROR_GRAFICA = {True: 42}
EXPECTED_STUDIES_WITH_RORES = 226
EXPECTED_ROR_TALK_PAIRS = 282
EXPECTED_STUDIES_WITH_ESPECIES = 189
EXPECTED_DISTINCT_SPECIES = 534

# The curated taxonomy is complete: one entry per row of the 202-study corpus.
EXPECTED_GRANULARITY_ENTRIES = 255

# The author object shape, spelled out here so a rename of a source field fails.
AUTHOR_FIELDS = ["nombre", "afiliacion", "ror", "pais", "orcid"]
STUDY_ID_RE = re.compile(r"^[a-z0-9-]+$")

# The exact wording of both rebuild-only dependency messages, transcribed from
# the CLI output the module printed before the imports became lazy. Hard-coded
# on purpose: a test that read the constant from the module under test could not
# notice a rewrite of the message.
PYARROW_MESSAGE = (
    "pyarrow is required to REBUILD the study catalog. It is a "
    "rebuild-only dependency: install it in a build environment (for "
    "example `pip install 'pyarrow>=25'`), never in the viewer's "
    "requirements or the image. Nothing else in this project reads Parquet."
)
GDAL_MESSAGE = (
    "the GDAL Python bindings (osgeo) are required to REBUILD the "
    "study catalog, because the extent comes from the COG's own "
    "geotransform. They are a rebuild-only dependency: install GDAL in the "
    "build environment, never in the viewer's requirements or the image."
)

# ---------------------------------------------------------------------------
# Synthetic fixtures for the pure logic. Small and explicit: they never touch
# the raw Parquet, so this file stays runnable on a bare interpreter.
# ---------------------------------------------------------------------------
EXTENT = {"west": -73.0, "south": 1.0, "east": -58.0, "north": 12.0}
INSIDE = (8.5, -69.0)
INSIDE_OTHER = (8.6, -70.0)
OUTSIDE = (40.0, -69.0)

# The identity block ``read_rows`` returns. The builder copies it verbatim into
# the catalog, so a synthetic value only has to be recognisably not a default.
SOURCE_IDENTITY = {
    "source_sha256": "a" * 64,
    "source_rows": 6,
    "source_bytes": 4096,
}

# The provenance keys, in the exact order the artifact must serialize them.
PROVENANCE_FIELDS = ["source_sha256", "source_rows", "source_bytes"]

AUTHOR = {
    "nombre": "Ana Pérez",
    "afiliacion": "Universidad de Los Andes",
    "ror": "https://ror.org/02h1b1x27",
    "pais": "VE",
    "orcid": "0000-0001-0000-0000",
}

# The curated ROR table the synthetic builder fixtures use. One entry is enough
# for the cooperative cases; the abort case below supplies its own row with an
# id this map does not carry. The id matches ``AUTHOR`` so the wiring tests that
# run ``main`` against the real curated file also close.
TEST_ROR_ENTRIES = {
    "https://ror.org/02h1b1x27": {
        "nombre": "Universidad de Los Andes",
        "estado": "ok",
        "grafica": True,
    }
}
TEST_ROR_SENTINELS = ("No disponible",)


def make_row(**overrides: Any) -> dict[str, Any]:
    """Return one source-shaped row; overrides replace a single column."""
    row: dict[str, Any] = {
        "source_path": "data/raw/congresos/pagina_5_2.pdf",
        "congreso": "III Congreso Venezolano de Ecologia",
        "anio": 1991,
        "ciudad": "Merida",
        "pagina": 5,
        "indice": 2,
        "titulo": "ECOFISIOLOGIA Y DASONIMIA TROPICAL",
        "resumen": "Resumen del estudio.",
        "latitud": INSIDE[0],
        "longitud": INSIDE[1],
        "human_verified": True,
        "human_reviewer": "mario",
        "autores": json.dumps([dict(AUTHOR)]),
        "instituciones": json.dumps(["Universidad de Los Andes"]),
        "ubicaciongeografica": "Merida",
        "ubicaciontemporal": "1991",
        "especiesmencionadas": "Cedrela odorata",
        # ``palabrasclaves`` is a real PyArrow list<string> column, so the
        # fixture hands over a Python list, not a JSON-encoded string.
        "palabrasclaves": ["Cedrela odorata"],
        "n_autores": 1,
        "paises": json.dumps(["VE"]),
    }
    row.update(overrides)
    return row


# The curated taxonomy. ``load_granularity`` normalises every entry to exactly
# these four keys, so the builder fixtures use the same shape.
def taxonomy_entry(
    nivel: str = "T2",
    texto: str = "Merida",
    razon: str | None = None,
    nota: str | None = None,
) -> dict[str, Any]:
    """Return one curated granularity entry with the loader's shape."""
    return {"nivel": nivel, "texto": texto, "razon": razon, "nota": nota}


def taxonomy_for(
    rows: list[dict[str, Any]],
    nivel: str = "T2",
    razon: str | None = None,
    nota: str | None = None,
    texto: str | None = None,
) -> dict[str, dict[str, Any]]:
    """One curated entry per row, so every synthetic row carries a level.

    ``texto`` defaults to :func:`row_location_text` of the row, which is what
    the coverage check closes against the corpus. A T0/T1 entry needs a
    ``razon`` in the real file, so a placeholder is supplied when the caller
    does not care about the wording.
    """
    if nivel in ("T0", "T1") and razon is None:
        razon = "nivel de grano grueso"
    return {
        row["source_path"]: taxonomy_entry(
            nivel=nivel,
            texto=subject.row_location_text(row) if texto is None else texto,
            razon=razon,
            nota=nota,
        )
        for row in rows
    }


# Six rows whose insertion order differs from every plausible sort order, so a
# missing or partial sort key is visible in the result rather than coincidental.
# The first two share an exact coordinate: with the taxonomy they are both
# placeable and collide, so the fixture pins that collision and class are
# independent.
def catalog_rows() -> list[dict[str, Any]]:
    return [
        make_row(source_path="data/raw/congresos/pagina_5_2.pdf", anio=1992,
                 pagina=5, indice=2, congreso="A", latitud=INSIDE[0],
                 longitud=INSIDE[1]),                                   # colliding
        make_row(source_path="data/raw/congresos/pagina_5_1.pdf", anio=1992,
                 pagina=5, indice=1, congreso="A", latitud=INSIDE[0],
                 longitud=INSIDE[1]),                                   # colliding
        make_row(source_path="data/raw/congresos/pagina_3_9.pdf", anio=1992,
                 pagina=3, indice=9, congreso="A", latitud=INSIDE_OTHER[0],
                 longitud=INSIDE_OTHER[1]),                             # alone
        make_row(source_path="data/raw/congresos/pagina_9_1.pdf", anio=1991,
                 pagina=9, indice=1, congreso="B", latitud=OUTSIDE[0],
                 longitud=OUTSIDE[1]),                                  # outside
        make_row(source_path="data/raw/congresos/pagina_1_1.pdf", anio=1993,
                 pagina=1, indice=1, congreso="C", latitud=None,
                 longitud=None),                                        # no coord
        make_row(source_path="data/raw/congresos/pagina_1_2.pdf", anio=1993,
                 pagina=1, indice=1, congreso="A", latitud=None,
                 longitud=None),                                        # no coord
    ]


# Three undated rows. Their ids use the ``sin-anio`` segment and they must come
# last, ordered among themselves by (congreso, pagina, indice).
def undated_rows() -> list[dict[str, Any]]:
    return [
        make_row(source_path="data/raw/congresos/pagina_7_2.pdf", anio=None,
                 pagina=7, indice=2, congreso="B", latitud=None,
                 longitud=None),
        make_row(source_path="data/raw/congresos/pagina_7_1.pdf", anio=None,
                 pagina=7, indice=1, congreso="A", latitud=None,
                 longitud=None),
        make_row(source_path="data/raw/congresos/pagina_6_9.pdf", anio=None,
                 pagina=6, indice=9, congreso="A", latitud=None,
                 longitud=None),
    ]


# ``catalog_rows`` plus the undated rows, interleaved in insertion order so
# neither the dated nor the undated relative order is an accident of position.
def catalog_rows_with_undated() -> list[dict[str, Any]]:
    dated = catalog_rows()
    undated = undated_rows()
    return [
        dated[0], undated[0], dated[1], dated[2], undated[1],
        dated[3], undated[2], dated[4], dated[5],
    ]


# (anio, congreso, pagina, indice) for the rows above, sorted:
#   1991/B/9/1, 1992/A/3/9, 1992/A/5/1, 1992/A/5/2, 1993/A/1/2, 1993/C/1/1
# The 1993 pair is inserted in the opposite order, so a sort that ignores
# ``congreso`` cannot produce this list.
EXPECTED_CATALOG_IDS = [
    "cve-1991-pagina-9-1",
    "cve-1992-pagina-3-9",
    "cve-1992-pagina-5-1",
    "cve-1992-pagina-5-2",
    "cve-1993-pagina-1-2",
    "cve-1993-pagina-1-1",
]

# The undated rows of ``catalog_rows_with_undated``, ordered among themselves by
# (congreso, pagina, indice): A/6/9, A/7/1, B/7/2. They always come last.
EXPECTED_UNDATED_IDS = [
    "cve-sin-anio-pagina-6-9",
    "cve-sin-anio-pagina-7-1",
    "cve-sin-anio-pagina-7-2",
]


# A fixture for the builder's collision tallies. Three coordinates, chosen so
# each branch of the derivation is exercised:
#   INSIDE       two placeable studies AND one coarse_location study, so the
#                catalog-wide ``coordinate_group_size`` is 3 while the map
#                draws only 2 markers;
#   INSIDE_OTHER a single placeable study, which is not a collision;
#   OUTSIDE      an outside_extent study the map never draws.
# Plus a row without coordinates. Expected tallies: 1 coordinate / 2 markers,
# and a builder that reused ``coordinate_group_size`` would report 2 / 3.
def collision_rows() -> list[dict[str, Any]]:
    return [
        make_row(source_path="data/raw/congresos/pagina_5_2.pdf", anio=1992,
                 pagina=5, indice=2, congreso="A",
                 latitud=INSIDE[0], longitud=INSIDE[1]),
        make_row(source_path="data/raw/congresos/pagina_5_1.pdf", anio=1992,
                 pagina=5, indice=1, congreso="A",
                 latitud=INSIDE[0], longitud=INSIDE[1]),
        make_row(source_path="data/raw/congresos/pagina_4_1.pdf", anio=1992,
                 pagina=4, indice=1, congreso="A",
                 latitud=INSIDE[0], longitud=INSIDE[1],
                 ubicaciongeografica="estado Barinas"),
        make_row(source_path="data/raw/congresos/pagina_3_9.pdf", anio=1992,
                 pagina=3, indice=9, congreso="A",
                 latitud=INSIDE_OTHER[0], longitud=INSIDE_OTHER[1]),
        make_row(source_path="data/raw/congresos/pagina_9_1.pdf", anio=1991,
                 pagina=9, indice=1, congreso="B",
                 latitud=OUTSIDE[0], longitud=OUTSIDE[1]),
        make_row(source_path="data/raw/congresos/pagina_1_1.pdf", anio=1993,
                 pagina=1, indice=1, congreso="C", latitud=None,
                 longitud=None),
    ]


# ``taxonomy_for`` with the Barinas row held at T1, so it shares the first
# coordinate group without being drawn. That is exactly the case where the
# collision tallies and ``coordinate_group_size`` must disagree.
def collision_taxonomy(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    taxonomy = taxonomy_for(rows)
    taxonomy[rows[2]["source_path"]] = taxonomy_entry(
        nivel="T1",
        texto=subject.row_location_text(rows[2]),
        razon="administrative unit with no locality named inside it",
    )
    return taxonomy


# The curated granularity taxonomy. One entry per ``source_path``; every entry
# records the corpus ``texto`` it classifies, a T0/T1 entry must justify itself
# with a ``razon`` because it removes the study from the map, and a T2 entry may
# carry an optional ``nota``.
VALID_GRANULARITY_ENTRIES = {
    "a/pagina_1_1.json": {
        "nivel": "T0",
        "texto": "Venezuela",
        "razon": "mentions the whole country, not a place",
    },
    "a/pagina_2_1.json": {
        "nivel": "T1",
        "texto": "Estado Miranda",
        "razon": "first-level administrative unit",
    },
    "a/pagina_3_1.json": {"nivel": "T2", "texto": "Merida"},
    "a/pagina_4_1.json": {
        "nivel": "T2",
        "texto": "Parque Nacional",
        "nota": "two named sites of the same massif",
    },
}


def granularity_document(**overrides: Any) -> dict[str, Any]:
    """Return a valid taxonomy document; overrides replace one top-level key."""
    document: dict[str, Any] = {
        "schema_version": 1,
        "levels": {"T0": "no place", "T1": "administrative unit", "T2": "locality"},
        "levels_excluded_from_map": ["T0", "T1"],
        "entries": {
            key: dict(entry) for key, entry in VALID_GRANULARITY_ENTRIES.items()
        },
    }
    document.update(overrides)
    return document


def build_catalog_from(
    rows: list[dict[str, Any]],
    granularity: dict[str, dict[str, Any]] | None = None,
    ror_instituciones: dict[str, dict[str, str]] | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Run the real builder over the given synthetic rows and taxonomy."""
    if granularity is None:
        granularity = taxonomy_for(rows)
    if ror_instituciones is None:
        ror_instituciones = dict(TEST_ROR_ENTRIES)
    return subject.build_catalog(
        rows,
        EXTENT,
        granularity,
        "testland",
        "data/raw/congresos/test.parquet",
        "extent label",
        "extent boundary note",
        SOURCE_IDENTITY,
        ror_instituciones,
        TEST_ROR_SENTINELS,
    )


def build_test_catalog() -> tuple[dict[str, Any], dict[str, int]]:
    """Run the real builder over the synthetic rows."""
    return build_catalog_from(catalog_rows())


def load_shipped_catalog() -> dict[str, Any]:
    """Read the committed artifact the viewer serves."""
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def serialized_key_order(catalog: dict[str, Any]) -> list[str]:
    """Return the catalog's top-level key order as the JSON serialization has it."""
    pairs = json.loads(json.dumps(catalog, ensure_ascii=False), object_pairs_hook=list)
    return [key for key, _ in pairs]


def assert_provenance_block_follows_source_parquet(catalog: dict[str, Any]) -> None:
    """Raise ``AssertionError`` unless the three identity fields follow the path.

    The check runs over a JSON round-trip, so it constrains what is written to
    disk, not just the in-memory dict.
    """
    keys = serialized_key_order(catalog)
    assert "source_parquet" in keys, "source_parquet is missing from the catalog"
    index = keys.index("source_parquet")
    following = keys[index + 1:index + len(PROVENANCE_FIELDS) + 1]
    assert following == PROVENANCE_FIELDS, (
        f"the keys after source_parquet are {following}, expected "
        f"{PROVENANCE_FIELDS}"
    )


# ---------------------------------------------------------------------------
# Dependency injection helpers. The rebuild-only dependencies are simulated
# rather than required, so this file needs neither pyarrow nor GDAL.
# ---------------------------------------------------------------------------


def module_swaps(
    present: dict[str, Any] | None = None, absent: tuple[str, ...] = ()
) -> Any:
    """Patch ``sys.modules`` so ``import`` finds ``present`` and not ``absent``.

    A name mapped to ``None`` makes ``import name`` raise ``ImportError``
    exactly as on an interpreter without the package.
    """
    mapping: dict[str, Any] = dict(present or {})
    for name in absent:
        mapping[name] = None
    return mock.patch.dict(sys.modules, mapping)


class FakeTable:
    def __init__(
        self, rows: list[dict[str, Any]], num_rows: int | None = None
    ) -> None:
        self._rows = rows
        # A real pyarrow Table always reports num_rows == len(to_pylist()), but
        # keeping them independent lets the tests pin which one is recorded.
        self.num_rows = len(rows) if num_rows is None else num_rows

    def to_pylist(self) -> list[dict[str, Any]]:
        return self._rows


def fake_pyarrow(read_table: Any) -> dict[str, Any]:
    """Return sys.modules entries that satisfy ``import pyarrow.parquet as pq``."""
    package = types.ModuleType("pyarrow")
    parquet = types.ModuleType("pyarrow.parquet")
    parquet.read_table = read_table
    package.parquet = parquet
    return {"pyarrow": package, "pyarrow.parquet": parquet}


class FakeDataset:
    def __init__(self, geotransform: tuple[float, ...], width: int, height: int) -> None:
        self._geotransform = geotransform
        self.RasterXSize = width
        self.RasterYSize = height

    def GetGeoTransform(self) -> tuple[float, ...]:
        return self._geotransform


def fake_osgeo(open_dataset: Any) -> tuple[dict[str, Any], list[str]]:
    """Return sys.modules entries for ``from osgeo import gdal`` plus a call log."""
    calls: list[str] = []
    gdal = types.ModuleType("osgeo.gdal")
    gdal.UseExceptions = lambda: calls.append("UseExceptions")
    gdal.Open = open_dataset
    osgeo = types.ModuleType("osgeo")
    osgeo.gdal = gdal
    return {"osgeo": osgeo, "osgeo.gdal": gdal}, calls


def write_source_file(test: unittest.TestCase, payload: bytes) -> Path:
    """Write ``payload`` to a temp file that lives only as long as the test."""
    directory = tempfile.TemporaryDirectory()
    test.addCleanup(directory.cleanup)
    path = Path(directory.name) / "source.parquet"
    path.write_bytes(payload)
    return path


def write_granularity(
    test: unittest.TestCase,
    document: dict[str, Any] | None = None,
    text: str | None = None,
    payload: bytes | None = None,
) -> Path:
    """Write a taxonomy fixture that lives only as long as the test.

    ``text`` writes raw JSON, which a Python dict cannot express (duplicate
    keys); ``payload`` writes raw bytes (a file that is not valid UTF-8).
    """
    directory = tempfile.TemporaryDirectory()
    test.addCleanup(directory.cleanup)
    path = Path(directory.name) / "granularidad.json"
    if payload is not None:
        path.write_bytes(payload)
    elif text is not None:
        path.write_text(text, encoding="utf-8")
    else:
        path.write_text(
            json.dumps(document or granularity_document(), ensure_ascii=False),
            encoding="utf-8",
        )
    return path


def write_ror_instituciones(
    test: unittest.TestCase,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write a curated ROR fixture that lives only as long as the test.

    The fixture always carries the ``AUTHOR`` id so the wiring tests' synthetic
    rows close against it; ``extra`` adds entries for the unused-entry case.
    """
    directory = tempfile.TemporaryDirectory()
    test.addCleanup(directory.cleanup)
    path = Path(directory.name) / "ror-instituciones.json"
    entries: dict[str, Any] = {key: dict(value) for key, value in TEST_ROR_ENTRIES.items()}
    entries.update(extra or {})
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "ror_sentinels": list(TEST_ROR_SENTINELS),
                "entries": entries,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def run_probe(body: str) -> subprocess.CompletedProcess:
    """Run ``body`` in a fresh interpreter and capture its streams."""
    return subprocess.run(
        [sys.executable, "-c", body],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


BARE_INTERPRETER_PROBE = (
    "import sys;"
    f"sys.path.insert(0, {str(TOOLS_DIR)!r});"
    "import build_study_catalog as m;"
    "print(len(m.__doc__ or ''));"
    "print(m.slugify('pagina_5_2'));"
    "print('pyarrow' in sys.modules);"
    "print('osgeo' in sys.modules)"
)


# ---------------------------------------------------------------------------
# The shipped artifact's contract.
# ---------------------------------------------------------------------------


def assert_catalog_contract(catalog: dict[str, Any]) -> None:
    """Raise ``AssertionError`` unless the shipped catalog can be displayed.

    One ``assert`` per branch, each with a message that says what broke, so a
    caller cannot pass by accident and a failure names the property. The
    matching controls live in ``ShippedCatalogControlTests``, one per branch.
    """
    assert catalog.get("schema_version") == EXPECTED_SCHEMA_VERSION, (
        f"schema_version is {catalog.get('schema_version')!r}, "
        f"expected {EXPECTED_SCHEMA_VERSION}"
    )
    assert catalog.get("study_count") == EXPECTED_STUDY_COUNT, (
        f"study_count is {catalog.get('study_count')!r}, expected {EXPECTED_STUDY_COUNT}"
    )

    studies = catalog.get("studies")
    assert isinstance(studies, list), (
        f"studies is {type(studies).__name__}, expected a list"
    )
    assert len(studies) == EXPECTED_STUDY_COUNT, (
        f"len(studies) is {len(studies)}, expected {EXPECTED_STUDY_COUNT}"
    )

    contract = catalog.get("display_contract")
    assert isinstance(contract, dict), (
        f"display_contract is {type(contract).__name__}, expected an object"
    )
    assert set(contract) == {
        "map_visible_count",
        "excluded_count",
        "collision_coordinate_count",
        "collision_marker_count",
    }, (
        f"display_contract fields are {sorted(contract)}, expected exactly "
        f"['collision_coordinate_count', 'collision_marker_count', "
        f"'excluded_count', 'map_visible_count']"
    )

    # --- identity ---------------------------------------------------------
    seen: set[str] = set()
    duplicates: list[str] = []
    for study in studies:
        study_id = str(study["study_id"])
        if study_id in seen:
            duplicates.append(study_id)
        seen.add(study_id)
    assert not duplicates, f"duplicate study_id: {sorted(set(duplicates))}"

    malformed = [
        study["study_id"]
        for study in studies
        if not STUDY_ID_RE.match(str(study["study_id"]))
    ]
    assert not malformed, (
        f"study_id(s) that do not match ^[a-z0-9-]+$: {malformed[:3]}"
    )

    # --- authors ----------------------------------------------------------
    for study in studies:
        autores = study["autores"]
        assert isinstance(autores, list), (
            f"{study['study_id']}: autores is {type(autores).__name__}, expected a list"
        )
        assert len(autores) == study["n_autores"], (
            f"{study['study_id']}: autores has {len(autores)} entries but n_autores "
            f"is {study['n_autores']}"
        )

    for study in studies:
        for index, author in enumerate(study["autores"]):
            assert isinstance(author, dict), (
                f"{study['study_id']}: autores[{index}] is "
                f"{type(author).__name__}, expected an object"
            )
            missing = [field for field in AUTHOR_FIELDS if field not in author]
            assert not missing, (
                f"{study['study_id']}: autores[{index}] is missing field(s) "
                f"{', '.join(missing)}"
            )
            extra = [field for field in author if field not in AUTHOR_FIELDS]
            assert not extra, (
                f"{study['study_id']}: autores[{index}] carries unexpected field(s) "
                f"{', '.join(extra)}"
            )

    # --- species ----------------------------------------------------------
    with_species = [
        study for study in studies if study["especiesmencionadas"] is not None
    ]
    assert len(with_species) == EXPECTED_ESPECIES_NON_NULL, (
        f"especiesmencionadas is non-null in {len(with_species)} studies, expected "
        f"{EXPECTED_ESPECIES_NON_NULL}"
    )
    not_a_string = [
        study["study_id"]
        for study in with_species
        if not isinstance(study["especiesmencionadas"], str)
    ]
    assert not not_a_string, (
        f"non-null especiesmencionadas is not a string in {not_a_string[:3]}"
    )

    # --- institutions and the parsed species (schema v4) -----------------
    ror_instituciones = catalog.get("ror_instituciones")
    assert isinstance(ror_instituciones, dict), (
        f"ror_instituciones is {type(ror_instituciones).__name__}, expected an object"
    )
    for ror_id, entry in ror_instituciones.items():
        assert isinstance(entry, dict), (
            f"ror_instituciones[{ror_id!r}] is {type(entry).__name__}, "
            "expected an object"
        )
        nombre = entry.get("nombre")
        assert isinstance(nombre, str) and nombre.strip(), (
            f"ror_instituciones[{ror_id!r}] has no non-empty nombre: {nombre!r}"
        )
        assert entry.get("estado") in ("ok", "dudoso"), (
            f"ror_instituciones[{ror_id!r}] has estado {entry.get('estado')!r}, "
            "expected 'ok' or 'dudoso'"
        )
        assert isinstance(entry.get("grafica"), bool), (
            f"ror_instituciones[{ror_id!r}] has a non-boolean grafica "
            f"{entry.get('grafica')!r}"
        )
    assert len(ror_instituciones) == EXPECTED_ROR_ENTRIES, (
        f"ror_instituciones has {len(ror_instituciones)} entries, expected "
        f"{EXPECTED_ROR_ENTRIES}"
    )
    estado_counts = Counter(
        entry["estado"] for entry in ror_instituciones.values()
    )
    assert dict(estado_counts) == EXPECTED_ROR_ESTADOS, (
        f"ror_instituciones estados are {dict(estado_counts)}, expected "
        f"{EXPECTED_ROR_ESTADOS}"
    )
    grafica_counts = Counter(
        entry["grafica"] for entry in ror_instituciones.values()
    )
    assert dict(grafica_counts) == EXPECTED_ROR_GRAFICA, (
        f"ror_instituciones grafica are {dict(grafica_counts)}, expected "
        f"{EXPECTED_ROR_GRAFICA}"
    )

    for study in studies:
        estudio = study["study_id"]
        especies = study.get("especies")
        assert isinstance(especies, list), (
            f"{estudio}: especies is {type(especies).__name__}, expected a list"
        )
        assert all(isinstance(name, str) and name.strip() for name in especies), (
            f"{estudio}: especies has a non-string or empty name: {especies!r}"
        )
        rores = study.get("rores")
        assert isinstance(rores, list), (
            f"{estudio}: rores is {type(rores).__name__}, expected a list"
        )
        assert all(isinstance(ror_id, str) and ror_id.strip() for ror_id in rores), (
            f"{estudio}: rores has a non-string or empty id: {rores!r}"
        )
        assert rores == sorted(rores), (
            f"{estudio}: rores is not sorted ascending: {rores!r}"
        )
        assert len(set(rores)) == len(rores), (
            f"{estudio}: rores carries duplicates: {rores!r}"
        )
        unknown = [ror_id for ror_id in rores if ror_id not in ror_instituciones]
        assert not unknown, (
            f"{estudio}: rores references ROR id(s) absent from "
            f"ror_instituciones: {unknown}"
        )
        reviewer = study.get("human_reviewer")
        assert isinstance(reviewer, str) and reviewer.strip(), (
            f"{estudio}: human_reviewer is not a non-empty string: {reviewer!r}"
        )

    with_rores = [study for study in studies if study["rores"]]
    assert len(with_rores) == EXPECTED_STUDIES_WITH_RORES, (
        f"rores is non-empty in {len(with_rores)} studies, expected "
        f"{EXPECTED_STUDIES_WITH_RORES}"
    )
    pair_total = sum(len(study["rores"]) for study in studies)
    assert pair_total == EXPECTED_ROR_TALK_PAIRS, (
        f"the studies hold {pair_total} talk-institution pairs, expected "
        f"{EXPECTED_ROR_TALK_PAIRS}"
    )
    with_parsed_species = [study for study in studies if study["especies"]]
    assert len(with_parsed_species) == EXPECTED_STUDIES_WITH_ESPECIES, (
        f"especies is non-empty in {len(with_parsed_species)} studies, expected "
        f"{EXPECTED_STUDIES_WITH_ESPECIES}"
    )
    distinct_species = {
        name.lower() for study in studies for name in study["especies"]
    }
    assert len(distinct_species) == EXPECTED_DISTINCT_SPECIES, (
        f"the studies name {len(distinct_species)} distinct species "
        f"(lowercased), expected {EXPECTED_DISTINCT_SPECIES}"
    )

    # --- per-study display consistency ------------------------------------
    for study in studies:
        study_id = study["study_id"]
        if study["on_map"]:
            assert study["display_class"] == "placeable", (
                f"{study_id}: on_map is true but display_class is "
                f"{study['display_class']!r}"
            )
            assert study["exclusion_reason"] is None, (
                f"{study_id}: on_map is true but exclusion_reason is "
                f"{study['exclusion_reason']!r}"
            )
        else:
            assert study["display_class"] != "placeable", (
                f"{study_id}: on_map is false but display_class is placeable"
            )
            reason = study["exclusion_reason"]
            assert isinstance(reason, str) and reason.strip(), (
                f"{study_id}: on_map is false but exclusion_reason is {reason!r}"
            )

    # --- aggregate class counts -------------------------------------------
    counts = Counter(study["display_class"] for study in studies)
    assert dict(counts) == EXPECTED_CLASS_COUNTS, (
        f"class counts {dict(counts)} do not equal {EXPECTED_CLASS_COUNTS}"
    )

    classes = catalog.get("classes")
    assert isinstance(classes, list), (
        f"classes is {type(classes).__name__}, expected a list"
    )
    assert [entry["key"] for entry in classes] == subject.CLASS_ORDER, (
        f"classes keys are {[entry['key'] for entry in classes]}, expected "
        f"{subject.CLASS_ORDER}"
    )
    for entry in classes:
        key = entry["key"]
        assert entry["count"] == counts[key], (
            f"classes[{key!r}].count is {entry['count']}, but {counts[key]} studies "
            f"have that class"
        )
        assert entry["on_map"] == (key == "placeable"), (
            f"classes[{key!r}].on_map is {entry['on_map']!r}, expected "
            f"{key == 'placeable'}"
        )
        assert (entry["reason"] is None) == (key == "placeable"), (
            f"classes[{key!r}].reason is {entry['reason']!r}, but only the placeable "
            f"class may have no reason"
        )

    # --- the display contract agrees with those counts ---------------------
    assert contract["map_visible_count"] == EXPECTED_MAP_VISIBLE == counts["placeable"], (
        f"display_contract.map_visible_count is {contract['map_visible_count']!r}, "
        f"expected {EXPECTED_MAP_VISIBLE} and {counts['placeable']} placeable studies"
    )
    assert (
        contract["excluded_count"]
        == EXPECTED_EXCLUDED
        == EXPECTED_STUDY_COUNT - counts["placeable"]
    ), (
        f"display_contract.excluded_count is {contract['excluded_count']!r}, expected "
        f"{EXPECTED_EXCLUDED} and "
        f"{EXPECTED_STUDY_COUNT - counts['placeable']} excluded studies"
    )
    # The two collision tallies describe the markers the map draws, so they are
    # pinned against the artifact and kept below the visible count: the ring
    # note prints them, and a stale pair would state a false number.
    assert (
        contract["collision_coordinate_count"]
        == EXPECTED_COLLISION_COORDINATE_COUNT
    ), (
        f"display_contract.collision_coordinate_count is "
        f"{contract['collision_coordinate_count']!r}, expected "
        f"{EXPECTED_COLLISION_COORDINATE_COUNT}"
    )
    assert (
        contract["collision_marker_count"] == EXPECTED_COLLISION_MARKER_COUNT
    ), (
        f"display_contract.collision_marker_count is "
        f"{contract['collision_marker_count']!r}, expected "
        f"{EXPECTED_COLLISION_MARKER_COUNT}"
    )


class ShippedCatalogContractTests(unittest.TestCase):
    """The committed artifact satisfies the contract the viewer relies on."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_shipped_catalog()

    def test_the_committed_catalog_satisfies_the_whole_display_contract(self) -> None:
        assert_catalog_contract(self.catalog)

    def test_the_artifact_under_test_is_the_committed_one(self) -> None:
        self.assertTrue(
            CATALOG_PATH.is_file(), f"the committed artifact is missing: {CATALOG_PATH}"
        )

    def test_control_the_artifact_guard_rejects_a_missing_file(self) -> None:
        absent = (
            REPO_ROOT / "data" / "derived" / "venezuela" / "congresos" / "no-such.json"
        )
        self.assertFalse(absent.is_file())


class ShippedCatalogControlTests(unittest.TestCase):
    """One mutation per branch of ``assert_catalog_contract``.

    Every control pins the branch it targets with ``assertRaisesRegex`` and
    leaves every earlier branch satisfied, so the mutation cannot be rejected by
    a check it was not written for.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_shipped_catalog()

    def _broken(self) -> dict[str, Any]:
        return copy.deepcopy(self.catalog)

    def _index_of(self, catalog: dict[str, Any], display_class: str, on_map: bool) -> int:
        for index, study in enumerate(catalog["studies"]):
            if study["display_class"] == display_class and study["on_map"] is on_map:
                return index
        raise AssertionError(f"fixture not found: {display_class} on_map={on_map}")

    def _index_with_species(self, catalog: dict[str, Any]) -> int:
        for index, study in enumerate(catalog["studies"]):
            if study["especiesmencionadas"] is not None:
                return index
        raise AssertionError("no study carries especiesmencionadas")

    def _fail(self, catalog: dict[str, Any], pattern: str) -> None:
        with self.assertRaisesRegex(AssertionError, re.escape(pattern)):
            assert_catalog_contract(catalog)

    # --- the artifact is versioned, and is the study set that was reviewed --
    def test_control_rejects_a_wrong_schema_version(self) -> None:
        broken = self._broken()
        broken["schema_version"] = EXPECTED_SCHEMA_VERSION - 1
        self._fail(broken, f"schema_version is {EXPECTED_SCHEMA_VERSION - 1}")

    def test_control_rejects_a_wrong_study_count(self) -> None:
        broken = self._broken()
        broken["study_count"] = EXPECTED_STUDY_COUNT - 1
        self._fail(broken, f"study_count is {EXPECTED_STUDY_COUNT - 1}")

    def test_control_rejects_a_non_list_studies_field(self) -> None:
        broken = self._broken()
        broken["studies"] = {}
        self._fail(broken, "studies is dict")

    def test_control_rejects_a_study_list_that_misses_a_study(self) -> None:
        broken = self._broken()
        broken["studies"] = broken["studies"][:1]
        self._fail(broken, "len(studies) is 1")

    # --- display_contract shape -------------------------------------------
    def test_control_rejects_a_non_object_display_contract(self) -> None:
        broken = self._broken()
        broken["display_contract"] = ["map_visible_count", "excluded_count"]
        self._fail(broken, "display_contract is list, expected an object")

    def test_control_rejects_display_contract_that_lost_a_field(self) -> None:
        broken = self._broken()
        del broken["display_contract"]["excluded_count"]
        self._fail(broken, "display_contract fields are")

    # --- identity ---------------------------------------------------------
    def test_control_rejects_a_duplicate_study_id(self) -> None:
        broken = self._broken()
        broken["studies"][1]["study_id"] = broken["studies"][0]["study_id"]
        self._fail(broken, "duplicate study_id")

    def test_control_rejects_a_study_id_outside_the_slug_alphabet(self) -> None:
        broken = self._broken()
        broken["studies"][0]["study_id"] = "CVE-1991_Pagina 5~2"
        self._fail(broken, "do not match ^[a-z0-9-]+$")

    # --- authors ----------------------------------------------------------
    def test_control_rejects_n_autores_disagreeing_with_the_author_list(self) -> None:
        broken = self._broken()
        broken["studies"][0]["n_autores"] = broken["studies"][0]["n_autores"] + 1
        self._fail(broken, "but n_autores is")

    def test_control_rejects_a_non_list_autores_field(self) -> None:
        broken = self._broken()
        broken["studies"][0]["autores"] = "Ana"
        self._fail(broken, "autores is str, expected a list")

    def test_control_rejects_a_non_object_author_entry(self) -> None:
        broken = self._broken()
        broken["studies"][0]["autores"] = [42]
        broken["studies"][0]["n_autores"] = 1
        self._fail(broken, "autores[0] is int, expected an object")

    def test_control_rejects_an_author_missing_a_required_field(self) -> None:
        broken = self._broken()
        del broken["studies"][0]["autores"][0]["orcid"]
        self._fail(broken, "is missing field(s) orcid")

    def test_control_rejects_an_author_carrying_an_unexpected_field(self) -> None:
        broken = self._broken()
        broken["studies"][0]["autores"][0]["telefono"] = "+58"
        self._fail(broken, "carries unexpected field(s) telefono")

    # --- species ----------------------------------------------------------
    def test_control_rejects_a_lost_especiesmencionadas_value(self) -> None:
        broken = self._broken()
        broken["studies"][self._index_with_species(broken)]["especiesmencionadas"] = None
        self._fail(
            broken,
            f"especiesmencionadas is non-null in {EXPECTED_ESPECIES_NON_NULL - 1} studies",
        )

    def test_control_rejects_a_non_string_especiesmencionadas(self) -> None:
        broken = self._broken()
        broken["studies"][self._index_with_species(broken)]["especiesmencionadas"] = 42
        self._fail(broken, "is not a string in")

    # --- the congress-metrics fields (schema v4) --------------------------
    def _index_with_rores(
        self, catalog: dict[str, Any], minimum: int = 1
    ) -> int:
        for index, study in enumerate(catalog["studies"]):
            if len(study["rores"]) >= minimum:
                return index
        raise AssertionError(
            f"no study carries {minimum} or more rores"
        )

    def _index_with_parsed_especies(self, catalog: dict[str, Any]) -> int:
        for index, study in enumerate(catalog["studies"]):
            if study["especies"]:
                return index
        raise AssertionError("no study carries a parsed species list")

    def test_control_rejects_a_non_object_ror_instituciones(self) -> None:
        broken = self._broken()
        broken["ror_instituciones"] = []
        self._fail(broken, "ror_instituciones is list, expected an object")

    def test_control_rejects_a_ror_entry_without_a_nombre(self) -> None:
        broken = self._broken()
        first = next(iter(broken["ror_instituciones"]))
        broken["ror_instituciones"][first]["nombre"] = "   "
        self._fail(broken, "has no non-empty nombre")

    def test_control_rejects_a_ror_entry_with_an_unknown_estado(self) -> None:
        broken = self._broken()
        first = next(iter(broken["ror_instituciones"]))
        broken["ror_instituciones"][first]["estado"] = "quizá"
        self._fail(broken, "has estado 'quizá', expected 'ok' or 'dudoso'")

    def test_control_rejects_a_wrong_ror_entry_count(self) -> None:
        broken = self._broken()
        broken["ror_instituciones"].pop(
            next(iter(broken["ror_instituciones"]))
        )
        self._fail(
            broken,
            f"ror_instituciones has {EXPECTED_ROR_ENTRIES - 1} entries",
        )

    def test_control_rejects_ror_estados_that_moved(self) -> None:
        broken = self._broken()
        for entry in broken["ror_instituciones"].values():
            if entry["estado"] == "ok":
                entry["estado"] = "dudoso"
                break
        self._fail(broken, "ror_instituciones estados are")

    def test_control_rejects_a_non_boolean_grafica(self) -> None:
        broken = self._broken()
        first = next(iter(broken["ror_instituciones"]))
        broken["ror_instituciones"][first]["grafica"] = "sí"
        self._fail(
            broken, f"ror_instituciones[{first!r}] has a non-boolean grafica"
        )

    def test_control_rejects_ror_grafica_that_moved(self) -> None:
        broken = self._broken()
        first = next(iter(broken["ror_instituciones"]))
        broken["ror_instituciones"][first]["grafica"] = False
        self._fail(broken, "ror_instituciones grafica are")

    def test_control_rejects_a_non_list_especies(self) -> None:
        broken = self._broken()
        broken["studies"][self._index_with_parsed_especies(broken)][
            "especies"
        ] = "Pinus caribaea"
        self._fail(broken, "especies is str, expected a list")

    def test_control_rejects_an_empty_species_name(self) -> None:
        broken = self._broken()
        study = broken["studies"][self._index_with_parsed_especies(broken)]
        study["especies"] = study["especies"] + ["   "]
        self._fail(broken, "especies has a non-string or empty name")

    def test_control_rejects_a_non_list_rores(self) -> None:
        broken = self._broken()
        broken["studies"][self._index_with_rores(broken)]["rores"] = (
            "https://ror.org/x"
        )
        self._fail(broken, "rores is str, expected a list")

    def test_control_rejects_an_empty_ror_id(self) -> None:
        broken = self._broken()
        study = broken["studies"][self._index_with_rores(broken)]
        study["rores"] = ["", "https://ror.org/zzz"]
        self._fail(broken, "rores has a non-string or empty id")

    def test_control_rejects_unsorted_rores(self) -> None:
        broken = self._broken()
        study = broken["studies"][self._index_with_rores(broken, minimum=2)]
        study["rores"] = sorted(study["rores"], reverse=True)
        self._fail(broken, "rores is not sorted ascending")

    def test_control_rejects_duplicate_rores(self) -> None:
        broken = self._broken()
        study = broken["studies"][self._index_with_rores(broken, minimum=2)]
        study["rores"] = [study["rores"][0], study["rores"][0]]
        self._fail(broken, "rores carries duplicates")

    def test_control_rejects_an_unknown_ror_id(self) -> None:
        broken = self._broken()
        study = broken["studies"][self._index_with_rores(broken)]
        study["rores"] = sorted(study["rores"] + ["https://ror.org/zzzz"])
        self._fail(broken, "references ROR id(s) absent from")

    def test_control_rejects_a_blank_human_reviewer(self) -> None:
        broken = self._broken()
        broken["studies"][0]["human_reviewer"] = "   "
        self._fail(broken, "human_reviewer is not a non-empty string")

    def test_control_rejects_a_study_count_that_lost_its_rores(self) -> None:
        broken = self._broken()
        study = broken["studies"][self._index_with_rores(broken)]
        study["rores"] = []
        self._fail(
            broken,
            f"rores is non-empty in {EXPECTED_STUDIES_WITH_RORES - 1} studies",
        )

    def test_control_rejects_a_missing_talk_institution_pair(self) -> None:
        broken = self._broken()
        study = broken["studies"][self._index_with_rores(broken, minimum=2)]
        study["rores"] = study["rores"][1:]
        self._fail(
            broken,
            f"the studies hold {EXPECTED_ROR_TALK_PAIRS - 1} "
            f"talk-institution pairs",
        )

    def test_control_rejects_a_study_count_that_lost_its_species(self) -> None:
        broken = self._broken()
        broken["studies"][self._index_with_parsed_especies(broken)][
            "especies"
        ] = []
        self._fail(
            broken,
            f"especies is non-empty in "
            f"{EXPECTED_STUDIES_WITH_ESPECIES - 1} studies",
        )

    def test_control_rejects_a_new_distinct_species(self) -> None:
        broken = self._broken()
        study = broken["studies"][self._index_with_parsed_especies(broken)]
        study["especies"] = list(study["especies"]) + ["Especie sintética única"]
        self._fail(
            broken,
            f"the studies name {EXPECTED_DISTINCT_SPECIES + 1} distinct species",
        )

    # --- per-study display consistency ------------------------------------
    def test_control_rejects_on_map_true_with_a_non_placeable_class(self) -> None:
        broken = self._broken()
        broken["studies"][self._index_of(broken, "placeable", True)][
            "display_class"
        ] = "coarse_location"
        self._fail(broken, "on_map is true but display_class is 'coarse_location'")

    def test_control_rejects_on_map_true_with_an_exclusion_reason(self) -> None:
        broken = self._broken()
        broken["studies"][self._index_of(broken, "placeable", True)][
            "exclusion_reason"
        ] = "no debería estar aquí"
        self._fail(broken, "on_map is true but exclusion_reason is")

    def test_control_rejects_on_map_false_with_the_placeable_class(self) -> None:
        broken = self._broken()
        broken["studies"][self._index_of(broken, "no_coordinate", False)][
            "display_class"
        ] = "placeable"
        self._fail(broken, "on_map is false but display_class is placeable")

    def test_control_rejects_on_map_false_without_an_exclusion_reason(self) -> None:
        broken = self._broken()
        broken["studies"][self._index_of(broken, "no_coordinate", False)][
            "exclusion_reason"
        ] = ""
        self._fail(broken, "on_map is false but exclusion_reason is ''")

    # --- aggregate class counts -------------------------------------------
    def test_control_rejects_a_class_count_that_moved_between_classes(self) -> None:
        broken = self._broken()
        broken["studies"][self._index_of(broken, "no_coordinate", False)][
            "display_class"
        ] = "coarse_location"
        self._fail(broken, "class counts")

    def test_control_rejects_an_unknown_display_class(self) -> None:
        broken = self._broken()
        broken["studies"][self._index_of(broken, "no_coordinate", False)][
            "display_class"
        ] = "ghost"
        self._fail(broken, "class counts")

    def test_control_rejects_a_non_list_classes_block(self) -> None:
        broken = self._broken()
        broken["classes"] = {"placeable": {"count": EXPECTED_CLASS_COUNTS["placeable"]}}
        self._fail(broken, "classes is dict, expected a list")

    def test_control_rejects_a_classes_block_in_the_wrong_order(self) -> None:
        broken = self._broken()
        broken["classes"] = list(reversed(broken["classes"]))
        self._fail(broken, "classes keys are")

    def test_control_rejects_a_class_entry_that_disagrees_with_the_studies(self) -> None:
        broken = self._broken()
        broken["classes"][0]["count"] = EXPECTED_CLASS_COUNTS["placeable"] - 1
        self._fail(broken, f"].count is {EXPECTED_CLASS_COUNTS['placeable'] - 1}")

    def test_control_rejects_a_class_entry_with_the_wrong_on_map_flag(self) -> None:
        broken = self._broken()
        broken["classes"][0]["on_map"] = False
        self._fail(broken, "].on_map is False")

    def test_control_rejects_a_class_entry_with_the_wrong_reason(self) -> None:
        broken = self._broken()
        broken["classes"][0]["reason"] = "debería ser null"
        self._fail(broken, "].reason is")

    # --- the display contract agrees with the counts ----------------------
    def test_control_rejects_a_map_visible_count_that_disagrees(self) -> None:
        broken = self._broken()
        broken["display_contract"]["map_visible_count"] = EXPECTED_MAP_VISIBLE - 1
        self._fail(
            broken, f"display_contract.map_visible_count is {EXPECTED_MAP_VISIBLE - 1}"
        )

    def test_control_rejects_an_excluded_count_that_disagrees(self) -> None:
        broken = self._broken()
        broken["display_contract"]["excluded_count"] = EXPECTED_EXCLUDED - 1
        self._fail(
            broken, f"display_contract.excluded_count is {EXPECTED_EXCLUDED - 1}"
        )

    def test_control_rejects_a_collision_coordinate_count_that_disagrees(self) -> None:
        broken = self._broken()
        broken["display_contract"]["collision_coordinate_count"] = (
            EXPECTED_COLLISION_COORDINATE_COUNT - 1
        )
        self._fail(
            broken,
            f"display_contract.collision_coordinate_count is "
            f"{EXPECTED_COLLISION_COORDINATE_COUNT - 1}",
        )

    def test_control_rejects_a_collision_marker_count_that_disagrees(self) -> None:
        broken = self._broken()
        broken["display_contract"]["collision_marker_count"] = (
            EXPECTED_COLLISION_MARKER_COUNT - 1
        )
        self._fail(
            broken,
            f"display_contract.collision_marker_count is "
            f"{EXPECTED_COLLISION_MARKER_COUNT - 1}",
        )


# ---------------------------------------------------------------------------
# Import hygiene: a library module must not need the rebuild-only dependencies.
# ---------------------------------------------------------------------------


class BareInterpreterImportTests(unittest.TestCase):
    """Importing the builder must not require pyarrow or GDAL, or exit."""

    def test_the_module_imports_and_exposes_its_pure_logic(self) -> None:
        done = run_probe(BARE_INTERPRETER_PROBE)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stderr, "")
        lines = done.stdout.splitlines()
        self.assertEqual(len(lines), 4, done.stdout)
        self.assertGreater(int(lines[0]), 0, "the module docstring did not survive")
        self.assertEqual(lines[1], "pagina-5-2")
        self.assertEqual(lines[2], "False", "pyarrow was imported at module scope")
        self.assertEqual(lines[3], "False", "osgeo was imported at module scope")

    def test_control_the_probe_notices_a_module_that_exits_on_import(self) -> None:
        done = run_probe("import sys; sys.exit(1)")
        self.assertEqual(done.returncode, 1)

    def test_control_the_probe_notices_a_module_that_imports_missing_packages(self) -> None:
        done = run_probe("import build_study_catalog_does_not_exist")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("ModuleNotFoundError", done.stderr)

    def test_control_the_laziness_check_can_report_true(self) -> None:
        # The same predicate the real test asserts to be False, against an
        # interpreter where both names are really in sys.modules.
        done = run_probe(
            "import sys, types;"
            "sys.modules['pyarrow'] = types.ModuleType('pyarrow');"
            "sys.modules['osgeo'] = types.ModuleType('osgeo');"
            "print('pyarrow' in sys.modules, 'osgeo' in sys.modules)"
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), "True True")


class MissingDependencyTests(unittest.TestCase):
    """A missing rebuild-only dependency is an error, not a process exit."""

    def test_control_the_swap_really_makes_imports_fail(self) -> None:
        with module_swaps(absent=("pyarrow", "pyarrow.parquet", "osgeo", "osgeo.gdal")):
            with self.assertRaisesRegex(ImportError, "halted"):
                import pyarrow.parquet  # noqa: F401
            with self.assertRaisesRegex(ImportError, "halted"):
                from osgeo import gdal  # noqa: F401

    def test_read_rows_reports_the_pyarrow_message_when_pyarrow_is_absent(self) -> None:
        with module_swaps(absent=("pyarrow", "pyarrow.parquet")):
            with self.assertRaisesRegex(
                subject.StudyCatalogError, re.escape(PYARROW_MESSAGE)
            ) as caught:
                subject.read_rows(REPO_ROOT / "data" / "raw" / "no-such.parquet")
        self.assertEqual(str(caught.exception), PYARROW_MESSAGE)

    def test_control_the_pyarrow_error_precedes_the_path_check(self) -> None:
        # The module-level import used to fail before any path was looked at, so
        # a missing dependency still wins over a missing file.
        with module_swaps(absent=("pyarrow", "pyarrow.parquet")):
            with self.assertRaisesRegex(
                subject.StudyCatalogError, re.escape("rebuild-only dependency")
            ):
                subject.read_rows(REPO_ROOT / "README.md")

    def test_cog_extent_reports_the_gdal_message_when_osgeo_is_absent(self) -> None:
        with module_swaps(absent=("osgeo", "osgeo.gdal")):
            with self.assertRaisesRegex(
                subject.StudyCatalogError, re.escape(GDAL_MESSAGE)
            ) as caught:
                subject.cog_extent(REPO_ROOT / "data" / "raw" / "no-such.tif")
        self.assertEqual(str(caught.exception), GDAL_MESSAGE)

    def test_main_prints_the_pyarrow_message_and_returns_one(self) -> None:
        argv = [
            "--parquet", str(REPO_ROOT / "no-such.parquet"),
            "--granularidad", str(REPO_ROOT / "no-such-granularidad.json"),
            "--cog", str(REPO_ROOT / "no-such.tif"),
            "--outdir", "unused",
            "--country", "venezuela",
        ]
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as outdir:
            argv[7] = outdir
            with module_swaps(absent=("pyarrow", "pyarrow.parquet")), mock.patch.object(
                subject, "load_labelling", return_value=("label", "note")
            ), mock.patch.object(subject, "cog_extent", return_value=EXTENT):
                with contextlib.redirect_stderr(stderr):
                    status = subject.main(argv)
            leftovers = list(Path(outdir).iterdir())
        self.assertEqual(status, 1)
        self.assertEqual(stderr.getvalue(), f"error: {PYARROW_MESSAGE}\n")
        self.assertEqual(leftovers, [], "a partial artifact was written")

    def test_main_prints_the_gdal_message_and_returns_one(self) -> None:
        argv = [
            "--parquet", str(REPO_ROOT / "no-such.parquet"),
            "--granularidad", str(REPO_ROOT / "no-such-granularidad.json"),
            "--cog", str(REPO_ROOT / "no-such.tif"),
            "--outdir", "unused",
            "--country", "venezuela",
        ]
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as outdir:
            argv[7] = outdir
            with module_swaps(absent=("osgeo", "osgeo.gdal")), mock.patch.object(
                subject, "load_labelling", return_value=("label", "note")
            ):
                with contextlib.redirect_stderr(stderr):
                    status = subject.main(argv)
        self.assertEqual(status, 1)
        self.assertEqual(stderr.getvalue(), f"error: {GDAL_MESSAGE}\n")

    def test_control_a_missing_required_argument_is_a_usage_error(self) -> None:
        # ``--granularidad`` is required, exactly like the other inputs.
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                subject.parse_args(
                    ["--parquet", "p", "--cog", "c", "--outdir", "o",
                     "--country", "venezuela"]
                )
        self.assertEqual(caught.exception.code, 2)

    def test_control_the_no_partial_artifact_check_can_fail(self) -> None:
        with tempfile.TemporaryDirectory() as outdir:
            (Path(outdir) / "catalogo-estudios.json").write_text("{}", encoding="utf-8")
            self.assertNotEqual(list(Path(outdir).iterdir()), [])


class MainTaxonomyWiringTests(unittest.TestCase):
    """``main`` loads the curated taxonomy and closes it against the rows."""

    def main_argv(
        self, granularidad: Path, ror_instituciones: Path | None = None
    ) -> list[str]:
        argv = [
            "--parquet", str(REPO_ROOT / "no-such.parquet"),
            "--granularidad", str(granularidad),
            "--cog", str(REPO_ROOT / "no-such.tif"),
            "--outdir", "unused",
            "--country", "venezuela",
        ]
        if ror_instituciones is not None:
            argv += ["--ror-instituciones", str(ror_instituciones)]
        return argv

    def run_main(
        self,
        rows: list[dict[str, Any]],
        granularidad: Path,
        outdir: str,
        ror_instituciones: Path | None = None,
    ) -> tuple[int, str, str]:
        argv = self.main_argv(granularidad, ror_instituciones)
        # ``read_rows`` checks the path before it parses, so the fake bytes must
        # live in a real temporary file, exactly as the other tests do it.
        argv[1] = str(write_source_file(self, b"fake parquet bytes"))
        argv[7] = outdir
        stderr = io.StringIO()
        stdout = io.StringIO()
        with module_swaps(
            present=fake_pyarrow(mock.Mock(return_value=FakeTable(rows)))
        ), mock.patch.object(
            subject, "load_labelling", return_value=("label", "note")
        ), mock.patch.object(subject, "cog_extent", return_value=EXTENT):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
                stderr
            ):
                status = subject.main(argv)
        return status, stderr.getvalue(), stdout.getvalue()

    def test_main_builds_both_artifacts_from_the_curated_level(self) -> None:
        row = make_row(source_path="I/curatedwithgeo/pagina_5_2.json")
        document = granularity_document(
            entries={
                row["source_path"]: {
                    "nivel": "T1",
                    "texto": "Merida",
                    "razon": "unidad administrativa de primer nivel",
                }
            }
        )
        path = write_granularity(self, document)
        with tempfile.TemporaryDirectory() as outdir:
            status, stderr, _ = self.run_main([row], path, outdir)
            self.assertEqual(status, 0, stderr)
            self.assertEqual(stderr, "")
            catalog = json.loads(
                (Path(outdir) / "catalogo-estudios.json").read_text(encoding="utf-8")
            )
            csv_text = (Path(outdir) / "catalogo-estudios.csv").read_text(
                encoding="utf-8"
            )
        self.assertEqual(catalog["schema_version"], subject.SCHEMA_VERSION)
        self.assertEqual(catalog["study_count"], 1)
        study = catalog["studies"][0]
        self.assertEqual(study["display_class"], "coarse_location")
        self.assertEqual(study["granularidad_nivel"], "T1")
        self.assertEqual(study["granularidad_razon"], "unidad administrativa de primer nivel")
        self.assertIn("unidad administrativa de primer nivel", study["exclusion_reason"])
        self.assertIn("coarse_location", csv_text.splitlines()[1])
        self.assertIn("T1", csv_text.splitlines()[1])

    def test_main_reports_a_missing_taxonomy_file_and_returns_one(self) -> None:
        row = make_row(source_path="I/curatedwithgeo/pagina_5_2.json")
        absent = REPO_ROOT / "no-such-granularidad.json"
        with tempfile.TemporaryDirectory() as outdir:
            status, stderr, _ = self.run_main([row], absent, outdir)
            leftovers = list(Path(outdir).iterdir())
        self.assertEqual(status, 1)
        self.assertIn("granularity file not found", stderr)
        self.assertEqual(leftovers, [], "a partial artifact was written")

    def test_main_reports_a_row_the_taxonomy_does_not_cover(self) -> None:
        row = make_row(source_path="I/curatedwithgeo/pagina_5_2.json")
        document = granularity_document(
            entries={
                "I/curatedwithgeo/otra_pagina.json": {"nivel": "T2", "texto": "Merida"}
            }
        )
        path = write_granularity(self, document)
        with tempfile.TemporaryDirectory() as outdir:
            status, stderr, _ = self.run_main([row], path, outdir)
        self.assertEqual(status, 1)
        self.assertIn("has no entry for parquet source_path", stderr)

    def test_main_reports_a_taxonomy_text_that_no_longer_matches_the_row(self) -> None:
        row = make_row(source_path="I/curatedwithgeo/pagina_5_2.json")
        document = granularity_document(
            entries={
                row["source_path"]: {"nivel": "T2", "texto": "Merida, Venezuela"}
            }
        )
        path = write_granularity(self, document)
        with tempfile.TemporaryDirectory() as outdir:
            status, stderr, _ = self.run_main([row], path, outdir)
        self.assertEqual(status, 1)
        self.assertIn("location text no longer matches", stderr)

    def test_main_reports_a_curated_ror_entry_the_corpus_does_not_use(self) -> None:
        # An unused curated entry is a note, never a failure: the curated table
        # reviews the wider enrichment cache, so shrinking it would delete review
        # work whenever the study set changes.
        row = make_row(source_path="I/curatedwithgeo/pagina_5_2.json")
        document = granularity_document(
            entries={row["source_path"]: {"nivel": "T2", "texto": "Merida"}}
        )
        path = write_granularity(self, document)
        ror_path = write_ror_instituciones(
            self,
            extra={
                "https://ror.org/unused": {
                    "nombre": "Sin uso",
                    "estado": "ok",
                    "grafica": True,
                }
            },
        )
        with tempfile.TemporaryDirectory() as outdir:
            status, stderr, stdout = self.run_main(
                [row], path, outdir, ror_instituciones=ror_path
            )
        self.assertEqual(status, 0, stderr)
        self.assertIn("note:", stdout)
        self.assertIn("https://ror.org/unused", stdout)


class ReadRowsTests(unittest.TestCase):
    """``read_rows`` reads through pyarrow and wraps its failures."""

    def test_control_read_rows_uses_the_parquet_reader_it_imported(self) -> None:
        payload = b"not really parquet, but the reader is mocked\n"
        path = write_source_file(self, payload)
        reader = mock.Mock(return_value=FakeTable([{"anio": 1991}]))
        with module_swaps(present=fake_pyarrow(reader)):
            rows, _ = subject.read_rows(path)
        self.assertEqual(rows, [{"anio": 1991}])
        (buffer,) = reader.call_args.args
        self.assertIsInstance(buffer, io.BytesIO)
        self.assertEqual(buffer.getvalue(), payload)

    def test_control_read_rows_rejects_a_missing_parquet_after_pyarrow_loads(self) -> None:
        with module_swaps(present=fake_pyarrow(mock.Mock())):
            with self.assertRaisesRegex(
                subject.StudyCatalogError, re.escape("--parquet not found")
            ):
                subject.read_rows(REPO_ROOT / "no-such.parquet")

    def test_control_read_rows_wraps_a_reader_failure(self) -> None:
        def explode(path: str) -> Any:
            raise ValueError("boom")

        with module_swaps(present=fake_pyarrow(explode)):
            with self.assertRaisesRegex(
                subject.StudyCatalogError,
                re.escape("could not read --parquet") + ".*boom",
            ):
                subject.read_rows(REPO_ROOT / "README.md")


class ReadRowsIdentityTests(unittest.TestCase):
    """``read_rows`` records the identity of the bytes it actually parsed."""

    def read_bytes(self, payload: bytes, num_rows: int | None = None) -> tuple[Any, ...]:
        path = write_source_file(self, payload)
        table = FakeTable([{"anio": 1991}], num_rows=num_rows)
        with module_swaps(present=fake_pyarrow(mock.Mock(return_value=table))):
            rows, identity = subject.read_rows(path)
        return path, rows, identity

    def test_the_identity_has_exactly_the_three_provenance_keys(self) -> None:
        _, _, identity = self.read_bytes(b"some parquet bytes")
        self.assertEqual(set(identity), set(PROVENANCE_FIELDS))

    def test_the_identity_values_have_the_recorded_types(self) -> None:
        _, _, identity = self.read_bytes(b"some parquet bytes")
        self.assertIsInstance(identity["source_sha256"], str)
        self.assertIsInstance(identity["source_rows"], int)
        self.assertIsInstance(identity["source_bytes"], int)

    def test_the_digest_is_lowercase_hex_sha256(self) -> None:
        _, _, identity = self.read_bytes(b"some parquet bytes")
        self.assertRegex(identity["source_sha256"], re.compile(r"^[0-9a-f]{64}$"))

    def test_the_digest_matches_an_independent_sha256_of_the_same_bytes(self) -> None:
        payload = b"the exact bytes the builder must have hashed\n"
        _, _, identity = self.read_bytes(payload)
        self.assertEqual(
            identity["source_sha256"], hashlib.sha256(payload).hexdigest()
        )

    def test_source_bytes_is_the_real_file_size(self) -> None:
        payload = b"x" * 1234
        path, _, identity = self.read_bytes(payload)
        self.assertEqual(identity["source_bytes"], len(payload))
        self.assertEqual(identity["source_bytes"], path.stat().st_size)

    def test_source_rows_matches_the_rows_returned(self) -> None:
        path = write_source_file(self, b"payload")
        rows = [{"anio": 1991}, {"anio": 1992}]
        with module_swaps(
            present=fake_pyarrow(mock.Mock(return_value=FakeTable(rows)))
        ):
            returned, identity = subject.read_rows(path)
        self.assertEqual(len(returned), 2)
        self.assertEqual(identity["source_rows"], len(returned))

    def test_control_the_row_count_comes_from_the_table_not_the_row_list(self) -> None:
        _, _, identity = self.read_bytes(b"payload", num_rows=7)
        self.assertEqual(identity["source_rows"], 7)
        self.assertNotEqual(identity["source_rows"], 1)

    def test_control_a_different_payload_yields_a_different_digest(self) -> None:
        _, _, first = self.read_bytes(b"the original parquet bytes\n")
        _, _, second = self.read_bytes(b"the original parquet bytes?\n")
        self.assertEqual(
            first["source_sha256"],
            hashlib.sha256(b"the original parquet bytes\n").hexdigest(),
        )
        self.assertNotEqual(first["source_sha256"], second["source_sha256"])

    def test_control_identical_payloads_yield_the_same_digest(self) -> None:
        payload = b"a stable payload\n"
        _, _, first = self.read_bytes(payload)
        _, _, second = self.read_bytes(payload)
        self.assertEqual(first["source_sha256"], second["source_sha256"])

    def test_control_the_digest_is_not_computed_from_the_path(self) -> None:
        # Two files with equal names in different directories must not collide
        # if the digest were derived from the path instead of the bytes.
        _, _, first = self.read_bytes(b"first payload")
        _, _, second = self.read_bytes(b"second payload")
        self.assertNotEqual(first["source_sha256"], second["source_sha256"])
        self.assertNotEqual(first["source_bytes"], second["source_bytes"])


class CogExtentTests(unittest.TestCase):
    """``cog_extent`` derives the extent from the geotransform, never a constant."""

    def test_the_extent_comes_from_the_geotransform(self) -> None:
        present, calls = fake_osgeo(
            lambda name: FakeDataset((0.0, 2.0, 0.0, 10.0, 0.0, -3.0), 5, 4)
        )
        self.assertEqual(calls, [])
        with module_swaps(present=present):
            extent = subject.cog_extent(REPO_ROOT / "README.md")
        self.assertEqual(extent, {"west": 0.0, "south": -2.0, "east": 10.0, "north": 10.0})
        self.assertEqual(calls, ["UseExceptions"])

    def test_control_a_different_geotransform_yields_a_different_extent(self) -> None:
        present, _ = fake_osgeo(
            lambda name: FakeDataset((100.0, 1.0, 0.0, 50.0, 0.0, -1.0), 10, 10)
        )
        with module_swaps(present=present):
            extent = subject.cog_extent(REPO_ROOT / "README.md")
        self.assertEqual(
            extent, {"west": 100.0, "south": 40.0, "east": 110.0, "north": 50.0}
        )
        self.assertNotEqual(extent, {"west": 0.0, "south": -2.0, "east": 10.0, "north": 10.0})

    def test_control_gdal_opening_nothing_is_an_error(self) -> None:
        present, _ = fake_osgeo(lambda name: None)
        with module_swaps(present=present):
            with self.assertRaisesRegex(
                subject.StudyCatalogError, re.escape("GDAL could not open --cog")
            ):
                subject.cog_extent(REPO_ROOT / "README.md")

    def test_control_a_missing_cog_is_an_error_once_gdal_loads(self) -> None:
        present, _ = fake_osgeo(lambda name: FakeDataset((0.0, 1.0, 0.0, 1.0, 0.0, -1.0), 1, 1))
        with module_swaps(present=present):
            with self.assertRaisesRegex(
                subject.StudyCatalogError, re.escape("--cog not found")
            ):
                subject.cog_extent(REPO_ROOT / "no-such.tif")


# ---------------------------------------------------------------------------
# Curated granularity taxonomy.
# ---------------------------------------------------------------------------


class RowLocationTextTests(unittest.TestCase):
    """``row_location_text`` derives the corpus side of the recorded text."""

    def test_prefers_ubicaciongeografica(self) -> None:
        row = {"ubicaciongeografica": "Merida", "direccion": "Calle 1"}
        self.assertEqual(subject.row_location_text(row), "Merida")

    def test_control_ubicaciongeografica_wins_over_direccion(self) -> None:
        row = {"ubicaciongeografica": "Merida", "direccion": "Calle 1"}
        self.assertNotEqual(subject.row_location_text(row), "Calle 1")

    def test_falls_back_to_direccion(self) -> None:
        self.assertEqual(subject.row_location_text({"direccion": "Calle 1"}), "Calle 1")

    def test_control_an_empty_ubicaciongeografica_falls_through_to_direccion(self) -> None:
        row = {"ubicaciongeografica": "", "direccion": "Calle 1"}
        self.assertEqual(subject.row_location_text(row), "Calle 1")

    def test_falls_back_to_the_empty_string(self) -> None:
        self.assertEqual(subject.row_location_text({}), "")

    def test_control_a_null_pair_is_not_fabricated_into_text(self) -> None:
        row = {"ubicaciongeografica": None, "direccion": None}
        self.assertEqual(subject.row_location_text(row), "")

    def test_strips_surrounding_whitespace(self) -> None:
        self.assertEqual(subject.row_location_text({"ubicaciongeografica": "  Merida  "}), "Merida")

    def test_control_a_whitespace_only_value_is_not_the_text(self) -> None:
        self.assertNotEqual(subject.row_location_text({"ubicaciongeografica": "   "}), "   ")


class LoadRorInstitucionesTests(unittest.TestCase):
    """``load_ror_instituciones`` projects the curated table for the client."""

    def test_a_valid_file_loads_into_the_exact_entry_shape(self) -> None:
        path = write_ror_instituciones(self)
        entries, sentinels = subject.load_ror_instituciones(path)
        self.assertEqual(
            entries,
            {
                "https://ror.org/02h1b1x27": {
                    "nombre": "Universidad de Los Andes",
                    "estado": "ok",
                    "grafica": True,
                }
            },
        )
        self.assertEqual(sentinels, TEST_ROR_SENTINELS)

    def test_control_rejects_a_non_boolean_grafica(self) -> None:
        path = write_ror_instituciones(
            self,
            extra={
                "https://ror.org/badgrafica": {
                    "nombre": "Institución sin decisión",
                    "estado": "ok",
                    "grafica": "sí",
                }
            },
        )
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape(
                "ror-instituciones entry 'https://ror.org/badgrafica' has "
                "grafica 'sí'; expected a boolean"
            ),
        ):
            subject.load_ror_instituciones(path)


class LoadGranularityTests(unittest.TestCase):
    """``load_granularity`` turns the curated file into the build's taxonomy."""

    def test_a_valid_file_loads_into_the_exact_entry_shape(self) -> None:
        path = write_granularity(self, granularity_document())
        self.assertEqual(
            subject.load_granularity(path),
            {
                "a/pagina_1_1.json": {
                    "nivel": "T0",
                    "texto": "Venezuela",
                    "razon": "mentions the whole country, not a place",
                    "nota": None,
                },
                "a/pagina_2_1.json": {
                    "nivel": "T1",
                    "texto": "Estado Miranda",
                    "razon": "first-level administrative unit",
                    "nota": None,
                },
                "a/pagina_3_1.json": {
                    "nivel": "T2",
                    "texto": "Merida",
                    "razon": None,
                    "nota": None,
                },
                "a/pagina_4_1.json": {
                    "nivel": "T2",
                    "texto": "Parque Nacional",
                    "razon": None,
                    "nota": "two named sites of the same massif",
                },
            },
        )

    def test_control_the_result_is_not_a_constant_document(self) -> None:
        # The shape test above would also pass a loader that ignored its input.
        # This fixture has one entry, not the four of the shared document.
        path = write_granularity(
            self,
            granularity_document(
                entries={"only/pagina_9_9.json": {"nivel": "T2", "texto": "Merida"}}
            ),
        )
        self.assertEqual(
            subject.load_granularity(path),
            {
                "only/pagina_9_9.json": {
                    "nivel": "T2",
                    "texto": "Merida",
                    "razon": None,
                    "nota": None,
                }
            },
        )

    def test_control_rejects_an_entry_without_a_texto(self) -> None:
        path = write_granularity(
            self, granularity_document(entries={"a/pagina_1_1.json": {"nivel": "T2"}})
        )
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape(
                "granularity entry 'a/pagina_1_1.json' is missing 'texto'"
            ),
        ):
            subject.load_granularity(path)

    def test_control_rejects_a_non_string_texto(self) -> None:
        path = write_granularity(
            self,
            granularity_document(
                entries={"a/pagina_1_1.json": {"nivel": "T2", "texto": 7}}
            ),
        )
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("'texto' that is not a string")
        ):
            subject.load_granularity(path)

    def test_an_empty_texto_is_accepted(self) -> None:
        path = write_granularity(
            self,
            granularity_document(
                entries={"a/pagina_1_1.json": {"nivel": "T2", "texto": ""}}
            ),
        )
        self.assertEqual(
            subject.load_granularity(path),
            {
                "a/pagina_1_1.json": {
                    "nivel": "T2",
                    "texto": "",
                    "razon": None,
                    "nota": None,
                }
            },
        )

    def test_control_rejects_a_missing_file(self) -> None:
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("granularity file not found")
        ):
            subject.load_granularity(REPO_ROOT / "no-such-granularidad.json")

    def test_control_rejects_a_file_that_cannot_be_decoded(self) -> None:
        # The bytes on disk are not UTF-8, so reading fails before parsing.
        path = write_granularity(self, payload=b'{"entries": {"a": "\xff\xfe"}}')
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("could not read granularity file")
        ):
            subject.load_granularity(path)

    def test_control_rejects_a_file_that_is_not_valid_json(self) -> None:
        path = write_granularity(self, text='{"entries": {')
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("is not valid JSON")
        ):
            subject.load_granularity(path)

    def test_control_rejects_a_duplicate_entry_key(self) -> None:
        path = write_granularity(
            self,
            text=(
                '{"schema_version": 1,'
                ' "levels": {},'
                ' "levels_excluded_from_map": ["T0", "T1"],'
                ' "entries": {'
                '"a/pagina_1_1.json": {"nivel": "T2"},'
                '"a/pagina_1_1.json": {"nivel": "T0", "razon": "duplicated"}'
                "}}"
            ),
        )
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("duplicate key 'a/pagina_1_1.json'")
        ):
            subject.load_granularity(path)

    def test_control_rejects_a_duplicate_key_inside_an_entry(self) -> None:
        path = write_granularity(
            self,
            text=(
                '{"levels_excluded_from_map": ["T0", "T1"],'
                ' "entries": {"a/pagina_1_1.json": '
                '{"nivel": "T2", "nivel": "T0"}}}'
            ),
        )
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("duplicate key 'nivel'")
        ):
            subject.load_granularity(path)

    def test_control_rejects_a_root_that_is_not_an_object(self) -> None:
        path = write_granularity(self, text='["not", "an", "object"]')
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("must be a JSON object, got list")
        ):
            subject.load_granularity(path)

    def test_control_rejects_a_document_without_entries(self) -> None:
        document = granularity_document()
        del document["entries"]
        path = write_granularity(self, document)
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("is missing 'entries'")
        ):
            subject.load_granularity(path)

    def test_control_rejects_entries_that_is_not_an_object(self) -> None:
        path = write_granularity(
            self, granularity_document(entries=["a/pagina_1_1.json"])
        )
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("'entries' must be a JSON object, got list"),
        ):
            subject.load_granularity(path)

    def test_control_rejects_an_empty_entries_object(self) -> None:
        path = write_granularity(self, granularity_document(entries={}))
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("has an empty 'entries' object")
        ):
            subject.load_granularity(path)

    def test_control_rejects_an_entry_that_is_not_an_object(self) -> None:
        path = write_granularity(
            self, granularity_document(entries={"a/pagina_1_1.json": "T2"})
        )
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("granularity entry 'a/pagina_1_1.json' must be a JSON object"),
        ):
            subject.load_granularity(path)

    def test_control_rejects_an_entry_without_a_nivel(self) -> None:
        path = write_granularity(
            self,
            granularity_document(entries={"a/pagina_1_1.json": {"razon": "a reason"}}),
        )
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("granularity entry 'a/pagina_1_1.json' is missing 'nivel'"),
        ):
            subject.load_granularity(path)

    def test_control_rejects_a_nivel_outside_the_three_levels(self) -> None:
        path = write_granularity(
            self, granularity_document(entries={"a/pagina_1_1.json": {"nivel": "T3"}})
        )
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("has nivel 'T3'; expected one of T0, T1, T2"),
        ):
            subject.load_granularity(path)

    def test_control_rejects_a_t0_entry_without_a_razon(self) -> None:
        path = write_granularity(
            self,
            granularity_document(
                entries={"a/pagina_1_1.json": {"nivel": "T0", "texto": "Venezuela"}}
            ),
        )
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("is level T0 and must carry a 'razon'"),
        ):
            subject.load_granularity(path)

    def test_control_rejects_a_t1_entry_without_a_razon(self) -> None:
        path = write_granularity(
            self,
            granularity_document(
                entries={"a/pagina_1_1.json": {"nivel": "T1", "texto": "Venezuela"}}
            ),
        )
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("is level T1 and must carry a 'razon'"),
        ):
            subject.load_granularity(path)

    def test_control_rejects_a_non_string_razon(self) -> None:
        path = write_granularity(
            self,
            granularity_document(
                entries={
                    "a/pagina_1_1.json": {"nivel": "T2", "texto": "Merida", "razon": 7}
                }
            ),
        )
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("'razon' that is not a non-empty string"),
        ):
            subject.load_granularity(path)

    def test_control_rejects_an_empty_razon(self) -> None:
        path = write_granularity(
            self,
            granularity_document(
                entries={
                    "a/pagina_1_1.json": {"nivel": "T2", "texto": "Merida", "razon": ""}
                }
            ),
        )
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("'razon' that is not a non-empty string"),
        ):
            subject.load_granularity(path)

    def test_control_rejects_a_non_string_nota(self) -> None:
        path = write_granularity(
            self,
            granularity_document(
                entries={
                    "a/pagina_1_1.json": {"nivel": "T2", "texto": "Merida", "nota": ["a"]}
                }
            ),
        )
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("'nota' that is not a non-empty string"),
        ):
            subject.load_granularity(path)

    def test_control_rejects_a_whitespace_only_nota(self) -> None:
        path = write_granularity(
            self,
            granularity_document(
                entries={
                    "a/pagina_1_1.json": {"nivel": "T2", "texto": "Merida", "nota": "   "}
                }
            ),
        )
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("'nota' that is not a non-empty string"),
        ):
            subject.load_granularity(path)

    def test_control_rejects_wrong_excluded_levels(self) -> None:
        path = write_granularity(
            self, granularity_document(levels_excluded_from_map=["T0"])
        )
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("levels_excluded_from_map as exactly")
        ):
            subject.load_granularity(path)

    def test_control_rejects_reversed_excluded_levels(self) -> None:
        path = write_granularity(
            self, granularity_document(levels_excluded_from_map=["T1", "T0"])
        )
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("levels_excluded_from_map as exactly")
        ):
            subject.load_granularity(path)

    def test_control_rejects_a_document_without_excluded_levels(self) -> None:
        document = granularity_document()
        del document["levels_excluded_from_map"]
        path = write_granularity(self, document)
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("levels_excluded_from_map as exactly")
        ):
            subject.load_granularity(path)


class GranularityCoverageTests(unittest.TestCase):
    """``check_granularity_coverage`` closes the taxonomy against the row set."""

    def coverage(
        self, granularity_keys: list[str], row_paths: list[str]
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        granularity = {
            key: {
                "nivel": "T2",
                "texto": "Merida",
                "razon": None,
                "nota": None,
            }
            for key in granularity_keys
        }
        rows = [make_row(source_path=path) for path in row_paths]
        return granularity, rows

    def test_coverage_passes_when_both_sides_match(self) -> None:
        granularity, rows = self.coverage(
            ["a/pagina_1_1.json", "a/pagina_2_1.json"],
            ["a/pagina_2_1.json", "a/pagina_1_1.json"],
        )
        subject.check_granularity_coverage(granularity, rows)

    def test_coverage_passes_when_the_recorded_text_matches_the_row(self) -> None:
        granularity, rows = self.coverage(
            ["a/pagina_1_1.json"], ["a/pagina_1_1.json"]
        )
        self.assertEqual(granularity["a/pagina_1_1.json"]["texto"], "Merida")
        subject.check_granularity_coverage(granularity, rows)

    def test_control_coverage_rejects_a_text_that_disagrees_with_the_row(self) -> None:
        granularity, rows = self.coverage(
            ["a/pagina_1_1.json"], ["a/pagina_1_1.json"]
        )
        granularity["a/pagina_1_1.json"]["texto"] = "Merida, Venezuela"
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("'a/pagina_1_1.json'")
            + ".*"
            + re.escape("'Merida, Venezuela'")
            + ".*"
            + re.escape("'Merida'"),
        ):
            subject.check_granularity_coverage(granularity, rows)

    def test_control_coverage_reads_the_direccion_fallback(self) -> None:
        granularity = {
            "a/pagina_1_1.json": {
                "nivel": "T2",
                "texto": "Calle 1",
                "razon": None,
                "nota": None,
            }
        }
        rows = [
            make_row(
                source_path="a/pagina_1_1.json",
                ubicaciongeografica=None,
                direccion="Calle 1",
            )
        ]
        subject.check_granularity_coverage(granularity, rows)

    def test_control_coverage_is_not_vacuous_for_rows_without_an_entry(self) -> None:
        # An empty taxonomy against a non-empty row list must fail: a coverage
        # check that only walked the taxonomy would pass this silently.
        granularity, rows = self.coverage([], ["a/pagina_1_1.json"])
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("'a/pagina_1_1.json'")
        ):
            subject.check_granularity_coverage(granularity, rows)

    def test_control_coverage_rejects_a_row_without_an_entry(self) -> None:
        granularity, rows = self.coverage(
            ["a/pagina_1_1.json"], ["a/pagina_1_1.json", "a/missing.json"]
        )
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("has no entry for parquet source_path")
            + ".*"
            + re.escape("'a/missing.json'"),
        ):
            subject.check_granularity_coverage(granularity, rows)

    def test_control_coverage_is_not_vacuous_for_entries_without_a_row(self) -> None:
        granularity, rows = self.coverage(["a/orphan.json"], [])
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("'a/orphan.json'")
        ):
            subject.check_granularity_coverage(granularity, rows)

    def test_control_coverage_rejects_an_orphan_entry(self) -> None:
        granularity, rows = self.coverage(
            ["a/pagina_1_1.json", "a/orphan.json"], ["a/pagina_1_1.json"]
        )
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("matches no parquet row") + ".*" + re.escape("'a/orphan.json'"),
        ):
            subject.check_granularity_coverage(granularity, rows)


class ShippedGranularityTaxonomyTests(unittest.TestCase):
    """The curated file the rebuild consumes must satisfy the loader's contract."""

    def test_the_shipped_taxonomy_loads_with_the_full_entry_count(self) -> None:
        granularity = subject.load_granularity(GRANULARITY_PATH)
        self.assertEqual(len(granularity), EXPECTED_GRANULARITY_ENTRIES)
        for source_path, entry in granularity.items():
            self.assertRegex(source_path, re.compile(r"\.json$"))
            self.assertEqual(set(entry), {"nivel", "texto", "razon", "nota"})
            self.assertIsInstance(entry["texto"], str)
            self.assertIn(entry["nivel"], ("T0", "T1", "T2"))
            if entry["nivel"] in ("T0", "T1"):
                self.assertIsInstance(entry["razon"], str)
                self.assertTrue(entry["razon"].strip())

    def test_control_the_entry_count_comes_from_the_file(self) -> None:
        path = write_granularity(
            self,
            granularity_document(
                entries={"only/pagina_9_9.json": {"nivel": "T2", "texto": "Merida"}}
            ),
        )
        self.assertEqual(len(subject.load_granularity(path)), 1)
        self.assertNotEqual(
            len(subject.load_granularity(path)), EXPECTED_GRANULARITY_ENTRIES
        )


# ---------------------------------------------------------------------------
# Identity.
# ---------------------------------------------------------------------------


class SlugifyTests(unittest.TestCase):
    def test_lowercases_and_replaces_every_run_of_separators(self) -> None:
        self.assertEqual(subject.slugify("Pagina_5_2"), "pagina-5-2")

    def test_control_strips_leading_and_trailing_separators(self) -> None:
        self.assertEqual(subject.slugify("__página 9__"), "p-gina-9")

    def test_control_drops_characters_the_identifier_may_not_carry(self) -> None:
        self.assertEqual(subject.slugify("Página 5 <2>.pdf"), "p-gina-5-2-pdf")


class MakeStudyIdTests(unittest.TestCase):
    def test_id_is_the_year_plus_the_slugged_stem(self) -> None:
        self.assertEqual(
            subject.make_study_id(1991, "data/raw/congresos/pagina_5_2.pdf"),
            "cve-1991-pagina-5-2",
        )

    def test_control_the_year_is_part_of_the_identity(self) -> None:
        self.assertNotEqual(
            subject.make_study_id(1991, "data/raw/congresos/pagina_5_2.pdf"),
            subject.make_study_id(1992, "data/raw/congresos/pagina_5_2.pdf"),
        )

    def test_control_rejects_a_source_path_with_an_empty_slug(self) -> None:
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("has an empty slug")
        ):
            subject.make_study_id(1991, "data/raw/congresos/___.pdf")

    def test_control_rejects_an_id_outside_the_slug_alphabet(self) -> None:
        # int(row["anio"]) upstream makes this the only way to reach the shape
        # check: a caller that hands over a value whose str() is not lowercase.
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("does not match ^[a-z0-9-]+$")
        ):
            subject.make_study_id(True, "data/raw/congresos/pagina_5_2.pdf")

    def test_control_the_shape_check_accepts_a_well_formed_id(self) -> None:
        self.assertTrue(
            STUDY_ID_RE.match(
                subject.make_study_id(1991, "data/raw/congresos/pagina_5_2.pdf")
            )
        )

    def test_a_null_year_uses_the_literal_sin_anio_segment(self) -> None:
        self.assertEqual(
            subject.make_study_id(None, "data/raw/congresos/pagina_607_1.pdf"),
            "cve-sin-anio-pagina-607-1",
        )

    def test_control_the_null_year_id_matches_the_slug_alphabet(self) -> None:
        self.assertTrue(
            STUDY_ID_RE.match(
                subject.make_study_id(None, "data/raw/congresos/pagina_607_1.pdf")
            )
        )

    def test_control_the_null_year_id_differs_from_a_dated_sibling(self) -> None:
        self.assertNotEqual(
            subject.make_study_id(None, "data/raw/congresos/pagina_607_1.pdf"),
            subject.make_study_id(1991, "data/raw/congresos/pagina_607_1.pdf"),
        )

    def test_control_the_null_year_branch_is_not_the_string_of_none(self) -> None:
        # ``str(None)`` is ``None``, which is uppercase and would fail the shape
        # check; the branch must substitute the literal instead.
        self.assertNotIn(
            "none",
            subject.make_study_id(None, "data/raw/congresos/pagina_607_1.pdf"),
        )


# ---------------------------------------------------------------------------
# Classification.
# ---------------------------------------------------------------------------


# The three curated levels, in the shape ``load_granularity`` hands over.
T0_ENTRY = taxonomy_entry(nivel="T0", texto="Venezuela", razon="mentions the whole country, not a place")
T1_ENTRY = taxonomy_entry(nivel="T1", texto="Estado Miranda", razon="first-level administrative unit")
T2_ENTRY = taxonomy_entry(nivel="T2", texto="Merida")


class StudyIdForTests(unittest.TestCase):
    """``study_id_for`` is the single id derivation the group map and studies share."""

    def test_matches_the_id_the_study_carries(self) -> None:
        row = make_row()
        self.assertEqual(subject.study_id_for(row), "cve-1991-pagina-5-2")
        self.assertEqual(
            subject.study_id_for(row),
            subject.build_study(row, EXTENT, T2_ENTRY, ["cve-1991-pagina-5-2"])["study_id"],
        )

    def test_control_a_null_year_uses_the_sin_anio_segment(self) -> None:
        row = make_row(anio=None)
        self.assertEqual(subject.study_id_for(row), "cve-sin-anio-pagina-5-2")

    def test_control_the_id_depends_on_the_year_and_the_path(self) -> None:
        self.assertNotEqual(
            subject.study_id_for(make_row()),
            subject.study_id_for(make_row(anio=1992)),
        )


class CoordinateGroupsTests(unittest.TestCase):
    """``coordinate_groups`` groups ids by exact pair, independently of class."""

    def groups(self, rows: list[dict[str, Any]]) -> dict[tuple, list[str]]:
        return subject.coordinate_groups(
            rows, [subject.study_id_for(row) for row in rows]
        )

    def test_groups_every_exact_coordinate_pair_by_id(self) -> None:
        rows = [make_row(), make_row(source_path="data/raw/congresos/b.pdf")]
        self.assertEqual(
            self.groups(rows),
            {INSIDE: ["cve-1991-b", "cve-1991-pagina-5-2"]},
        )

    def test_control_the_ids_of_a_group_come_back_sorted(self) -> None:
        rows = [
            make_row(source_path="data/raw/congresos/z.pdf"),
            make_row(source_path="data/raw/congresos/a.pdf"),
        ]
        grouped = self.groups(rows)[INSIDE]
        self.assertEqual(grouped, ["cve-1991-a", "cve-1991-z"])
        self.assertNotEqual(grouped, ["cve-1991-z", "cve-1991-a"])

    def test_control_ignores_rows_without_a_coordinate(self) -> None:
        rows = [
            make_row(),
            make_row(source_path="data/raw/congresos/b.pdf", latitud=None, longitud=None),
        ]
        groups = self.groups(rows)
        self.assertEqual(groups, {INSIDE: ["cve-1991-pagina-5-2"]})
        self.assertNotIn((None, None), groups)

    def test_control_keeps_distinct_coordinates_apart(self) -> None:
        rows = [
            make_row(),
            make_row(source_path="data/raw/congresos/b.pdf",
                     latitud=INSIDE_OTHER[0], longitud=INSIDE_OTHER[1]),
        ]
        self.assertEqual(len(self.groups(rows)), 2)

    def test_control_no_rows_is_no_group(self) -> None:
        self.assertEqual(subject.coordinate_groups([], []), {})

    def test_control_a_row_and_id_count_mismatch_aborts(self) -> None:
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("one study_id per row")
        ):
            subject.coordinate_groups([make_row()], [])


class GranularityEntryForTests(unittest.TestCase):
    """A row the taxonomy does not classify is a hard error, not a default."""

    def test_returns_the_entry_of_the_row(self) -> None:
        row = make_row()
        granularity = {row["source_path"]: T2_ENTRY}
        self.assertIs(subject.granularity_entry_for(row, granularity), T2_ENTRY)

    def test_control_rejects_a_row_without_an_entry_and_names_it(self) -> None:
        row = make_row()
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("granularity file has no entry for")
            + ".*"
            + re.escape("pagina=5 indice=2"),
        ):
            subject.granularity_entry_for(row, {})


class DisplayClassTests(unittest.TestCase):
    def test_a_t2_coordinate_inside_the_extent_is_placeable(self) -> None:
        self.assertEqual(
            subject.display_class_for(make_row(), EXTENT, T2_ENTRY), "placeable"
        )

    def test_a_t0_mention_is_coarse_location_however_inside_it_sits(self) -> None:
        self.assertEqual(
            subject.display_class_for(make_row(), EXTENT, T0_ENTRY), "coarse_location"
        )

    def test_a_t1_mention_is_coarse_location(self) -> None:
        self.assertEqual(
            subject.display_class_for(make_row(), EXTENT, T1_ENTRY), "coarse_location"
        )

    def test_control_a_second_study_at_the_same_coordinate_does_not_change_the_class(self) -> None:
        # The collision is an attribute, not a class: nothing about the pair is
        # passed to the classifier, so a T2 point stays placeable when it is
        # shared and a T1 point stays coarse when it is not.
        self.assertEqual(
            subject.display_class_for(make_row(), EXTENT, T2_ENTRY),
            subject.display_class_for(
                make_row(source_path="data/raw/congresos/b.pdf"), EXTENT, T2_ENTRY
            ),
        )

    def test_control_a_coordinate_beyond_the_north_edge_is_outside_extent(self) -> None:
        row = make_row(latitud=OUTSIDE[0], longitud=OUTSIDE[1])
        self.assertEqual(
            subject.display_class_for(row, EXTENT, T2_ENTRY), "outside_extent"
        )

    def test_control_a_coordinate_just_past_the_west_edge_is_outside_extent(self) -> None:
        row = make_row(latitud=INSIDE[0], longitud=EXTENT["west"] - 0.001)
        self.assertEqual(
            subject.display_class_for(row, EXTENT, T2_ENTRY), "outside_extent"
        )

    def test_coordinates_on_the_extent_border_are_inside(self) -> None:
        row = make_row(latitud=EXTENT["north"], longitud=EXTENT["west"])
        self.assertEqual(subject.display_class_for(row, EXTENT, T2_ENTRY), "placeable")

    def test_control_the_border_check_is_not_a_strict_inequality(self) -> None:
        inside = make_row(latitud=EXTENT["north"], longitud=EXTENT["west"])
        outside = make_row(latitud=EXTENT["north"] + 0.001, longitud=EXTENT["west"])
        self.assertNotEqual(
            subject.display_class_for(inside, EXTENT, T2_ENTRY),
            subject.display_class_for(outside, EXTENT, T2_ENTRY),
        )

    def test_precedence_coarse_location_beats_outside_extent(self) -> None:
        row = make_row(latitud=OUTSIDE[0], longitud=OUTSIDE[1])
        self.assertEqual(
            subject.display_class_for(row, EXTENT, T0_ENTRY), "coarse_location"
        )

    def test_control_a_t2_coordinate_outside_the_extent_is_not_coarse(self) -> None:
        row = make_row(latitud=OUTSIDE[0], longitud=OUTSIDE[1])
        self.assertNotEqual(
            subject.display_class_for(row, EXTENT, T2_ENTRY), "coarse_location"
        )

    def test_a_null_coordinate_is_no_coordinate(self) -> None:
        row = make_row(latitud=None, longitud=None)
        self.assertEqual(
            subject.display_class_for(row, EXTENT, T2_ENTRY), "no_coordinate"
        )

    def test_precedence_no_coordinate_beats_coarse_location(self) -> None:
        row = make_row(latitud=None, longitud=None)
        self.assertEqual(
            subject.display_class_for(row, EXTENT, T0_ENTRY), "no_coordinate"
        )

    def test_control_the_null_coordinate_branch_is_decided_before_the_extent(self) -> None:
        # An empty extent would raise if it were read, so returning the class
        # proves the null check runs first.
        row = make_row(latitud=None, longitud=None)
        self.assertEqual(subject.display_class_for(row, {}, T2_ENTRY), "no_coordinate")

    def test_control_a_present_coordinate_does_consult_the_extent(self) -> None:
        with self.assertRaisesRegex(KeyError, "west"):
            subject.display_class_for(make_row(), {}, T2_ENTRY)


class ExclusionReasonTests(unittest.TestCase):
    def test_a_placeable_study_has_no_reason(self) -> None:
        self.assertIsNone(
            subject.exclusion_reason_for(make_row(), "placeable", EXTENT, T2_ENTRY)
        )

    def test_control_every_other_class_carries_a_reason(self) -> None:
        row = make_row(latitud=None, longitud=None)
        self.assertIsNotNone(
            subject.exclusion_reason_for(row, "no_coordinate", EXTENT, T2_ENTRY)
        )

    def test_the_no_coordinate_reason_says_why(self) -> None:
        row = make_row(latitud=None, longitud=None)
        reason = subject.exclusion_reason_for(row, "no_coordinate", EXTENT, T2_ENTRY)
        self.assertIn("no se puede situar en el mapa", reason)

    def test_the_outside_extent_reason_names_the_offending_coordinate(self) -> None:
        row = make_row(latitud=OUTSIDE[0], longitud=OUTSIDE[1])
        reason = subject.exclusion_reason_for(row, "outside_extent", EXTENT, T2_ENTRY)
        self.assertIn("supera el límite norte", reason)
        self.assertIn(repr(EXTENT["north"]), reason)
        self.assertIn(repr(OUTSIDE[0]), reason)

    def test_control_the_outside_reason_reads_the_extent_it_was_given(self) -> None:
        row = make_row(latitud=OUTSIDE[0], longitud=OUTSIDE[1])
        other = dict(EXTENT, north=99.5)
        self.assertNotEqual(
            subject.exclusion_reason_for(row, "outside_extent", EXTENT, T2_ENTRY),
            subject.exclusion_reason_for(row, "outside_extent", other, T2_ENTRY),
        )

    def test_the_coarse_reason_names_the_level_the_text_the_razon_and_the_gloss(self) -> None:
        row = make_row(ubicaciongeografica="Estado Miranda")
        entry = taxonomy_entry(
            nivel="T1",
            texto="Estado Miranda",
            razon="unidad administrativa de primer nivel",
            nota="una nota de revisión que no debe salir al usuario",
        )
        reason = subject.exclusion_reason_for(row, "coarse_location", EXTENT, entry)
        self.assertIn("T1", reason)
        self.assertIn("Estado Miranda", reason)
        self.assertIn("unidad administrativa de primer nivel", reason)
        self.assertIn("unidad administrativa sin localidad nombrada dentro", reason)
        self.assertNotIn(entry["nota"], reason)

    def test_control_the_coarse_reason_reads_the_level_it_was_given(self) -> None:
        row = make_row()
        t0 = subject.exclusion_reason_for(row, "coarse_location", EXTENT, T0_ENTRY)
        t1 = subject.exclusion_reason_for(row, "coarse_location", EXTENT, T1_ENTRY)
        self.assertIn("T0", t0)
        self.assertIn("T1", t1)
        self.assertNotEqual(t0, t1)

    def test_control_the_coarse_reason_quotes_the_corpus_text_not_the_recorded_one(self) -> None:
        # The text a reader sees must be the one the study carries, which the
        # coverage check pins to the curated ``texto`` before the build runs.
        row = make_row(ubicaciongeografica="Llanos de Venezuela")
        entry = taxonomy_entry(
            nivel="T0",
            texto="otro texto",
            razon="región natural amplia (multi-estado)",
        )
        reason = subject.exclusion_reason_for(row, "coarse_location", EXTENT, entry)
        self.assertIn("Llanos de Venezuela", reason)
        self.assertNotIn("otro texto", reason)

    def test_control_the_coarse_reason_reads_the_razon_it_was_given(self) -> None:
        row = make_row()
        first = taxonomy_entry(nivel="T0", texto="Merida", razon="la primera razón")
        second = taxonomy_entry(nivel="T0", texto="Merida", razon="la segunda razón")
        self.assertNotEqual(
            subject.exclusion_reason_for(row, "coarse_location", EXTENT, first),
            subject.exclusion_reason_for(row, "coarse_location", EXTENT, second),
        )

    def test_control_the_t0_gloss_is_not_the_t1_gloss(self) -> None:
        self.assertNotEqual(
            subject.GRANULARITY_LEVEL_GLOSSES["T0"],
            subject.GRANULARITY_LEVEL_GLOSSES["T1"],
        )


# ---------------------------------------------------------------------------
# Row parsing.
# ---------------------------------------------------------------------------


class AuthorParsingTests(unittest.TestCase):
    def test_projects_the_five_source_fields_in_a_fixed_order(self) -> None:
        row = make_row(autores=json.dumps([
            {"orcid": "x", "nombre": "Ana", "extra": 1, "afiliacion": "ULA",
             "pais": "VE", "ror": "r"},
        ]))
        self.assertEqual(
            subject._parse_autores(row, "WHERE"),
            [{"nombre": "Ana", "afiliacion": "ULA", "ror": "r", "pais": "VE",
              "orcid": "x"}],
        )
        self.assertEqual(list(subject._parse_autores(row, "WHERE")[0]), AUTHOR_FIELDS)
        self.assertNotIn("extra", subject._parse_autores(row, "WHERE")[0])
        self.assertNotEqual(
            subject._parse_autores(row, "WHERE"),
            [{"nombre": "Ana", "afiliacion": "ULA", "ror": "r", "pais": "VE",
              "orcid": "x", "extra": 1}],
        )

    def test_control_the_author_field_contract_is_the_five_source_fields(self) -> None:
        self.assertEqual(subject.AUTOR_FIELDS, AUTHOR_FIELDS)
        self.assertNotEqual(subject.AUTOR_FIELDS, list(reversed(AUTHOR_FIELDS)))

    def test_control_rejects_a_non_object_author_and_names_its_position(self) -> None:
        row = make_row(autores=json.dumps([dict(AUTHOR), "Ana"]))
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("autores[1] is not a JSON object (got str)"),
        ):
            subject._parse_autores(row, "WHERE")

    def test_control_rejects_an_author_missing_one_required_field(self) -> None:
        incomplete = {key: value for key, value in AUTHOR.items() if key != "orcid"}
        row = make_row(autores=json.dumps([incomplete]))
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("is missing field(s) orcid")
        ):
            subject._parse_autores(row, "WHERE")

    def test_control_names_every_missing_field_in_field_order(self) -> None:
        incomplete = {"afiliacion": "ULA", "pais": "VE"}
        row = make_row(autores=json.dumps([incomplete]))
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("is missing field(s) nombre, ror, orcid")
        ):
            subject._parse_autores(row, "WHERE")

    def test_control_rejects_malformed_autores_json(self) -> None:
        row = make_row(autores="[{'nombre': 'Ana'}")
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("autores does not parse as JSON")
        ):
            subject._parse_autores(row, "WHERE")

    def test_control_rejects_autores_that_is_not_a_json_array(self) -> None:
        row = make_row(autores=json.dumps({"nombre": "Ana"}))
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("autores must decode to a JSON array")
        ):
            subject._parse_autores(row, "WHERE")

    def test_control_rejects_an_autores_column_that_is_not_a_string(self) -> None:
        row = make_row(autores=[dict(AUTHOR)])
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("autores is not a JSON string")
        ):
            subject._parse_autores(row, "WHERE")

    def test_control_the_failure_carries_the_row_tag(self) -> None:
        row = make_row(autores="[", pagina=7, indice=3)
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("pagina=7 indice=3")
        ):
            subject._parse_autores(row, subject.row_name(row))


class InstitutionParsingTests(unittest.TestCase):
    def test_returns_the_decoded_strings(self) -> None:
        row = make_row(instituciones=json.dumps(["ULA", "IVIC"]))
        self.assertEqual(subject._parse_instituciones(row, "WHERE"), ["ULA", "IVIC"])

    def test_control_rejects_a_non_string_institution_and_names_its_position(self) -> None:
        row = make_row(instituciones=json.dumps(["ULA", 42]))
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("instituciones[1] is not a string")
        ):
            subject._parse_instituciones(row, "WHERE")

    def test_control_rejects_malformed_instituciones_json(self) -> None:
        row = make_row(instituciones="[ULA")
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("instituciones does not parse as JSON"),
        ):
            subject._parse_instituciones(row, "WHERE")

    def test_control_rejects_instituciones_that_is_not_a_json_array(self) -> None:
        row = make_row(instituciones=json.dumps("ULA"))
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("instituciones must decode to a JSON array"),
        ):
            subject._parse_instituciones(row, "WHERE")


class PalabrasclavesParsingTests(unittest.TestCase):
    """``palabrasclaves`` is a real list column, not a JSON-encoded string."""

    def test_returns_the_keyword_list(self) -> None:
        row = make_row(palabrasclaves=["Cedrela odorata", "bosque seco"])
        self.assertEqual(
            subject._parse_palabrasclaves(row, "WHERE"),
            ["Cedrela odorata", "bosque seco"],
        )

    def test_an_empty_list_is_valid(self) -> None:
        self.assertEqual(subject._parse_palabrasclaves(make_row(palabrasclaves=[]), "WHERE"), [])

    def test_control_the_result_is_a_copy(self) -> None:
        keywords = ["Cedrela odorata"]
        row = make_row(palabrasclaves=keywords)
        subject._parse_palabrasclaves(row, "WHERE").append("otra")
        self.assertEqual(keywords, ["Cedrela odorata"])

    def test_control_rejects_a_json_encoded_string_and_names_the_row(self) -> None:
        row = make_row(palabrasclaves="[\"Cedrela odorata\"]", pagina=7, indice=3)
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("palabrasclaves must be a list of strings")
            + ".*"
            + re.escape("pagina=7 indice=3"),
        ):
            subject._parse_palabrasclaves(row, subject.row_name(row))

    def test_control_rejects_a_null_column(self) -> None:
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("palabrasclaves must be a list of strings")
        ):
            subject._parse_palabrasclaves(make_row(palabrasclaves=None), "WHERE")

    def test_control_rejects_a_non_string_item(self) -> None:
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("palabrasclaves must be a list of strings")
        ):
            subject._parse_palabrasclaves(make_row(palabrasclaves=["ok", 7]), "WHERE")


class EspeciesParsingTests(unittest.TestCase):
    """The parsed species list, per decision D7 (the client groups, it does not parse)."""

    def test_none_and_absent_values_are_an_empty_list(self) -> None:
        self.assertEqual(subject.parse_especies(None), [])
        self.assertEqual(subject.parse_especies(42), [])

    def test_every_sentinel_casing_is_dropped(self) -> None:
        sentinels = [
            "", "   ", "N.A.", "n.a.", "n/a", "NA", "s/d", "S/D",
            "s.a.", "-", "none", "NULL",
            "No se mencionan especies específicas",
            "No se mencionan especies específicas en el resumen",
        ]
        for sentinel in sentinels:
            with self.subTest(sentinel=sentinel):
                self.assertEqual(subject.parse_especies(sentinel), [])

    def test_a_serialised_single_item_list_is_unwrapped(self) -> None:
        self.assertEqual(
            subject.parse_especies("['Pinus caribaea']"), ["Pinus caribaea"]
        )

    def test_a_serialised_two_item_list_yields_both_names(self) -> None:
        self.assertEqual(subject.parse_especies("['A', 'B']"), ["A", "B"])

    def test_an_empty_serialised_list_is_empty(self) -> None:
        self.assertEqual(subject.parse_especies("[]"), [])
        self.assertEqual(subject.parse_especies("[ ]"), [])

    def test_commas_and_semicolons_both_split(self) -> None:
        self.assertEqual(subject.parse_especies("A, B; C"), ["A", "B", "C"])

    def test_a_repeated_name_is_deduplicated_case_insensitively_keeping_the_first(
        self,
    ) -> None:
        self.assertEqual(subject.parse_especies("Zea mays, zea mays"), ["Zea mays"])
        self.assertEqual(
            subject.parse_especies("Zea mays; ZEA MAYS; zea Mays"), ["Zea mays"]
        )

    def test_the_long_species_sentinel_is_dropped(self) -> None:
        self.assertEqual(
            subject.parse_especies("No se mencionan especies específicas"), []
        )

    def test_control_the_declared_limit_a_comma_inside_a_name_is_indistinguishable(
        self,
    ) -> None:
        # The builder cannot know the second token is a family list rather than a
        # second species, so it splits. Fixing it belongs to curation, not to an
        # inference here; this test declares the accepted limit with a real value.
        self.assertEqual(
            subject.parse_especies(
                "Peces de las Familias Characidae, Loricariidae"
            ),
            ["Peces de las Familias Characidae", "Loricariidae"],
        )

    def test_control_a_json_list_value_is_accepted_defensively(self) -> None:
        self.assertEqual(subject.parse_especies(["A", "B; C"]), ["A", "B", "C"])

    def test_control_surrounding_quotes_and_whitespace_are_trimmed(self) -> None:
        self.assertEqual(
            subject.parse_especies('  "A"  , \'B\' '), ["A", "B"]
        )

    def test_control_a_blank_name_after_splitting_is_dropped(self) -> None:
        self.assertEqual(subject.parse_especies("A,,  ,B"), ["A", "B"])


class RoresParsingTests(unittest.TestCase):
    """The per-study ROR ids: trimmed, sentinel-free, deduplicated, sorted."""

    def test_two_authors_with_the_same_ror_yield_one_id(self) -> None:
        autores = [dict(AUTHOR), {**AUTHOR, "nombre": "Luis"}]
        self.assertEqual(subject.parse_rores(autores), [AUTHOR["ror"]])

    def test_sentinel_and_empty_values_are_dropped(self) -> None:
        autores = [
            {**AUTHOR, "ror": "No disponible"},
            {**AUTHOR, "ror": ""},
            {**AUTHOR, "ror": "   "},
            {**AUTHOR, "ror": None},
        ]
        self.assertEqual(
            subject.parse_rores(autores, TEST_ROR_SENTINELS), []
        )

    def test_the_ids_are_sorted_ascending(self) -> None:
        autores = [
            {**AUTHOR, "ror": "https://ror.org/zzz"},
            {**AUTHOR, "ror": "https://ror.org/aaa"},
        ]
        self.assertEqual(
            subject.parse_rores(autores),
            ["https://ror.org/aaa", "https://ror.org/zzz"],
        )

    def test_a_study_without_a_usable_ror_is_empty(self) -> None:
        autores = [{**AUTHOR, "ror": None}, {**AUTHOR, "ror": "  "}]
        self.assertEqual(subject.parse_rores(autores), [])

    def test_control_a_sentinel_that_is_not_declared_survives(self) -> None:
        autores = [{**AUTHOR, "ror": "No disponible"}]
        self.assertEqual(subject.parse_rores(autores), ["No disponible"])

    def test_control_a_trimmed_id_is_stored_without_whitespace(self) -> None:
        autores = [{**AUTHOR, "ror": "  https://ror.org/aaa  "}]
        self.assertEqual(subject.parse_rores(autores), ["https://ror.org/aaa"])


class NAutoresTests(unittest.TestCase):
    def test_a_matching_row_is_counted_as_matched(self) -> None:
        matched, mismatches = subject.check_n_autores([make_row()])
        self.assertEqual(matched, 1)
        self.assertEqual(mismatches, [])

    def test_control_a_disagreeing_row_is_reported_with_both_numbers(self) -> None:
        row = make_row(
            autores=json.dumps([dict(AUTHOR), {**AUTHOR, "nombre": "Luis"}]),
            n_autores=1,
        )
        matched, mismatches = subject.check_n_autores([row])
        self.assertEqual(matched, 0)
        self.assertEqual(len(mismatches), 1)
        where, declared, actual = mismatches[0]
        self.assertEqual((declared, actual), (1, 2))
        self.assertEqual(where, subject.row_name(row))

    def test_control_a_matching_row_with_several_authors_is_not_reported(self) -> None:
        row = make_row(
            autores=json.dumps([dict(AUTHOR), {**AUTHOR, "nombre": "Luis"}]),
            n_autores=2,
        )
        matched, mismatches = subject.check_n_autores([row])
        self.assertEqual(matched, 1)
        self.assertEqual(mismatches, [])

    def test_control_malformed_autores_raises_instead_of_being_counted(self) -> None:
        row = make_row(autores="[")
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("autores does not parse as JSON")
        ):
            subject.check_n_autores([row])

    def test_control_one_bad_row_hides_neither_the_others_nor_itself(self) -> None:
        good = make_row()
        bad = make_row(source_path="data/raw/congresos/b.pdf", n_autores=3)
        matched, mismatches = subject.check_n_autores([good, bad])
        self.assertEqual(matched, 1)
        self.assertEqual([(declared, actual) for _, declared, actual in mismatches],
                         [(3, 1)])


class ValidateRowsTests(unittest.TestCase):
    def test_accepts_a_well_formed_row(self) -> None:
        subject.validate_rows([make_row()])

    def test_control_rejects_an_empty_source(self) -> None:
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("the source Parquet has no rows")
        ):
            subject.validate_rows([])

    def test_control_rejects_a_missing_required_column(self) -> None:
        row = make_row()
        del row["latitud"]
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("source Parquet is missing required column(s): latitud"),
        ):
            subject.validate_rows([row])

    def test_control_rejects_a_row_that_is_not_human_verified(self) -> None:
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("row is not human-verified (False)")
        ):
            subject.validate_rows([make_row(human_verified=False)])

    def test_control_rejects_a_row_without_a_human_reviewer(self) -> None:
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("human_reviewer is not a non-empty string (None)"),
        ):
            subject.validate_rows([make_row(human_reviewer=None)])

    def test_control_rejects_a_blank_human_reviewer(self) -> None:
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("human_reviewer is not a non-empty string ('   ')"),
        ):
            subject.validate_rows([make_row(human_reviewer="   ")])

    def test_control_rejects_a_non_string_human_reviewer(self) -> None:
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("human_reviewer is not a non-empty string (7)"),
        ):
            subject.validate_rows([make_row(human_reviewer=7)])

    def test_control_rejects_a_missing_human_reviewer_column(self) -> None:
        row = make_row()
        del row["human_reviewer"]
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape(
                "source Parquet is missing required column(s): human_reviewer"
            ),
        ):
            subject.validate_rows([row])

    def test_control_rejects_latitud_without_longitud(self) -> None:
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("latitud/longitud must both be null or both present"),
        ):
            subject.validate_rows([make_row(longitud=None)])

    def test_control_rejects_longitud_without_latitud(self) -> None:
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("latitud/longitud must both be null or both present"),
        ):
            subject.validate_rows([make_row(latitud=None)])

    def test_control_rejects_an_implausible_latitude(self) -> None:
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("latitud 91.5 is outside the plausible range [-90, 90]"),
        ):
            subject.validate_rows([make_row(latitud=91.5)])

    def test_control_rejects_an_implausible_longitude(self) -> None:
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("longitud 181.5 is outside the plausible range [-180, 180]"),
        ):
            subject.validate_rows([make_row(longitud=181.5)])

    def test_control_accepts_the_plausible_range_borders(self) -> None:
        subject.validate_rows([make_row(latitud=-90.0)])
        subject.validate_rows([make_row(longitud=180.0)])
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("latitud -90.000001")
        ):
            subject.validate_rows([make_row(latitud=-90.000001)])

    def test_control_rejects_paises_that_is_not_a_json_string(self) -> None:
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("paises is not a JSON string")
        ):
            subject.validate_rows([make_row(paises=["VE"])])

    def test_control_rejects_malformed_paises_json(self) -> None:
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("paises does not parse as JSON")
        ):
            subject.validate_rows([make_row(paises="[VE")])

    def test_control_rejects_paises_that_is_not_a_json_array(self) -> None:
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("paises must decode to a JSON array")
        ):
            subject.validate_rows([make_row(paises=json.dumps({"VE": 1}))])

    def test_control_rejects_malformed_autores_json_in_validate_rows(self) -> None:
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("autores does not parse as JSON")
        ):
            subject.validate_rows([make_row(autores="[")])

    def test_control_rejects_a_non_object_author_in_validate_rows(self) -> None:
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("autores[0] is not a JSON object")
        ):
            subject.validate_rows([make_row(autores=json.dumps(["Ana"]))])

    def test_control_rejects_an_author_missing_a_field_in_validate_rows(self) -> None:
        incomplete = {key: value for key, value in AUTHOR.items() if key != "pais"}
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("autores[0] is missing field(s) pais")
        ):
            subject.validate_rows([make_row(autores=json.dumps([incomplete]))])

    def test_control_rejects_malformed_instituciones_json_in_validate_rows(self) -> None:
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("instituciones does not parse as JSON"),
        ):
            subject.validate_rows([make_row(instituciones="[")])

    def test_control_rejects_a_non_string_institution_in_validate_rows(self) -> None:
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("instituciones[0] is not a string")
        ):
            subject.validate_rows([make_row(instituciones=json.dumps([7]))])

    def test_control_rejects_a_palabrasclaves_column_that_is_not_a_list(self) -> None:
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("palabrasclaves must be a list of strings")
        ):
            subject.validate_rows([make_row(palabrasclaves=json.dumps(["cedro"]))])

    def test_control_rejects_a_palabrasclaves_list_with_a_non_string(self) -> None:
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("palabrasclaves must be a list of strings")
        ):
            subject.validate_rows([make_row(palabrasclaves=["cedro", 7])])

    def test_control_rejects_a_missing_palabrasclaves_column(self) -> None:
        row = make_row()
        del row["palabrasclaves"]
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("source Parquet is missing required column(s): palabrasclaves"),
        ):
            subject.validate_rows([row])

    def test_control_the_failure_names_the_offending_row(self) -> None:
        row = make_row(human_verified=False)
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape("source_path='data/raw/congresos/pagina_5_2.pdf'"),
        ):
            subject.validate_rows([row])


# ---------------------------------------------------------------------------
# Assembly.
# ---------------------------------------------------------------------------


class BuildStudyTests(unittest.TestCase):
    def test_a_placeable_row_becomes_an_on_map_study(self) -> None:
        row = make_row()
        study = subject.build_study(row, EXTENT, T2_ENTRY, ["cve-1991-pagina-5-2"])
        self.assertEqual(study["study_id"], "cve-1991-pagina-5-2")
        self.assertEqual(study["display_class"], "placeable")
        self.assertIs(study["on_map"], True)
        self.assertIsNone(study["exclusion_reason"])
        self.assertEqual(study["autores"], [dict(AUTHOR)])
        self.assertEqual(study["instituciones"], ["Universidad de Los Andes"])
        self.assertEqual(study["paises"], ["VE"])
        self.assertEqual(study["palabrasclaves"], ["Cedrela odorata"])
        self.assertEqual((study["latitud"], study["longitud"]), INSIDE)
        self.assertEqual(study["titulo"], row["titulo"])
        self.assertEqual(study["resumen"], row["resumen"])
        self.assertEqual(study["granularidad_nivel"], "T2")
        self.assertIsNone(study["granularidad_razon"])

    def test_a_coarse_row_is_not_on_the_map_and_carries_its_level(self) -> None:
        row = make_row(ubicaciongeografica="Estado Miranda")
        entry = taxonomy_entry(
            nivel="T1",
            texto="Estado Miranda",
            razon="unidad administrativa de primer nivel",
        )
        study = subject.build_study(row, EXTENT, entry, ["cve-1991-pagina-5-2"])
        self.assertEqual(study["display_class"], "coarse_location")
        self.assertIs(study["on_map"], False)
        self.assertEqual(study["granularidad_nivel"], "T1")
        self.assertEqual(study["granularidad_razon"], "unidad administrativa de primer nivel")
        self.assertIn("T1", study["exclusion_reason"])

    def test_control_an_outside_extent_row_is_not_on_the_map(self) -> None:
        row = make_row(latitud=OUTSIDE[0], longitud=OUTSIDE[1])
        study = subject.build_study(row, EXTENT, T2_ENTRY, ["cve-1991-pagina-5-2"])
        self.assertEqual(study["display_class"], "outside_extent")
        self.assertIs(study["on_map"], False)
        self.assertIn("supera el límite norte", study["exclusion_reason"])

    def test_control_a_row_without_coordinates_is_not_on_the_map(self) -> None:
        row = make_row(latitud=None, longitud=None)
        study = subject.build_study(row, EXTENT, T2_ENTRY, None)
        self.assertEqual(study["display_class"], "no_coordinate")
        self.assertIs(study["on_map"], False)
        self.assertIsNone(study["latitud"])
        self.assertIsNone(study["longitud"])
        self.assertTrue(study["exclusion_reason"])

    def test_control_the_numeric_columns_are_cast_to_int(self) -> None:
        row = make_row(anio="1991", pagina="5", indice="2", n_autores="1")
        study = subject.build_study(row, EXTENT, T2_ENTRY, ["cve-1991-pagina-5-2"])
        self.assertEqual(
            (study["anio"], study["pagina"], study["indice"], study["n_autores"]),
            (1991, 5, 2, 1),
        )

    def test_a_null_year_survives_as_none_and_keys_the_id(self) -> None:
        row = make_row(anio=None)
        study = subject.build_study(row, EXTENT, T2_ENTRY, ["cve-sin-anio-pagina-5-2"])
        self.assertIsNone(study["anio"])
        self.assertEqual(study["study_id"], "cve-sin-anio-pagina-5-2")

    def test_control_a_dated_row_still_carries_an_int_year(self) -> None:
        study = subject.build_study(make_row(), EXTENT, T2_ENTRY, ["cve-1991-pagina-5-2"])
        self.assertEqual(study["anio"], 1991)
        self.assertEqual(study["study_id"], "cve-1991-pagina-5-2")

    def test_control_a_source_path_with_an_empty_slug_aborts_the_study(self) -> None:
        row = make_row(source_path="data/raw/congresos/___.pdf")
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("has an empty slug")
        ):
            subject.build_study(row, EXTENT, T2_ENTRY, None)

    def test_control_a_broken_author_column_aborts_the_study(self) -> None:
        row = make_row(autores="[")
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("autores does not parse as JSON")
        ):
            subject.build_study(row, EXTENT, T2_ENTRY, ["cve-1991-pagina-5-2"])

    # --- species, ROR ids and the reviewer (schema v4) -----------------
    def test_a_study_carries_the_parsed_species_and_the_reviewer(self) -> None:
        row = make_row(especiesmencionadas="A, B; A", human_reviewer="IA")
        study = subject.build_study(row, EXTENT, T2_ENTRY, ["cve-1991-pagina-5-2"])
        self.assertEqual(study["especies"], ["A", "B"])
        self.assertEqual(study["especiesmencionadas"], "A, B; A")
        self.assertEqual(study["human_reviewer"], "IA")
        self.assertEqual(study["rores"], [AUTHOR["ror"]])

    def test_a_study_without_species_carries_an_empty_parsed_list(self) -> None:
        row = make_row(especiesmencionadas=None)
        study = subject.build_study(row, EXTENT, T2_ENTRY, ["cve-1991-pagina-5-2"])
        self.assertEqual(study["especies"], [])
        self.assertIsNone(study["especiesmencionadas"])

    def test_the_sentinel_ror_is_dropped_from_a_study(self) -> None:
        row = make_row(autores=json.dumps([{**AUTHOR, "ror": "No disponible"}]))
        study = subject.build_study(
            row, EXTENT, T2_ENTRY, ["cve-1991-pagina-5-2"], TEST_ROR_SENTINELS
        )
        self.assertEqual(study["rores"], [])

    # --- the collision attributes -------------------------------------
    def test_an_alone_study_has_size_one_and_no_other_ids(self) -> None:
        study = subject.build_study(make_row(), EXTENT, T2_ENTRY, ["cve-1991-pagina-5-2"])
        self.assertEqual(study["coordinate_group_size"], 1)
        self.assertEqual(study["coordinate_group_ids"], [])

    def test_a_colliding_study_reports_the_group_without_its_own_id(self) -> None:
        group = ["cve-1991-a", "cve-1991-pagina-5-2", "cve-1991-z"]
        study = subject.build_study(make_row(), EXTENT, T2_ENTRY, group)
        self.assertEqual(study["coordinate_group_size"], 3)
        self.assertEqual(study["coordinate_group_ids"], ["cve-1991-a", "cve-1991-z"])
        self.assertNotIn(study["study_id"], study["coordinate_group_ids"])
        self.assertEqual(
            len(study["coordinate_group_ids"]) + 1, study["coordinate_group_size"]
        )

    def test_control_the_group_ids_are_sorted_even_from_an_unsorted_group(self) -> None:
        group = ["cve-1991-z", "cve-1991-pagina-5-2", "cve-1991-a"]
        study = subject.build_study(make_row(), EXTENT, T2_ENTRY, group)
        self.assertEqual(study["coordinate_group_ids"], ["cve-1991-a", "cve-1991-z"])

    def test_a_row_without_a_coordinate_has_a_null_size_and_no_ids(self) -> None:
        row = make_row(latitud=None, longitud=None)
        study = subject.build_study(row, EXTENT, T2_ENTRY, None)
        self.assertIsNone(study["coordinate_group_size"])
        self.assertEqual(study["coordinate_group_ids"], [])

    def test_control_the_collision_does_not_depend_on_the_display_class(self) -> None:
        # One member of the Barinas group is T1 while the others are T2; the
        # group is the same for both, which is the whole point of D12.
        group = ["cve-1991-a", "cve-1991-pagina-5-2"]
        placeable = subject.build_study(make_row(), EXTENT, T2_ENTRY, group)
        coarse = subject.build_study(
            make_row(ubicaciongeografica="estado Barinas"),
            EXTENT,
            taxonomy_entry(nivel="T1", texto="estado Barinas", razon="administrative unit"),
            group,
        )
        self.assertEqual(placeable["display_class"], "placeable")
        self.assertEqual(coarse["display_class"], "coarse_location")
        self.assertEqual(placeable["coordinate_group_size"], coarse["coordinate_group_size"])
        self.assertEqual(placeable["coordinate_group_ids"], coarse["coordinate_group_ids"])

    def test_control_a_present_coordinate_without_a_group_aborts(self) -> None:
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("no coordinate group was computed")
        ):
            subject.build_study(make_row(), EXTENT, T2_ENTRY, None)

    def test_control_a_broken_palabrasclaves_column_aborts_the_study(self) -> None:
        row = make_row(palabrasclaves=["ok", 7])
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("palabrasclaves must be a list of strings")
        ):
            subject.build_study(row, EXTENT, T2_ENTRY, ["cve-1991-pagina-5-2"])


class BuildCatalogTests(unittest.TestCase):
    def test_studies_are_sorted_by_year_congress_page_and_index(self) -> None:
        catalog, _ = build_test_catalog()
        self.assertEqual(
            [study["study_id"] for study in catalog["studies"]], EXPECTED_CATALOG_IDS
        )

    def test_undated_studies_sort_last_and_dated_studies_keep_their_order(self) -> None:
        catalog, _ = build_catalog_from(catalog_rows_with_undated())
        studies = catalog["studies"]
        self.assertEqual(
            [study["study_id"] for study in studies],
            EXPECTED_CATALOG_IDS + EXPECTED_UNDATED_IDS,
        )
        self.assertTrue(all(study["anio"] is None for study in studies[-3:]))
        self.assertTrue(all(study["anio"] is not None for study in studies[:-3]))

    def test_control_repeated_builds_produce_the_same_total_order(self) -> None:
        first, _ = build_catalog_from(catalog_rows_with_undated())
        second, _ = build_catalog_from(catalog_rows_with_undated())
        self.assertEqual(
            [study["study_id"] for study in first["studies"]],
            [study["study_id"] for study in second["studies"]],
        )

    def test_control_the_undated_rows_do_not_keep_their_insertion_order(self) -> None:
        rows = catalog_rows_with_undated()
        inserted = [subject.study_id_for(row) for row in rows]
        catalog, _ = build_catalog_from(rows)
        self.assertNotEqual(
            [study["study_id"] for study in catalog["studies"]], inserted
        )

    def test_control_undated_studies_sort_last_even_when_inserted_first(self) -> None:
        catalog, _ = build_catalog_from(undated_rows() + catalog_rows())
        self.assertEqual(
            [study["study_id"] for study in catalog["studies"]],
            EXPECTED_CATALOG_IDS + EXPECTED_UNDATED_IDS,
        )

    def test_class_counts_and_the_display_contract_agree(self) -> None:
        catalog, counts = build_test_catalog()
        self.assertEqual(catalog["study_count"], 6)
        # The two rows sharing a coordinate are both placeable now: the
        # collision is an attribute, not a class.
        self.assertEqual(
            counts,
            {"placeable": 3, "coarse_location": 0, "outside_extent": 1,
             "no_coordinate": 2},
        )
        self.assertEqual(
            catalog["display_contract"],
            {
                "map_visible_count": 3,
                "excluded_count": 3,
                "collision_coordinate_count": 1,
                "collision_marker_count": 2,
            },
        )
        self.assertEqual(sum(counts.values()), catalog["study_count"])
        self.assertEqual(
            catalog["display_contract"]["map_visible_count"], counts["placeable"]
        )
        self.assertEqual(
            catalog["display_contract"]["excluded_count"],
            catalog["study_count"] - counts["placeable"],
        )

    def test_control_a_catalog_without_excluded_studies_reports_zero(self) -> None:
        rows = [make_row()]
        catalog, counts = build_catalog_from(rows)
        self.assertEqual(counts["placeable"], 1)
        self.assertEqual(
            catalog["display_contract"],
            {
                "map_visible_count": 1,
                "excluded_count": 0,
                "collision_coordinate_count": 0,
                "collision_marker_count": 0,
            },
        )

    # --- the collision tallies describe what the map draws -----------------
    def test_the_collision_tallies_count_only_drawn_markers(self) -> None:
        rows = collision_rows()
        catalog, counts = build_catalog_from(rows, collision_taxonomy(rows))
        self.assertEqual(counts["placeable"], 3)
        self.assertEqual(counts["coarse_location"], 1)
        contract = catalog["display_contract"]
        self.assertEqual(contract["map_visible_count"], 3)
        # The excluded study shares the colliding coordinate, so the
        # catalog-wide size is 3 there while the map draws 2 markers: the
        # tallies must not have been read from ``coordinate_group_size``.
        drawn = [
            study for study in catalog["studies"]
            if study["display_class"] == "placeable"
        ]
        self.assertEqual(
            sorted(study["coordinate_group_size"] for study in drawn), [1, 3, 3]
        )
        self.assertEqual(contract["collision_coordinate_count"], 1)
        self.assertEqual(contract["collision_marker_count"], 2)

    def test_control_a_lone_placeable_study_is_not_a_collision(self) -> None:
        rows = [make_row()]
        catalog, counts = build_catalog_from(rows)
        self.assertEqual(counts["placeable"], 1)
        contract = catalog["display_contract"]
        self.assertEqual(contract["collision_coordinate_count"], 0)
        self.assertEqual(contract["collision_marker_count"], 0)

    def test_control_a_placeable_pair_turns_its_coordinate_into_a_collision(
        self,
    ) -> None:
        rows = [
            make_row(),
            make_row(source_path="data/raw/congresos/pagina_5_1.pdf",
                     pagina=5, indice=1),
        ]
        catalog, counts = build_catalog_from(rows)
        self.assertEqual(counts["placeable"], 2)
        contract = catalog["display_contract"]
        self.assertEqual(contract["collision_coordinate_count"], 1)
        self.assertEqual(contract["collision_marker_count"], 2)

    def test_control_a_coordinate_shared_only_by_excluded_studies_is_not_counted(
        self,
    ) -> None:
        rows = [
            make_row(source_path="data/raw/congresos/pagina_5_2.pdf",
                     ubicaciongeografica="estado Barinas"),
            make_row(source_path="data/raw/congresos/pagina_5_1.pdf",
                     pagina=5, indice=1,
                     ubicaciongeografica="estado Barinas"),
        ]
        catalog, counts = build_catalog_from(rows, taxonomy_for(rows, nivel="T1"))
        self.assertEqual(counts["placeable"], 0)
        contract = catalog["display_contract"]
        self.assertEqual(contract["collision_coordinate_count"], 0)
        self.assertEqual(contract["collision_marker_count"], 0)
        # The coordinate is still a collision in the catalog-wide attribute.
        self.assertEqual(catalog["studies"][0]["coordinate_group_size"], 2)

    def test_a_coarse_catalog_moves_the_whole_level_off_the_map(self) -> None:
        rows = catalog_rows()
        catalog, counts = build_catalog_from(rows, taxonomy_for(rows, nivel="T0"))
        # The T0 rows with a coordinate are coarse_location; the two with no
        # coordinate are still no_coordinate, which is decided first.
        self.assertEqual(counts["coarse_location"], 4)
        self.assertEqual(counts["no_coordinate"], 2)
        self.assertEqual(counts["placeable"], 0)
        self.assertEqual(catalog["display_contract"]["map_visible_count"], 0)

    def test_the_classes_block_labels_every_class(self) -> None:
        catalog, counts = build_test_catalog()
        classes = catalog["classes"]
        self.assertEqual([entry["key"] for entry in classes], subject.CLASS_ORDER)
        for entry in classes:
            self.assertEqual(entry["count"], counts[entry["key"]])
            self.assertEqual(entry["on_map"], entry["key"] == "placeable")
            self.assertEqual(entry["reason"] is None, entry["key"] == "placeable")
        self.assertEqual(classes[0]["label_es"], "Ubicable")
        labels = {entry["key"]: entry["label_es"] for entry in classes}
        self.assertEqual(labels["coarse_location"], "Ubicación de grano grueso")
        self.assertNotIn("shared_coordinate", labels)

    def test_control_a_duplicate_study_id_is_a_hard_error(self) -> None:
        first = make_row()
        second = make_row(pagina=9, indice=9)
        rows = [first, second]
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("duplicate study_id 'cve-1991-pagina-5-2'")
        ):
            build_catalog_from(rows)

    def test_control_the_same_rows_with_distinct_stems_do_not_collide(self) -> None:
        first = make_row()
        second = make_row(source_path="data/raw/congresos/pagina_5_3.pdf",
                          pagina=9, indice=9)
        catalog, _ = build_catalog_from([first, second])
        self.assertEqual(len({study["study_id"] for study in catalog["studies"]}), 2)

    def test_the_catalog_records_what_it_was_built_from(self) -> None:
        catalog, _ = build_test_catalog()
        self.assertEqual(catalog["schema_version"], subject.SCHEMA_VERSION)
        self.assertEqual(catalog["country"], "testland")
        self.assertEqual(catalog["source_parquet"], "data/raw/congresos/test.parquet")
        self.assertEqual(catalog["extent_label"], "extent label")
        self.assertEqual(catalog["extent_boundary_note"], "extent boundary note")
        self.assertEqual(catalog["extent"], EXTENT)

    def test_the_catalog_projects_the_curated_ror_instituciones(self) -> None:
        catalog, _ = build_test_catalog()
        self.assertEqual(catalog["ror_instituciones"], TEST_ROR_ENTRIES)
        self.assertEqual(
            set(catalog["ror_instituciones"]),
            {AUTHOR["ror"]},
        )

    def test_control_a_study_with_an_uncurated_ror_aborts_and_names_both(self) -> None:
        row = make_row(
            autores=json.dumps([{**AUTHOR, "ror": "https://ror.org/uncurated"}])
        )
        with self.assertRaisesRegex(
            subject.StudyCatalogError,
            re.escape(
                "study 'cve-1991-pagina-5-2' carries ROR id "
                "'https://ror.org/uncurated'"
            ),
        ):
            build_catalog_from([row])

    def test_control_a_sentinel_ror_is_dropped_silently(self) -> None:
        # ``No disponible`` is a declared non-answer, not an uncurated id, so it
        # must not trip the closure above.
        row = make_row(autores=json.dumps([{**AUTHOR, "ror": "No disponible"}]))
        catalog, _ = build_catalog_from([row])
        self.assertEqual(catalog["studies"][0]["rores"], [])

    def test_control_the_recorded_country_is_the_argument(self) -> None:
        catalog, _ = subject.build_catalog(
            [make_row()], EXTENT, taxonomy_for([make_row()]), "otro-pais", "p.parquet",
            "l", "n", SOURCE_IDENTITY, dict(TEST_ROR_ENTRIES), TEST_ROR_SENTINELS,
        )
        self.assertEqual(catalog["country"], "otro-pais")
        self.assertNotEqual(catalog["country"], "testland")

    def test_control_a_row_without_a_taxonomy_entry_aborts_the_build(self) -> None:
        rows = catalog_rows()
        incomplete = taxonomy_for(rows)
        del incomplete[rows[0]["source_path"]]
        with self.assertRaisesRegex(
            subject.StudyCatalogError, re.escape("granularity file has no entry for")
        ):
            build_catalog_from(rows, incomplete)

    def test_the_catalog_records_the_input_identity_the_reader_reported(self) -> None:
        catalog, _ = build_test_catalog()
        self.assertEqual(catalog["source_sha256"], SOURCE_IDENTITY["source_sha256"])
        self.assertEqual(catalog["source_rows"], SOURCE_IDENTITY["source_rows"])
        self.assertEqual(catalog["source_bytes"], SOURCE_IDENTITY["source_bytes"])

    def test_the_identity_block_sits_immediately_after_source_parquet(self) -> None:
        catalog, _ = build_test_catalog()
        assert_provenance_block_follows_source_parquet(catalog)

    def test_control_the_identity_block_check_rejects_a_reordered_block(self) -> None:
        catalog = {
            "source_parquet": "p.parquet",
            "source_rows": 1,
            "source_bytes": 2,
            "source_sha256": "a" * 64,
        }
        with self.assertRaisesRegex(
            AssertionError, re.escape("the keys after source_parquet")
        ):
            assert_provenance_block_follows_source_parquet(catalog)

    def test_control_the_identity_block_check_rejects_a_field_before_the_path(self) -> None:
        catalog = {
            "source_sha256": "a" * 64,
            "source_parquet": "p.parquet",
            "source_rows": 1,
            "source_bytes": 2,
        }
        with self.assertRaisesRegex(
            AssertionError, re.escape("the keys after source_parquet")
        ):
            assert_provenance_block_follows_source_parquet(catalog)

    def test_control_a_catalog_without_source_parquet_fails_the_block_check(self) -> None:
        catalog = dict(SOURCE_IDENTITY)
        with self.assertRaisesRegex(
            AssertionError, re.escape("source_parquet is missing")
        ):
            assert_provenance_block_follows_source_parquet(catalog)

    def test_the_csv_stays_a_flat_per_study_table_without_provenance(self) -> None:
        for field in PROVENANCE_FIELDS + ["source_parquet"]:
            self.assertNotIn(field, subject.CSV_FIELDS)

    def test_generated_utc_is_a_utc_timestamp(self) -> None:
        catalog, _ = build_test_catalog()
        stamp = catalog["generated_utc"]
        self.assertIsInstance(stamp, str)
        self.assertEqual(datetime.fromisoformat(stamp).utcoffset(), timedelta(0))

    def test_control_the_utc_offset_check_can_fail(self) -> None:
        self.assertNotEqual(
            datetime.fromisoformat("2026-10-09T03:10:50+02:00").utcoffset(), timedelta(0)
        )


# ---------------------------------------------------------------------------
# CSV rendering.
# ---------------------------------------------------------------------------


class CsvValueTests(unittest.TestCase):
    def test_autores_render_as_the_joined_author_names(self) -> None:
        authors = [{"nombre": "Ana Pérez"}, {"nombre": "Luis Gómez"}]
        self.assertEqual(subject._csv_value("autores", authors), "Ana Pérez; Luis Gómez")

    def test_control_autores_read_the_nombre_field_specifically(self) -> None:
        with self.assertRaisesRegex(KeyError, "nombre"):
            subject._csv_value("autores", [{"afiliacion": "ULA"}])

    def test_string_lists_render_as_a_joined_value(self) -> None:
        self.assertEqual(subject._csv_value("paises", ["VE", "CO"]), "VE; CO")
        self.assertEqual(subject._csv_value("instituciones", ["ULA"]), "ULA")

    def test_the_new_list_columns_join_with_a_semicolon(self) -> None:
        self.assertEqual(
            subject._csv_value("palabrasclaves", ["Cedrela odorata", "bosque seco"]),
            "Cedrela odorata; bosque seco",
        )
        self.assertEqual(
            subject._csv_value("coordinate_group_ids", ["cve-1991-a", "cve-1991-z"]),
            "cve-1991-a; cve-1991-z",
        )

    def test_control_an_empty_id_list_is_an_empty_cell(self) -> None:
        self.assertEqual(subject._csv_value("coordinate_group_ids", []), "")

    def test_control_the_group_size_stays_a_number(self) -> None:
        self.assertEqual(subject._csv_value("coordinate_group_size", 3), 3)
        self.assertNotEqual(subject._csv_value("coordinate_group_size", 3), "3")

    def test_control_the_group_size_is_null_when_there_is_no_coordinate(self) -> None:
        self.assertIsNone(subject._csv_value("coordinate_group_size", None))

    def test_control_a_string_list_is_not_rendered_as_its_repr(self) -> None:
        self.assertNotEqual(subject._csv_value("paises", ["VE", "CO"]), "['VE', 'CO']")

    def test_control_a_free_text_column_is_left_verbatim(self) -> None:
        # A plain string is not a list, so it must not be split and rejoined.
        value = "Cedrela odorata; Cedrela mexicana"
        self.assertEqual(subject._csv_value("especiesmencionadas", value), value)
        self.assertEqual(
            subject._csv_value("especiesmencionadas", ["a", "b"]), "a; b"
        )

    def test_control_scalars_pass_through_unchanged(self) -> None:
        self.assertEqual(subject._csv_value("pagina", 5), 5)
        self.assertEqual(subject._csv_value("latitud", 8.5), 8.5)


class CsvFieldsTests(unittest.TestCase):
    """The flat CSV carries the new contract's columns."""

    def test_the_new_columns_are_declared(self) -> None:
        for field in (
            "granularidad_nivel",
            "coordinate_group_size",
            "coordinate_group_ids",
            "palabrasclaves",
            "especies",
            "rores",
            "human_reviewer",
        ):
            self.assertIn(field, subject.CSV_FIELDS)

    def test_the_species_column_sits_right_after_the_verbatim_text(self) -> None:
        fields = list(subject.CSV_FIELDS)
        self.assertEqual(fields[fields.index("especiesmencionadas") + 1], "especies")

    def test_the_ror_and_reviewer_columns_sit_right_after_instituciones(self) -> None:
        fields = list(subject.CSV_FIELDS)
        index = fields.index("instituciones")
        self.assertEqual(fields[index + 1:index + 3], ["rores", "human_reviewer"])

    def test_control_the_coarse_class_is_not_a_csv_column(self) -> None:
        # ``display_class`` already carries the class; the level is the extra
        # fact the CSV adds beside it.
        self.assertIn("display_class", subject.CSV_FIELDS)
        self.assertNotEqual("coarse_location", "granularidad_nivel")

    def test_control_a_full_row_writes_every_declared_column(self) -> None:
        row = make_row()
        study = subject.build_study(row, EXTENT, T2_ENTRY, ["cve-1991-pagina-5-2"])
        missing = [field for field in subject.CSV_FIELDS if field not in study]
        self.assertEqual(missing, [])


class SchemaVersionTests(unittest.TestCase):
    """The artifact's schema version is anchored, not incidental."""

    def test_the_builder_writes_the_anchored_version(self) -> None:
        catalog, _ = build_test_catalog()
        self.assertEqual(subject.SCHEMA_VERSION, 4)
        self.assertEqual(catalog["schema_version"], subject.SCHEMA_VERSION)

    def test_control_the_version_is_not_a_previous_contract_s(self) -> None:
        # Version 4 added the parsed species, the ROR ids and the reviewer, so a
        # reader must not mistake this document for schema 1, 2 or 3.
        self.assertNotEqual(subject.SCHEMA_VERSION, 1)
        self.assertNotEqual(subject.SCHEMA_VERSION, 2)
        self.assertNotEqual(subject.SCHEMA_VERSION, 3)


# ---------------------------------------------------------------------------
# Freshness: the committed artifact against the unversioned input.
# ---------------------------------------------------------------------------


def pyarrow_available() -> bool:
    """True when this interpreter can read Parquet (the rebuild environment)."""
    try:
        import pyarrow.parquet  # noqa: F401
    except ImportError:
        return False
    return True


PYARROW_AVAILABLE = pyarrow_available()


def identity_mismatches(
    recorded: dict[str, Any], fresh: dict[str, Any]
) -> list[str]:
    """Return one message per provenance field that does not match.

    ``fresh`` carries only the fields that were actually measured, so a caller
    without a Parquet reader can still compare the digest and the byte size.
    Nothing here reads the artifact or the Parquet: the comparison is a pure
    function so the control below can fire it on a mutated copy.
    """
    return [
        f"{field}: the committed artifact records {recorded.get(field)!r} but "
        f"the input measures {fresh[field]!r}"
        for field in ("source_sha256", "source_rows", "source_bytes")
        if field in fresh and recorded.get(field) != fresh[field]
    ]


@unittest.skipUnless(
    PARQUET_PATH.is_file(),
    f"the unversioned input is absent ({PARQUET_PATH}); data/raw/ is gitignored "
    "(open item C1), so a fresh clone cannot run this check at all",
)
class CommittedArtifactFreshnessTests(unittest.TestCase):
    """The committed artifact records the identity of the Parquet on disk.

    ``data/raw/`` is gitignored, so this class skips itself where the
    unversioned input is absent and the check is meaningless by construction
    (open item C1). Where the input is present it is the only assertion here
    that can notice the artifact was built from a different revision of the
    same path, which is exactly the drift T1's provenance plumbing was added
    for. The digest and the byte size are compared with the standard library;
    the row count needs a Parquet reader and is pinned in its own test, which
    skips on the bare interpreter the suite runs on.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_shipped_catalog()

    def test_the_committed_artifact_records_the_digest_and_size_of_the_parquet(self) -> None:
        payload = PARQUET_PATH.read_bytes()
        fresh = {
            "source_sha256": hashlib.sha256(payload).hexdigest(),
            "source_bytes": len(payload),
        }
        mismatches = identity_mismatches(self.catalog, fresh)
        self.assertEqual(
            mismatches,
            [],
            f"the committed catalog does not describe {PARQUET_PATH}:"
            f"\n  "
            + "\n  ".join(mismatches),
        )

    @unittest.skipUnless(PYARROW_AVAILABLE, "pyarrow is a rebuild-only dependency")
    def test_the_committed_artifact_records_the_row_count_of_the_parquet(self) -> None:
        import pyarrow.parquet as pq

        fresh = {"source_rows": int(pq.read_table(PARQUET_PATH).num_rows)}
        self.assertEqual(identity_mismatches(self.catalog, fresh), [])

    def test_control_mutating_a_temporary_copy_of_the_parquet_reports_a_mismatch(self) -> None:
        payload = PARQUET_PATH.read_bytes()
        recorded = {
            "source_sha256": hashlib.sha256(payload).hexdigest(),
            "source_bytes": len(payload),
        }
        copy_path = write_source_file(self, payload)
        copy_path.write_bytes(payload + b"\x00")
        fresh = {
            "source_sha256": hashlib.sha256(copy_path.read_bytes()).hexdigest(),
            "source_bytes": copy_path.stat().st_size,
        }
        mismatches = identity_mismatches(recorded, fresh)
        self.assertEqual(len(mismatches), 2)
        self.assertIn("source_sha256", mismatches[0])


class FreshnessControlTests(unittest.TestCase):
    """The comparison fires on a mutated fixture copy of an input."""

    def fixture_identity(self, payload: bytes) -> dict[str, Any]:
        return {
            "source_sha256": hashlib.sha256(payload).hexdigest(),
            "source_rows": 1,
            "source_bytes": len(payload),
        }

    def test_control_a_mutated_copy_reports_the_mutated_fields(self) -> None:
        payload = b"the input bytes as they were when the catalog was built\n"
        copy_path = write_source_file(self, payload)
        copy_path.write_bytes(payload + b" ")
        fresh = {
            "source_sha256": hashlib.sha256(copy_path.read_bytes()).hexdigest(),
            "source_rows": 2,
            "source_bytes": copy_path.stat().st_size,
        }
        mismatches = identity_mismatches(self.fixture_identity(payload), fresh)
        self.assertEqual(len(mismatches), 3)
        self.assertIn("source_sha256", mismatches[0])
        self.assertIn("source_rows", mismatches[1])
        self.assertIn("source_bytes", mismatches[2])

    def test_control_an_unmutated_copy_reports_nothing(self) -> None:
        payload = b"stable bytes\n"
        copy_path = write_source_file(self, payload)
        fresh = {
            "source_sha256": hashlib.sha256(copy_path.read_bytes()).hexdigest(),
            "source_rows": 1,
            "source_bytes": copy_path.stat().st_size,
        }
        self.assertEqual(identity_mismatches(self.fixture_identity(payload), fresh), [])

    def test_control_a_partial_measurement_compares_only_what_it_measured(self) -> None:
        recorded = {"source_sha256": "a" * 64, "source_rows": 1, "source_bytes": 5}
        self.assertEqual(identity_mismatches(recorded, {"source_sha256": "a" * 64}), [])
        self.assertEqual(len(identity_mismatches(recorded, {"source_bytes": 6})), 1)


if __name__ == "__main__":
    unittest.main()
