"""Typed error tree, the Diagnostic model, and the stable TG_* code registry.

Two failure channels, kept strictly separate (spec §9.16):

  * **Exceptions** are raised ONLY on *misuse* — a null registry, an out-of-order
    patch, a mutation of a frozen graph. They signal a programming/usage error.
  * **Diagnostics** carry *graph-content* problems (dangling refs, unit
    mismatches, missing required fields). ``compile_graph`` COLLECTS these and
    never raises on them, so an adopter gets every problem in a single pass.

stdlib + pydantic only.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Exception tree (misuse only)
# ---------------------------------------------------------------------------
class TwinGraphError(Exception):
    """Base class for all twingraph misuse errors."""


class UnknownTypeRefError(TwinGraphError):
    """A type_ref could not be resolved by a TypeRegistry (registry misuse)."""


class UnknownModelRefError(TwinGraphError):
    """A model_ref / callable_key could not be resolved by a ModelRegistry."""


class DanglingReferenceError(TwinGraphError):
    """A cross-reference could not be resolved (used by strict callers)."""


class MissingRequiredFieldError(TwinGraphError):
    """A type-required property/variable/action was absent (strict callers)."""


class UnitError(TwinGraphError):
    """A unit could not be parsed or was incompatible (strict callers)."""


class LeakageError(TwinGraphError):
    """A data binding lacked the availability guarantee (strict callers)."""


class CycleError(TwinGraphError):
    """An unresolvable execution cycle in the dependency graph."""


class OutOfOrderPatchError(TwinGraphError):
    """A patch's base_version_id did not match the target graph's version_id."""


class ImmutableGraphError(TwinGraphError):
    """A material edit was attempted against an active/frozen graph (§10.5)."""


class FrozenGraphError(TwinGraphError):
    """An in-place mutation was attempted after activation."""


class CompositionError(TwinGraphError):
    """Multi-twin composition was handed colliding ids under id_policy='reject'
    (misuse: the author must namespace/qualify or supply disjoint ids)."""


class FmiParseError(TwinGraphError):
    """An FMU modelDescription.xml could not be parsed as FMI 2.x or 3.x."""


# ---------------------------------------------------------------------------
# Stable diagnostic codes
# ---------------------------------------------------------------------------
class CODES:
    """Stable machine-readable diagnostic codes (string-compared in tests)."""

    DANGLING_REF = "TG_DANGLING_REF"
    DUPLICATE_ID = "TG_DUPLICATE_ID"
    UNKNOWN_TYPE = "TG_UNKNOWN_TYPE"
    MISSING_REQUIRED = "TG_MISSING_REQUIRED"
    UNIT_MISMATCH = "TG_UNIT_MISMATCH"
    UNKNOWN_UNIT = "TG_UNKNOWN_UNIT"
    UNKNOWN_MODEL = "TG_UNKNOWN_MODEL"
    LEAKAGE = "TG_LEAKAGE"
    CYCLE = "TG_CYCLE"
    HASH_MISMATCH = "TG_HASH_MISMATCH"
    VALIDATOR_FAIL = "TG_VALIDATOR_FAIL"
    MODEL_NOT_EXECUTABLE = "TG_MODEL_NOT_EXECUTABLE"
    MODEL_KIND_MISMATCH = "TG_MODEL_KIND_MISMATCH"
    IO_CONTRACT = "TG_IO_CONTRACT"
    PROGRAM_INCOMPATIBLE = "TG_PROGRAM_INCOMPATIBLE"
    STRUCTURE = "TG_STRUCTURE"


Severity = Literal["error", "warning", "info"]


class Diagnostic(BaseModel):
    """A single, located finding produced by the compile pipeline (§9.16)."""

    model_config = ConfigDict(extra="forbid")

    severity: Severity
    code: str = Field(description="Stable TG_* machine code")
    message: str
    stage: str
    ref: dict[str, Any] | None = Field(
        default=None, description="Locator, e.g. {'entity': 'bat', 'field': 'power_max_mw'}"
    )

    @property
    def is_error(self) -> bool:
        return self.severity == "error"
