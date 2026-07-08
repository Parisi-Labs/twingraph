"""TwinGraph 0.1 primitives — the ten typed building blocks (spec §9.3-9.12).

Every model is ``extra="forbid"`` EXCEPT the deliberately-open maps
(``properties``, ``params``/``parameters``, ``filters``, ``provenance`` at the
document root, ``extensions``). All cross-references are ids, never display
names. ``metis_expr`` values are PARSED (refs extracted) but never evaluated by
compile.

Open-source core: stdlib + pydantic only.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .units import Quantity

# An id is permissive: authoring ids ('bat','soc') and ULIDs both allowed.
ID_PATTERN = r"^[A-Za-z0-9_.:-]+$"
# type_ref like 'metis.energy.Battery@1' — dotted namespace (leading lowercase)
# whose final class segment may be CamelCase, then '@<major>'.
TYPE_REF_PATTERN = r"^[a-z][A-Za-z0-9_.]*@\d+$"
# model_ref like 'registry://metis.components.battery_linear@1.0.0'
MODEL_REF_PATTERN = r"^registry://[a-z][a-z0-9_.]*@\d+\.\d+\.\d+$"


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ---------------------------------------------------------------------------
# Shared enums + provenance (§9.13, §9.12)
# ---------------------------------------------------------------------------
class ConfirmationState(str, Enum):
    inferred = "inferred"
    proposed = "proposed"
    confirmed = "confirmed"
    disputed = "disputed"
    deprecated = "deprecated"


class LifecycleState(str, Enum):
    planned = "planned"
    active = "active"
    degraded = "degraded"
    offline = "offline"
    retired = "retired"


SourceKind = Literal[
    "asset_configuration",
    "warehouse_profile",
    "document_excerpt",
    "user_confirmation",
    "test_result",
    "model_metric",
    "prior_version",
    "generated_proposal",
]


class Provenance(_Base):
    source_kind: SourceKind
    source_ref: str | None = None
    extracted_by: str | None = None
    created_at: datetime | None = None
    created_by: str | None = None
    note: str | None = None


# ---------------------------------------------------------------------------
# Entity (§9.3)
# ---------------------------------------------------------------------------
class EntityPort(_Base):
    """A concrete interface exposed by an entity instance.

    ``kind`` should match one of the entity type's declared port kinds when the
    type registry declares ports. The dict key on ``Entity.ports`` is the local
    port id used by relations, so a plant can expose ``poi_34_5kv`` while the
    type-level kind remains ``ac_power``.
    """

    kind: str
    unit: str | None = None
    direction: Literal["input", "output", "bidirectional"] = "bidirectional"
    variable_id: str | None = None
    relation_types: list[str] = Field(default_factory=list)
    description: str | None = None


class Entity(_Base):
    id: str = Field(pattern=ID_PATTERN)
    type_ref: str = Field(pattern=TYPE_REF_PATTERN, description="e.g. metis.energy.Battery@1")
    name: str
    namespace: str = "metis.demo"
    lifecycle_state: LifecycleState = LifecycleState.active
    properties: dict[str, Any] = Field(default_factory=dict)  # OPEN: scalar | Quantity
    ports: dict[str, EntityPort] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    provenance: Provenance | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    confirmation_state: ConfirmationState = ConfirmationState.confirmed


# ---------------------------------------------------------------------------
# Relation (§9.4)
# ---------------------------------------------------------------------------
# The P0 vocabulary — kept as a DOCUMENTED Literal alias (and exported) so
# adopters can introspect the built-in set, but it NO LONGER constrains the
# field. As of 0.2 a relation ``type_ref`` is a registry-resolved string
# (validated at compile against the registered relation TypeDefs), exactly like
# entity ``type_ref``s — see RELATION_TYPE_REF_PATTERN.
RelationType = Literal[
    "contains",
    "connected_to",
    "controls",
    "constrained_by",
    "settles_at",
    "observed_by",
    "driven_by",
    "charges",
    "degrades_with",
    "evaluated_by",
    "located_in",
]

# A relation type_ref is permissive at PARSE: either a bare snake_case verb
# (``connected_to``, ``feeds_into``, ``ships_to``) which compile namespaces to
# ``metis.relation.<verb>@1``, OR an already-namespaced foreign/explicit ref
# (``acme.logistics.ships_to@1``). A structurally-malformed value still
# ValidationErrors at parse; a well-formed-but-unregistered value PARSES and
# then compile-errors TG_UNKNOWN_TYPE (the contract moved from parse-reject to
# compile-resolve in 0.2, opening cross-domain relation vocabularies).
RELATION_TYPE_REF_PATTERN = r"^[a-z][A-Za-z0-9_]*$|^[a-z][A-Za-z0-9_.]*@\d+$"


class Relation(_Base):
    id: str = Field(pattern=ID_PATTERN)
    type_ref: str = Field(
        pattern=RELATION_TYPE_REF_PATTERN,
        description="bare verb (metis.relation.<x>@1) or namespaced foreign ref",
    )
    source_entity_id: str
    target_entity_id: str
    directionality: Literal["directed", "undirected"] = "directed"
    source_port: str | None = None
    target_port: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    confirmation_state: ConfirmationState = ConfirmationState.confirmed
    provenance: Provenance | None = None


# ---------------------------------------------------------------------------
# Variable (§9.5)
# ---------------------------------------------------------------------------
VariableRole = Literal[
    "state",
    "control",
    "exogenous",
    "observed",
    "derived",
    "latent",
    "parameter",
    "outcome",
]


class VarBounds(_Base):
    min: float | None = None
    max: float | None = None
    min_from: str | None = None
    max_from: str | None = None

    @model_validator(mode="after")
    def _min_lte_max(self) -> VarBounds:
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("variable bounds require min <= max")
        return self


class VarInitFallback(_Base):
    strategy: str
    value: Any | None = None


class VarInitialization(_Base):
    strategy: str
    value: Any | None = None
    expression: str | None = None
    fallback: VarInitFallback | None = None


class VarUncertainty(_Base):
    kind: Literal["deterministic", "measured", "forecast_distribution"] = "deterministic"
    tolerance: float | None = None
    required_quantiles: list[float] | None = None


class Variable(_Base):
    id: str = Field(pattern=ID_PATTERN)
    owner_ref: str = Field(description="Entity OR relation id that owns this variable")
    name: str
    display_name: str | None = None
    role: VariableRole
    data_type: Literal[
        "float", "integer", "boolean", "category", "string", "vector", "distribution"
    ] = "float"
    unit: str = "dimensionless"
    temporal_semantics: Literal[
        "instant",
        "interval_average",
        "interval_sum",
        "start_of_interval_state",
        "end_of_interval_state",
        "publication_event",
    ] = "instant"
    bounds: VarBounds | None = None
    resolution: str | None = None
    initialization: VarInitialization | None = None
    uncertainty: VarUncertainty | None = None
    required_for: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Data binding (§9.6) — the leakage primitive
# ---------------------------------------------------------------------------
class UnitTransform(_Base):
    from_unit: str
    to_unit: str
    scale: float = 1.0
    offset: float = 0.0


class DataSource(_Base):
    adapter: str = "central_warehouse"
    semantic_view: str
    filters: dict[str, Any] = Field(default_factory=dict)  # OPEN


class QueryPolicy(_Base):
    as_of_required: bool = True
    deduplication: str = "latest_available_at"
    latest_before_issue_time: bool | None = None
    max_lookback: str | None = None
    missing_value_policy: str = "fail_required_horizon"


class BindingValidation(_Base):
    expected_resolution: str | None = None
    max_staleness: str | None = None
    allowed_min: float | None = None
    allowed_max: float | None = None

    @model_validator(mode="after")
    def _allowed_min_lte_max(self) -> BindingValidation:
        if (
            self.allowed_min is not None
            and self.allowed_max is not None
            and self.allowed_min > self.allowed_max
        ):
            raise ValueError("binding validation range requires allowed_min <= allowed_max")
        return self


class DataBinding(_Base):
    id: str = Field(pattern=ID_PATTERN)
    variable_id: str
    source: DataSource
    event_time_column: str = Field(description="REQUIRED — the event time column")
    available_at_column: str | None = None
    value_column: str
    unit: str
    unit_column: str | None = None
    unit_transform: UnitTransform | None = None
    grain: list[str] = Field(default_factory=list)
    query_policy: QueryPolicy = Field(default_factory=QueryPolicy)
    # When availability is omitted, an explicit conservative justification is required.
    conservative_availability_policy: str | None = None
    validation: BindingValidation | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    provenance: Provenance | None = None

    @model_validator(mode="after")
    def _availability_never_silently_omitted(self) -> DataBinding:
        # §9.6/§12.4: either available_at_column is set, OR as_of_required is
        # explicitly False with a written conservative-availability justification.
        has_col = self.available_at_column is not None
        as_of = self.query_policy.as_of_required
        if has_col:
            return self
        if as_of is False and self.conservative_availability_policy:
            return self
        raise ValueError(
            "data_binding availability cannot be silently omitted: set "
            "available_at_column, OR set query_policy.as_of_required=false WITH "
            "a conservative_availability_policy justification (§9.6/§12.4)"
        )


# ---------------------------------------------------------------------------
# Model binding (§9.7) — references only, no code
# ---------------------------------------------------------------------------
ModelBindingKind = Literal[
    "native_component",
    "forecast_model",
    "derived_expression",
    "optimizer",
    "rule_policy",
    "calibration_model",
    "explanation_template",
    # Foreign-reference kinds (§31.3) — NOT natively executed by twingraph.
    "fmu",
    "modelica_class",
]
# §31.3 foreign references. ``fmu`` / ``modelica_class`` are NOT dead, warn-only
# enums: compile VALIDATES them as foreign references (model_ref resolved,
# io_contract checked) and marks the resulting component ``external=True`` —
# "TwinGraph should RETAIN foreign references and compile relevant pieces into
# its operational representation." They are deliberately absent from
# EXECUTABLE_MODEL_KINDS: an FMI/Modelica runtime executes them, not twingraph's
# native dispatch. A retained, validated foreign reference — not a dead value.
FOREIGN_MODEL_KINDS = frozenset({"fmu", "modelica_class"})

EXECUTABLE_MODEL_KINDS = frozenset(
    {
        "native_component",
        "forecast_model",
        "derived_expression",
        "optimizer",
        "rule_policy",
        "calibration_model",
        "explanation_template",
    }
)


class ModelExecution(_Base):
    deterministic: bool = True
    interval: str | None = None


class ModelBinding(_Base):
    id: str = Field(pattern=ID_PATTERN)
    kind: ModelBindingKind
    model_ref: str = Field(pattern=MODEL_REF_PATTERN)
    scope_ref: str | None = None
    inputs: dict[str, str] = Field(default_factory=dict)
    outputs: dict[str, str] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)  # OPEN
    execution: ModelExecution | None = None


# ---------------------------------------------------------------------------
# Action (§9.8)
# ---------------------------------------------------------------------------
class ActionBound(_Base):
    unit: str | None = None
    min: float | None = None
    min_from: str | None = None
    max: float | None = None
    max_from: str | None = None

    @model_validator(mode="after")
    def _min_lte_max(self) -> ActionBound:
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("action bounds require min <= max")
        return self


class ActionPermissions(_Base):
    propose: list[str] = Field(default_factory=list)
    approve: list[str] = Field(default_factory=list)


class Action(_Base):
    id: str = Field(pattern=ID_PATTERN)
    name: str
    controller_entity_id: str | None = None
    target_entity_id: str
    control_variables: list[str] = Field(default_factory=list)
    cadence: str | None = None
    bounds: dict[str, ActionBound] = Field(default_factory=dict)
    mutual_exclusion: list[list[str]] = Field(default_factory=list)
    execution_mode: Literal["advisory", "automatic"] = "advisory"
    requires_approval: bool = True
    permissions: ActionPermissions | None = None


# ---------------------------------------------------------------------------
# Constraint (§9.9) — typed kinds, expression XOR evaluator_ref
# ---------------------------------------------------------------------------
ConstraintClass = Literal[
    "hard_physical",
    "hard_commercial",
    "hard_permission",
    "soft_operational",
    "soft_risk",
    "informational",
]


class ConstraintExpression(_Base):
    language: str = "metis_expr/0.1"
    value: str


class ConstraintEvaluator(_Base):
    pattern_ref: str
    params: dict[str, Any] = Field(default_factory=dict)  # OPEN


class ConstraintEnforcement(_Base):
    stages: list[Literal["compile", "optimize", "simulate", "outcome"]] = Field(
        default_factory=lambda: ["simulate"]
    )


class Constraint(_Base):
    id: str = Field(pattern=ID_PATTERN)
    name: str
    class_: ConstraintClass = Field(alias="class")
    scope_ref: str | None = None
    expression: ConstraintExpression | None = None
    evaluator_ref: ConstraintEvaluator | None = None
    enforcement: ConstraintEnforcement = Field(default_factory=ConstraintEnforcement)
    unit: str | None = None
    tolerance: float = 0.0
    on_violation: Literal["reject_result", "mark_uncertified", "warn", "penalize"] = (
        "reject_result"
    )
    evidence_refs: list[str] = Field(default_factory=list)
    provenance: Provenance | None = None

    @model_validator(mode="after")
    def _exactly_one_of_expression_or_evaluator(self) -> Constraint:
        has_expr = self.expression is not None
        has_eval = self.evaluator_ref is not None
        if has_expr == has_eval:
            raise ValueError(
                "constraint must specify EXACTLY ONE of expression OR evaluator_ref (§9.9)"
            )
        return self


# ---------------------------------------------------------------------------
# Objective (§9.10 + §16.2) — structured terms
# ---------------------------------------------------------------------------
class ObjectiveTerm(_Base):
    id: str = Field(pattern=ID_PATTERN)
    direction: Literal["maximize", "minimize"]
    measure_ref: str = Field(description="var:<id> | <variable_id> | metric:<name>")
    weight: float = 1.0


class ObjectiveAggregation(_Base):
    kind: Literal["expected_value", "expected_value_plus_risk"]
    risk_measure: Literal["none", "CVaR"] = "none"
    alpha: float | None = Field(default=None, gt=0.0, lt=1.0)
    lambda_: float | None = Field(default=None, alias="lambda", ge=0.0)


class Objective(_Base):
    id: str = Field(pattern=ID_PATTERN)
    name: str
    terms: list[ObjectiveTerm] = Field(default_factory=list)
    aggregation: ObjectiveAggregation


# ---------------------------------------------------------------------------
# Validator (§9.11)
# ---------------------------------------------------------------------------
class Validator(_Base):
    id: str = Field(pattern=ID_PATTERN)
    name: str | None = None
    evaluator_ref: str = Field(description="Registered pattern name")
    params: dict[str, Any] = Field(default_factory=dict)  # OPEN
    required: bool = True
    scope_ref: str | None = None


class ValidatorResult(BaseModel):
    """Produced at compile/run, NOT stored in the graph."""

    model_config = ConfigDict(extra="forbid")

    validator_id: str
    status: Literal["pass", "warn", "fail", "skipped"]
    observed_value: float | None = None
    threshold: float | None = None
    unit: str | None = None
    message: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Evidence (§9.12)
# ---------------------------------------------------------------------------
class Evidence(_Base):
    id: str = Field(pattern=ID_PATTERN)
    kind: Literal[
        "document_excerpt",
        "warehouse_profile",
        "user_confirmation",
        "test_result",
        "model_metric",
        "asset_configuration",
        "prior_version",
        "generated_proposal",
    ]
    source_ref: str
    locator: dict[str, Any] = Field(default_factory=dict)
    claim: str | None = None
    created_at: datetime | None = None
    created_by: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


__all__ = [
    "EXECUTABLE_MODEL_KINDS",
    "FOREIGN_MODEL_KINDS",
    "RELATION_TYPE_REF_PATTERN",
    "Action",
    "ActionBound",
    "ActionPermissions",
    "BindingValidation",
    "ConfirmationState",
    "Constraint",
    "ConstraintClass",
    "ConstraintEnforcement",
    "ConstraintEvaluator",
    "ConstraintExpression",
    "DataBinding",
    "DataSource",
    "Entity",
    "Evidence",
    "LifecycleState",
    "ModelBinding",
    "ModelBindingKind",
    "ModelExecution",
    "Objective",
    "ObjectiveAggregation",
    "ObjectiveTerm",
    "Provenance",
    "Quantity",
    "QueryPolicy",
    "Relation",
    "RelationType",
    "UnitTransform",
    "Validator",
    "ValidatorResult",
    "VarBounds",
    "VarInitialization",
    "VarUncertainty",
    "Variable",
    "VariableRole",
]
