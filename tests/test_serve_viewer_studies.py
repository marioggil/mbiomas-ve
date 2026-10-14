"""Anchor the import-time invariants of the studies-catalog validator.

``tools/serve_viewer.py`` parses and validates
``data/derived/<country>/congresos/catalogo-estudios.json`` once when the module
loads, and refuses to start on an internally inconsistent artifact. This file
loads the committed artifact, deep-copies it per case, mutates exactly one thing
and proves that the branch it was written for fires. A bare ``assertRaises`` is
not enough: a mutation can be rejected by an earlier check and leave the target
branch silently untested, so every control pins its branch with
``assertRaisesRegex``.

The coordinate-conditional display-class rule is the one the feature document
records after an interaction: an absent coordinate outranks the taxonomy test
(``display_class_for`` returns ``no_coordinate`` first), while the level is still
recorded for those rows because rule A of the curated taxonomy classifies an
unusable location text as T0. The shipped artifact reflects it — ``no_coordinate``
10 (all T0), ``coarse_location`` 87 (56 T0 + 31 T1), ``outside_extent`` 13 (T2),
``placeable`` 145 (T2) — and the positive case here asserts the whole catalog
passes the validator as committed.

Interpreter. ``serve_viewer`` imports ``fastapi``, which the repository's bare
system interpreter does not have. The module therefore imports cleanly without it
and every case skips there, so ``python3 -m unittest discover -s tests`` still
discovers and runs the rest of the suite. It runs fully with the repository venv,
where ``fastapi``, ``uvicorn`` and ``pydantic`` live::

    .venv/bin/python -m unittest tests.test_serve_viewer_studies -v

Design note. This file reads the real committed artifact and modifies no
production code. It does not rebuild the artifact: the rebuild needs ``pyarrow``
and GDAL, which the venv does not carry.
"""

from __future__ import annotations

import copy
import json
import sys
import unittest
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

# fastapi is a serve-only dependency. The bare interpreter cannot import
# serve_viewer at all, so the guard keeps discovery working there and the cases
# below are skipped instead of erroring.
try:
    import fastapi  # noqa: F401

    _HAVE_FASTAPI = True
except ImportError:  # pragma: no cover - exercised on the bare interpreter
    _HAVE_FASTAPI = False

if _HAVE_FASTAPI:
    import serve_viewer  # noqa: E402
else:  # pragma: no cover - exercised on the bare interpreter
    serve_viewer = None  # type: ignore[assignment]

SERVE_ONLY = "fastapi is a serve-only dependency"

# The committed artifact is parsed once and deep-copied per case, so a mutation
# can never leak into the next case and the file on disk is never touched.
_COMMITTED_CATALOG: dict[str, Any] | None = None


def _committed_catalog() -> dict[str, Any]:
    """Return a deep copy of the committed studies catalog."""
    global _COMMITTED_CATALOG
    if _COMMITTED_CATALOG is None:
        assert serve_viewer is not None
        _COMMITTED_CATALOG = json.loads(
            serve_viewer.STUDIES_CATALOG_PATH.read_text(encoding="utf-8")
        )
    return copy.deepcopy(_COMMITTED_CATALOG)


@unittest.skipUnless(_HAVE_FASTAPI, SERVE_ONLY)
class CommittedStudiesCatalogTests(unittest.TestCase):
    """The committed artifact satisfies the validator exactly as shipped."""

    def test_committed_catalog_satisfies_the_validator(self) -> None:
        assert serve_viewer is not None
        serve_viewer._validate_studies_catalog(
            _committed_catalog(), serve_viewer.STUDIES_CATALOG_PATH
        )

    def test_committed_catalog_is_the_version_3_255_study_rebuild(self) -> None:
        catalog = _committed_catalog()
        self.assertEqual(catalog["schema_version"], 3)
        self.assertEqual(catalog["study_count"], 255)
        self.assertEqual(len(catalog["studies"]), 255)
        # The numbers the map note renders, pinned against the committed
        # artifact as a whole rather than through the validator. 28 of the 69
        # markers sit on the Imataca reserve centroid alone: the reserve is T2,
        # a decision the review kept.
        contract = catalog["display_contract"]
        self.assertEqual(contract["collision_coordinate_count"], 15)
        self.assertEqual(contract["collision_marker_count"], 69)


@unittest.skipUnless(_HAVE_FASTAPI, SERVE_ONLY)
class StudiesCatalogInvariantControlTests(unittest.TestCase):
    """Prove every new branch of the validator fires on its own mutation."""

    def setUp(self) -> None:
        self.catalog = _committed_catalog()

    def _validate(self, catalog: dict[str, Any]) -> None:
        assert serve_viewer is not None
        serve_viewer._validate_studies_catalog(
            catalog, serve_viewer.STUDIES_CATALOG_PATH
        )

    def _fail(self, catalog: dict[str, Any], pattern: str) -> None:
        assert serve_viewer is not None
        with self.assertRaisesRegex(serve_viewer.StudiesCatalogError, pattern):
            self._validate(catalog)

    def _study(self, predicate: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
        for study in self.catalog["studies"]:
            if predicate(study):
                return study
        raise AssertionError("the committed artifact has no study for this control")

    def _study_by_id(self, study_id: str) -> dict[str, Any]:
        for study in self.catalog["studies"]:
            if study["study_id"] == study_id:
                return study
        raise AssertionError(f"the committed artifact has no study {study_id!r}")

    # --- invariant 8: the granularity level is one of T0/T1/T2 -----------------

    def test_control_rejects_an_unknown_granularity_level(self) -> None:
        study = self._study(lambda s: s["granularidad_nivel"] == "T2")
        study["granularidad_nivel"] = "T9"
        self._fail(
            self.catalog,
            r"granularidad_nivel 'T9' which is not one of \['T0', 'T1', 'T2'\]",
        )

    # --- invariant 9: coordinate presence and display class agree --------------

    def test_control_rejects_a_coordinate_less_study_classified_coarse(self) -> None:
        # A null-coordinate row that would otherwise be a coarse_location: the
        # absent coordinate must win, so the class cannot be coarse_location.
        study = self._study(lambda s: s["display_class"] == "no_coordinate")
        study["display_class"] = "coarse_location"
        self._fail(
            self.catalog,
            r"a study without a coordinate must be 'no_coordinate'",
        )

    def test_control_rejects_a_coordinate_bearing_study_classified_no_coordinate(
        self,
    ) -> None:
        study = self._study(lambda s: s["display_class"] == "no_coordinate")
        study["latitud"] = 8.0
        study["longitud"] = -66.0
        self._fail(
            self.catalog,
            r"'no_coordinate' requires latitud and longitud to be null",
        )

    def test_control_rejects_a_t0_study_classified_outside_extent(self) -> None:
        study = self._study(lambda s: s["display_class"] == "outside_extent")
        study["granularidad_nivel"] = "T0"
        self._fail(
            self.catalog,
            r"a T0/T1 study with a coordinate must be 'coarse_location'",
        )

    def test_control_rejects_a_placeable_study_carrying_t1(self) -> None:
        study = self._study(lambda s: s["display_class"] == "placeable")
        study["granularidad_nivel"] = "T1"
        self._fail(
            self.catalog,
            r"a T0/T1 study with a coordinate must be 'coarse_location'",
        )

    def test_control_rejects_a_coarse_study_carrying_t2(self) -> None:
        study = self._study(lambda s: s["display_class"] == "coarse_location")
        study["granularidad_nivel"] = "T2"
        self._fail(
            self.catalog,
            r"a T2 study must be 'placeable' or 'outside_extent'",
        )

    # --- invariant 10: granularidad_razon is non-empty iff T0/T1 ----------------

    def test_control_rejects_a_t0_study_without_a_reason(self) -> None:
        study = self._study(lambda s: s["granularidad_nivel"] in ("T0", "T1"))
        study["granularidad_razon"] = None
        self._fail(self.catalog, r"but no non-empty 'granularidad_razon'")

    def test_control_rejects_a_t1_study_with_a_blank_reason(self) -> None:
        study = self._study(lambda s: s["granularidad_nivel"] in ("T0", "T1"))
        study["granularidad_razon"] = "   "
        self._fail(self.catalog, r"but no non-empty 'granularidad_razon'")

    def test_control_rejects_a_t2_study_that_carries_a_reason(self) -> None:
        study = self._study(lambda s: s["granularidad_nivel"] == "T2")
        study["granularidad_razon"] = "no debería estar aquí"
        self._fail(self.catalog, r"it must be null except for T0/T1")

    # --- invariant 11: palabrasclaves is a list of strings ---------------------

    def test_control_rejects_a_non_list_palabrasclaves(self) -> None:
        study = self._study(lambda s: True)
        study["palabrasclaves"] = "no es una lista"
        self._fail(self.catalog, r"has 'palabrasclaves' which is not a list of strings")

    def test_control_rejects_a_non_string_keyword(self) -> None:
        study = self._study(lambda s: True)
        study["palabrasclaves"] = ["clave válida", 7]
        self._fail(self.catalog, r"has 'palabrasclaves' which is not a list of strings")

    # --- invariant 12: coordinate_group_size -----------------------------------

    def test_control_rejects_a_size_on_a_coordinate_less_study(self) -> None:
        study = self._study(lambda s: s["display_class"] == "no_coordinate")
        study["coordinate_group_size"] = 2
        self._fail(
            self.catalog,
            r"has no coordinate but coordinate_group_size 2; it must be null",
        )

    def test_control_rejects_a_null_size_on_a_coordinate_bearing_study(self) -> None:
        study = self._study(lambda s: s["coordinate_group_size"] == 1)
        study["coordinate_group_size"] = None
        self._fail(self.catalog, r"is not an integer >= 1")

    def test_control_rejects_a_zero_size(self) -> None:
        study = self._study(lambda s: s["coordinate_group_size"] == 1)
        study["coordinate_group_size"] = 0
        self._fail(self.catalog, r"is not an integer >= 1")

    def test_control_rejects_a_boolean_size(self) -> None:
        # True is an int in Python; the check must reject it as a bool.
        study = self._study(lambda s: s["coordinate_group_size"] == 1)
        study["coordinate_group_size"] = True
        self._fail(self.catalog, r"is not an integer >= 1")

    # --- invariant 13: coordinate_group_ids ------------------------------------

    def test_control_rejects_a_non_list_group_ids(self) -> None:
        study = self._study(lambda s: s["coordinate_group_size"] == 1)
        study["coordinate_group_ids"] = "cve-1991-pagina-5-2"
        self._fail(
            self.catalog,
            r"has 'coordinate_group_ids' which is not a list of strings",
        )

    def test_control_rejects_a_non_string_group_id(self) -> None:
        study = self._study(lambda s: s["coordinate_group_size"] == 1)
        study["coordinate_group_ids"] = [7]
        self._fail(
            self.catalog,
            r"has 'coordinate_group_ids' which is not a list of strings",
        )

    def test_control_rejects_unsorted_group_ids(self) -> None:
        study = self._study(
            lambda s: s["coordinate_group_size"] is not None
            and s["coordinate_group_size"] >= 3
        )
        study["coordinate_group_ids"] = list(
            reversed(study["coordinate_group_ids"])
        )
        self._fail(
            self.catalog, r"'coordinate_group_ids' that are not sorted ascending"
        )

    def test_control_rejects_duplicate_group_ids(self) -> None:
        study = self._study(
            lambda s: s["coordinate_group_size"] is not None
            and s["coordinate_group_size"] >= 3
        )
        first = study["coordinate_group_ids"][0]
        study["coordinate_group_ids"] = [first, first]
        self._fail(self.catalog, r"has duplicate 'coordinate_group_ids'")

    def test_control_rejects_a_self_reference(self) -> None:
        study = self._study(
            lambda s: s["coordinate_group_size"] is not None
            and s["coordinate_group_size"] >= 2
        )
        study["coordinate_group_ids"] = sorted(
            study["coordinate_group_ids"] + [study["study_id"]]
        )
        self._fail(self.catalog, r"lists itself in 'coordinate_group_ids'")

    def test_control_rejects_a_reference_to_an_unknown_study(self) -> None:
        study = self._study(lambda s: s["coordinate_group_size"] == 2)
        study["coordinate_group_ids"] = ["cve-0000-unknown"]
        self._fail(
            self.catalog,
            r"references unknown study_id 'cve-0000-unknown' in "
            r"'coordinate_group_ids'",
        )

    # --- invariants 14 and 15: size/clique consistency and symmetric groups ----

    def test_control_rejects_a_size_that_does_not_match_the_id_list(self) -> None:
        study = self._study(lambda s: s["coordinate_group_size"] == 2)
        study["coordinate_group_ids"] = []
        self._fail(
            self.catalog,
            r"has coordinate_group_size 2 but 0 coordinate_group_ids \(expected 1\)",
        )

    def test_control_rejects_ids_on_a_study_with_a_null_size(self) -> None:
        study = self._study(lambda s: s["display_class"] == "no_coordinate")
        # An id that cannot equal the study's own, so only the null-size branch
        # can be the one that fires.
        study["coordinate_group_ids"] = ["cve-0000-not-a-real-study"]
        self._fail(
            self.catalog,
            r"has coordinate_group_size null but a non-empty "
            r"'coordinate_group_ids'",
        )

    def test_control_rejects_group_members_at_different_coordinates(self) -> None:
        study = self._study(lambda s: s["coordinate_group_size"] == 2)
        other = self._study_by_id(study["coordinate_group_ids"][0])
        other["latitud"] = other["latitud"] + 1.0
        self._fail(
            self.catalog,
            r"shares a coordinate group with .* but their coordinates differ",
        )

    def test_control_rejects_an_asymmetric_group_membership(self) -> None:
        study = self._study(lambda s: s["coordinate_group_size"] == 2)
        other = self._study_by_id(study["coordinate_group_ids"][0])
        # Drop the back-reference from this study while keeping its own
        # attributes consistent; only the other study's reference remains.
        study["coordinate_group_ids"] = []
        study["coordinate_group_size"] = 1
        self._fail(self.catalog, r"does not list .* back")
        # The other study still holds the dangling membership.
        self.assertEqual(other["coordinate_group_ids"], [study["study_id"]])

    # --- invariant 16: the display_contract field set ----------------------

    def test_control_rejects_a_display_contract_missing_a_collision_count(
        self,
    ) -> None:
        del self.catalog["display_contract"]["collision_marker_count"]
        self._fail(
            self.catalog, r"'display_contract' fields are .*expected exactly"
        )

    # --- invariant 17: the collision counts describe what the map draws ----

    def test_control_rejects_a_negative_collision_coordinate_count(self) -> None:
        self.catalog["display_contract"]["collision_coordinate_count"] = -1
        self._fail(
            self.catalog,
            r"collision_coordinate_count' \(-1\) is not a non-boolean "
            r"integer >= 0",
        )

    def test_control_rejects_a_boolean_collision_marker_count(self) -> None:
        # True is an int in Python; the check must reject it as a bool.
        self.catalog["display_contract"]["collision_marker_count"] = True
        self._fail(
            self.catalog,
            r"collision_marker_count' \(True\) is not a non-boolean "
            r"integer >= 0",
        )

    # --- the bounds on the declared numbers ---------------------------------

    def test_control_rejects_a_marker_count_above_the_map_visible_count(
        self,
    ) -> None:
        self.catalog["display_contract"]["collision_marker_count"] = 146
        self._fail(
            self.catalog,
            r"collision_marker_count' \(146\) exceeds 'map_visible_count' \(145\)",
        )

    def test_control_rejects_a_marker_count_below_twice_the_coordinate_count(
        self,
    ) -> None:
        self.catalog["display_contract"]["collision_coordinate_count"] = 20
        self.catalog["display_contract"]["collision_marker_count"] = 32
        self._fail(
            self.catalog,
            r"collision_marker_count' \(32\) is below twice "
            r"'display_contract.collision_coordinate_count' \(20\)",
        )

    # --- the recount: the counts must describe the real data ----------------

    def test_control_rejects_a_fabricated_pair_that_passes_the_bounds(self) -> None:
        # 2 coordinates / 4 markers is a non-boolean int pair that satisfies
        # both bounds (4 <= 145, 4 >= 2*2), so only the recount can reject it.
        self.catalog["display_contract"]["collision_coordinate_count"] = 2
        self.catalog["display_contract"]["collision_marker_count"] = 4
        self._fail(
            self.catalog,
            r"collision_coordinate_count' \(2\) does not match the 15 "
            r"coordinates",
        )

    def test_control_rejects_a_marker_count_that_does_not_match_the_studies(
        self,
    ) -> None:
        # The coordinate count is honest, so the bounds pass and only the
        # marker recount can reject the mutation.
        self.catalog["display_contract"]["collision_marker_count"] = 31
        self._fail(
            self.catalog,
            r"collision_marker_count' \(31\) does not match the 69 placeable "
            r"studies",
        )

    # --- invariant 18: the schema version this service understands ---------

    def test_control_rejects_a_previous_schema_version(self) -> None:
        self.catalog["schema_version"] = 2
        self._fail(self.catalog, r"schema_version is 2, expected 3")


if __name__ == "__main__":
    unittest.main()
