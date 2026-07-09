"""Cross-domain type-pack coverage for the TwinGraph core.

These tests keep the kernel power-first while proving the same IR can represent
adjacent operational twins: data centers, warehouses, factories, ports, and
logistics/supply-chain flow.
"""

from __future__ import annotations

import twingraph as tg
from twingraph.errors import UnknownModelRefError
from twingraph.registry import IOContract, ModelSpec


def _compile(graph, model_registry, **kw):
    return tg.compile_graph(
        graph,
        type_registry=tg.BUILTIN_TYPE_REGISTRY,
        model_registry=model_registry,
        **kw,
    )


def test_builtin_registry_is_power_first_but_cross_domain():
    # Power remains first-class.
    for ref in (
        "metis.energy.Battery@1",
        "metis.energy.SolarArray@1",
        "metis.energy.WindTurbine@1",
        "metis.energy.PowerGenerator@1",
        "metis.energy.TransmissionLine@1",
        "metis.energy.Transformer@1",
        "metis.energy.Substation@1",
        "metis.bess.ContainerFleet@1",
        "metis.bess.BatteryModuleFleet@1",
        "metis.bess.PowerConversionSystem@1",
        "metis.bess.BatteryManagementSystem@1",
        "metis.bess.ThermalManagementSystem@1",
    ):
        assert tg.BUILTIN_TYPE_REGISTRY.has(ref)

    # Adjacent operating systems are represented by explicit packs, not ad-hoc
    # extensions or nearest-neighbor energy mappings.
    for ref in (
        "metis.datacenter.Facility@1",
        "metis.datacenter.CoolingLoop@1",
        "metis.operations.Warehouse@1",
        "metis.operations.Factory@1",
        "metis.operations.PortTerminal@1",
        "metis.operations.TransportRoute@1",
        "metis.data.Dataset@1",
        "metis.analysis.Backtest@1",
        "metis.ops.ShadowRun@1",
        "metis.ops.ControlGate@1",
    ):
        assert tg.BUILTIN_TYPE_REGISTRY.has(ref)

    for rel in (
        "supplies",
        "transports_to",
        "ships_to",
        "cools",
        "depends_on",
        "informs",
        "simulates",
        "evaluates",
        "uses_data",
    ):
        assert tg.BUILTIN_TYPE_REGISTRY.has(f"metis.relation.{rel}@1")


def test_analysis_pack_is_exported_and_optional():
    registry = tg.build_type_registry(
        (
            tg.RELATION_TYPE_PACK,
            tg.POWER_TYPE_PACK,
            tg.DATA_TYPE_PACK,
            tg.PLATFORM_ANALYSIS_TYPE_PACK,
        )
    )
    assert registry.has("metis.analysis.CounterfactualSettlement@1")

    power_only = tg.build_type_registry((tg.RELATION_TYPE_PACK, tg.POWER_TYPE_PACK))
    assert power_only.has("metis.energy.Battery@1")
    assert not power_only.has("metis.analysis.CounterfactualSettlement@1")


def test_bess_pack_is_exported_and_composable():
    registry = tg.build_type_registry(
        (tg.RELATION_TYPE_PACK, tg.POWER_TYPE_PACK, tg.BESS_TYPE_PACK)
    )
    assert registry.has("metis.energy.Battery@1")
    assert registry.has("metis.bess.PowerConversionSystem@1")


def test_analysis_lineage_twin_compiles(model_registry):
    g = tg.TwinGraph.new("AnalysisLineage", namespace="metis.demo.analysis", created_by="test")
    g.entities.extend(
        [
            tg.Entity(
                id="asset",
                type_ref="metis.energy.Battery@1",
                name="Demo BESS",
                properties={
                    "power_max_mw": {"value": 50.0, "unit": "MW"},
                    "energy_max_mwh": {"value": 100.0, "unit": "MW.h"},
                },
            ),
            tg.Entity(
                id="dataset",
                type_ref="metis.data.Dataset@1",
                name="Public market history",
                properties={
                    "warehouse": "ducklake",
                    "warehouse_table": "public.market_history",
                    "trust_boundary": "public",
                },
            ),
            tg.Entity(
                id="settlement",
                type_ref="metis.analysis.CounterfactualSettlement@1",
                name="Counterfactual settlement",
            ),
            tg.Entity(
                id="gate",
                type_ref="metis.ops.ControlGate@1",
                name="Readiness gate",
                properties={"status": "passed"},
            ),
        ]
    )
    g.variables.append(
        tg.Variable(id="soc", owner_ref="asset", name="state_of_charge", role="state", unit="MW.h")
    )
    g.actions.extend(
        [
            tg.Action(
                id="charge",
                name="charge_power",
                target_entity_id="asset",
                control_variables=["charge_power"],
            ),
            tg.Action(
                id="discharge",
                name="discharge_power",
                target_entity_id="asset",
                control_variables=["discharge_power"],
            ),
        ]
    )
    g.variables.extend(
        [
            tg.Variable(id="charge_power", owner_ref="asset", name="charge_power", role="control", unit="MW"),
            tg.Variable(
                id="discharge_power",
                owner_ref="asset",
                name="discharge_power",
                role="control",
                unit="MW",
            ),
        ]
    )
    g.relations.extend(
        [
            tg.Relation(
                id="r_dataset_settlement",
                type_ref="uses_data",
                source_entity_id="settlement",
                target_entity_id="dataset",
            ),
            tg.Relation(
                id="r_settlement_gate",
                type_ref="gates",
                source_entity_id="gate",
                target_entity_id="settlement",
            ),
            tg.Relation(
                id="r_settlement_asset",
                type_ref="evaluates",
                source_entity_id="settlement",
                target_entity_id="asset",
            ),
        ]
    )

    res = _compile(g, model_registry)
    assert res.ok, [d.message for d in res.report.errors()]


def test_power_plus_logistics_twin_compiles(model_registry):
    g = tg.TwinGraph.new("PowerAndWarehouse", namespace="metis.demo.ops", created_by="test")
    g.entities.extend(
        [
            tg.Entity(
                id="gen",
                type_ref="metis.energy.PowerGenerator@1",
                name="Peaker",
                properties={
                    "rated_power_mw": {"value": 50.0, "unit": "MW"},
                    "ramp_rate_mw_per_min": {"value": 8.0, "unit": "MW/min"},
                },
            ),
            tg.Entity(
                id="line",
                type_ref="metis.energy.TransmissionLine@1",
                name="Feeder",
                properties={
                    "thermal_limit_mw": {"value": 80.0, "unit": "MW"},
                    "nominal_voltage_kv": {"value": 13.8, "unit": "kV"},
                    "length_km": {"value": 12.0, "unit": "km"},
                },
            ),
            tg.Entity(
                id="wh",
                type_ref="metis.operations.Warehouse@1",
                name="Cold-chain warehouse",
                properties={"storage_capacity_items": {"value": 50000, "unit": "item"}},
            ),
        ]
    )
    g.variables.extend(
        [
            tg.Variable(id="gen_p", owner_ref="gen", name="power_output", role="control", unit="MW"),
            tg.Variable(id="line_flow", owner_ref="line", name="flow", role="observed", unit="MW"),
            tg.Variable(id="inventory", owner_ref="wh", name="inventory", role="state", unit="item"),
        ]
    )
    g.relations.extend(
        [
            tg.Relation(
                id="r_gen_line",
                type_ref="supplies",
                source_entity_id="gen",
                target_entity_id="line",
                source_port="ac_power",
                target_port="from_bus",
            ),
            tg.Relation(
                id="r_line_wh",
                type_ref="supplies",
                source_entity_id="line",
                target_entity_id="wh",
                source_port="to_bus",
                target_port="ac_power",
            ),
        ]
    )

    res = _compile(g, model_registry)
    assert res.ok, [d.message for d in res.report.errors()]


def test_data_center_twin_compiles_with_power_and_thermal_ports(model_registry):
    g = tg.TwinGraph.new("DataCenter", namespace="metis.demo.dc", created_by="test")
    g.entities.extend(
        [
            tg.Entity(
                id="facility",
                type_ref="metis.datacenter.Facility@1",
                name="DC-1",
                properties={"power_capacity_mw": {"value": 12.0, "unit": "MW"}},
            ),
            tg.Entity(
                id="rack",
                type_ref="metis.datacenter.Rack@1",
                name="Rack A01",
                properties={
                    "power_capacity_kw": {"value": 35.0, "unit": "kW"},
                    "rack_units": {"value": 42.0, "unit": "rack_unit"},
                },
            ),
            tg.Entity(
                id="cooling",
                type_ref="metis.datacenter.CoolingLoop@1",
                name="Chilled water loop",
                properties={"cooling_capacity_kw": {"value": 2500.0, "unit": "kW"}},
            ),
            tg.Entity(
                id="workload",
                type_ref="metis.datacenter.Workload@1",
                name="Inference workload",
                properties={"max_requests_per_s": {"value": 12000.0, "unit": "request/s"}},
            ),
        ]
    )
    g.variables.extend(
        [
            tg.Variable(id="load", owner_ref="facility", name="load", role="exogenous", unit="MW"),
            tg.Variable(
                id="cooling_load",
                owner_ref="cooling",
                name="cooling_load",
                role="observed",
                unit="kW",
            ),
            tg.Variable(
                id="request_rate",
                owner_ref="workload",
                name="request_rate",
                role="exogenous",
                unit="request/s",
            ),
        ]
    )
    g.relations.extend(
        [
            tg.Relation(
                id="r_facility_rack",
                type_ref="contains",
                source_entity_id="facility",
                target_entity_id="rack",
            ),
            tg.Relation(
                id="r_cooling_facility",
                type_ref="cools",
                source_entity_id="cooling",
                target_entity_id="facility",
                source_port="thermal",
                target_port="cooling",
            ),
            tg.Relation(
                id="r_workload_facility",
                type_ref="driven_by",
                source_entity_id="facility",
                target_entity_id="workload",
                source_port="workload",
                target_port="workload",
            ),
        ]
    )

    res = _compile(g, model_registry)
    assert res.ok, [d.message for d in res.report.errors()]


def test_relation_port_must_be_declared_on_endpoint(model_registry):
    g = tg.TwinGraph.new("BadPort", namespace="metis.demo.bad", created_by="test")
    g.entities.extend(
        [
            tg.Entity(
                id="solar",
                type_ref="metis.energy.SolarArray@1",
                name="Solar",
                properties={"capacity_mw": 2.0},
            ),
            tg.Entity(
                id="line",
                type_ref="metis.energy.TransmissionLine@1",
                name="Line",
                properties={"thermal_limit_mw": 20.0, "nominal_voltage_kv": 13.8},
            ),
        ]
    )
    g.variables.extend(
        [
            tg.Variable(id="gen", owner_ref="solar", name="generation", role="exogenous", unit="MW"),
            tg.Variable(id="flow", owner_ref="line", name="flow", role="observed", unit="MW"),
        ]
    )
    g.relations.append(
        tg.Relation(
            id="r_bad_port",
            type_ref="feeds_into",
            source_entity_id="solar",
            target_entity_id="line",
            source_port="fuel",  # not a SolarArray port
            target_port="from_bus",
        )
    )

    res = _compile(g, model_registry)
    assert not res.ok
    assert tg.CODES.STRUCTURE in {d.code for d in res.report.errors()}


def test_entity_quantity_property_units_checked_against_type_def(model_registry):
    g = tg.TwinGraph.new("BadUnits", namespace="metis.demo.bad", created_by="test")
    g.entities.append(
        tg.Entity(
            id="line",
            type_ref="metis.energy.TransmissionLine@1",
            name="Line",
            properties={
                "thermal_limit_mw": {"value": 20.0, "unit": "kV"},
                "nominal_voltage_kv": {"value": 13.8, "unit": "kV"},
            },
        )
    )
    g.variables.append(tg.Variable(id="flow", owner_ref="line", name="flow", role="observed", unit="MW"))

    res = _compile(g, model_registry)
    assert not res.ok
    assert tg.CODES.UNIT_MISMATCH in {d.code for d in res.report.errors()}


def test_relation_quantity_property_units_checked_against_type_def(model_registry):
    g = tg.TwinGraph.new("BadRelationUnits", namespace="metis.demo.bad", created_by="test")
    g.entities.extend(
        [
            tg.Entity(
                id="gen",
                type_ref="metis.energy.PowerGenerator@1",
                name="Gen",
                properties={"rated_power_mw": 10.0},
            ),
            tg.Entity(
                id="line",
                type_ref="metis.energy.TransmissionLine@1",
                name="Line",
                properties={"thermal_limit_mw": 20.0, "nominal_voltage_kv": 13.8},
            ),
        ]
    )
    g.variables.extend(
        [
            tg.Variable(id="gen_p", owner_ref="gen", name="power_output", role="control", unit="MW"),
            tg.Variable(id="flow", owner_ref="line", name="flow", role="observed", unit="MW"),
        ]
    )
    g.relations.append(
        tg.Relation(
            id="r_bad_capacity",
            type_ref="feeds_into",
            source_entity_id="gen",
            target_entity_id="line",
            source_port="ac_power",
            target_port="from_bus",
            properties={"capacity_mw": {"value": 10.0, "unit": "kV"}},
        )
    )

    res = _compile(g, model_registry)
    assert not res.ok
    assert tg.CODES.UNIT_MISMATCH in {d.code for d in res.report.errors()}


class _ContractRegistry:
    def __init__(self, expected_unit: str) -> None:
        self._spec = ModelSpec(
            model_ref="registry://metis.components.facility_load@1.0.0",
            kind="native_component",
            io_contract=IOContract(outputs={"load": {"unit": expected_unit}}),
            callable_key="facility_load",
        )

    def get(self, model_ref: str) -> ModelSpec:
        if model_ref == self._spec.model_ref:
            return self._spec
        raise UnknownModelRefError(model_ref)

    def has(self, model_ref: str) -> bool:
        return model_ref == self._spec.model_ref

    def resolve(self, callable_key: str):  # pragma: no cover - compile only
        raise NotImplementedError

    def register(self, *args, **kwargs):  # pragma: no cover - compile only
        raise NotImplementedError


def test_model_io_contract_units_checked():
    g = tg.TwinGraph.new("BadModelUnits", namespace="metis.demo.bad", created_by="test")
    g.entities.append(
        tg.Entity(
            id="facility",
            type_ref="metis.datacenter.Facility@1",
            name="DC",
            properties={"power_capacity_mw": 2.0},
        )
    )
    g.variables.append(tg.Variable(id="load", owner_ref="facility", name="load", role="exogenous", unit="MW"))
    g.model_bindings.append(
        tg.ModelBinding(
            id="mb_load",
            kind="native_component",
            model_ref="registry://metis.components.facility_load@1.0.0",
            scope_ref="facility",
            outputs={"load": "load"},
        )
    )

    ok = _compile(g, _ContractRegistry("kW"))
    assert ok.ok, [d.message for d in ok.report.errors()]

    bad = _compile(g, _ContractRegistry("request/s"))
    assert not bad.ok
    assert tg.CODES.IO_CONTRACT in {d.code for d in bad.report.errors()}
