"""Anchor the composition-summary JSON contract (schema version 2).

Closes native review finding ``R3-missing-coverage-v2-shape`` (reliability, CRITICAL,
causality unknown), raised against commit ``a48cb6c`` and escalated terminally by the
provider with ``native_stop_required``. That commit moved every per-year record under a
single ``per_year`` object and added a top-level ``schema_version``, but nothing asserted
the resulting shape: a refactor that flattened the years back to the top level, or dropped
``schema_version``, would have satisfied every existing check.

This test drives the real writer, ``tools.composition_stats.write_outputs``, with synthetic
totals. It reads no raster and modifies no production code, so it adds no unreviewed
production surface.

Run it with the SYSTEM interpreter, not the pinned ``.venv``: ``composition_stats`` imports
``from osgeo import gdal`` at module level and the venv carries no GDAL. From the repository
root::

    python3 -m unittest discover -s tests -v

Design note. Passing over the current output is not evidence, so the same standard applied to
the COG pyramid in T3 is applied here: the NEAREST resampling claim was only accepted once an
AVERAGE control fabricated class codes, proving the method could separate the two.
``SchemaContractControlTests`` feeds deliberately broken summaries to the same
``assert_v2_contract`` checker and asserts that it rejects them. That is what shows the checker
separates v2 from v1 instead of accepting whatever it is handed.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from composition_stats import SCHEMA_VERSION, YearTotals, write_outputs  # noqa: E402
from spatial_units import ExtentUnit  # noqa: E402

COUNTRY = "testland"
COLLECTION = "1"

# A four-digit year key, which is the shape that must never appear at the top level.
YEAR_KEY_RE = re.compile(r"^\d{4}$")

# The schema-version-1 per-year payload field set. Schema version 2 moved the record but
# did not change its contents, so this set must hold exactly, not as a subset.
PER_YEAR_FIELDS = frozenset(
    {
        "valid_area_ha",
        "nodata_area_ha",
        "total_extent_ha",
        "nodata_pixels",
        "total_pixels",
        "valid_pixels",
        "class_pixels",
        "class_presence",
    }
)

# Two classes in one level-1 group plus one class in a second group, so the level-1
# aggregation the writer performs is genuinely exercised rather than being a copy of the
# level-2 rows.
CODEBOOK: dict[str, Any] = {
    "level1": [
        {
            "pixel_id": 1,
            "code": "1",
            "name_es": "Formaciones boscosas",
            "name_en": "Forest Formations",
        },
        {
            "pixel_id": 26,
            "code": "26",
            "name_es": "Cuerpos de agua",
            "name_en": "Water Bodies",
        },
    ],
    "classes": [
        {
            "pixel_id": 3,
            "code": "3",
            "level1_pixel_id": 1,
            "level1_code": "1",
            "name_es": "Bosque",
            "name_en": "Forest",
        },
        {
            "pixel_id": 4,
            "code": "4",
            "level1_pixel_id": 1,
            "level1_code": "1",
            "name_es": "Sabana",
            "name_en": "Savanna",
        },
        {
            "pixel_id": 33,
            "code": "33",
            "level1_pixel_id": 26,
            "level1_code": "26",
            "name_es": "Río, lago u océano",
            "name_en": "River, lake or ocean",
        },
    ],
    "invariants": {"nodata_value": 0},
}

# Synthetic totals that satisfy the writer's own pre-write assertions: the class areas sum
# to the level-1 areas derived from those same classes, and class areas plus nodata equal
# the total extent. Width times height equals total_pixels, and class pixels plus nodata
# pixels equals that same total, so the payload is internally coherent.
CLASS_PIXELS = {3: 60, 4: 25, 33: 10}
CLASS_AREA_M2 = {3: 1000.0, 4: 500.0, 33: 250.0}
NODATA_PIXELS = 5
NODATA_AREA_M2 = 250.0
TOTAL_EXTENT_M2 = 2000.0
WIDTH = 10
HEIGHT = 10

SAMPLE_YEARS = (1985, 2000, 2024)


def make_year_totals(year: int) -> YearTotals:
    """Return coherent synthetic totals for one year."""
    return YearTotals(
        year=year,
        class_pixels=dict(CLASS_PIXELS),
        class_area_m2=dict(CLASS_AREA_M2),
        nodata_pixels=NODATA_PIXELS,
        nodata_area_m2=NODATA_AREA_M2,
        total_extent_m2=TOTAL_EXTENT_M2,
        width=WIDTH,
        height=HEIGHT,
    )


def write_summary(years: tuple[int, ...], outdir: str) -> dict[str, Any]:
    """Run the real writer into ``outdir`` and return the parsed summary JSON."""
    write_outputs(
        Namespace(country=COUNTRY, collection=COLLECTION),
        CODEBOOK,
        [make_year_totals(year) for year in years],
        Path(outdir),
        ExtentUnit(),
    )
    summary_path = Path(outdir) / (
        f"composition-summary-{COUNTRY}-collection-{COLLECTION}.json"
    )
    return json.loads(summary_path.read_text(encoding="utf-8"))


def assert_v2_contract(summary: dict[str, Any]) -> None:
    """Raise ``AssertionError`` unless ``summary`` is a valid schema-version-2 summary.

    Every check is an explicit assertion rather than ``assertTrue``, so a failure names the
    property that broke instead of only the test.
    """
    # 1. The summary is versioned, and with the version the writer currently emits.
    assert "schema_version" in summary, "summary has no top-level schema_version"
    assert summary["schema_version"] == SCHEMA_VERSION, (
        f"schema_version is {summary['schema_version']!r}, expected {SCHEMA_VERSION!r}"
    )

    # 2. The per-year records live in an object, not a list.
    assert "per_year" in summary, "summary has no per_year object"
    per_year = summary["per_year"]
    assert isinstance(per_year, dict), (
        f"per_year is {type(per_year).__name__}, expected dict"
    )
    assert per_year, "per_year is empty"

    # 3. Its keys are four-digit years, and they are exactly the reported years.
    for key in per_year:
        assert isinstance(key, str) and YEAR_KEY_RE.match(key), (
            f"per_year key {key!r} is not a four-digit year string"
        )
    reported = {str(year) for year in summary["years"]}
    assert set(per_year) == reported, (
        f"per_year keys {sorted(per_year)} != reported years {sorted(reported)}"
    )

    # 4. The regression this file exists for: no year key may survive at the top level.
    stray = sorted(key for key in summary if YEAR_KEY_RE.match(str(key)))
    assert not stray, f"year keys leaked to the top level: {stray}"

    # 5. Each per-year payload keeps the schema-version-1 field set exactly.
    for key, payload in per_year.items():
        assert isinstance(payload, dict), f"per_year[{key!r}] is not an object"
        fields = set(payload)
        missing = PER_YEAR_FIELDS - fields
        extra = fields - PER_YEAR_FIELDS
        assert not missing, f"per_year[{key!r}] lost fields: {sorted(missing)}"
        assert not extra, f"per_year[{key!r}] gained fields: {sorted(extra)}"

        # 6. class_pixels is keyed by string pixel id.
        assert isinstance(payload["class_pixels"], dict), (
            f"per_year[{key!r}].class_pixels is not an object"
        )
        for pixel_id in payload["class_pixels"]:
            assert isinstance(pixel_id, str) and pixel_id.isdigit(), (
                f"per_year[{key!r}].class_pixels key {pixel_id!r} "
                "is not a string pixel id"
            )


class CompositionSummarySchemaTests(unittest.TestCase):
    """The writer's output satisfies the version-2 contract."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.summary = write_summary(SAMPLE_YEARS, cls._tmp.name)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_writer_output_satisfies_the_whole_contract(self) -> None:
        assert_v2_contract(self.summary)

    def test_schema_version_is_two(self) -> None:
        self.assertIn("schema_version", self.summary)
        self.assertEqual(self.summary["schema_version"], 2)

    def test_per_year_is_an_object_keyed_by_four_digit_years(self) -> None:
        per_year = self.summary.get("per_year")
        self.assertIsInstance(per_year, dict)
        self.assertTrue(per_year)
        for key in per_year:
            self.assertRegex(key, r"^\d{4}$")

    def test_per_year_covers_exactly_the_reported_years(self) -> None:
        self.assertEqual(
            set(self.summary["per_year"]),
            {str(year) for year in self.summary["years"]},
        )

    def test_no_year_key_survives_at_the_top_level(self) -> None:
        stray = sorted(key for key in self.summary if YEAR_KEY_RE.match(str(key)))
        self.assertEqual(stray, [], f"year keys leaked to the top level: {stray}")

    def test_per_year_payload_keeps_the_v1_field_set(self) -> None:
        for key, payload in self.summary["per_year"].items():
            self.assertEqual(
                set(payload),
                set(PER_YEAR_FIELDS),
                f"per_year[{key!r}] field set changed",
            )

    def test_class_pixels_is_keyed_by_string_pixel_id(self) -> None:
        for key, payload in self.summary["per_year"].items():
            for pixel_id in payload["class_pixels"]:
                self.assertIsInstance(pixel_id, str, f"per_year[{key!r}]")
                self.assertTrue(pixel_id.isdigit(), f"per_year[{key!r}]")


class SchemaContractControlTests(unittest.TestCase):
    """Prove every check in ``assert_v2_contract`` can actually fire.

    Each case pins the *specific* assertion it exercises with ``assertRaisesRegex``. A bare
    ``assertRaises`` is not enough: the first version of this file used it, and the control for
    a flattened summary was rejected by the missing-version check long before reaching the
    year-leak check it was supposed to prove. The year leak is the regression this whole file
    exists for, so it needs its own control with the summary otherwise valid.
    """

    def _payload(self, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {field: None for field in PER_YEAR_FIELDS}
        payload["class_pixels"] = {}
        payload.update(overrides)
        return payload

    def _valid_v2(self, years: tuple[int, ...] = (1985,)) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "years": list(years),
            "per_year": {str(year): self._payload() for year in years},
        }

    # --- check 1: the summary is versioned -------------------------------------------

    def test_control_rejects_a_flattened_v1_summary(self) -> None:
        flattened = {
            "extent_label": "extension MapBiomas Venezuela",
            "years": [1985],
            "1985": self._payload(),
        }
        with self.assertRaisesRegex(AssertionError, "no top-level schema_version"):
            assert_v2_contract(flattened)

    def test_control_rejects_a_missing_schema_version(self) -> None:
        broken = {"years": [1985], "per_year": {"1985": self._payload()}}
        with self.assertRaisesRegex(AssertionError, "no top-level schema_version"):
            assert_v2_contract(broken)

    def test_control_rejects_a_wrong_schema_version(self) -> None:
        broken = self._valid_v2()
        broken["schema_version"] = 1
        with self.assertRaisesRegex(AssertionError, "schema_version is 1"):
            assert_v2_contract(broken)

    # --- check 3: per_year exists and is a non-empty object --------------------------

    def test_control_rejects_a_missing_per_year_object(self) -> None:
        broken = {"schema_version": SCHEMA_VERSION, "years": [1985]}
        with self.assertRaisesRegex(AssertionError, "no per_year object"):
            assert_v2_contract(broken)

    def test_control_rejects_a_per_year_list_instead_of_an_object(self) -> None:
        broken = self._valid_v2()
        broken["per_year"] = [self._payload()]
        with self.assertRaisesRegex(AssertionError, "per_year is list"):
            assert_v2_contract(broken)

    def test_control_rejects_an_empty_per_year_object(self) -> None:
        broken = {"schema_version": SCHEMA_VERSION, "years": [], "per_year": {}}
        with self.assertRaisesRegex(AssertionError, "per_year is empty"):
            assert_v2_contract(broken)

    # --- check 6: per_year keys are four-digit years ---------------------------------

    def test_control_rejects_a_per_year_key_that_is_not_a_year(self) -> None:
        broken = self._valid_v2()
        broken["per_year"] = {"year-1985": self._payload()}
        with self.assertRaisesRegex(AssertionError, "is not a four-digit year"):
            assert_v2_contract(broken)

    # --- check 7: per_year keys are exactly the reported years -----------------------

    def test_control_rejects_per_year_keys_that_miss_a_reported_year(self) -> None:
        broken = self._valid_v2((1985, 2000))
        del broken["per_year"]["2000"]
        with self.assertRaisesRegex(AssertionError, "!= reported years"):
            assert_v2_contract(broken)

    # --- check 8: THE REGRESSION. A year key must not survive at the top level. ------

    def test_control_rejects_a_valid_v2_summary_with_a_stray_top_level_year(self) -> None:
        # Everything else is correct, so the only thing that can reject this is the
        # year-leak check. This is the case the earlier bare assertRaises controls missed.
        broken = self._valid_v2()
        broken["1985"] = self._payload()
        with self.assertRaisesRegex(AssertionError, "leaked to the top level"):
            assert_v2_contract(broken)

    def test_control_rejects_many_stray_top_level_years(self) -> None:
        broken = self._valid_v2((1985, 2000, 2024))
        for year in (1985, 2000, 2024):
            broken[str(year)] = self._payload()
        with self.assertRaisesRegex(AssertionError, "leaked to the top level"):
            assert_v2_contract(broken)

    # --- check 9: each payload is an object -----------------------------------------

    def test_control_rejects_a_non_object_payload(self) -> None:
        broken = self._valid_v2()
        broken["per_year"] = {"1985": "not-an-object"}
        with self.assertRaisesRegex(AssertionError, "is not an object"):
            assert_v2_contract(broken)

    # --- check 10 and 11: the payload field set is exact ----------------------------

    def test_control_rejects_a_payload_that_lost_a_field(self) -> None:
        broken = self._valid_v2()
        del broken["per_year"]["1985"]["class_presence"]
        with self.assertRaisesRegex(AssertionError, "lost fields"):
            assert_v2_contract(broken)

    def test_control_rejects_a_payload_that_gained_a_field(self) -> None:
        broken = self._valid_v2()
        broken["per_year"]["1985"]["unexpected_field"] = 1
        with self.assertRaisesRegex(AssertionError, "gained fields"):
            assert_v2_contract(broken)

    # --- check 12 and 13: class_pixels is keyed by string pixel id -------------------

    def test_control_rejects_a_non_object_class_pixels(self) -> None:
        broken = self._valid_v2()
        broken["per_year"]["1985"]["class_pixels"] = [3, 4]
        with self.assertRaisesRegex(AssertionError, "class_pixels is not an object"):
            assert_v2_contract(broken)

    def test_control_rejects_a_non_string_class_pixel_id(self) -> None:
        broken = self._valid_v2()
        broken["per_year"]["1985"]["class_pixels"] = {3: 1}
        with self.assertRaisesRegex(AssertionError, "is not a string pixel id"):
            assert_v2_contract(broken)


if __name__ == "__main__":
    unittest.main()
