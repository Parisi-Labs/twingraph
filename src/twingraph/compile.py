"""The TwinGraph compile pipeline (spec §9.16).

``compile_graph`` runs a deterministic 11-stage pipeline over a document,
COLLECTING Diagnostics (it never raises on graph-content errors — adopters get
every problem in one pass; it raises ONLY on misuse, e.g. a null registry). It
emits an immutable ``CompileReport`` plus an ``ExecutablePlan`` (data-only,
carrying ``callable_key`` strings, not callables) that a runtime consumes.

Pure: depends only on the registry INTERFACES and imports no application
runtime code. stdlib + pydantic only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .canonical import hash_input
from .document import TwinGraph
from .errors import CODES, Diagnostic, UnknownModelRefError, UnknownTypeRefError
from .metis_expr import ExpressionParseError, extract_references
from .primitives import EXECUTABLE_MODEL_KINDS, FOREIGN_MODEL_KINDS
from .programs import BUILTIN_PROGRAM_REGISTRY, ProgramRegistry
from .registry import ModelRegistry, TypeRegistry
from .units import DEFAULT_UNIT_REGISTRY, UnitRegistry

COMPILER_VERSION = "twingraph-compile/0.1.0"


# ---------------------------------------------------------------------------
# Output artifacts
# ---------------------------------------------------------------------------
class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_binding_id: str
    variable_id: str
    semantic_view: str
    filters: dict[str, Any] = Field(default_factory=dict)
    value_column: str
    event_time_column: str
    available_at_column: str | None = None
    unit: str
    unit_transform: dict[str, Any] | None = None
    as_of_required: bool = True
    deduplication: str = "latest_available_at"
    latest_before_issue_time: bool | None = None
    missing_value_policy: str = "fail_required_horizon"
    expected_resolution: str | None = None
    grain: list[str] = Field(default_factory=list)
    leakage_safe: bool = True


class ResolvedComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_binding_id: str
    kind: str
    model_ref: str
    callable_key: str
    inputs: dict[str, str] = Field(default_factory=dict)
    outputs: dict[str, str] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    # §31.3: a foreign-reference component (fmu/modelica_class) is validated and
    # retained but NOT natively executed by twingraph — an external runtime (FMI/
    # Modelica) dispatches it. The flag, not the topo position, signals this.
    external: bool = False


class CompiledConstraint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    constraint_id: str
    class_: str = Field(alias="class")
    mode: str  # "expression" | "evaluator"
    expression: str | None = None
    pattern_ref: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    unit: str | None = None
    tolerance: float = 0.0
    stages: list[str] = Field(default_factory=list)


class ResolvedObjective(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: str
    name: str
    terms: list[dict[str, Any]] = Field(default_factory=list)
    aggregation: dict[str, Any] = Field(default_factory=dict)


class ProgramCompatibilityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program: str
    compatible: bool
    missing: list[str] = Field(default_factory=list)


class ExecutablePlan(BaseModel):
    """Data-only, serializable execution plan consumed by the runtime."""

    model_config = ConfigDict(extra="forbid")

    graph_id: str
    version_id: str
    content_hash: str
    horizon_resolution: str | None = None
    components: list[ResolvedComponent] = Field(default_factory=list)
    variables: dict[str, dict[str, Any]] = Field(default_factory=dict)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    constraints: list[CompiledConstraint] = Field(default_factory=list)
    objective: ResolvedObjective | None = None
    query_plan: list[QueryPlan] = Field(default_factory=list)
    validators: list[dict[str, Any]] = Field(default_factory=list)
    program_compatibility: list[ProgramCompatibilityReport] = Field(default_factory=list)


class CompileReport(BaseModel):
    """Immutable §9.16 compile artifact."""

    model_config = ConfigDict(extra="forbid")

    compiler_version: str = COMPILER_VERSION
    graph_content_hash: str
    normalized_graph: dict[str, Any]
    resolved_types: dict[str, str] = Field(default_factory=dict)
    unit_table_version: str
    variable_unit_table: list[dict[str, Any]] = Field(default_factory=list)
    dependency_order: list[str] = Field(default_factory=list)
    query_plan: list[QueryPlan] = Field(default_factory=list)
    constraint_results: list[dict[str, Any]] = Field(default_factory=list)
    validator_plan: list[dict[str, Any]] = Field(default_factory=list)
    validator_results: list[dict[str, Any]] = Field(default_factory=list)
    program_compatibility: list[ProgramCompatibilityReport] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    created_at: datetime

    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "error"]

    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "warning"]


class CompileResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    report: CompileReport
    plan: ExecutablePlan | None = None


# ---------------------------------------------------------------------------
# Internal compile context
# ---------------------------------------------------------------------------
class _Ctx:
    def __init__(self, graph: TwinGraph) -> None:
        self.graph = graph
        self.diagnostics: list[Diagnostic] = []
        # Indexes
        self.entities = {e.id: e for e in graph.entities}
        self.variables = {v.id: v for v in graph.variables}
        self.relations = {r.id: r for r in graph.relations}
        self.actions = {a.id: a for a in graph.actions}
        self.bindings = {b.id: b for b in graph.data_bindings}
        self.model_bindings = {m.id: m for m in graph.model_bindings}
        self.constraints = {c.id: c for c in graph.constraints}
        self.objectives = {o.id: o for o in graph.objectives}
        self.validators = {v.id: v for v in graph.validators}
        self.all_ids: set[str] = set()
        for seq in (
            graph.entities,
            graph.relations,
            graph.variables,
            graph.data_bindings,
            graph.model_bindings,
            graph.actions,
            graph.constraints,
            graph.objectives,
            graph.validators,
            graph.evidence,
        ):
            for item in seq:
                self.all_ids.add(item.id)
        self.resolved_types: dict[str, str] = {}
        self.var_units: dict[str, str] = {}  # variable_id -> declared unit
        self._callable_keys: dict[str, str] = {}  # model_ref -> callable_key
        self.external_bindings: set[str] = set()  # model_binding ids = foreign refs

    def add(self, severity: str, code: str, message: str, stage: str, ref=None) -> None:
        self.diagnostics.append(
            Diagnostic(severity=severity, code=code, message=message, stage=stage, ref=ref)
        )


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------
def compile_graph(
    graph: TwinGraph,
    *,
    type_registry: TypeRegistry,
    model_registry: ModelRegistry,
    program_registry: ProgramRegistry | None = None,
    unit_registry: UnitRegistry | None = None,
    validator_registry: Any | None = None,
    now: datetime | None = None,
) -> CompileResult:
    if type_registry is None or model_registry is None:
        raise ValueError("compile_graph requires non-null type and model registries")
    program_registry = (
        program_registry if program_registry is not None else BUILTIN_PROGRAM_REGISTRY
    )
    unit_registry = unit_registry if unit_registry is not None else DEFAULT_UNIT_REGISTRY
    now = now or datetime.now(timezone.utc)
    ctx = _Ctx(graph)

    normalized = _stage_canonicalize(ctx)
    _stage_resolve_types(ctx, type_registry)
    _stage_required_fields(ctx, type_registry)
    _stage_resolve_refs(ctx, type_registry)
    _stage_validate_units(ctx, type_registry, unit_registry)
    _stage_resolve_models(ctx, model_registry, unit_registry)
    validator_results = _stage_structural_validators(ctx)
    dependency_order = _stage_dependency_graph(ctx)
    query_plan = _stage_query_plan(ctx)
    program_compat = _stage_decision_compatibility(ctx, program_registry)

    # Assemble report
    var_unit_table = [
        {
            "variable_id": v.id,
            "unit": v.unit,
            "role": v.role,
            "temporal_semantics": v.temporal_semantics,
            "bounds": v.bounds.model_dump() if v.bounds else None,
        }
        for v in graph.variables
    ]
    constraint_results = [
        {
            "constraint_id": c.id,
            "compiled": True,
            "stage_coverage": list(c.enforcement.stages),
        }
        for c in graph.constraints
    ]
    validator_plan = [
        {
            "validator_id": v.id,
            "evaluator_ref": v.evaluator_ref,
            "when_stages": ["compile"],
            "required": v.required,
        }
        for v in graph.validators
    ]

    report = CompileReport(
        graph_content_hash=ctx_content_hash(graph),
        normalized_graph=normalized,
        resolved_types=ctx.resolved_types,
        unit_table_version=_unit_table_version(),
        variable_unit_table=var_unit_table,
        dependency_order=dependency_order,
        query_plan=query_plan,
        constraint_results=constraint_results,
        validator_plan=validator_plan,
        validator_results=[r.model_dump() for r in validator_results],
        program_compatibility=program_compat,
        diagnostics=ctx.diagnostics,
        created_at=now,
    )

    ok = not report.errors()
    plan = _build_plan(ctx, graph, query_plan, program_compat) if ok else None
    return CompileResult(ok=ok, report=report, plan=plan)


def ctx_content_hash(graph: TwinGraph) -> str:
    from .canonical import content_hash

    return content_hash(hash_input(graph.model_dump(mode="json")))


def _unit_table_version() -> str:
    from .units import UNIT_TABLE_VERSION

    return UNIT_TABLE_VERSION


# --- stage 1 ---------------------------------------------------------------
def _stage_canonicalize(ctx: _Ctx) -> dict[str, Any]:
    from .canonical import canonicalize

    doc = ctx.graph.model_dump(mode="json")
    normalized = canonicalize(doc)
    computed = ctx_content_hash(ctx.graph)
    declared = ctx.graph.content_hash
    if declared is not None and declared != computed:
        ctx.add(
            "warning",
            CODES.HASH_MISMATCH,
            f"declared content_hash {declared} != computed {computed}",
            "canonicalize",
        )
    return normalized


# --- stage 2 ---------------------------------------------------------------
def _stage_resolve_types(ctx: _Ctx, types: TypeRegistry) -> None:
    for e in ctx.graph.entities:
        try:
            td = types.resolve(e.type_ref)
            ctx.resolved_types[e.type_ref] = e.type_ref.split("@", 1)[1]
            _ = td
        except UnknownTypeRefError:
            ctx.add(
                "error",
                CODES.UNKNOWN_TYPE,
                f"entity '{e.id}' references unknown type_ref '{e.type_ref}'",
                "resolve_types",
                {"entity": e.id, "type_ref": e.type_ref},
            )

    # Relations: a bare verb (``connected_to``, ``feeds_into``) is namespaced to
    # the registry id (``metis.relation.<verb>@1``); an already-namespaced ref
    # (``acme.logistics.ships_to@1``) is resolved as-is. Either way the
    # registered relation TypeDefs are exercised — the "TYPE REGISTRY resolves
    # type_ref" contract now holds for cross-domain relation vocabularies too.
    for r in ctx.graph.relations:
        namespaced = _normalize_relation_type_ref(r.type_ref)
        try:
            types.resolve(namespaced)
            ctx.resolved_types[namespaced] = namespaced.rsplit("@", 1)[1]
        except UnknownTypeRefError:
            ctx.add(
                "error",
                CODES.UNKNOWN_TYPE,
                f"relation '{r.id}' references unknown relation type "
                f"'{r.type_ref}' (no registered '{namespaced}')",
                "resolve_types",
                {"relation": r.id, "type_ref": r.type_ref},
            )


def _normalize_relation_type_ref(raw: str) -> str:
    """Bare verb -> ``metis.relation.<verb>@1``; namespaced ref -> as-is."""
    if "@" in raw:
        return raw
    return f"metis.relation.{raw}@1"


# --- stage 3 ---------------------------------------------------------------
def _stage_required_fields(ctx: _Ctx, types: TypeRegistry) -> None:
    # Variables/actions grouped by owning entity.
    vars_by_owner: dict[str, set[str]] = {}
    for v in ctx.graph.variables:
        vars_by_owner.setdefault(v.owner_ref, set()).add(v.name)
    # An entity "exposes" a controllable capability if it appears as an action
    # name, a bound key, or the name of a control variable the action governs.
    actions_by_target: dict[str, set[str]] = {}
    var_name_by_id = {v.id: v.name for v in ctx.graph.variables}
    for a in ctx.graph.actions:
        caps = actions_by_target.setdefault(a.target_entity_id, set())
        caps.add(a.name)
        caps.update(a.bounds.keys())
        for cv in a.control_variables:
            if cv in var_name_by_id:
                caps.add(var_name_by_id[cv])

    for e in ctx.graph.entities:
        if not types.has(e.type_ref):
            continue  # unknown type already reported
        td = types.resolve(e.type_ref)
        for ps in td.required_properties:
            if ps.required and ps.name not in e.properties:
                ctx.add(
                    "error",
                    CODES.MISSING_REQUIRED,
                    f"entity '{e.id}' ({e.type_ref}) missing required property '{ps.name}'",
                    "validate_required_fields",
                    {"entity": e.id, "field": ps.name},
                )
        present_vars = vars_by_owner.get(e.id, set())
        for vs in td.required_variables:
            if vs.required and vs.name not in present_vars:
                ctx.add(
                    "error",
                    CODES.MISSING_REQUIRED,
                    f"entity '{e.id}' ({e.type_ref}) missing required variable '{vs.name}'",
                    "validate_required_fields",
                    {"entity": e.id, "variable": vs.name},
                )
        present_actions = actions_by_target.get(e.id, set())
        for as_ in td.required_actions:
            if as_.required and as_.name not in present_actions:
                ctx.add(
                    "error",
                    CODES.MISSING_REQUIRED,
                    f"entity '{e.id}' ({e.type_ref}) missing required action '{as_.name}'",
                    "validate_required_fields",
                    {"entity": e.id, "action": as_.name},
                )

    for r in ctx.graph.relations:
        type_ref = _normalize_relation_type_ref(r.type_ref)
        if not types.has(type_ref):
            continue  # unknown relation type already reported
        td = types.resolve(type_ref)
        for ps in td.required_properties:
            if ps.required and ps.name not in r.properties:
                ctx.add(
                    "error",
                    CODES.MISSING_REQUIRED,
                    f"relation '{r.id}' ({type_ref}) missing required property '{ps.name}'",
                    "validate_required_fields",
                    {"relation": r.id, "field": ps.name},
                )


# --- stage 4 ---------------------------------------------------------------
def _ref_exists(ctx: _Ctx, ident: str) -> bool:
    return ident in ctx.all_ids


def _stage_resolve_refs(ctx: _Ctx, types: TypeRegistry) -> None:
    g = ctx.graph

    for e in g.entities:
        for port_id, port in e.ports.items():
            if port.variable_id is not None and port.variable_id not in ctx.variables:
                ctx.add(
                    "error",
                    CODES.DANGLING_REF,
                    f"entity '{e.id}' port '{port_id}' variable_id "
                    f"'{port.variable_id}' does not resolve",
                    "resolve_refs",
                    {"entity": e.id, "port": port_id, "ref": port.variable_id},
                )

    for r in g.relations:
        for side in ("source_entity_id", "target_entity_id"):
            val = getattr(r, side)
            if val not in ctx.entities:
                ctx.add(
                    "error",
                    CODES.DANGLING_REF,
                    f"relation '{r.id}' {side} '{val}' does not resolve to an entity",
                    "resolve_refs",
                    {"relation": r.id, "field": side, "ref": val},
                )
        _validate_relation_ports(ctx, types, r)

    for v in g.variables:
        if v.owner_ref not in ctx.entities and v.owner_ref not in ctx.relations:
            ctx.add(
                "error",
                CODES.DANGLING_REF,
                f"variable '{v.id}' owner_ref '{v.owner_ref}' does not resolve",
                "resolve_refs",
                {"variable": v.id, "ref": v.owner_ref},
            )
        else:
            ctx.var_units[v.id] = v.unit

    for b in g.data_bindings:
        if b.variable_id not in ctx.variables:
            ctx.add(
                "error",
                CODES.DANGLING_REF,
                f"data_binding '{b.id}' variable_id '{b.variable_id}' does not resolve",
                "resolve_refs",
                {"data_binding": b.id, "ref": b.variable_id},
            )

    for m in g.model_bindings:
        for port, ref in m.inputs.items():
            _check_io_ref(ctx, m.id, "input", port, ref)
        for port, ref in m.outputs.items():
            if ref not in ctx.variables:
                ctx.add(
                    "error",
                    CODES.DANGLING_REF,
                    f"model_binding '{m.id}' output '{port}' -> '{ref}' is not a variable",
                    "resolve_refs",
                    {"model_binding": m.id, "port": port, "ref": ref},
                )

    for a in g.actions:
        if a.target_entity_id not in ctx.entities:
            ctx.add(
                "error",
                CODES.DANGLING_REF,
                f"action '{a.id}' target_entity_id '{a.target_entity_id}' does not resolve",
                "resolve_refs",
                {"action": a.id, "ref": a.target_entity_id},
            )
        if a.controller_entity_id and a.controller_entity_id not in ctx.entities:
            ctx.add(
                "error",
                CODES.DANGLING_REF,
                f"action '{a.id}' controller_entity_id '{a.controller_entity_id}' does not resolve",
                "resolve_refs",
                {"action": a.id, "ref": a.controller_entity_id},
            )
        for cv in a.control_variables:
            if cv not in ctx.variables:
                ctx.add(
                    "error",
                    CODES.DANGLING_REF,
                    f"action '{a.id}' control_variable '{cv}' does not resolve",
                    "resolve_refs",
                    {"action": a.id, "ref": cv},
                )
            elif ctx.variables[cv].role != "control":
                ctx.add(
                    "error",
                    CODES.STRUCTURE,
                    f"action '{a.id}' control_variable '{cv}' is not role=control",
                    "resolve_refs",
                    {"action": a.id, "ref": cv},
                )

    # Constraint expression refs (parsed, not evaluated).
    for c in g.constraints:
        if c.expression is not None:
            try:
                refs = extract_references(c.expression.value)
            except ExpressionParseError as exc:
                ctx.add(
                    "error",
                    CODES.STRUCTURE,
                    f"constraint '{c.id}' expression failed to parse: {exc}",
                    "resolve_refs",
                    {"constraint": c.id},
                )
                continue
            for ref in refs:
                ident = ref.split(":", 1)[1] if ref.startswith("var:") else ref
                # Allow numbers-as-idents already filtered; check resolution.
                if ident not in ctx.variables and ident not in ctx.entities:
                    ctx.add(
                        "error",
                        CODES.DANGLING_REF,
                        f"constraint '{c.id}' expression references unknown id '{ident}'",
                        "resolve_refs",
                        {"constraint": c.id, "ref": ident},
                    )

    # Objective measure_refs + scope.
    for o in g.objectives:
        for term in o.terms:
            mr = term.measure_ref
            if mr.startswith("metric:"):
                continue  # runtime metric, validated by the optimizer
            ident = mr.split(":", 1)[1] if mr.startswith("var:") else mr
            if ident not in ctx.variables:
                ctx.add(
                    "error",
                    CODES.DANGLING_REF,
                    f"objective '{o.id}' term measure_ref '{mr}' does not resolve",
                    "resolve_refs",
                    {"objective": o.id, "ref": mr},
                )


def _check_io_ref(ctx: _Ctx, mb_id: str, side: str, port: str, ref: str) -> None:
    if ref.startswith("property:"):
        return  # resolved at param-binding time against an entity
    if ref.startswith("entity:"):
        eid = ref.split(":", 1)[1]
        if eid not in ctx.entities:
            ctx.add(
                "error",
                CODES.DANGLING_REF,
                f"model_binding '{mb_id}' {side} '{port}' -> entity '{eid}' does not resolve",
                "resolve_refs",
                {"model_binding": mb_id, "port": port, "ref": ref},
            )
        return
    if ref not in ctx.variables:
        ctx.add(
            "error",
            CODES.DANGLING_REF,
            f"model_binding '{mb_id}' {side} '{port}' -> '{ref}' does not resolve",
            "resolve_refs",
            {"model_binding": mb_id, "port": port, "ref": ref},
        )


# --- stage 5 ---------------------------------------------------------------
def _validate_relation_ports(ctx: _Ctx, types: TypeRegistry, relation) -> None:
    """Validate relation endpoint ports against entity TypeDef.ports when declared."""

    endpoint_specs = (
        ("source_port", relation.source_entity_id, relation.source_port),
        ("target_port", relation.target_entity_id, relation.target_port),
    )
    for field, entity_id, port in endpoint_specs:
        if port is None:
            continue
        entity = ctx.entities.get(entity_id)
        if entity is None or not types.has(entity.type_ref):
            continue
        type_def = types.resolve(entity.type_ref)
        entity_port = entity.ports.get(port)
        if entity.ports and entity_port is None:
            # Entity-level ports are concrete exported interfaces. They refine,
            # but do not replace, type-level port names: internal relations may
            # still use the generic TypeDef port ("ac_power", "from_bus", ...).
            if type_def.ports is None or port not in type_def.ports:
                ctx.add(
                    "error",
                    CODES.STRUCTURE,
                    f"relation '{relation.id}' {field} '{port}' is neither an "
                    f"exposed port on entity '{entity_id}' nor a declared port "
                    f"on entity type '{entity.type_ref}'",
                    "resolve_refs",
                    {
                        "relation": relation.id,
                        "field": field,
                        "entity": entity_id,
                        "port": port,
                        "allowed_ports": sorted(entity.ports),
                        "allowed_port_kinds": list(type_def.ports or ()),
                    },
                )
                continue
        port_kind = entity_port.kind if entity_port is not None else port
        if type_def.ports is not None and port_kind not in type_def.ports:
            ctx.add(
                "error",
                CODES.STRUCTURE,
                f"relation '{relation.id}' {field} '{port}' has kind '{port_kind}', "
                f"which is not declared on entity type '{entity.type_ref}'",
                "resolve_refs",
                {
                    "relation": relation.id,
                    "field": field,
                    "entity": entity_id,
                    "port": port,
                    "port_kind": port_kind,
                    "allowed_port_kinds": list(type_def.ports),
                },
            )

    if relation.source_port and relation.target_port:
        source = ctx.entities.get(relation.source_entity_id)
        target = ctx.entities.get(relation.target_entity_id)
        source_port = source.ports.get(relation.source_port) if source else None
        target_port = target.ports.get(relation.target_port) if target else None
        if source_port and source_port.direction == "input":
            ctx.add(
                "error",
                CODES.STRUCTURE,
                f"relation '{relation.id}' source_port '{relation.source_port}' is input-only",
                "resolve_refs",
                {"relation": relation.id, "field": "source_port"},
            )
        if target_port and target_port.direction == "output":
            ctx.add(
                "error",
                CODES.STRUCTURE,
                f"relation '{relation.id}' target_port '{relation.target_port}' is output-only",
                "resolve_refs",
                {"relation": relation.id, "field": "target_port"},
            )


def _stage_validate_units(ctx: _Ctx, types: TypeRegistry, units: UnitRegistry) -> None:
    g = ctx.graph

    # Variable units must be known.
    for v in g.variables:
        if not units.is_known(v.unit):
            ctx.add(
                "error",
                CODES.UNKNOWN_UNIT,
                f"variable '{v.id}' has unknown unit '{v.unit}'",
                "validate_units",
                {"variable": v.id, "unit": v.unit},
            )

    # Entity and relation Quantity-valued properties must match TypeDef units.
    for e in g.entities:
        if not types.has(e.type_ref):
            continue
        _validate_property_units(
            ctx, "entity", e.id, e.properties, types.resolve(e.type_ref), units
        )
        _validate_entity_port_units(ctx, e, units)

    for r in g.relations:
        type_ref = _normalize_relation_type_ref(r.type_ref)
        if not types.has(type_ref):
            continue
        _validate_property_units(
            ctx, "relation", r.id, r.properties, types.resolve(type_ref), units
        )

    # Data binding units must match the bound variable's unit.
    for b in g.data_bindings:
        var = ctx.variables.get(b.variable_id)
        if var is None:
            continue
        if not units.compatible(b.unit, var.unit):
            ctx.add(
                "error",
                CODES.UNIT_MISMATCH,
                f"data_binding '{b.id}' unit '{b.unit}' incompatible with "
                f"variable '{var.id}' unit '{var.unit}'",
                "validate_units",
                {"data_binding": b.id, "unit": b.unit, "expected": var.unit},
            )

    # Action bound units must match the controlled variable, if declared.
    for a in g.actions:
        for key, bound in a.bounds.items():
            if bound.unit is None:
                continue
            if not units.is_known(bound.unit):
                ctx.add(
                    "error",
                    CODES.UNKNOWN_UNIT,
                    f"action '{a.id}' bound '{key}' has unknown unit '{bound.unit}'",
                    "validate_units",
                    {"action": a.id, "unit": bound.unit},
                )


def _property_unit(prop: Any) -> str | None:
    if isinstance(prop, dict):
        unit = prop.get("unit")
        return unit if isinstance(unit, str) else None
    if hasattr(prop, "unit") and isinstance(getattr(prop, "unit"), str):
        return getattr(prop, "unit")
    return None


def _validate_property_units(
    ctx: _Ctx,
    owner_kind: str,
    owner_id: str,
    properties: dict[str, Any],
    type_def,
    units: UnitRegistry,
) -> None:
    specs = {
        ps.name: ps
        for ps in (*type_def.required_properties, *type_def.optional_properties)
        if ps.unit is not None
    }
    for name, prop in properties.items():
        spec = specs.get(name)
        if spec is None:
            continue
        prop_unit = _property_unit(prop)
        if prop_unit is None:
            continue  # bare scalar is interpreted in the TypeDef's declared unit
        if not units.is_known(prop_unit):
            ctx.add(
                "error",
                CODES.UNKNOWN_UNIT,
                f"{owner_kind} '{owner_id}' property '{name}' has unknown unit '{prop_unit}'",
                "validate_units",
                {owner_kind: owner_id, "property": name, "unit": prop_unit},
            )
            continue
        if not units.compatible(prop_unit, spec.unit):
            ctx.add(
                "error",
                CODES.UNIT_MISMATCH,
                f"{owner_kind} '{owner_id}' property '{name}' unit '{prop_unit}' "
                f"incompatible with TypeDef unit '{spec.unit}'",
                "validate_units",
                {
                    owner_kind: owner_id,
                    "property": name,
                    "unit": prop_unit,
                    "expected": spec.unit,
                },
            )


def _validate_entity_port_units(ctx: _Ctx, entity, units: UnitRegistry) -> None:
    for port_id, port in entity.ports.items():
        if port.unit is not None and not units.is_known(port.unit):
            ctx.add(
                "error",
                CODES.UNKNOWN_UNIT,
                f"entity '{entity.id}' port '{port_id}' has unknown unit '{port.unit}'",
                "validate_units",
                {"entity": entity.id, "port": port_id, "unit": port.unit},
            )


# --- stage 6 ---------------------------------------------------------------
def _stage_resolve_models(ctx: _Ctx, models: ModelRegistry, units: UnitRegistry) -> None:
    for m in ctx.graph.model_bindings:
        try:
            spec = models.get(m.model_ref)
        except UnknownModelRefError:
            ctx.add(
                "error",
                CODES.UNKNOWN_MODEL,
                f"model_binding '{m.id}' references unknown model_ref '{m.model_ref}'",
                "resolve_models",
                {"model_binding": m.id, "model_ref": m.model_ref},
            )
            continue
        ctx._callable_keys[m.model_ref] = spec.callable_key
        _validate_model_io_units(ctx, m, spec, units)
        if m.kind in FOREIGN_MODEL_KINDS:
            # §31.3: a retained, VALIDATED foreign reference — not a dead enum
            # and not a MODEL_NOT_EXECUTABLE warning. The model_ref resolved
            # above; now validate the io_contract and flag the component
            # external (an FMI/Modelica runtime executes it, not twingraph).
            _validate_foreign_io_contract(ctx, m, spec)
            ctx.external_bindings.add(m.id)
        elif m.kind not in EXECUTABLE_MODEL_KINDS:
            ctx.add(
                "warning",
                CODES.MODEL_NOT_EXECUTABLE,
                f"model_binding '{m.id}' kind '{m.kind}' is not executable in 0.1",
                "resolve_models",
                {"model_binding": m.id, "kind": m.kind},
            )
        # forecast_model outputs must map to forecast_distribution variables.
        if m.kind == "forecast_model":
            for port, ref in m.outputs.items():
                var = ctx.variables.get(ref)
                if var is not None and (
                    var.uncertainty is None
                    or var.uncertainty.kind != "forecast_distribution"
                ):
                    ctx.add(
                        "error",
                        CODES.IO_CONTRACT,
                        f"forecast_model '{m.id}' output '{port}' -> variable "
                        f"'{ref}' lacks uncertainty.kind=forecast_distribution",
                        "resolve_models",
                        {"model_binding": m.id, "port": port, "ref": ref},
                    )
        _ = spec


def _validate_model_io_units(ctx: _Ctx, m, spec, units: UnitRegistry) -> None:
    """Validate variable units against any units declared in a ModelSpec IOContract."""

    for side, bindings, contract_ports in (
        ("input", m.inputs, spec.io_contract.inputs),
        ("output", m.outputs, spec.io_contract.outputs),
    ):
        for port, ref in bindings.items():
            contract = contract_ports.get(port)
            if not contract:
                continue
            expected = contract.get("unit")
            if not isinstance(expected, str):
                continue
            if not units.is_known(expected):
                ctx.add(
                    "error",
                    CODES.UNKNOWN_UNIT,
                    f"model_binding '{m.id}' {side} port '{port}' contract declares "
                    f"unknown unit '{expected}'",
                    "resolve_models",
                    {"model_binding": m.id, "port": port, "unit": expected},
                )
                continue
            if ref.startswith(("property:", "entity:")):
                continue
            variable = ctx.variables.get(ref)
            if variable is None:
                continue  # dangling refs are reported in resolve_refs
            if not units.compatible(variable.unit, expected):
                ctx.add(
                    "error",
                    CODES.IO_CONTRACT,
                    f"model_binding '{m.id}' {side} port '{port}' expects unit "
                    f"'{expected}' but variable '{ref}' has unit '{variable.unit}'",
                    "resolve_models",
                    {
                        "model_binding": m.id,
                        "port": port,
                        "variable": ref,
                        "unit": variable.unit,
                        "expected": expected,
                    },
                )


def _validate_foreign_io_contract(ctx: _Ctx, m, spec) -> None:
    """Validate a foreign-reference binding's io_contract (§31.3).

    If the resolved ModelSpec's io_contract declares input/output ports, the
    binding's ``inputs``/``outputs`` port-name sets must match the contract
    bidirectionally. If the contract is empty, the binding must still write
    graph state (>=1 output mapping) — a foreign component that produces nothing
    cannot participate in a decision twin. Violations → TG_IO_CONTRACT.
    """
    contract = spec.io_contract
    declared_inputs = set(getattr(contract, "inputs", {}) or {})
    declared_outputs = set(getattr(contract, "outputs", {}) or {})

    if not declared_inputs and not declared_outputs:
        if not m.outputs:
            ctx.add(
                "error",
                CODES.IO_CONTRACT,
                f"foreign model_binding '{m.id}' ({m.kind}) has no io_contract "
                "and writes no graph state (needs >=1 output mapping)",
                "resolve_models",
                {"model_binding": m.id, "kind": m.kind},
            )
        return

    if set(m.inputs) != declared_inputs:
        ctx.add(
            "error",
            CODES.IO_CONTRACT,
            f"foreign model_binding '{m.id}' ({m.kind}) input ports "
            f"{sorted(m.inputs)} do not match io_contract inputs "
            f"{sorted(declared_inputs)}",
            "resolve_models",
            {"model_binding": m.id, "expected": sorted(declared_inputs)},
        )
    if set(m.outputs) != declared_outputs:
        ctx.add(
            "error",
            CODES.IO_CONTRACT,
            f"foreign model_binding '{m.id}' ({m.kind}) output ports "
            f"{sorted(m.outputs)} do not match io_contract outputs "
            f"{sorted(declared_outputs)}",
            "resolve_models",
            {"model_binding": m.id, "expected": sorted(declared_outputs)},
        )


# --- stage 7 ---------------------------------------------------------------
def _stage_structural_validators(ctx: _Ctx):
    from .primitives import ValidatorResult

    results: list[ValidatorResult] = []

    # reference_integrity / schema_integrity: pass iff no dangling/structure errors so far.
    has_ref_errors = any(
        d.code in (CODES.DANGLING_REF, CODES.STRUCTURE) for d in ctx.diagnostics
    )
    results.append(
        ValidatorResult(
            validator_id="reference_integrity",
            status="fail" if has_ref_errors else "pass",
            message="all cross-references resolve" if not has_ref_errors else "dangling refs present",
        )
    )

    has_unit_errors = any(
        d.code in (CODES.UNIT_MISMATCH, CODES.UNKNOWN_UNIT) for d in ctx.diagnostics
    )
    results.append(
        ValidatorResult(
            validator_id="unit_compatibility",
            status="fail" if has_unit_errors else "pass",
            message="units compatible" if not has_unit_errors else "unit mismatch present",
        )
    )

    # data_binding_availability: each binding feeding a horizon var must carry availability.
    avail_ok = True
    for b in ctx.graph.data_bindings:
        if b.available_at_column is None and not b.conservative_availability_policy:
            avail_ok = False
    results.append(
        ValidatorResult(
            validator_id="data_binding_availability",
            status="pass" if avail_ok else "fail",
            message="availability declared on every binding"
            if avail_ok
            else "binding missing availability",
        )
    )

    # issue_time_leakage (static): bindings into exogenous/forecast horizon vars
    # must have available_at_column.
    leak_ok = True
    for b in ctx.graph.data_bindings:
        var = ctx.variables.get(b.variable_id)
        if var is None:
            continue
        # A horizon-feeding variable (exogenous/observed) demands an EXPLICIT
        # availability column AND an enforced as-of cutoff. A conservative
        # policy is acceptable for general availability accounting, but not as
        # the leakage guarantee on the forecast horizon; and as_of_required=false
        # tells the runtime to skip the cutoff entirely, so it cannot be
        # certified leakage-safe (§12.4).
        if var.role in ("exogenous", "observed") and (
            b.available_at_column is None or b.query_policy.as_of_required is not True
        ):
            leak_ok = False
    results.append(
        ValidatorResult(
            validator_id="issue_time_leakage",
            status="pass" if leak_ok else "fail",
            message="no leakage: availability present on horizon-feeding bindings"
            if leak_ok
            else "potential leakage: horizon binding lacks availability",
        )
    )

    return results


# --- stage 8 ---------------------------------------------------------------
def _stage_dependency_graph(ctx: _Ctx) -> list[str]:
    """Topo-order executable model components by their input/output variables."""
    # Map: which variables each component writes; reads.
    nodes = [m.id for m in ctx.graph.model_bindings]
    reads: dict[str, set[str]] = {}
    writer_of: dict[str, str] = {}
    for m in ctx.graph.model_bindings:
        out_vars = set(m.outputs.values())
        reads[m.id] = {r for r in m.inputs.values() if r in ctx.variables}
        for ov in out_vars:
            writer_of[ov] = m.id

    # Edge A -> B if B reads a variable A writes.
    deps: dict[str, set[str]] = {n: set() for n in nodes}
    for n in nodes:
        for rv in reads[n]:
            w = writer_of.get(rv)
            if w and w != n:
                deps[n].add(w)

    order: list[str] = []
    visited: dict[str, int] = {}  # 0=visiting,1=done

    def visit(n: str) -> None:
        state = visited.get(n)
        if state == 1:
            return
        if state == 0:
            ctx.add(
                "error",
                CODES.CYCLE,
                f"execution cycle through model_binding '{n}'",
                "build_dependency_graph",
                {"model_binding": n},
            )
            return
        visited[n] = 0
        for d in sorted(deps[n]):
            visit(d)
        visited[n] = 1
        order.append(n)

    for n in nodes:
        visit(n)
    return order


# --- stage 9 ---------------------------------------------------------------
def _stage_query_plan(ctx: _Ctx) -> list[QueryPlan]:
    plans: list[QueryPlan] = []
    for b in ctx.graph.data_bindings:
        var = ctx.variables.get(b.variable_id)
        feeds_horizon = var is not None and var.role in ("exogenous", "observed")
        if feeds_horizon:
            # A horizon-feeding binding is leakage-safe ONLY with an explicit
            # availability column AND a policy that the runtime will actually
            # apply the as-of cutoff (as_of_required). A binding that declares
            # an availability column but sets as_of_required=false tells the
            # connector to SKIP the issue-time filter (see connectors.py), so
            # certifying it leakage-safe on column-presence alone would lie
            # about runtime behavior (§12.4).
            leakage_safe = (
                b.available_at_column is not None
                and b.query_policy.as_of_required is True
            )
        else:
            leakage_safe = b.available_at_column is not None or (
                b.query_policy.as_of_required is False
                and b.conservative_availability_policy is not None
            )
        if feeds_horizon and not leakage_safe:
            ctx.add(
                "error",
                CODES.LEAKAGE,
                f"data_binding '{b.id}' feeds horizon variable '{b.variable_id}' "
                "without an enforceable as-of availability guarantee "
                "(needs available_at_column AND query_policy.as_of_required=true)",
                "build_query_plan",
                {"data_binding": b.id, "variable": b.variable_id},
            )
        plans.append(
            QueryPlan(
                data_binding_id=b.id,
                variable_id=b.variable_id,
                semantic_view=b.source.semantic_view,
                filters=dict(b.source.filters),
                value_column=b.value_column,
                event_time_column=b.event_time_column,
                available_at_column=b.available_at_column,
                unit=b.unit,
                unit_transform=b.unit_transform.model_dump() if b.unit_transform else None,
                as_of_required=b.query_policy.as_of_required,
                deduplication=b.query_policy.deduplication,
                latest_before_issue_time=b.query_policy.latest_before_issue_time,
                missing_value_policy=b.query_policy.missing_value_policy,
                expected_resolution=(
                    b.validation.expected_resolution if b.validation else None
                ),
                grain=list(b.grain),
                leakage_safe=leakage_safe,
            )
        )
    return plans


# --- stage 10 --------------------------------------------------------------
def _stage_decision_compatibility(
    ctx: _Ctx, program_registry: ProgramRegistry
) -> list[ProgramCompatibilityReport]:
    """Report each registered program profile's compatibility (never errors).

    Domain-agnostic: every profile carries its own labelled requirements (see
    ``programs.py``). With only ``tomorrow_dispatch`` registered (the builtin),
    this reproduces the legacy five-check report byte-for-byte; a registry with
    a non-battery profile reports that profile's own compatibility instead.
    """
    return [profile.check(ctx) for profile in program_registry.all()]


# ---------------------------------------------------------------------------
# Plan assembly (only on ok)
# ---------------------------------------------------------------------------
def _build_plan(
    ctx: _Ctx,
    graph: TwinGraph,
    query_plan: list[QueryPlan],
    program_compat: list[ProgramCompatibilityReport],
) -> ExecutablePlan:
    components: list[ResolvedComponent] = []
    # Order components by the dependency topo-order for execution.
    order = _stage_dependency_graph(ctx)  # deterministic; already error-free
    mb_by_id = {m.id: m for m in graph.model_bindings}

    for mb_id in order:
        m = mb_by_id[mb_id]
        # Resolve params (property:/entity: -> value).
        resolved_params = _resolve_params_for_binding(ctx, m)
        components.append(
            ResolvedComponent(
                model_binding_id=m.id,
                kind=m.kind,
                model_ref=m.model_ref,
                callable_key=ctx._callable_keys.get(m.model_ref, m.model_ref),
                inputs=dict(m.inputs),
                outputs=dict(m.outputs),
                params=resolved_params,
                external=m.id in ctx.external_bindings,
            )
        )

    variables = {
        v.id: {
            "unit": v.unit,
            "role": v.role,
            "temporal_semantics": v.temporal_semantics,
            "owner_ref": v.owner_ref,
            "bounds": v.bounds.model_dump() if v.bounds else None,
        }
        for v in graph.variables
    }

    actions = [
        {
            "id": a.id,
            "name": a.name,
            "target_entity_id": a.target_entity_id,
            "control_variables": list(a.control_variables),
            "bounds": {k: _resolve_action_bound(ctx, a, k, b) for k, b in a.bounds.items()},
            "mutual_exclusion": [list(g) for g in a.mutual_exclusion],
        }
        for a in graph.actions
    ]

    constraints = []
    for c in graph.constraints:
        if c.expression is not None:
            constraints.append(
                CompiledConstraint(
                    constraint_id=c.id,
                    **{"class": c.class_},
                    mode="expression",
                    expression=c.expression.value,
                    unit=c.unit,
                    tolerance=c.tolerance,
                    stages=list(c.enforcement.stages),
                )
            )
        else:
            constraints.append(
                CompiledConstraint(
                    constraint_id=c.id,
                    **{"class": c.class_},
                    mode="evaluator",
                    pattern_ref=c.evaluator_ref.pattern_ref,
                    params=_resolve_evaluator_params(ctx, c),
                    unit=c.unit,
                    tolerance=c.tolerance,
                    stages=list(c.enforcement.stages),
                )
            )

    objective = None
    if graph.objectives:
        o = graph.objectives[0]
        objective = ResolvedObjective(
            objective_id=o.id,
            name=o.name,
            terms=[t.model_dump() for t in o.terms],
            aggregation=o.aggregation.model_dump(by_alias=True),
        )

    validators = [
        {"id": v.id, "evaluator_ref": v.evaluator_ref, "params": dict(v.params), "required": v.required}
        for v in graph.validators
    ]

    return ExecutablePlan(
        graph_id=graph.graph_id,
        version_id=graph.version_id,
        content_hash=ctx_content_hash(graph),
        horizon_resolution=_infer_horizon_resolution(graph),
        components=components,
        variables=variables,
        actions=actions,
        constraints=constraints,
        objective=objective,
        query_plan=query_plan,
        validators=validators,
        program_compatibility=program_compat,
    )


def _resolve_params_for_binding(ctx: _Ctx, m) -> dict[str, Any]:
    out: dict[str, Any] = {}
    # The model binding's entity (for property: resolution) = the entity that
    # owns one of its output variables, else None.
    owner_entity = None
    for ref in list(m.outputs.values()) + list(m.inputs.values()):
        var = ctx.variables.get(ref)
        if var and var.owner_ref in ctx.entities:
            owner_entity = var.owner_ref
            break
    for key, val in m.parameters.items():
        if isinstance(val, str) and val.startswith("property:"):
            pkey = val.split(":", 1)[1]
            ent = ctx.entities.get(owner_entity) if owner_entity else None
            if ent and pkey in ent.properties:
                prop = ent.properties[pkey]
                out[key] = prop["value"] if isinstance(prop, dict) and "value" in prop else prop
            else:
                out[key] = val
        else:
            out[key] = val
    # Also surface the owning entity's full resolved properties for component build.
    if owner_entity:
        ent = ctx.entities[owner_entity]
        out.setdefault("_entity_id", owner_entity)
        out.setdefault(
            "_entity_properties",
            {
                k: (v["value"] if isinstance(v, dict) and "value" in v else v)
                for k, v in ent.properties.items()
            },
        )
    return out


def _resolve_action_bound(ctx: _Ctx, action, key: str, bound) -> dict[str, Any]:
    ent = ctx.entities.get(action.target_entity_id)

    def resolve_from(spec: str | None) -> float | None:
        if spec is None:
            return None
        if spec.startswith("property:") and ent is not None:
            pkey = spec.split(":", 1)[1]
            if pkey in ent.properties:
                prop = ent.properties[pkey]
                return prop["value"] if isinstance(prop, dict) and "value" in prop else prop
        return None

    lo = bound.min if bound.min is not None else resolve_from(bound.min_from)
    hi = bound.max if bound.max is not None else resolve_from(bound.max_from)
    return {"unit": bound.unit, "min": lo, "max": hi}


def _resolve_evaluator_params(ctx: _Ctx, c) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in c.evaluator_ref.params.items():
        if isinstance(v, str) and v.startswith("property:"):
            ent = ctx.entities.get(c.scope_ref) if c.scope_ref else None
            if ent is not None:
                pkey = v.split(":", 1)[1]
                if pkey in ent.properties:
                    prop = ent.properties[pkey]
                    out[k] = prop["value"] if isinstance(prop, dict) and "value" in prop else prop
                    continue
        out[k] = v
    return out


def _infer_horizon_resolution(graph: TwinGraph) -> str | None:
    for v in graph.variables:
        if v.resolution:
            return v.resolution
    return None
