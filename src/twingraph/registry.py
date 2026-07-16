"""Type and model registries (spec §9.7, §17).

The IR *references* types and models by id; the application *registers*
implementations. ``twingraph`` ships:

  * the ``TypeRegistry`` / ``ModelCatalog`` / ``CallableResolver`` Protocols,
  * the metadata dataclasses (TypeDef/PropSpec/VarSpec/ActionSpec, IOContract/
    ModelSpec),
  * an ``InMemoryTypeRegistry`` and a ``BUILTIN_TYPE_REGISTRY`` seeded with the
    open energy P0 vocabulary the demo needs.

It NEVER ships model implementations or imports application runtime code. The
application provides model metadata through a ``ModelCatalog``. A runtime may
independently provide executable components through a ``CallableResolver``.
``ModelRegistry`` remains as the combined compatibility protocol. stdlib +
pydantic only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .execution import ComponentCallable

from .errors import UnknownTypeRefError


# ---------------------------------------------------------------------------
# Type registry metadata
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PropSpec:
    name: str
    unit: str | None = None
    data_type: str = "float"
    required: bool = True


@dataclass(frozen=True)
class VarSpec:
    name: str
    role: str
    unit: str | None = None
    required: bool = False


@dataclass(frozen=True)
class ActionSpec:
    name: str
    required: bool = False


@dataclass(frozen=True)
class TypeDef:
    type_ref: str
    kind: str  # "entity" | "relation"
    title: str
    required_properties: tuple[PropSpec, ...] = ()
    optional_properties: tuple[PropSpec, ...] = ()
    required_variables: tuple[VarSpec, ...] = ()
    required_actions: tuple[ActionSpec, ...] = ()
    ports: tuple[str, ...] | None = None
    parent: str | None = None


@dataclass(frozen=True)
class TypePack:
    """A named, registerable bundle of TypeDefs.

    Type packs are intentionally data-only. They give adopters a stable way to
    start from the power-first builtins, add a data-center or operations pack,
    or construct a narrower registry for a public/open-core release.
    """

    name: str
    type_defs: tuple[TypeDef, ...]
    description: str = ""


@runtime_checkable
class TypeRegistry(Protocol):
    def resolve(self, type_ref: str) -> TypeDef: ...
    def has(self, type_ref: str) -> bool: ...
    def versions(self, dotted_name: str) -> list[str]: ...
    def register(self, type_def: TypeDef) -> None: ...


class InMemoryTypeRegistry:
    """A simple, mutable in-memory ``TypeRegistry``."""

    def __init__(self, type_defs: list[TypeDef] | None = None) -> None:
        self._by_ref: dict[str, TypeDef] = {}
        for td in type_defs or []:
            self.register(td)

    def register(self, type_def: TypeDef) -> None:
        self._by_ref[type_def.type_ref] = type_def

    def has(self, type_ref: str) -> bool:
        return type_ref in self._by_ref

    def resolve(self, type_ref: str) -> TypeDef:
        try:
            return self._by_ref[type_ref]
        except KeyError as exc:
            raise UnknownTypeRefError(type_ref) from exc

    def versions(self, dotted_name: str) -> list[str]:
        prefix = dotted_name + "@"
        out = [
            ref.split("@", 1)[1] for ref in self._by_ref if ref.startswith(prefix)
        ]
        return sorted(out)


# ---------------------------------------------------------------------------
# Model registry metadata
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class IOContract:
    """Named model interface metadata.

    Input/output entries are required by default when a side is declared. Use
    ``{"required": False}`` for an optional port. Parameter entries are
    optional by default (to preserve a model's default parameter values); use
    ``{"required": True}`` when a binding must supply one. Every entry may
    additionally declare ``unit`` for compile-time unit compatibility checks.
    """

    inputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    params: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelSpec:
    model_ref: str
    kind: str
    io_contract: IOContract
    callable_key: str


@runtime_checkable
class ModelCatalog(Protocol):
    """Compile-time model metadata, with no executable-code requirement."""

    def get(self, model_ref: str) -> ModelSpec: ...
    def has(self, model_ref: str) -> bool: ...


@runtime_checkable
class CallableResolver(Protocol):
    """Runtime lookup from a plan's stable callable key to an implementation."""

    def resolve(self, callable_key: str) -> ComponentCallable: ...


@runtime_checkable
class ModelRegistry(ModelCatalog, CallableResolver, Protocol):
    """Backward-compatible combined metadata and runtime registry protocol."""

    def register(
        self, model_ref: str, callable_key: str, factory: Callable[..., Any]
    ) -> None: ...


# ---------------------------------------------------------------------------
# Builtin type packs (open vocabulary, nothing proprietary)
# ---------------------------------------------------------------------------
def _relation_type_defs() -> tuple[TypeDef, ...]:
    # The metis.relation vocabulary is intentionally operational, not just power:
    # it covers physical containment, power/material flow, control, dependency,
    # service, and settlement. A bare verb still normalizes to
    # metis.relation.<verb>@1 at compile.
    relation_names = (
        "contains",
        "connected_to",
        "controls",
        "constrained_by",
        "settles_at",
        "observed_by",
        "driven_by",
        "charges",
        "discharges_to",
        "degrades_with",
        "evaluated_by",
        "located_in",
        "feeds_into",
        "supplies",
        "consumes",
        "stores",
        "transforms",
        "transports_to",
        "ships_to",
        "serves",
        "served_by",
        "backs_up",
        "depends_on",
        "cools",
        "heats",
        "measures",
        "informs",
        "simulates",
        "evaluates",
        "observes",
        "explains",
        "gates",
        "annotates",
        "uses_data",
    )
    common_properties = (
        PropSpec("capacity_mw", unit="MW", required=False),
        PropSpec("capacity_mva", unit="MVA", required=False),
        PropSpec("thermal_limit_mw", unit="MW", required=False),
        PropSpec("loss_factor", unit="ratio", required=False),
        PropSpec("distance_km", unit="km", required=False),
        PropSpec("transit_time_h", unit="h", required=False),
        PropSpec("capacity_items_per_h", unit="item/h", required=False),
        PropSpec("capacity_teu_per_h", unit="TEU/h", required=False),
        PropSpec("capacity_tonne", unit="tonne", required=False),
    )
    return tuple(
        TypeDef(
            type_ref=f"metis.relation.{rel}@1",
            kind="relation",
            title=rel.replace("_", " "),
            optional_properties=common_properties,
        )
        for rel in relation_names
    )


RELATION_TYPE_PACK = TypePack(
    name="metis.relation.core@1",
    description="Core operational relation verbs shared by power and operations twins.",
    type_defs=_relation_type_defs(),
)


POWER_TYPE_PACK = TypePack(
    name="metis.energy.power@1",
    description="Power-first asset vocabulary for storage, renewables, generators, and grid assets.",
    type_defs=(
        TypeDef(
            type_ref="metis.energy.Battery@1",
            kind="entity",
            title="Battery energy storage system",
            required_properties=(
                PropSpec("power_max_mw", unit="MW"),
                PropSpec("energy_max_mwh", unit="MW.h"),
            ),
            optional_properties=(
                PropSpec("eta_charge", unit="ratio", required=False),
                PropSpec("eta_discharge", unit="ratio", required=False),
                PropSpec("soc_min_mwh", unit="MW.h", required=False),
                PropSpec("soc_init_mwh", unit="MW.h", required=False),
                PropSpec("terminal_reserve_mwh", unit="MW.h", required=False),
                PropSpec("degradation_cost_per_mwh", unit="USD/MW.h", required=False),
                PropSpec("dt_h", unit="h", required=False),
            ),
            required_variables=(
                VarSpec("state_of_charge", role="state", unit="MW.h", required=True),
            ),
            required_actions=(
                ActionSpec("charge_power", required=True),
                ActionSpec("discharge_power", required=True),
            ),
            ports=("dc_power", "ac_power", "controls", "telemetry"),
        ),
        TypeDef(
            type_ref="metis.energy.MarketNode@1",
            kind="entity",
            title="Market settlement node",
            required_properties=(
                PropSpec("market", data_type="string"),
                PropSpec("location_id", data_type="string"),
            ),
            required_variables=(
                VarSpec("price", role="exogenous", unit="USD/MW.h", required=True),
            ),
            ports=("settlement", "telemetry"),
        ),
        TypeDef(
            type_ref="metis.energy.Interconnect@1",
            kind="entity",
            title="Point-of-interconnection limit",
            required_properties=(
                PropSpec("import_limit_mw", unit="MW"),
                PropSpec("export_limit_mw", unit="MW"),
            ),
            ports=("ac_power", "meter", "controls"),
        ),
        TypeDef(
            type_ref="metis.energy.SolarArray@1",
            kind="entity",
            title="Solar PV array",
            required_properties=(PropSpec("capacity_mw", unit="MW"),),
            optional_properties=(
                PropSpec("dc_capacity_mw", unit="MW", required=False),
                PropSpec("ac_export_limit_mw", unit="MW", required=False),
            ),
            required_variables=(
                VarSpec("generation", role="exogenous", unit="MW", required=True),
            ),
            ports=("dc_power", "ac_power", "irradiance", "telemetry"),
        ),
        TypeDef(
            type_ref="metis.energy.WindTurbine@1",
            kind="entity",
            title="Wind turbine",
            required_properties=(PropSpec("rated_power_mw", unit="MW"),),
            optional_properties=(
                PropSpec("hub_height_m", unit="m", required=False),
                PropSpec("cut_in_wind_speed_mps", unit="m/s", required=False),
                PropSpec("cut_out_wind_speed_mps", unit="m/s", required=False),
            ),
            required_variables=(
                VarSpec("generation", role="exogenous", unit="MW", required=True),
            ),
            ports=("ac_power", "wind_resource", "telemetry"),
        ),
        TypeDef(
            type_ref="metis.energy.WindFarm@1",
            kind="entity",
            title="Wind farm",
            required_properties=(PropSpec("capacity_mw", unit="MW"),),
            required_variables=(
                VarSpec("generation", role="exogenous", unit="MW", required=True),
            ),
            ports=("ac_power", "wind_resource", "telemetry"),
        ),
        TypeDef(
            type_ref="metis.energy.PowerGenerator@1",
            kind="entity",
            title="Dispatchable power generator",
            required_properties=(PropSpec("rated_power_mw", unit="MW"),),
            optional_properties=(
                PropSpec("min_stable_mw", unit="MW", required=False),
                PropSpec("ramp_rate_mw_per_min", unit="MW/min", required=False),
                PropSpec("heat_rate_mmbtu_per_mwh", unit="MMBtu/MW.h", required=False),
            ),
            required_variables=(
                VarSpec("power_output", role="control", unit="MW", required=True),
            ),
            ports=("fuel", "ac_power", "controls", "telemetry"),
        ),
        TypeDef(
            type_ref="metis.energy.Transformer@1",
            kind="entity",
            title="Power transformer",
            required_properties=(PropSpec("rated_mva", unit="MVA"),),
            optional_properties=(
                PropSpec("high_side_kv", unit="kV", required=False),
                PropSpec("low_side_kv", unit="kV", required=False),
            ),
            required_variables=(
                VarSpec("loading", role="observed", unit="ratio", required=False),
            ),
            ports=("hv_ac", "lv_ac", "telemetry"),
        ),
        TypeDef(
            type_ref="metis.energy.TransmissionLine@1",
            kind="entity",
            title="Transmission or distribution line",
            required_properties=(
                PropSpec("thermal_limit_mw", unit="MW"),
                PropSpec("nominal_voltage_kv", unit="kV"),
            ),
            optional_properties=(
                PropSpec("length_km", unit="km", required=False),
                PropSpec("reactive_limit_mvar", unit="MVAr", required=False),
            ),
            required_variables=(
                VarSpec("flow", role="observed", unit="MW", required=True),
            ),
            ports=("from_bus", "to_bus", "telemetry"),
        ),
        TypeDef(
            type_ref="metis.energy.Substation@1",
            kind="entity",
            title="Substation or bus aggregation",
            optional_properties=(PropSpec("nominal_voltage_kv", unit="kV", required=False),),
            ports=("bus", "telemetry", "controls"),
        ),
        TypeDef(
            type_ref="metis.energy.Load@1",
            kind="entity",
            title="Electrical load",
            required_properties=(PropSpec("peak_load_mw", unit="MW"),),
            required_variables=(VarSpec("demand", role="exogenous", unit="MW", required=True),),
            ports=("ac_power", "telemetry"),
        ),
        TypeDef(
            type_ref="metis.energy.Inverter@1",
            kind="entity",
            title="Power inverter",
            required_properties=(PropSpec("ac_power_limit_mw", unit="MW"),),
            optional_properties=(PropSpec("dc_power_limit_mw", unit="MW", required=False),),
            ports=("dc_power", "ac_power", "controls", "telemetry"),
        ),
        TypeDef(
            type_ref="metis.energy.FuelSupply@1",
            kind="entity",
            title="Fuel supply source or contract",
            required_properties=(PropSpec("max_flow_mmbtu_per_h", unit="MMBtu/h"),),
            required_variables=(VarSpec("fuel_price", role="exogenous", unit="USD/MW.h", required=False),),
            ports=("fuel", "settlement"),
        ),
        TypeDef(
            type_ref="metis.energy.WeatherRegion@1",
            kind="entity",
            title="Weather context region",
            optional_properties=(
                PropSpec("latitude", unit="dimensionless", required=False),
                PropSpec("longitude", unit="dimensionless", required=False),
            ),
            required_variables=(
                VarSpec("temperature", role="exogenous", unit="degC", required=False),
                VarSpec("wind_speed", role="exogenous", unit="m/s", required=False),
                VarSpec("irradiance", role="exogenous", unit="W/m2", required=False),
            ),
            ports=("weather",),
        ),
    ),
)


BESS_TYPE_PACK = TypePack(
    name="metis.energy.bess@1",
    description=(
        "Physical BESS subasset vocabulary for containerized storage, controls, "
        "power conversion, and thermal operation."
    ),
    type_defs=(
        TypeDef(
            type_ref="metis.bess.ContainerFleet@1",
            kind="entity",
            title="Battery container fleet",
            required_properties=(PropSpec("container_count", unit="count"),),
            optional_properties=(
                PropSpec("container_energy_mwh", unit="MW.h", required=False),
                PropSpec("container_power_mw", unit="MW", required=False),
            ),
            ports=("dc_power", "thermal", "telemetry", "controls"),
        ),
        TypeDef(
            type_ref="metis.bess.BatteryModuleFleet@1",
            kind="entity",
            title="Battery module fleet",
            required_properties=(
                PropSpec("module_count", unit="count"),
                PropSpec("nominal_energy_mwh", unit="MW.h"),
            ),
            required_variables=(
                VarSpec("state_of_health", role="derived", unit="ratio", required=False),
                VarSpec("cell_temperature", role="derived", unit="degC", required=False),
            ),
            ports=("dc_power", "thermal", "telemetry"),
        ),
        TypeDef(
            type_ref="metis.bess.PowerConversionSystem@1",
            kind="entity",
            title="Battery power conversion system",
            required_properties=(PropSpec("ac_power_max_mw", unit="MW"),),
            optional_properties=(
                PropSpec("dc_power_max_mw", unit="MW", required=False),
                PropSpec("efficiency", unit="ratio", required=False),
                PropSpec("ac_voltage_kv", unit="kV", required=False),
            ),
            ports=("dc_power", "ac_power", "controls", "telemetry"),
        ),
        TypeDef(
            type_ref="metis.bess.BatteryManagementSystem@1",
            kind="entity",
            title="Battery management system",
            optional_properties=(
                PropSpec("vendor", data_type="string", required=False),
                PropSpec("firmware_version", data_type="string", required=False),
            ),
            ports=("telemetry", "controls", "safety"),
        ),
        TypeDef(
            type_ref="metis.bess.ThermalManagementSystem@1",
            kind="entity",
            title="Battery thermal management system",
            required_properties=(PropSpec("cooling_capacity_mw", unit="MW_th"),),
            optional_properties=(
                PropSpec("temperature_setpoint_deg_c", unit="degC", required=False),
            ),
            ports=("thermal", "controls", "telemetry"),
        ),
    ),
)


DATA_CENTER_TYPE_PACK = TypePack(
    name="metis.datacenter.core@1",
    description="Data-center physical and workload vocabulary tied back to power.",
    type_defs=(
        TypeDef(
            type_ref="metis.datacenter.Facility@1",
            kind="entity",
            title="Data center facility",
            required_properties=(PropSpec("power_capacity_mw", unit="MW"),),
            required_variables=(
                VarSpec("load", role="exogenous", unit="MW", required=True),
                VarSpec("pue", role="observed", unit="ratio", required=False),
            ),
            ports=("ac_power", "cooling", "network", "workload", "telemetry"),
        ),
        TypeDef(
            type_ref="metis.datacenter.Rack@1",
            kind="entity",
            title="Compute rack",
            required_properties=(PropSpec("power_capacity_kw", unit="kW"),),
            optional_properties=(PropSpec("rack_units", unit="rack_unit", required=False),),
            required_variables=(VarSpec("rack_load", role="observed", unit="kW", required=False),),
            ports=("ac_power", "network", "cooling", "telemetry"),
        ),
        TypeDef(
            type_ref="metis.datacenter.CoolingLoop@1",
            kind="entity",
            title="Cooling loop or chilled-water circuit",
            required_properties=(PropSpec("cooling_capacity_kw", unit="kW"),),
            required_variables=(
                VarSpec("cooling_load", role="observed", unit="kW", required=True),
                VarSpec("supply_temperature", role="observed", unit="degC", required=False),
            ),
            ports=("thermal", "controls", "telemetry"),
        ),
        TypeDef(
            type_ref="metis.datacenter.UPS@1",
            kind="entity",
            title="Uninterruptible power supply",
            required_properties=(
                PropSpec("power_capacity_mw", unit="MW"),
                PropSpec("energy_capacity_mwh", unit="MW.h"),
            ),
            required_variables=(VarSpec("state_of_charge", role="state", unit="MW.h", required=True),),
            ports=("ac_power", "dc_power", "controls", "telemetry"),
        ),
        TypeDef(
            type_ref="metis.datacenter.Workload@1",
            kind="entity",
            title="Computing workload or service demand",
            required_properties=(PropSpec("max_requests_per_s", unit="request/s"),),
            required_variables=(
                VarSpec("request_rate", role="exogenous", unit="request/s", required=True),
            ),
            ports=("workload", "network", "controls", "telemetry"),
        ),
    ),
)


OPERATIONS_TYPE_PACK = TypePack(
    name="metis.operations.core@1",
    description="Warehouses, factories, ports, logistics nodes, and supply-chain flow.",
    type_defs=(
        TypeDef(
            type_ref="metis.operations.Warehouse@1",
            kind="entity",
            title="Warehouse or distribution center",
            required_properties=(PropSpec("storage_capacity_items", unit="item"),),
            required_variables=(VarSpec("inventory", role="state", unit="item", required=True),),
            ports=("inbound", "outbound", "storage", "ac_power", "telemetry"),
        ),
        TypeDef(
            type_ref="metis.operations.Factory@1",
            kind="entity",
            title="Factory or industrial site",
            required_properties=(PropSpec("power_capacity_mw", unit="MW"),),
            required_variables=(
                VarSpec("production_rate", role="observed", unit="item/h", required=True),
                VarSpec("load", role="exogenous", unit="MW", required=False),
            ),
            ports=("materials_in", "goods_out", "ac_power", "thermal", "telemetry"),
        ),
        TypeDef(
            type_ref="metis.operations.ProductionLine@1",
            kind="entity",
            title="Production line",
            required_properties=(PropSpec("throughput_capacity_items_per_h", unit="item/h"),),
            required_variables=(VarSpec("throughput", role="observed", unit="item/h", required=True),),
            ports=("materials_in", "goods_out", "controls", "telemetry"),
        ),
        TypeDef(
            type_ref="metis.operations.PortTerminal@1",
            kind="entity",
            title="Port terminal",
            required_properties=(PropSpec("throughput_capacity_teu_per_h", unit="TEU/h"),),
            required_variables=(VarSpec("container_throughput", role="observed", unit="TEU/h", required=True),),
            ports=("berth", "yard", "rail", "truck", "ac_power", "telemetry"),
        ),
        TypeDef(
            type_ref="metis.operations.LogisticsNode@1",
            kind="entity",
            title="Logistics node or transfer point",
            required_properties=(PropSpec("handling_capacity_items_per_h", unit="item/h"),),
            required_variables=(VarSpec("inventory", role="state", unit="item", required=False),),
            ports=("inbound", "outbound", "storage", "telemetry"),
        ),
        TypeDef(
            type_ref="metis.operations.TransportRoute@1",
            kind="entity",
            title="Transport route or lane",
            required_properties=(PropSpec("distance_km", unit="km"),),
            required_variables=(VarSpec("transit_time", role="observed", unit="h", required=False),),
            ports=("origin", "destination", "telemetry"),
        ),
        TypeDef(
            type_ref="metis.operations.FleetVehicle@1",
            kind="entity",
            title="Fleet vehicle",
            required_properties=(PropSpec("payload_capacity_tonne", unit="tonne"),),
            required_variables=(VarSpec("availability", role="state", unit="ratio", required=False),),
            ports=("cargo", "route", "fuel_or_energy", "telemetry"),
        ),
    ),
)


DATA_TYPE_PACK = TypePack(
    name="metis.data.core@1",
    description="Data-source nodes for auditable bindings, external extracts, and model lineage.",
    type_defs=(
        TypeDef(
            type_ref="metis.data.Source@1",
            kind="entity",
            title="Data source or external extract",
            optional_properties=(
                PropSpec("semantic_view", data_type="string", required=False),
                PropSpec("adapter", data_type="string", required=False),
                PropSpec("owner", data_type="string", required=False),
                PropSpec("trust_boundary", data_type="string", required=False),
            ),
            ports=("telemetry", "events", "settlement", "market", "weather", "documents"),
        ),
        TypeDef(
            type_ref="metis.data.Dataset@1",
            kind="entity",
            title="Warehouse dataset or table",
            optional_properties=(
                PropSpec("provider", data_type="string", required=False),
                PropSpec("owner", data_type="string", required=False),
                PropSpec("warehouse", data_type="string", required=False),
                PropSpec("warehouse_table", data_type="string", required=False),
                PropSpec("dataset", data_type="string", required=False),
                PropSpec("table", data_type="string", required=False),
                PropSpec("freshness", data_type="string", required=False),
                PropSpec("trust_boundary", data_type="string", required=False),
            ),
            ports=("query", "telemetry", "settlement", "market", "reference"),
        ),
    ),
)


PLATFORM_ANALYSIS_TYPE_PACK = TypePack(
    name="metis.platform.analysis@1",
    description="Operator-facing analysis, notebook, and decision-system nodes.",
    type_defs=(
        TypeDef(
            type_ref="metis.ops.Facility@1",
            kind="entity",
            title="Operational facility",
            optional_properties=(
                PropSpec("model_boundary", data_type="string", required=False),
                PropSpec("public_site_capacity_mw", unit="MW", required=False),
                PropSpec("public_site_energy_mwh", unit="MW.h", required=False),
            ),
            ports=("ac_power", "telemetry", "controls", "documents"),
        ),
        TypeDef(
            type_ref="metis.ops.ProductionLine@1",
            kind="entity",
            title="Operational production or decision line",
            optional_properties=(
                PropSpec("role", data_type="string", required=False),
                PropSpec("execution_mode", data_type="string", required=False),
            ),
            ports=("inputs", "outputs", "controls", "telemetry"),
        ),
        TypeDef(
            type_ref="metis.ops.Warehouse@1",
            kind="entity",
            title="Operational data warehouse",
            optional_properties=(
                PropSpec("provider", data_type="string", required=False),
                PropSpec("warehouse", data_type="string", required=False),
            ),
            ports=("query", "catalog", "lineage"),
        ),
        TypeDef(
            type_ref="metis.analysis.RareEventEngine@1",
            kind="entity",
            title="Rare-event analysis engine",
            optional_properties=(PropSpec("role", data_type="string", required=False),),
            ports=("features", "forecasts", "risk", "lineage"),
        ),
        TypeDef(
            type_ref="metis.market.PriceImpactModel@1",
            kind="entity",
            title="Market price-impact model",
            optional_properties=(PropSpec("role", data_type="string", required=False),),
            ports=("market", "dispatch", "value_curve"),
        ),
        TypeDef(
            type_ref="metis.market.CoOptimizationEngine@1",
            kind="entity",
            title="Market co-optimization engine",
            optional_properties=(PropSpec("role", data_type="string", required=False),),
            ports=("objective", "constraints", "recommendation", "audit"),
        ),
        TypeDef(
            type_ref="metis.analysis.CounterfactualSettlement@1",
            kind="entity",
            title="Counterfactual settlement analysis",
            optional_properties=(PropSpec("role", data_type="string", required=False),),
            ports=("actuals", "counterfactuals", "settlement", "audit"),
        ),
        TypeDef(
            type_ref="metis.ops.ShadowAuditTrail@1",
            kind="entity",
            title="Live shadow audit trail",
            optional_properties=(PropSpec("role", data_type="string", required=False),),
            ports=("inputs", "recommendations", "outcomes", "audit"),
        ),
        TypeDef(
            type_ref="metis.ops.OperatorTrustSurface@1",
            kind="entity",
            title="Operator trust and explanation surface",
            optional_properties=(PropSpec("role", data_type="string", required=False),),
            ports=("explanations", "recommendations", "rejections"),
        ),
        TypeDef(
            type_ref="metis.model.PhysicalModel@1",
            kind="entity",
            title="Physical model",
            optional_properties=(PropSpec("model_ref", data_type="string", required=False),),
            ports=("asset", "constraints", "telemetry", "simulation"),
        ),
        TypeDef(
            type_ref="metis.analysis.Backtest@1",
            kind="entity",
            title="Backtest analysis",
            optional_properties=(PropSpec("status", data_type="string", required=False),),
            ports=("baseline", "challenger", "actuals", "metrics"),
        ),
        TypeDef(
            type_ref="metis.ops.ShadowRun@1",
            kind="entity",
            title="Live shadow run",
            optional_properties=(PropSpec("status", data_type="string", required=False),),
            ports=("recommendations", "actuals", "audit"),
        ),
        TypeDef(
            type_ref="metis.ops.ControlGate@1",
            kind="entity",
            title="Operational readiness gate",
            optional_properties=(PropSpec("status", data_type="string", required=False),),
            ports=("inputs", "checks", "status"),
        ),
        TypeDef(
            type_ref="metis.analysis.Notebook@1",
            kind="entity",
            title="Rendered analysis notebook",
            optional_properties=(
                PropSpec("notebook_id", data_type="string", required=False),
                PropSpec("status", data_type="string", required=False),
            ),
            ports=("cells", "queries", "visualizations", "lineage"),
        ),
    ),
)


BUILTIN_TYPE_PACKS: tuple[TypePack, ...] = (
    RELATION_TYPE_PACK,
    POWER_TYPE_PACK,
    BESS_TYPE_PACK,
    DATA_CENTER_TYPE_PACK,
    OPERATIONS_TYPE_PACK,
    DATA_TYPE_PACK,
    PLATFORM_ANALYSIS_TYPE_PACK,
)


def register_type_pack(registry: TypeRegistry, pack: TypePack) -> None:
    """Register every TypeDef in ``pack`` into ``registry``."""
    for type_def in pack.type_defs:
        registry.register(type_def)


def build_type_registry(packs: tuple[TypePack, ...] | None = None) -> InMemoryTypeRegistry:
    """Build a fresh in-memory registry from the supplied packs.

    Omit ``packs`` to get the full built-in operational vocabulary. Supplying
    ``(RELATION_TYPE_PACK, POWER_TYPE_PACK)`` yields a power-only registry.
    """
    reg = InMemoryTypeRegistry()
    for pack in BUILTIN_TYPE_PACKS if packs is None else packs:
        register_type_pack(reg, pack)
    return reg


BUILTIN_TYPE_REGISTRY = build_type_registry()


__all__ = [
    "BESS_TYPE_PACK",
    "BUILTIN_TYPE_PACKS",
    "BUILTIN_TYPE_REGISTRY",
    "DATA_CENTER_TYPE_PACK",
    "DATA_TYPE_PACK",
    "OPERATIONS_TYPE_PACK",
    "PLATFORM_ANALYSIS_TYPE_PACK",
    "POWER_TYPE_PACK",
    "RELATION_TYPE_PACK",
    "ActionSpec",
    "CallableResolver",
    "IOContract",
    "InMemoryTypeRegistry",
    "ModelCatalog",
    "ModelRegistry",
    "ModelSpec",
    "PropSpec",
    "TypeDef",
    "TypePack",
    "TypeRegistry",
    "VarSpec",
    "build_type_registry",
    "register_type_pack",
]
