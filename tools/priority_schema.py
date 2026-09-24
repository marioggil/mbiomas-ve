"""Declarative, versioned schema for the F3 priority index (decision D3).

WHY THIS MODULE EXISTS
----------------------
Decision D3 establishes that the future priority index is a configurable,
weighted score whose weights are exposed and versioned - never a black
box. Decision D2 establishes that the "study gap" term must already exist
in the schema with weight 0.0 because the study abstracts are not
digitalized yet. Both decisions are encoded here as MECHANICAL invariants
in ``Term.__post_init__`` and ``PrioritySchema.__post_init__``, so they
cannot be lost in a refactor, a copy-paste, or a future AI-assisted edit
that only changes comments.

SCHEMA EVOLUTION
----------------
``SCHEMA_VERSION`` is bumped every time a term is added, removed, renamed
or has its stable key changed. Downstream tooling (the viewer in
``viewer/``, future analytics) pins a known version and re-validates
when it changes. Cosmetic edits to descriptions never bump the version.

INVARIANTS (enforced in ``__post_init__``, not assumed in callers)
-----------------------------------------------------------------
1. Every term key is unique within a schema.
2. Every weight is finite (``math.isfinite``) and non-negative.
3. A disabled term carries weight 0.0 (D2). The reverse is NOT enforced:
   a term with weight 0.0 may be enabled, because that is a legitimate
   state (a future contributor may want to remove a term's effect
   without flipping its enabled flag during a transition).
4. The shipped default schema declares ``study_gap`` disabled with
   weight 0.0 and a rationale naming D2. The invariant above guarantees
   no caller can break that.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any


SCHEMA_VERSION = 1

# Rationale attached to the study_gap term. Naming D2 here keeps the
# reason for the disabled flag tied to the project decision that
# authorised it, instead of leaving it as a free-form comment in the code.
STUDY_GAP_RATIONALE = (
    "D2: study abstracts are not digitalized yet, so this term ships "
    "disabled with weight 0.0 until the abstracts are ingested in a "
    "later phase. The term is present in the schema today so no future "
    "schema migration is required when the abstracts come online."
)


@dataclass(frozen=True)
class Term:
    """One weighted term of the priority score.

    Stable across versions: ``key`` never changes once published. Adding
    a new term, renaming a key, or removing a term bumps ``SCHEMA_VERSION``.
    """

    key: str
    description: str
    weight: float
    enabled: bool
    rationale: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key:
            raise ValueError(
                f"term key must be a non-empty string, got {self.key!r}"
            )
        if not isinstance(self.description, str) or not self.description:
            raise ValueError(
                f"term {self.key!r} description must be a non-empty string"
            )
        if not isinstance(self.weight, (int, float)) or isinstance(self.weight, bool):
            raise ValueError(
                f"term {self.key!r} weight must be a non-bool number, "
                f"got {self.weight!r} ({type(self.weight).__name__})"
            )
        weight_f = float(self.weight)
        # D3 mechanical invariant: weights are finite and non-negative.
        if not math.isfinite(weight_f) or weight_f < 0.0:
            raise ValueError(
                f"term {self.key!r} weight must be finite and non-negative, "
                f"got {weight_f!r}"
            )
        if not isinstance(self.enabled, bool):
            raise ValueError(
                f"term {self.key!r} enabled must be a bool, "
                f"got {type(self.enabled).__name__}"
            )
        # D2 mechanical invariant: a disabled term carries no weight.
        # Enforced here so it cannot be lost in a future refactor that
        # only adjusts the call site.
        if self.enabled is False and weight_f != 0.0:
            raise ValueError(
                f"term {self.key!r} is disabled but weight is {weight_f!r}; "
                f"a disabled term must have weight 0.0 (project decision D2)"
            )
        if not isinstance(self.rationale, str):
            raise ValueError(
                f"term {self.key!r} rationale must be a string when present"
            )


@dataclass(frozen=True)
class PrioritySchema:
    """A versioned collection of priority-index terms.

    Construct one via ``build_default_schema`` for the shipped defaults,
    or directly when validating an externally-supplied schema.
    """

    version: int
    terms: tuple[Term, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.version, int) or isinstance(self.version, bool):
            raise ValueError(
                f"schema version must be an int, got {self.version!r}"
            )
        if self.version <= 0:
            raise ValueError(
                f"schema version must be positive, got {self.version}"
            )
        if not isinstance(self.terms, tuple):
            raise ValueError(
                f"terms must be a tuple of Term, got {type(self.terms).__name__}"
            )
        keys: list[str] = []
        for t in self.terms:
            if not isinstance(t, Term):
                raise ValueError(
                    f"terms must be Term instances, got {type(t).__name__}"
                )
            keys.append(t.key)
            # Re-trigger Term invariants to defend against hand-built
            # tuples that bypassed the Term constructor.
            Term(
                key=t.key,
                description=t.description,
                weight=t.weight,
                enabled=t.enabled,
                rationale=t.rationale,
            )
        if len(keys) != len(set(keys)):
            raise ValueError(f"duplicate term keys in schema: {keys}")


def build_default_schema() -> PrioritySchema:
    """Return the F3 default priority schema with study_gap disabled per D2.

    The four terms fixed by the platform design are change magnitude,
    transition rarity/irreversibility, study gap, and accessibility.
    Weights sum to 1.0 across the enabled terms; the disabled study_gap
    keeps weight 0.0.
    """
    return PrioritySchema(
        version=SCHEMA_VERSION,
        terms=(
            Term(
                key="change_magnitude",
                description=(
                    "Magnitude of land-cover class change over the analysis "
                    "horizon, normalized by the study area."
                ),
                weight=0.4,
                enabled=True,
            ),
            Term(
                key="transition_rarity_irreversibility",
                description=(
                    "Rarity and reversibility of each transition; rarer and "
                    "less reversible transitions rank higher."
                ),
                weight=0.4,
                enabled=True,
            ),
            Term(
                key="study_gap",
                description=(
                    "Gap between raster-derived signal and peer-reviewed "
                    "study coverage of the same area and period."
                ),
                weight=0.0,
                enabled=False,
                rationale=STUDY_GAP_RATIONALE,
            ),
            Term(
                key="accessibility",
                description=(
                    "Physical and political accessibility of the area for "
                    "ground-truthing and field campaigns."
                ),
                weight=0.2,
                enabled=True,
            ),
        ),
    )


def emit_schema_json(schema: PrioritySchema | None = None) -> str:
    """Serialize a schema as JSON for the viewer (and other consumers).

    The returned string embeds ``schema_version`` at the top level so
    consumers can pin a known version and re-validate when it bumps.
    A disabled term's empty-entry rationale is omitted to keep the output
    terse; ``study_gap`` keeps its rationale because it is the term that
    encodes D2.
    """
    s = schema or build_default_schema()
    payload: dict[str, Any] = {
        "schema_version": s.version,
        "terms": [
            _term_to_json_dict(t) for t in s.terms
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _term_to_json_dict(t: Term) -> dict[str, Any]:
    """Render a term as JSON-safe dict. Empty rationale omitted for brevity."""
    out: dict[str, Any] = {
        "key": t.key,
        "description": t.description,
        "weight": t.weight,
        "enabled": t.enabled,
    }
    if t.rationale:
        out["rationale"] = t.rationale
    return out
