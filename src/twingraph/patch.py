"""Semantic patch format and application (spec §9.15) — FORMAT ONLY, no agents.

A ``SemanticPatch`` is an ordered set of single-twin operations that, applied in
sequence to a base document, produces a NEW version (forking a new draft). This
module ships the patch *format* and a pure ``apply_patch`` — building the agent
RUNTIME that proposes patches is deliberately out of 0.1 scope.

apply_patch:
  1. rejects if patch.base_version_id != graph.version_id (OutOfOrderPatchError);
  2. enforces immutability — material ops against an active/frozen graph are
     rejected (ImmutableGraphError); the normal flow forks a new DRAFT;
  3. deep-copies, applies ops in order (add must not collide; remove/replace
     must find the id; a dangling-ref-creating op is ALLOWED and caught by the
     post-apply compile per the §9.15 lifecycle);
  4. mints a new identity (new version_id, parent = base version_id, status
     draft, recomputed content_hash, provenance.applied_patch_id);
  5. returns the new document + a report. It does NOT auto-compile.

stdlib + pydantic only.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .document import TwinGraph
from .errors import ImmutableGraphError, OutOfOrderPatchError, TwinGraphError
from .ids import new_ulid
from .primitives import (
    Constraint,
    DataBinding,
    Entity,
    Evidence,
    ModelBinding,
    Objective,
    Relation,
    Validator,
    Variable,
)


class PatchStatus(str, Enum):
    proposed = "proposed"
    schema_validated = "schema_validated"
    execution_validated = "execution_validated"
    awaiting_approval = "awaiting_approval"
    approved = "approved"
    applied = "applied"
    rejected = "rejected"
    superseded = "superseded"


class _Op(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- add/remove/replace per primitive --------------------------------------
class AddEntity(_Op):
    op: Literal["add_entity"]
    entity: Entity


class RemoveEntity(_Op):
    op: Literal["remove_entity"]
    entity_id: str


class ReplaceEntity(_Op):
    op: Literal["replace_entity"]
    entity: Entity


class AddRelation(_Op):
    op: Literal["add_relation"]
    relation: Relation


class RemoveRelation(_Op):
    op: Literal["remove_relation"]
    relation_id: str


class ReplaceRelation(_Op):
    op: Literal["replace_relation"]
    relation: Relation


class AddVariable(_Op):
    op: Literal["add_variable"]
    variable: Variable


class RemoveVariable(_Op):
    op: Literal["remove_variable"]
    variable_id: str


class ReplaceVariable(_Op):
    op: Literal["replace_variable"]
    variable: Variable


class AddDataBinding(_Op):
    op: Literal["add_data_binding"]
    data_binding: DataBinding


class RemoveDataBinding(_Op):
    op: Literal["remove_data_binding"]
    data_binding_id: str


class ReplaceDataBinding(_Op):
    op: Literal["replace_data_binding"]
    data_binding: DataBinding


class AddModelBinding(_Op):
    op: Literal["add_model_binding"]
    model_binding: ModelBinding


class RemoveModelBinding(_Op):
    op: Literal["remove_model_binding"]
    model_binding_id: str


class ReplaceModelBinding(_Op):
    op: Literal["replace_model_binding"]
    model_binding: ModelBinding


class AddConstraint(_Op):
    op: Literal["add_constraint"]
    constraint: Constraint


class RemoveConstraint(_Op):
    op: Literal["remove_constraint"]
    constraint_id: str


class ReplaceConstraint(_Op):
    op: Literal["replace_constraint"]
    constraint: Constraint


class AddObjective(_Op):
    op: Literal["add_objective"]
    objective: Objective


class RemoveObjective(_Op):
    op: Literal["remove_objective"]
    objective_id: str


class ReplaceObjective(_Op):
    op: Literal["replace_objective"]
    objective: Objective


class AddValidator(_Op):
    op: Literal["add_validator"]
    validator: Validator


class RemoveValidator(_Op):
    op: Literal["remove_validator"]
    validator_id: str


class ReplaceValidator(_Op):
    op: Literal["replace_validator"]
    validator: Validator


class AddEvidence(_Op):
    op: Literal["add_evidence"]
    evidence: Evidence


class RemoveEvidence(_Op):
    op: Literal["remove_evidence"]
    evidence_id: str


class SetProperty(_Op):
    op: Literal["set_property"]
    entity_id: str
    key: str
    value: Any


class ResolveAssumption(_Op):
    op: Literal["resolve_assumption"]
    assumption_id: str
    resolution: str
    evidence_refs: list[str] = Field(default_factory=list)


Operation = Annotated[
    AddEntity | RemoveEntity | ReplaceEntity | AddRelation | RemoveRelation | ReplaceRelation | AddVariable | RemoveVariable | ReplaceVariable | AddDataBinding | RemoveDataBinding | ReplaceDataBinding | AddModelBinding | RemoveModelBinding | ReplaceModelBinding | AddConstraint | RemoveConstraint | ReplaceConstraint | AddObjective | RemoveObjective | ReplaceObjective | AddValidator | RemoveValidator | ReplaceValidator | AddEvidence | RemoveEvidence | SetProperty | ResolveAssumption,
    Field(discriminator="op"),
]


class SemanticPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patch_id: str = Field(default_factory=new_ulid)
    base_version_id: str
    intent: str
    created_by: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    operations: list[Operation] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    assumptions_created: list[str] = Field(default_factory=list)
    validation_plan: list[str] = Field(default_factory=list)
    status: PatchStatus = PatchStatus.proposed


class PatchApplyReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patch_id: str
    base_version_id: str
    result_version_id: str
    applied_ops: int
    status: PatchStatus = PatchStatus.applied


class PatchLog(BaseModel):
    """An append-only log the application holds (twingraph just defines it)."""

    model_config = ConfigDict(extra="forbid")

    entries: list[dict[str, Any]] = Field(default_factory=list)

    def record(self, report: PatchApplyReport, applied_at: datetime | None = None) -> None:
        self.entries.append(
            {
                "patch_id": report.patch_id,
                "base_version_id": report.base_version_id,
                "result_version_id": report.result_version_id,
                "applied_at": (applied_at or datetime.now(UTC)).isoformat(),
                "status": report.status.value,
            }
        )


def lineage(versions: list[TwinGraph]) -> list[dict[str, str | None]]:
    """Return the ordered lineage records of a list of versions."""
    return [v.lineage() for v in versions]


# Ops considered "material" for immutability purposes (§10.5).
_MATERIAL_OP_PREFIXES = (
    "add_entity",
    "remove_entity",
    "replace_entity",
    "add_relation",
    "remove_relation",
    "replace_relation",
    "add_variable",
    "remove_variable",
    "replace_variable",
    "add_model_binding",
    "remove_model_binding",
    "replace_model_binding",
    "add_constraint",
    "remove_constraint",
    "replace_constraint",
    "add_objective",
    "remove_objective",
    "replace_objective",
    "set_property",
)


def _list_for(graph: TwinGraph, attr: str) -> list:
    return getattr(graph, attr)


def _apply_add(seq: list, item, ident: str) -> None:
    if any(x.id == ident for x in seq):
        raise TwinGraphError(f"add: id '{ident}' already exists")
    seq.append(item)


def _apply_remove(seq: list, ident: str, label: str) -> None:
    for i, x in enumerate(seq):
        if x.id == ident:
            del seq[i]
            return
    raise TwinGraphError(f"remove: {label} id '{ident}' not found")


def _apply_replace(seq: list, item, label: str) -> None:
    for i, x in enumerate(seq):
        if x.id == item.id:
            seq[i] = item
            return
    raise TwinGraphError(f"replace: {label} id '{item.id}' not found")


def apply_patch(
    graph: TwinGraph,
    patch: SemanticPatch,
    *,
    mint_version_id: Callable[[], str] = new_ulid,
    now: datetime | None = None,
) -> tuple[TwinGraph, PatchApplyReport]:
    """Apply ``patch`` to ``graph``, returning a NEW draft document + report."""
    now = now or datetime.now(UTC)

    # (1) order check
    if patch.base_version_id != graph.version_id:
        raise OutOfOrderPatchError(
            f"patch base_version_id '{patch.base_version_id}' != graph "
            f"version_id '{graph.version_id}'"
        )

    # (2) immutability guard
    if graph.is_active() or graph.is_frozen():
        material = [op.op for op in patch.operations if op.op in _MATERIAL_OP_PREFIXES]
        if material:
            raise ImmutableGraphError(
                f"cannot apply material ops {material} to an active/frozen graph; "
                "patching forks a new draft but material edits require the source "
                "graph to already be a draft (§10.5)"
            )

    # (3) deep copy + apply in order (on the plain data, then re-validate)
    draft = graph.model_copy(deep=True)
    object.__setattr__(draft, "_frozen", False)
    draft.status = "draft"

    for op in patch.operations:
        _apply_op(draft, op)

    # (4) mint new identity
    draft.parent_version_id = graph.version_id
    draft.version_id = mint_version_id()
    draft.created_at = now
    new_prov = dict(draft.provenance)
    new_prov["applied_patch_id"] = patch.patch_id
    draft.provenance = new_prov
    draft.content_hash = draft.compute_content_hash()

    report = PatchApplyReport(
        patch_id=patch.patch_id,
        base_version_id=graph.version_id,
        result_version_id=draft.version_id,
        applied_ops=len(patch.operations),
        status=PatchStatus.applied,
    )
    return draft, report


def _apply_op(draft: TwinGraph, op: Operation) -> None:
    name = op.op
    if name == "add_entity":
        _apply_add(draft.entities, op.entity, op.entity.id)
    elif name == "remove_entity":
        _apply_remove(draft.entities, op.entity_id, "entity")
    elif name == "replace_entity":
        _apply_replace(draft.entities, op.entity, "entity")
    elif name == "add_relation":
        _apply_add(draft.relations, op.relation, op.relation.id)
    elif name == "remove_relation":
        _apply_remove(draft.relations, op.relation_id, "relation")
    elif name == "replace_relation":
        _apply_replace(draft.relations, op.relation, "relation")
    elif name == "add_variable":
        _apply_add(draft.variables, op.variable, op.variable.id)
    elif name == "remove_variable":
        _apply_remove(draft.variables, op.variable_id, "variable")
    elif name == "replace_variable":
        _apply_replace(draft.variables, op.variable, "variable")
    elif name == "add_data_binding":
        _apply_add(draft.data_bindings, op.data_binding, op.data_binding.id)
    elif name == "remove_data_binding":
        _apply_remove(draft.data_bindings, op.data_binding_id, "data_binding")
    elif name == "replace_data_binding":
        _apply_replace(draft.data_bindings, op.data_binding, "data_binding")
    elif name == "add_model_binding":
        _apply_add(draft.model_bindings, op.model_binding, op.model_binding.id)
    elif name == "remove_model_binding":
        _apply_remove(draft.model_bindings, op.model_binding_id, "model_binding")
    elif name == "replace_model_binding":
        _apply_replace(draft.model_bindings, op.model_binding, "model_binding")
    elif name == "add_constraint":
        _apply_add(draft.constraints, op.constraint, op.constraint.id)
    elif name == "remove_constraint":
        _apply_remove(draft.constraints, op.constraint_id, "constraint")
    elif name == "replace_constraint":
        _apply_replace(draft.constraints, op.constraint, "constraint")
    elif name == "add_objective":
        _apply_add(draft.objectives, op.objective, op.objective.id)
    elif name == "remove_objective":
        _apply_remove(draft.objectives, op.objective_id, "objective")
    elif name == "replace_objective":
        _apply_replace(draft.objectives, op.objective, "objective")
    elif name == "add_validator":
        _apply_add(draft.validators, op.validator, op.validator.id)
    elif name == "remove_validator":
        _apply_remove(draft.validators, op.validator_id, "validator")
    elif name == "replace_validator":
        _apply_replace(draft.validators, op.validator, "validator")
    elif name == "add_evidence":
        _apply_add(draft.evidence, op.evidence, op.evidence.id)
    elif name == "remove_evidence":
        _apply_remove(draft.evidence, op.evidence_id, "evidence")
    elif name == "set_property":
        ent = _find(draft.entities, op.entity_id, "entity")
        new_props = dict(ent.properties)
        new_props[op.key] = op.value
        ent.properties = new_props
    elif name == "resolve_assumption":
        _resolve_assumption(draft, op)
    else:  # pragma: no cover - discriminated union prevents this
        raise TwinGraphError(f"unknown patch op '{name}'")


def _find(seq: list, ident: str, label: str):
    for x in seq:
        if x.id == ident:
            return x
    raise TwinGraphError(f"{label} id '{ident}' not found")


def _resolve_assumption(draft: TwinGraph, op: ResolveAssumption) -> None:
    # Record the resolution into extensions and flip any affected
    # confirmation_states from proposed -> confirmed.
    ext = copy.deepcopy(draft.extensions)
    resolved = ext.setdefault("resolved_assumptions", [])
    resolved.append(
        {
            "assumption_id": op.assumption_id,
            "resolution": op.resolution,
            "evidence_refs": list(op.evidence_refs),
        }
    )
    draft.extensions = ext
    for ent in draft.entities:
        if ent.confirmation_state.value == "proposed":
            ent.confirmation_state = ent.confirmation_state.__class__.confirmed
