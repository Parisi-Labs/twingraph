"""Multi-twin composition tests (§9.14)."""

from __future__ import annotations

import pytest

import twingraph as tg
from twingraph import (
    CompositionError,
    Entity,
    EntityPort,
    ModelBinding,
    Relation,
    TwinGraph,
    Variable,
    compose,
)

from helpers import build_solar_twin, load_demo_twin


def _compile(graph, model_registry, **kw):
    return tg.compile_graph(
        graph,
        type_registry=tg.BUILTIN_TYPE_REGISTRY,
        model_registry=model_registry,
        **kw,
    )


# --- collision handling ----------------------------------------------------
def test_collision_rejection_raises(model_registry):
    battery = load_demo_twin()
    # A solar twin that deliberately reuses the battery's entity id 'bat'.
    solar = build_solar_twin(entity_id="bat", var_id="gen")
    with pytest.raises(CompositionError) as exc:
        compose([battery, solar], name="bad", created_by="t", id_policy="reject")
    assert "bat" in str(exc.value)


def test_disjoint_ids_compose_in_reject_mode():
    battery = load_demo_twin()
    solar = build_solar_twin()
    composite, report = compose(
        [battery, solar], name="battery+solar", created_by="t", id_policy="reject"
    )
    assert report.id_collisions == []
    # Both entities present.
    ids = {e.id for e in composite.entities}
    assert "bat" in ids and "solar" in ids


# --- cross-twin relation + composite compiles ------------------------------
def test_composite_battery_plus_solar_compiles_with_cross_relation(model_registry):
    battery = load_demo_twin()
    solar = build_solar_twin()
    xrel = Relation(
        id="r_solar_feeds_bat",
        type_ref="feeds_into",  # cross-domain verb, registered in BUILTIN
        source_entity_id="solar",
        target_entity_id="bat",
    )
    composite, report = compose(
        [battery, solar],
        name="battery+solar",
        created_by="t",
        cross_relations=[xrel],
        id_policy="reject",
    )
    assert report.cross_relations == ["r_solar_feeds_bat"]
    # The cross relation is present and resolves to both entities at compile.
    res = _compile(composite, model_registry)
    assert res.ok, [d.message for d in res.report.errors()]
    assert res.plan is not None  # ExecutablePlan
    # tomorrow_dispatch still compatible — the battery half is intact.
    pc = res.plan.program_compatibility[0]
    assert pc.program == "tomorrow_dispatch"
    assert pc.compatible


def _solar_plant_twin(name: str, plant_id: str, namespace: str) -> TwinGraph:
    twin = TwinGraph.new(name, namespace=namespace, created_by="test")
    twin.entities.extend(
        [
            Entity(
                id=f"{plant_id}_solar",
                type_ref="metis.energy.SolarArray@1",
                name=f"{name} array",
                properties={"capacity_mw": {"value": 20.0, "unit": "MW"}},
            ),
            Entity(
                id=f"{plant_id}_poi",
                type_ref="metis.energy.Interconnect@1",
                name=f"{name} POI",
                properties={
                    "import_limit_mw": {"value": 0.0, "unit": "MW"},
                    "export_limit_mw": {"value": 20.0, "unit": "MW"},
                },
                ports={
                    "export": EntityPort(kind="ac_power", unit="MW", direction="output")
                },
            ),
        ]
    )
    twin.variables.append(
        Variable(
            id=f"{plant_id}_gen",
            owner_ref=f"{plant_id}_solar",
            name="generation",
            role="exogenous",
            unit="MW",
        )
    )
    twin.relations.append(
        Relation(
            id=f"{plant_id}_array_to_poi",
            type_ref="feeds_into",
            source_entity_id=f"{plant_id}_solar",
            target_entity_id=f"{plant_id}_poi",
            source_port="ac_power",
            target_port="ac_power",
        )
    )
    return twin


def _grid_twin() -> TwinGraph:
    twin = TwinGraph.new("Grid", namespace="metis.demo.grid", created_by="test")
    twin.entities.extend(
        [
            Entity(
                id="sub",
                type_ref="metis.energy.Substation@1",
                name="Collector substation",
                properties={"nominal_voltage_kv": {"value": 34.5, "unit": "kV"}},
                ports={
                    "plant_a": EntityPort(kind="bus", unit="MW", direction="input"),
                    "plant_b": EntityPort(kind="bus", unit="MW", direction="input"),
                    "line_out": EntityPort(kind="bus", unit="MW", direction="output"),
                },
            ),
            Entity(
                id="line",
                type_ref="metis.energy.TransmissionLine@1",
                name="Grid tie line",
                properties={
                    "thermal_limit_mw": {"value": 60.0, "unit": "MW"},
                    "nominal_voltage_kv": {"value": 34.5, "unit": "kV"},
                },
                ports={
                    "from_sub": EntityPort(kind="from_bus", unit="MW", direction="input"),
                    "to_grid": EntityPort(kind="to_bus", unit="MW", direction="output"),
                },
            ),
        ]
    )
    twin.variables.append(
        Variable(id="line_flow", owner_ref="line", name="flow", role="observed", unit="MW")
    )
    twin.relations.append(
        Relation(
            id="sub_to_line",
            type_ref="feeds_into",
            source_entity_id="sub",
            target_entity_id="line",
            source_port="line_out",
            target_port="from_sub",
            properties={"capacity_mw": {"value": 60.0, "unit": "MW"}},
        )
    )
    return twin


def test_two_solar_plants_compose_through_grid_twin_interfaces(model_registry):
    plant_a = _solar_plant_twin("Solar A", "a", "metis.demo.plant_a")
    plant_b = _solar_plant_twin("Solar B", "b", "metis.demo.plant_b")
    grid = _grid_twin()

    xrels = [
        Relation(
            id="a_poi_to_sub",
            type_ref="feeds_into",
            source_entity_id="a_poi",
            target_entity_id="sub",
            source_port="export",
            target_port="plant_a",
            properties={
                "capacity_mw": {"value": 20.0, "unit": "MW"},
                "loss_factor": {"value": 0.01, "unit": "ratio"},
            },
        ),
        Relation(
            id="b_poi_to_sub",
            type_ref="feeds_into",
            source_entity_id="b_poi",
            target_entity_id="sub",
            source_port="export",
            target_port="plant_b",
            properties={"capacity_mw": {"value": 20.0, "unit": "MW"}},
        ),
    ]
    composite, report = compose(
        [plant_a, plant_b, grid],
        name="two-plants-plus-grid",
        created_by="test",
        cross_relations=xrels,
    )

    assert report.interface_conflicts == []
    assert report.cross_relations == ["a_poi_to_sub", "b_poi_to_sub"]
    res = _compile(composite, model_registry)
    assert res.ok, [d.message for d in res.report.errors()]


def test_compose_reports_cross_relation_interface_conflicts():
    plant = _solar_plant_twin("Solar A", "a", "metis.demo.plant_a")
    grid = _grid_twin()
    grid.entity("sub").ports["plant_a"] = EntityPort(
        kind="bus", unit="request/s", direction="input"
    )
    xrel = Relation(
        id="bad_interface",
        type_ref="feeds_into",
        source_entity_id="a_poi",
        target_entity_id="sub",
        source_port="export",
        target_port="plant_a",
    )

    _, report = compose(
        [plant, grid],
        name="bad-interface",
        created_by="test",
        cross_relations=[xrel],
    )

    assert report.interface_conflicts
    assert report.interface_conflicts[0]["kind"] == "port_unit_mismatch"


def test_cross_relation_with_bad_endpoint_dangles_at_compile(model_registry):
    battery = load_demo_twin()
    solar = build_solar_twin()
    xrel = Relation(
        id="r_bad",
        type_ref="feeds_into",
        source_entity_id="solar",
        target_entity_id="ghost",
    )
    composite, _ = compose(
        [battery, solar],
        name="x",
        created_by="t",
        cross_relations=[xrel],
        id_policy="reject",
    )
    res = _compile(composite, model_registry)
    assert not res.ok
    assert tg.CODES.DANGLING_REF in {d.code for d in res.report.errors()}


# --- lineage ---------------------------------------------------------------
def test_provenance_composed_from_recorded():
    battery = load_demo_twin()
    solar = build_solar_twin()
    composite, report = compose(
        [battery, solar], name="x", created_by="t"
    )
    cf = composite.provenance["composed_from"]
    assert [c["graph_id"] for c in cf] == [battery.graph_id, solar.graph_id]
    assert composite.parent_version_id is None
    assert composite.status == "draft"
    assert report.composite_graph_id == composite.graph_id
    assert report.composite_version_id == composite.version_id
    # The composite version is fresh, not either parent's.
    assert composite.version_id not in (battery.version_id, solar.version_id)


# --- qualify mode (isolated) -----------------------------------------------
def test_qualify_mode_remaps_colliding_twin_ids_and_references(model_registry):
    # Two twins each with id 'bat'/'gen' etc — qualify must prefix the colliding
    # twin and rewrite its references (endpoints + expression idents) so it
    # still resolves at compile.
    battery = load_demo_twin()
    # A solar twin colliding on entity id 'bat' and variable id 'soc'.
    solar = build_solar_twin(entity_id="bat", var_id="soc")
    composite, report = compose(
        [battery, solar],
        name="qualified",
        created_by="t",
        id_policy="qualify",
    )
    assert report.id_collisions  # collisions detected
    assert report.qualified_ids  # something was remapped
    # The solar twin's namespace leaf is 'solar_01'; its ids are now prefixed.
    qualified = set(report.qualified_ids.values())
    assert any(q.startswith("solar_01:") for q in qualified)
    # Composite ids are globally unique.
    all_ids = [
        item.id
        for attr in (
            "entities",
            "relations",
            "variables",
            "data_bindings",
            "model_bindings",
            "actions",
            "constraints",
            "objectives",
            "validators",
            "evidence",
        )
        for item in getattr(composite, attr)
    ]
    assert len(all_ids) == len(set(all_ids))
    # The remapped solar model_binding still points at the qualified gen var.
    solar_mb = next(
        m for m in composite.model_bindings if m.id.endswith("mb_solar")
    )
    assert solar_mb.outputs["generation"] == report.qualified_ids["soc"]


def test_qualify_mode_rewrites_expression_idents(model_registry):
    # Build two tiny twins both owning a variable 'x' referenced in a constraint
    # expression; qualify must rewrite the expression ident too.
    from twingraph import Constraint, Entity, TwinGraph, Variable
    from twingraph.primitives import ConstraintExpression

    def tiny(ns):
        t = TwinGraph.new("tiny", namespace=ns, created_by="t")
        t.entities.append(
            Entity(id="bat", type_ref="metis.energy.Battery@1", name="b",
                   properties={"power_max_mw": 1.0, "energy_max_mwh": 1.0})
        )
        t.variables.append(
            Variable(id="x", owner_ref="bat", name="state_of_charge",
                     role="state", unit="MW.h")
        )
        t.constraints.append(
            Constraint(
                id="c", name="c", **{"class": "hard_physical"}, scope_ref="bat",
                expression=ConstraintExpression(value="x >= 0"),
            )
        )
        return t

    a = tiny("acme.alpha")
    b = tiny("acme.beta")
    composite, report = compose([a, b], name="dup", created_by="t", id_policy="qualify")
    # Both constraint expressions must reference DISTINCT qualified var ids.
    exprs = [c.expression.value for c in composite.constraints if c.expression]
    assert len(exprs) == 2
    # One expression got its 'x' rewritten to the prefixed id.
    assert any("beta:x" in e for e in exprs)


# --- foreign-region marking ------------------------------------------------
def test_foreign_component_marked_unsupported_and_still_compiles(model_registry):
    battery = load_demo_twin()
    solar = build_solar_twin()
    # Add a foreign FMU binding to the solar twin (kind=fmu, ports match).
    solar.model_bindings.append(
        ModelBinding(
            id="mb_turbine",
            kind="fmu",
            model_ref="registry://metis.foreign.turbine_fmu@1.0.0",
            inputs={"wind_speed": "gen"},
            outputs={"power": "gen"},
        )
    )
    composite, report = compose(
        [battery, solar], name="x", created_by="t", id_policy="reject"
    )
    assert "mb_turbine" in report.unsupported_regions
    res = _compile(composite, model_registry)
    assert res.ok, [d.message for d in res.report.errors()]
    comp = next(c for c in res.plan.components if c.model_binding_id == "mb_turbine")
    assert comp.external is True
