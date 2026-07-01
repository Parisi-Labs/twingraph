"""Program-profile registry tests (§5 stage 10 de-hardcoded)."""

from __future__ import annotations

import twingraph as tg
from twingraph.programs import (
    BUILTIN_PROGRAM_REGISTRY,
    InMemoryProgramRegistry,
    ProfileRequirement,
    ProgramProfile,
)

from helpers import build_solar_twin

# The exact legacy stage-10 labels in the exact legacy order. This is the
# load-bearing back-compat invariant — program_compatibility[0] for the demo.
_TOMORROW_DISPATCH_LABELS = [
    "battery_entity",
    "native_component_model_binding",
    "exogenous_price_data_binding",
    "objective_with_terms",
    "hard_constraint",
]


def _compile(graph, model_registry, **kw):
    return tg.compile_graph(
        graph,
        type_registry=tg.BUILTIN_TYPE_REGISTRY,
        model_registry=model_registry,
        **kw,
    )


def test_demo_yields_exactly_tomorrow_dispatch_compatible(demo_doc, model_registry):
    g = tg.TwinGraph.load(demo_doc)
    res = _compile(g, model_registry)
    reports = res.plan.program_compatibility
    assert [r.program for r in reports] == ["tomorrow_dispatch"]
    pc = reports[0]
    assert pc.compatible
    assert pc.missing == []


def test_solar_only_twin_reports_its_own_profile_not_hardcoded_battery(model_registry):
    # A non-battery (solar) twin compiled with the DEFAULT registry reports the
    # builtin tomorrow_dispatch profile as INCOMPATIBLE with its own missing
    # list — it is checked generically, not via a hardcoded battery assertion.
    solar = build_solar_twin()
    res = _compile(solar, model_registry)
    assert res.ok, [d.message for d in res.report.errors()]
    pc = res.plan.program_compatibility[0]
    assert pc.program == "tomorrow_dispatch"
    assert not pc.compatible
    # Solar has an exogenous binding but no battery / objective / hard constraint.
    assert pc.missing == [
        "battery_entity",
        "native_component_model_binding",
        "objective_with_terms",
        "hard_constraint",
    ]


def test_solar_twin_against_its_own_registered_profile(model_registry):
    # A solar program profile registered into a SEPARATE registry reports the
    # solar twin compatible — the checker is domain-agnostic.
    solar = build_solar_twin()

    def has_solar_entity(ctx):
        return any(
            e.type_ref.startswith("metis.energy.SolarArray@")
            for e in ctx.graph.entities
        )

    def has_generation_binding(ctx):
        gen_vars = {
            v.id for v in ctx.graph.variables if v.name == "generation"
        }
        bound = {b.variable_id for b in ctx.graph.data_bindings}
        return bool(gen_vars & bound)

    solar_profile = ProgramProfile(
        name="solar_forecast",
        requirements=(
            ProfileRequirement("solar_entity", has_solar_entity),
            ProfileRequirement("generation_data_binding", has_generation_binding),
        ),
    )
    registry = InMemoryProgramRegistry([solar_profile])
    res = _compile(solar, model_registry, program_registry=registry)
    reports = res.plan.program_compatibility
    assert [r.program for r in reports] == ["solar_forecast"]
    assert reports[0].compatible
    assert reports[0].missing == []


def test_registry_is_open_register_adds_a_profile(demo_doc, model_registry):
    g = tg.TwinGraph.load(demo_doc)
    registry = InMemoryProgramRegistry(BUILTIN_PROGRAM_REGISTRY.all())
    registry.register(
        ProgramProfile(
            name="always_compatible", requirements=()
        )
    )
    res = _compile(g, model_registry, program_registry=registry)
    names = [r.program for r in res.plan.program_compatibility]
    assert names == ["tomorrow_dispatch", "always_compatible"]
    by_name = {r.program: r for r in res.plan.program_compatibility}
    assert by_name["tomorrow_dispatch"].compatible
    assert by_name["always_compatible"].compatible


def test_builtin_registry_holds_only_tomorrow_dispatch():
    assert [p.name for p in BUILTIN_PROGRAM_REGISTRY.all()] == ["tomorrow_dispatch"]
    profile = BUILTIN_PROGRAM_REGISTRY.get("tomorrow_dispatch")
    assert [r.missing_label for r in profile.requirements] == _TOMORROW_DISPATCH_LABELS
