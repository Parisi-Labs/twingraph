"""Graph layers, overlays, and cross-graph associations.

``GraphBundle`` keeps independently versioned ``TwinGraph`` documents separate
while giving applications a typed way to describe their roles and the stable
associations between them.  Selection, simulation, and execution remain
application responsibilities; this module only supplies IR and validation.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .canonical import canonical_json, content_hash, hash_input
from .compile import CompileResult, compile_graph
from .document import TwinGraph
from .errors import CODES, Diagnostic
from .ids import ID_PATTERN, new_ulid
from .patch import SemanticPatch
from .primitives import Provenance
from .programs import ProgramRegistry
from .registry import ModelCatalog, TypeRegistry
from .units import UnitRegistry

GraphRole = Literal["design", "desired", "observed", "candidate"]
CrossGraphBindingKind = Literal[
    "realizes",
    "implements",
    "derived_from",
    "proposes_change_to",
]
GraphObjectKind = Literal[
    "entity",
    "relation",
    "variable",
    "data_binding",
    "model_binding",
    "action",
    "constraint",
    "objective",
    "validator",
    "evidence",
]


class CandidateState(str, Enum):
    proposed = "proposed"
    evaluated = "evaluated"
    accepted = "accepted"
    rejected = "rejected"
    committed = "committed"


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GraphVersionRef(_Base):
    graph_id: str
    version_id: str
    as_of: datetime | None = None


class GraphObjectRef(GraphVersionRef):
    object_kind: GraphObjectKind
    object_id: str = Field(pattern=ID_PATTERN)


class GraphLayer(_Base):
    """One independently versioned graph and its role in a bundle."""

    id: str = Field(pattern=ID_PATTERN)
    role: GraphRole
    graph: TwinGraph
    overlay_base: GraphVersionRef | None = None
    candidate_state: CandidateState | None = None
    expected_delta: SemanticPatch | None = None
    observed_delta: SemanticPatch | None = None
    evidence_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _candidate_lifecycle_is_explicit(self) -> GraphLayer:
        if self.role == "candidate":
            if self.overlay_base is None:
                raise ValueError("candidate graph layers require overlay_base")
            if self.candidate_state is None:
                raise ValueError("candidate graph layers require candidate_state")
            if self.candidate_state == CandidateState.committed:
                raise ValueError(
                    "candidate graph layers cannot be committed in place; "
                    "promote the layer to an authoritative role"
                )
        elif self.candidate_state not in (None, CandidateState.committed):
            raise ValueError(
                "candidate_state is only valid for candidate layers, except "
                "committed which records an explicit promotion"
            )
        return self

    @property
    def is_authoritative(self) -> bool:
        return self.role != "candidate"


class CrossGraphBinding(_Base):
    """A typed, evidenced association between objects in separate graphs."""

    id: str = Field(pattern=ID_PATTERN)
    kind: CrossGraphBindingKind
    source: GraphObjectRef
    target: GraphObjectRef
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    provenance: Provenance | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class GraphBundle(_Base):
    schema_version: Literal["twingraph-bundle/0.1"] = "twingraph-bundle/0.1"
    bundle_id: str = Field(default_factory=new_ulid)
    name: str
    layers: list[GraphLayer] = Field(default_factory=list)
    bindings: list[CrossGraphBinding] = Field(default_factory=list)
    content_hash: str | None = None
    extensions: dict[str, Any] = Field(default_factory=dict)

    def compute_content_hash(self) -> str:
        """Return semantic identity for the bundle.

        ``bundle_id`` and embedded graph creation time / declared hash are
        excluded. Layer ``version_id`` values and exact graph/version references
        in overlays and bindings remain semantic: a bundle pins versions, so a
        different layer version or mapping is a different bundle assertion.
        """

        payload = self.model_dump(mode="json", exclude={"bundle_id", "content_hash"})
        for layer in payload["layers"]:
            graph_version_id = layer["graph"]["version_id"]
            layer["graph"] = hash_input(layer["graph"])
            layer["graph"]["version_id"] = graph_version_id
        payload["layers"] = sorted(
            payload["layers"],
            key=lambda layer: (
                layer["id"],
                layer["graph"]["graph_id"],
                canonical_json(layer),
            ),
        )
        payload["bindings"] = sorted(
            payload["bindings"], key=lambda item: (item["id"], canonical_json(item))
        )
        return content_hash(payload)

    def with_content_hash(self) -> GraphBundle:
        copy_ = self.model_copy(deep=True)
        copy_.content_hash = self.compute_content_hash()
        return copy_

    def promote_candidate(self, layer_id: str, *, role: Literal["desired", "observed"]) -> GraphBundle:
        """Return a copy where an accepted candidate is explicitly authoritative."""

        copy_ = self.model_copy(deep=True)
        try:
            layer = next(item for item in copy_.layers if item.id == layer_id)
        except StopIteration as exc:
            raise KeyError(layer_id) from exc
        if layer.role != "candidate" or layer.candidate_state != CandidateState.accepted:
            raise ValueError("only an accepted candidate layer can be promoted")
        layer.role = role
        layer.candidate_state = CandidateState.committed
        copy_.content_hash = None
        return GraphBundle.model_validate(copy_.model_dump())


class LayerCompileResult(_Base):
    layer_id: str
    role: GraphRole
    result: CompileResult


class BundleCompileReport(_Base):
    bundle_content_hash: str
    graph_results: list[LayerCompileResult]
    diagnostics: list[Diagnostic] = Field(default_factory=list)

    def errors(self) -> list[Diagnostic]:
        return [item for item in self.diagnostics if item.severity == "error"]


class BundleCompileResult(_Base):
    ok: bool
    report: BundleCompileReport


def compile_bundle(
    bundle: GraphBundle,
    *,
    type_registry: TypeRegistry,
    model_registry: ModelCatalog,
    program_registry: ProgramRegistry | None = None,
    unit_registry: UnitRegistry | None = None,
    validator_registry: Any | None = None,
    now: datetime | None = None,
) -> BundleCompileResult:
    """Compile every layer and validate bundle-level references deterministically."""

    graph_results = [
        LayerCompileResult(
            layer_id=layer.id,
            role=layer.role,
            result=compile_graph(
                layer.graph,
                type_registry=type_registry,
                model_registry=model_registry,
                program_registry=program_registry,
                unit_registry=unit_registry,
                validator_registry=validator_registry,
                now=now,
            ),
        )
        for layer in bundle.layers
    ]
    diagnostics = _validate_bundle(bundle)
    computed_hash = bundle.compute_content_hash()
    if bundle.content_hash is not None and bundle.content_hash != computed_hash:
        diagnostics.append(
            Diagnostic(
                severity="warning",
                code=CODES.HASH_MISMATCH,
                message="declared bundle content_hash does not match computed content hash",
                stage="validate_graph_bundle",
            )
        )
    report = BundleCompileReport(
        bundle_content_hash=computed_hash,
        graph_results=graph_results,
        diagnostics=diagnostics,
    )
    return BundleCompileResult(
        ok=not report.errors() and all(item.result.ok for item in graph_results),
        report=report,
    )


def _validate_bundle(bundle: GraphBundle) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    by_key: dict[tuple[str, str], GraphLayer] = {}
    layer_ids: set[str] = set()

    def add(code: str, message: str, ref: dict[str, Any] | None = None) -> None:
        diagnostics.append(
            Diagnostic(
                severity="error",
                code=code,
                message=message,
                stage="validate_graph_bundle",
                ref=ref,
            )
        )

    for layer in bundle.layers:
        if layer.id in layer_ids:
            add(CODES.DUPLICATE_ID, f"graph layer id '{layer.id}' appears more than once")
        layer_ids.add(layer.id)
        key = (layer.graph.graph_id, layer.graph.version_id)
        if key in by_key:
            add(
                CODES.DUPLICATE_ID,
                f"graph version {key[0]}@{key[1]} appears in more than one layer",
            )
        by_key[key] = layer

    evidence_ids_by_graph = {
        (layer.graph.graph_id, layer.graph.version_id): {
            evidence.id for evidence in layer.graph.evidence
        }
        for layer in bundle.layers
    }
    for layer in bundle.layers:
        if layer.overlay_base:
            base_key = (layer.overlay_base.graph_id, layer.overlay_base.version_id)
            if base_key not in by_key:
                add(
                    CODES.DANGLING_REF,
                    f"layer '{layer.id}' overlay_base {base_key[0]}@{base_key[1]} does not resolve",
                    {"layer": layer.id, "field": "overlay_base"},
                )
        if layer.overlay_base:
            for field in ("expected_delta", "observed_delta"):
                delta = getattr(layer, field)
                if delta and delta.base_version_id != layer.overlay_base.version_id:
                    add(
                        CODES.STRUCTURE,
                        f"layer '{layer.id}' {field} base_version_id does not match overlay_base",
                        {"layer": layer.id, "field": f"{field}.base_version_id"},
                    )
        layer_evidence_ids = evidence_ids_by_graph.get(
            (layer.graph.graph_id, layer.graph.version_id), set()
        )
        for evidence_ref in layer.evidence_refs:
            if evidence_ref not in layer_evidence_ids:
                add(
                    CODES.DANGLING_REF,
                    f"layer '{layer.id}' evidence_ref '{evidence_ref}' does not resolve",
                    {"layer": layer.id, "ref": evidence_ref},
                )

    binding_ids: set[str] = set()
    entity_only_kinds: set[CrossGraphBindingKind] = {
        "realizes",
        "implements",
        "proposes_change_to",
    }
    for binding in bundle.bindings:
        if binding.id in binding_ids:
            add(CODES.DUPLICATE_ID, f"cross-graph binding id '{binding.id}' appears more than once")
        binding_ids.add(binding.id)
        for side, endpoint in (("source", binding.source), ("target", binding.target)):
            key = (endpoint.graph_id, endpoint.version_id)
            layer = by_key.get(key)
            if layer is None:
                add(
                    CODES.DANGLING_REF,
                    f"binding '{binding.id}' {side} graph {key[0]}@{key[1]} does not resolve",
                    {"binding": binding.id, "field": side},
                )
            elif not _object_exists(layer.graph, endpoint.object_kind, endpoint.object_id):
                add(
                    CODES.DANGLING_REF,
                    f"binding '{binding.id}' {side} {endpoint.object_kind} "
                    f"'{endpoint.object_id}' does not resolve",
                    {"binding": binding.id, "field": side, "ref": endpoint.object_id},
                )
        if binding.kind in entity_only_kinds and (
            binding.source.object_kind != "entity" or binding.target.object_kind != "entity"
        ):
            add(
                CODES.STRUCTURE,
                f"binding '{binding.id}' kind '{binding.kind}' requires entity endpoints",
                {"binding": binding.id, "field": "kind"},
            )
        if binding.kind == "derived_from" and (
            binding.source.object_kind != binding.target.object_kind
        ):
            add(
                CODES.STRUCTURE,
                f"binding '{binding.id}' kind 'derived_from' requires compatible object kinds",
                {"binding": binding.id, "field": "kind"},
            )
        binding_evidence_ids = evidence_ids_by_graph.get(
            (binding.source.graph_id, binding.source.version_id), set()
        ) | evidence_ids_by_graph.get(
            (binding.target.graph_id, binding.target.version_id), set()
        )
        for evidence_ref in binding.evidence_refs:
            if evidence_ref not in binding_evidence_ids:
                add(
                    CODES.DANGLING_REF,
                    f"binding '{binding.id}' evidence_ref '{evidence_ref}' does not resolve",
                    {"binding": binding.id, "ref": evidence_ref},
                )
    return diagnostics


def _object_exists(graph: TwinGraph, kind: GraphObjectKind, object_id: str) -> bool:
    fields = {
        "entity": graph.entities,
        "relation": graph.relations,
        "variable": graph.variables,
        "data_binding": graph.data_bindings,
        "model_binding": graph.model_bindings,
        "action": graph.actions,
        "constraint": graph.constraints,
        "objective": graph.objectives,
        "validator": graph.validators,
        "evidence": graph.evidence,
    }
    return any(item.id == object_id for item in fields[kind])


__all__ = [
    "BundleCompileReport",
    "BundleCompileResult",
    "CandidateState",
    "CrossGraphBinding",
    "CrossGraphBindingKind",
    "GraphBundle",
    "GraphLayer",
    "GraphObjectKind",
    "GraphObjectRef",
    "GraphRole",
    "GraphVersionRef",
    "LayerCompileResult",
    "compile_bundle",
]
