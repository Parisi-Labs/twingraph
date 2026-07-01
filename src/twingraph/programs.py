"""Program-profile registry (spec §5 stage 10, decision compatibility).

A **decision program** (e.g. ``tomorrow_dispatch``) declares the structural
shape a graph must have to serve it: required entity types, variable roles,
model-binding kinds, objective shape, constraint classes. Compile stage 10
checks the graph against EVERY registered profile and REPORTS each one's
compatibility (it never errors — an incompatible program is information, not a
rejection: ``TG_PROGRAM_INCOMPATIBLE`` stays unused).

Before 0.2 this stage was hardcoded to the battery ``tomorrow_dispatch`` five
checks. It is now a generic, domain-agnostic checker: a ``ProgramProfile`` is a
tuple of ``ProfileRequirement``s, each carrying its OWN ``missing_label`` so the
checker appends labels in declared order with no battery knowledge baked in. A
non-battery twin (composed, PdM, …) registers its own profiles and reports their
compatibility — it is no longer measured against a hardcoded battery check.

``BUILTIN_PROGRAM_REGISTRY`` ships EXACTLY ONE profile — ``tomorrow_dispatch`` —
whose requirements reproduce the legacy five labels in the legacy order, so the
golden ``program_compatibility[0]`` is byte-identical. Demo/test profiles
(solar, PdM, …) register into a SEPARATE registry instance, never the builtin.

stdlib + pydantic only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids import cycle
    from .compile import ProgramCompatibilityReport, _Ctx


# ---------------------------------------------------------------------------
# A requirement carries its own label + a pure predicate over the compile ctx.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ProfileRequirement:
    """One structural check. ``predicate(ctx) -> bool``; on False the
    ``missing_label`` is appended to the report's ``missing`` list."""

    missing_label: str
    predicate: Callable[["_Ctx"], bool]
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProgramProfile:
    name: str
    requirements: tuple[ProfileRequirement, ...] = ()

    def check(self, ctx: "_Ctx") -> "ProgramCompatibilityReport":
        from .compile import ProgramCompatibilityReport

        missing: list[str] = []
        for req in self.requirements:
            if not req.predicate(ctx):
                missing.append(req.missing_label)
        return ProgramCompatibilityReport(
            program=self.name, compatible=not missing, missing=missing
        )


@runtime_checkable
class ProgramRegistry(Protocol):
    def all(self) -> list[ProgramProfile]: ...
    def register(self, profile: ProgramProfile) -> None: ...
    def get(self, name: str) -> ProgramProfile: ...


class InMemoryProgramRegistry:
    """A simple, ordered, mutable ``ProgramRegistry``."""

    def __init__(self, profiles: list[ProgramProfile] | None = None) -> None:
        self._profiles: dict[str, ProgramProfile] = {}
        for p in profiles or []:
            self.register(p)

    def register(self, profile: ProgramProfile) -> None:
        self._profiles[profile.name] = profile

    def get(self, name: str) -> ProgramProfile:
        return self._profiles[name]

    def all(self) -> list[ProgramProfile]:
        return list(self._profiles.values())


# ---------------------------------------------------------------------------
# The battery tomorrow_dispatch profile — predicates reproduce the legacy
# stage-10 checks EXACTLY (same labels, same order). Do not reorder.
# ---------------------------------------------------------------------------
def _battery_ids(ctx: "_Ctx") -> set[str]:
    return {
        e.id
        for e in ctx.graph.entities
        if e.type_ref.startswith("metis.energy.Battery@")
    }


def _has_battery_entity(ctx: "_Ctx") -> bool:
    return bool(_battery_ids(ctx))


def _has_battery_native_binding(ctx: "_Ctx") -> bool:
    bats = _battery_ids(ctx)
    return any(
        m.kind == "native_component"
        and any(
            (var := ctx.variables.get(o)) is not None and var.owner_ref in bats
            for o in m.outputs.values()
        )
        for m in ctx.graph.model_bindings
    )


def _has_exogenous_data_binding(ctx: "_Ctx") -> bool:
    exo = {v.id for v in ctx.graph.variables if v.role == "exogenous"}
    bound = {b.variable_id for b in ctx.graph.data_bindings}
    return bool(exo & bound)


def _has_objective_with_terms(ctx: "_Ctx") -> bool:
    return any(o.terms and o.aggregation for o in ctx.graph.objectives)


def _has_hard_constraint(ctx: "_Ctx") -> bool:
    return any(c.class_.startswith("hard_") for c in ctx.graph.constraints)


TOMORROW_DISPATCH_PROFILE = ProgramProfile(
    name="tomorrow_dispatch",
    requirements=(
        ProfileRequirement("battery_entity", _has_battery_entity),
        ProfileRequirement(
            "native_component_model_binding", _has_battery_native_binding
        ),
        ProfileRequirement(
            "exogenous_price_data_binding", _has_exogenous_data_binding
        ),
        ProfileRequirement("objective_with_terms", _has_objective_with_terms),
        ProfileRequirement("hard_constraint", _has_hard_constraint),
    ),
)


BUILTIN_PROGRAM_REGISTRY = InMemoryProgramRegistry([TOMORROW_DISPATCH_PROFILE])


__all__ = [
    "ProfileRequirement",
    "ProgramProfile",
    "ProgramRegistry",
    "InMemoryProgramRegistry",
    "BUILTIN_PROGRAM_REGISTRY",
    "TOMORROW_DISPATCH_PROFILE",
]
