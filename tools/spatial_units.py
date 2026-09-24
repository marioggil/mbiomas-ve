"""Single source of truth for spatial units and row-wise geodesic area.

WHY THIS MODULE EXISTS
----------------------
The composition engine consumes whatever spatial partition the platform
chooses: the whole raster extent (the committed behaviour today), H3
hexagons at resolution 8-9 (planned for phase F3, decision D4), or any
other partition a future contributor introduces. The rest of the tool
chain only cares about (class, unit) tables and stable unit identifiers;
it must not depend on whether the partition is contiguous, hexagonal or
irregular.

To keep that contract clean:

* `compute_row_areas_m2` is the ONLY row-wise geodesic area calculator in
  this codebase. Any module that needs the same numbers imports it from
  here. The WGS84 authalic radius constant and the north-up/south-up
  orientation guard live next to it so they cannot drift.
* `SpatialUnit` is the smallest interface an implementation must satisfy.
  Composition code consumes that interface and never inspects which
  concrete unit is active.
* `ExtentUnit` reproduces today's behaviour exactly: every pixel belongs
  to the single extent unit and the row area is taken whole.
* `H3Unit` is a declared stub. Construction and any interface call raise
  with a message that names phase F3, so a future contributor cannot
  accidentally wire it in and silently produce wrong-looking numbers.

USAGE FROM COMPOSITION STATS
----------------------------
    from tools.spatial_units import (
        compute_row_areas_m2, ExtentUnit, H3Unit, OUTSIDE_UNIT,
    )

    row_areas_m2 = compute_row_areas_m2(gt, width, height)
    unit = ExtentUnit()           # or H3Unit(...), once F3 ships
    for yoff in range(0, height, row_block):
        block_h = min(row_block, height - yoff)
        assign = unit.assign_row_block(gt, width, yoff, block_h)
        unit_areas = unit.unit_areas_m2_row_block(row_areas_m2, yoff, block_h)
        # ... accumulate (class x unit) counts and areas ...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

# Authalic radius of the WGS84 ellipsoid in metres: the radius of a
# sphere with the same surface area as the ellipsoid. Used so the sum of
# row areas approximates the true surface area of the geographic grid.
AUTHALIC_RADIUS_M = 6371007.181

# Sentinel used by SpatialUnit implementations to flag a pixel that does
# not fall inside any unit. Picked as a small negative integer so it fits
# in a signed 32-bit integer alongside real unit indices (which are
# non-negative) and so it cannot collide with any plausible unit id.
OUTSIDE_UNIT: int = -1

F3_H3_NOT_IMPLEMENTED_MSG = (
    "H3Unit is declared but not implemented: hexagonal aggregation is "
    "scheduled for phase F3 of the plataforma-cobertura-ve rollout "
    "(decision D4). Use --unit extent until F3 ships; do not request "
    "--unit h3 against this build."
)


def compute_row_areas_m2(
    geotransform: tuple[float, ...],
    width: int,
    height: int,
) -> np.ndarray:
    """Return a (height,) array of geodesic row areas in m^2.

    For each row j we derive the top and bottom edge latitudes from the
    file's own geotransform (gdal GetGeoTransform), map them to radians,
    and apply the spherical-strip formula

        R^2 * delta_lambda_rad * (sin(phi_top) - sin(phi_bottom))

    with R = AUTHALIC_RADIUS_M and delta_lambda_rad the longitude extent
    of the row in radians.

    We order phi_top >= phi_bot so that sin(phi_top) - sin(phi_bot) stays
    positive for both north-up rasters (negative pixel height) and
    south-up rasters (positive pixel height); the orientation is read
    from the geotransform, never hardcoded. Per-pixel area for row j is
    then area_m2[j] / width.
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


class SpatialUnit:
    """Smallest interface the composition engine needs from a partition.

    Implementations must expose:

    * ``name`` (str) and ``describe()`` (JSON-safe dict) for the summary
      metadata written by ``composition_stats``;
    * ``unit_count`` (int) and ``unit_ids`` (sequence of str) so the
      caller can size output buffers and report stable identifiers;
    * ``assign_row_block`` returning an int32 array of shape
      (block_h, width) where every cell holds either a unit index in
      ``[0, unit_count)`` or the sentinel ``OUTSIDE_UNIT``;
    * ``unit_areas_m2_row_block`` returning a float64 array of shape
      (block_h, unit_count) where row j, column u is the geodesic area
      in m^2 that unit u covers in row j. The full raster row-area
      vector is precomputed by the caller via ``compute_row_areas_m2``
      so the unit never re-derives the spherical-strip geometry.
    """

    name: str

    def describe(self) -> dict[str, Any]:
        raise NotImplementedError

    @property
    def unit_count(self) -> int:
        raise NotImplementedError

    @property
    def unit_ids(self) -> list[str]:
        raise NotImplementedError

    def assign_row_block(
        self,
        geotransform: tuple[float, ...],
        width: int,
        yoff: int,
        block_h: int,
    ) -> np.ndarray:
        raise NotImplementedError

    def unit_areas_m2_row_block(
        self,
        row_areas_m2: np.ndarray,
        yoff: int,
        block_h: int,
    ) -> np.ndarray:
        raise NotImplementedError


class ExtentUnit(SpatialUnit):
    """The whole raster as a single unit.

    Reproduces the pre-refactor behaviour exactly: every pixel belongs
    to unit 0, the unit covers the full row area in m^2, and the
    per-pixel area within the row is the row area divided by raster
    width. The assigned matrix and the per-row areas are allocated on
    demand per block, so streaming and bounded memory are preserved.
    """

    name = "extent"
    _unit_id = "extent:0"

    def __init__(self) -> None:
        # Extent unit is parameter-free: its geometry is the whole
        # raster, identified by its name only.
        return

    @property
    def unit_count(self) -> int:
        return 1

    @property
    def unit_ids(self) -> list[str]:
        return [self._unit_id]

    def describe(self) -> dict[str, Any]:
        return {
            "type": "extent",
            "name": self.name,
            "unit_count": self.unit_count,
            "unit_ids": list(self.unit_ids),
        }

    def assign_row_block(
        self,
        geotransform: tuple[float, ...],
        width: int,
        yoff: int,
        block_h: int,
    ) -> np.ndarray:
        # Every pixel lives in the single extent unit; sentinel never
        # appears. int32 to honour the SpatialUnit interface contract.
        return np.zeros((block_h, width), dtype=np.int32)

    def unit_areas_m2_row_block(
        self,
        row_areas_m2: np.ndarray,
        yoff: int,
        block_h: int,
    ) -> np.ndarray:
        # Shape (block_h, 1) so the 3-D (row, unit, class) histogram
        # below stays two-dimensional in the ExtentUnit case.
        return row_areas_m2[yoff:yoff + block_h].reshape(block_h, 1)


class H3Unit(SpatialUnit):
    """Declared stub for the F3 hexagonal partition (decision D4).

    Construction and any interface call raise immediately with a message
    that names phase F3. The class exists so that:

    * callers can type-annotate against the future implementation;
    * an accidental ``H3Unit(...)`` in a future commit fails loudly at
      the very first line of instantiation instead of returning
      plausible-looking but wrong numbers from a half-wired stub.

    Once F3 ships, replace this stub with a real implementation that
    satisfies the SpatialUnit contract using h3-py.
    """

    name = "h3"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError(F3_H3_NOT_IMPLEMENTED_MSG)

    @property
    def unit_count(self) -> int:
        raise RuntimeError(F3_H3_NOT_IMPLEMENTED_MSG)

    @property
    def unit_ids(self) -> list[str]:
        raise RuntimeError(F3_H3_NOT_IMPLEMENTED_MSG)

    def describe(self) -> dict[str, Any]:
        raise RuntimeError(F3_H3_NOT_IMPLEMENTED_MSG)

    def assign_row_block(
        self,
        geotransform: tuple[float, ...],
        width: int,
        yoff: int,
        block_h: int,
    ) -> np.ndarray:
        raise RuntimeError(F3_H3_NOT_IMPLEMENTED_MSG)

    def unit_areas_m2_row_block(
        self,
        row_areas_m2: np.ndarray,
        yoff: int,
        block_h: int,
    ) -> np.ndarray:
        raise RuntimeError(F3_H3_NOT_IMPLEMENTED_MSG)
