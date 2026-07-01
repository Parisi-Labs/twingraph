"""Shared helpers for the twingraph test suite (importable, not a conftest)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from twingraph.errors import UnknownModelRefError
from twingraph.registry import IOContract, ModelSpec

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = _PACKAGE_ROOT / "examples" / "ny_demo_bess_01.twingraph.json"


def load_demo_doc() -> dict:
    """Return a fresh active copy of the NY_Demo_BESS_01 document dict."""
    from twingraph import TwinGraph

    draft = json.loads(EXAMPLE_PATH.read_text())
    return TwinGraph.load(draft).activate().model_dump(
        mode="json", by_alias=True, exclude_none=True
    )


def mutate(doc: dict, fn) -> dict:
    """Return a deep copy of ``doc`` after applying ``fn`` in place.

    Mutating an active document forks a working DRAFT: its identity is no longer
    the activated original's, so we drop the stale ``content_hash`` and set
    ``status`` to ``draft`` (the loader enforces hash-on-active, §9.2). Tests
    that specifically exercise the active/freeze invariant should NOT use this
    helper.
    """
    d = copy.deepcopy(doc)
    d.pop("content_hash", None)
    if d.get("status") == "active":
        d["status"] = "draft"
    fn(d)
    return d


class StubModelRegistry:
    """A minimal ModelRegistry knowing the demo's model_refs (compile-only)."""

    _REFS = {
        "registry://metis.components.battery_linear@1.0.0": ("native_component", "battery_linear"),
        "registry://metis.policies.hold@1.0.0": ("rule_policy", "policy_hold"),
        "registry://metis.policies.price_threshold@0.1.0": ("rule_policy", "policy_threshold"),
        "registry://metis.policies.greedy_arbitrage@0.1.0": ("rule_policy", "policy_greedy"),
        "registry://metis.policies.oracle@0.1.0": ("rule_policy", "policy_oracle"),
        "registry://metis.expressions.energy_revenue@1.0.0": ("derived_expression", "energy_revenue"),
        # Solar native component for the composition demo (writes generation).
        "registry://metis.components.solar_pv@1.0.0": ("native_component", "solar_pv"),
    }

    # Foreign-reference model_refs available to tests (not in the demo plan).
    _FOREIGN_REFS = {
        "registry://metis.foreign.turbine_fmu@1.0.0": ("fmu", "turbine_fmu"),
        "registry://metis.foreign.thermal_modelica@1.0.0": ("modelica_class", "thermal_modelica"),
    }

    # io_contract overrides keyed by model_ref (else an empty IOContract). A
    # foreign FMU turbine declaring its ports — foreign-kind tests resolve this
    # and check the binding's input/output port sets match bidirectionally.
    _CONTRACTS = {
        "registry://metis.foreign.turbine_fmu@1.0.0": IOContract(
            inputs={"wind_speed": {"unit": "MW"}},
            outputs={"power": {"unit": "MW"}},
        ),
    }

    def __init__(self, refs: dict | None = None) -> None:
        if refs is None:
            src = {**self._REFS, **self._FOREIGN_REFS}
        else:
            src = refs
        self._specs = {
            ref: ModelSpec(
                model_ref=ref,
                kind=kind,
                io_contract=self._CONTRACTS.get(ref, IOContract()),
                callable_key=key,
            )
            for ref, (kind, key) in src.items()
        }

    def get(self, model_ref: str) -> ModelSpec:
        try:
            return self._specs[model_ref]
        except KeyError as exc:
            raise UnknownModelRefError(model_ref) from exc

    def has(self, model_ref: str) -> bool:
        return model_ref in self._specs

    def resolve(self, callable_key: str):  # pragma: no cover - unused in compile
        raise NotImplementedError

    def register(self, *a, **k):  # pragma: no cover
        pass


def build_solar_twin(
    *,
    entity_id: str = "solar",
    var_id: str = "gen",
    namespace: str = "metis.demo.solar_01",
):
    """A small standalone metis.energy.SolarArray@1 twin (draft).

    One solar entity, a generation variable, a native_component binding that
    writes it, and an exogenous data binding for the irradiance-derived path.
    Compiles on its own; composes with the battery twin in test_compose.
    """
    from twingraph import (
        DataBinding,
        Entity,
        ModelBinding,
        TwinGraph,
        Variable,
    )
    from twingraph.primitives import DataSource, QueryPolicy

    twin = TwinGraph.new(
        "Solar_Demo_01", namespace=namespace, created_by="metis.test.solar"
    )
    twin.entities.append(
        Entity(
            id=entity_id,
            type_ref="metis.energy.SolarArray@1",
            name="Demo Solar Array",
            namespace=namespace,
            properties={"capacity_mw": 5.0},
        )
    )
    twin.variables.append(
        Variable(
            id=var_id,
            owner_ref=entity_id,
            name="generation",
            role="exogenous",
            unit="MW",
            temporal_semantics="interval_average",
            resolution="PT1H",
        )
    )
    twin.model_bindings.append(
        ModelBinding(
            id="mb_solar",
            kind="native_component",
            model_ref="registry://metis.components.solar_pv@1.0.0",
            scope_ref=entity_id,
            inputs={},
            outputs={"generation": var_id},
            parameters={"capacity_mw": "property:capacity_mw"},
        )
    )
    twin.data_bindings.append(
        DataBinding(
            id="db_solar_gen",
            variable_id=var_id,
            source=DataSource(semantic_view="fixture:solar_demo_generation"),
            event_time_column="interval_start_utc",
            available_at_column="published_at_utc",
            value_column="generation_mw",
            unit="MW",
            grain=["interval_start_utc"],
            query_policy=QueryPolicy(as_of_required=True),
        )
    )
    return twin


def load_demo_twin():
    """Load the NY demo battery twin as a fresh DRAFT TwinGraph (composable)."""
    from twingraph import TwinGraph

    doc = load_demo_doc()
    doc.pop("content_hash", None)
    doc["status"] = "draft"
    return TwinGraph.load(doc)
