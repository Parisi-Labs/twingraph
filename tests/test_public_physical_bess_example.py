"""Public physical BESS example coverage."""

from __future__ import annotations

import json
from pathlib import Path

import twingraph as tg
from twingraph.errors import UnknownModelRefError
from twingraph.registry import IOContract, ModelSpec


class _PublicBessModelRegistry:
    def __init__(self) -> None:
        self._specs = {
            "registry://example.bess.dispatch_linear@1.0.0": ModelSpec(
                model_ref="registry://example.bess.dispatch_linear@1.0.0",
                kind="native_component",
                io_contract=IOContract(
                    inputs={"price": {"unit": "USD/MW.h"}, "state_of_charge": {"unit": "MW.h"}},
                    outputs={"charge_power": {"unit": "MW"}, "discharge_power": {"unit": "MW"}},
                ),
                callable_key="example_bess_dispatch_linear",
            ),
            "registry://example.bess.health_thermal_fmu@1.0.0": ModelSpec(
                model_ref="registry://example.bess.health_thermal_fmu@1.0.0",
                kind="fmu",
                io_contract=IOContract(
                    inputs={"state_of_charge": {"unit": "MW.h"}, "ambient_temperature": {"unit": "degC"}},
                    outputs={"cell_temperature": {"unit": "degC"}, "state_of_health": {"unit": "ratio"}},
                    params={"nominal_energy_mwh": {"unit": "MW.h"}},
                ),
                callable_key="example_bess_health_thermal_fmu",
            ),
        }

    def get(self, model_ref: str) -> ModelSpec:
        try:
            return self._specs[model_ref]
        except KeyError as exc:
            raise UnknownModelRefError(model_ref) from exc

    def has(self, model_ref: str) -> bool:
        return model_ref in self._specs

    def resolve(self, callable_key: str):  # pragma: no cover - compile only
        raise NotImplementedError

    def register(self, *args, **kwargs):  # pragma: no cover - protocol completeness
        raise NotImplementedError


def test_public_physical_bess_example_compiles_and_retains_external_model():
    path = Path(__file__).resolve().parents[1] / "examples" / "public_physical_bess_01.twingraph.json"
    graph = tg.TwinGraph.load(json.loads(path.read_text()))
    result = tg.compile_graph(
        graph,
        type_registry=tg.BUILTIN_TYPE_REGISTRY,
        model_registry=_PublicBessModelRegistry(),
    )

    assert result.ok, [diagnostic.message for diagnostic in result.report.errors()]
    assert result.plan is not None
    assert {entity.type_ref for entity in graph.entities} >= {
        "metis.bess.ContainerFleet@1",
        "metis.bess.BatteryModuleFleet@1",
        "metis.bess.PowerConversionSystem@1",
        "metis.bess.BatteryManagementSystem@1",
        "metis.bess.ThermalManagementSystem@1",
    }
    components = {component.model_binding_id: component for component in result.plan.components}
    assert components["mb_dispatch"].external is False
    assert components["mb_health_fmu"].external is True
