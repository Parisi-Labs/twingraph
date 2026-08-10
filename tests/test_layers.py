from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest
import twingraph as tg
from pydantic import ValidationError
from twingraph._bundle_schema_tool import build_bundle_schema
from twingraph.errors import CODES

_ROOT = Path(__file__).resolve().parents[1]


def _graph(graph_id: str, version_id: str, entity_id: str) -> tg.TwinGraph:
    return tg.TwinGraph(
        graph_id=graph_id,
        version_id=version_id,
        workspace_id=tg.SENTINEL_WORKSPACE,
        name=graph_id,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        created_by="test",
        entities=[
            tg.Entity(
                id=entity_id,
                type_ref="metis.ops.Facility@1",
                name=entity_id,
            )
        ],
    )


def _bundle() -> tg.GraphBundle:
    observed = _graph("observed", "observed-v1", "asset")
    desired = _graph("desired", "desired-v1", "asset-spec")
    candidate = _graph("candidate", "candidate-v1", "asset-proposal")
    patch = tg.SemanticPatch(
        patch_id="expected-delta",
        base_version_id="observed-v1",
        intent="propose an asset change",
        created_by="test",
    )
    return tg.GraphBundle(
        bundle_id="bundle-1",
        name="layered twin",
        layers=[
            tg.GraphLayer(id="observed", role="observed", graph=observed),
            tg.GraphLayer(id="desired", role="desired", graph=desired),
            tg.GraphLayer(
                id="candidate",
                role="candidate",
                graph=candidate,
                overlay_base=tg.GraphVersionRef(
                    graph_id="observed", version_id="observed-v1"
                ),
                candidate_state="accepted",
                expected_delta=patch,
            ),
        ],
        bindings=[
            tg.CrossGraphBinding(
                id="desired-realized-by-observed",
                kind="realizes",
                source=tg.GraphObjectRef(
                    graph_id="observed",
                    version_id="observed-v1",
                    object_kind="entity",
                    object_id="asset",
                ),
                target=tg.GraphObjectRef(
                    graph_id="desired",
                    version_id="desired-v1",
                    object_kind="entity",
                    object_id="asset-spec",
                ),
            )
        ],
    )


def test_bundle_round_trips_hashes_and_compiles(model_registry):
    bundle = _bundle().with_content_hash()
    loaded = tg.GraphBundle.model_validate_json(bundle.model_dump_json())
    assert loaded.compute_content_hash() == bundle.content_hash

    result = tg.compile_bundle(
        loaded,
        type_registry=tg.BUILTIN_TYPE_REGISTRY,
        model_registry=model_registry,
    )
    assert result.ok, result.report.diagnostics
    assert all(item.result.ok for item in result.report.graph_results)


def test_candidate_is_non_authoritative_until_explicitly_promoted():
    bundle = _bundle()
    candidate = next(layer for layer in bundle.layers if layer.id == "candidate")
    assert not candidate.is_authoritative

    promoted = bundle.promote_candidate("candidate", role="desired")
    layer = next(item for item in promoted.layers if item.id == "candidate")
    assert layer.is_authoritative
    assert layer.role == "desired"
    assert layer.candidate_state == tg.CandidateState.committed
    assert layer.expected_delta is not None
    assert bundle.layers[2].role == "candidate"


def test_candidate_requires_base_and_lifecycle():
    with pytest.raises(ValidationError, match="overlay_base"):
        tg.GraphLayer(id="candidate", role="candidate", graph=_graph("g", "v", "e"))


def test_graph_object_kind_and_binding_kind_are_explicit():
    with pytest.raises(ValidationError, match="object_kind"):
        tg.GraphObjectRef(graph_id="g", version_id="v", object_id="e")
    with pytest.raises(ValidationError, match="kind"):
        tg.CrossGraphBinding(
            id="binding",
            kind="custom_kind",
            source=tg.GraphObjectRef(
                graph_id="g",
                version_id="v",
                object_kind="entity",
                object_id="a",
            ),
            target=tg.GraphObjectRef(
                graph_id="h",
                version_id="v",
                object_kind="entity",
                object_id="b",
            ),
        )


def test_bundle_reports_dangling_and_incompatible_cross_graph_refs(model_registry):
    bundle = _bundle()
    bundle.bindings[0].target.object_id = "missing"
    bundle.bindings[0].source.object_kind = "variable"
    result = tg.compile_bundle(
        bundle,
        type_registry=tg.BUILTIN_TYPE_REGISTRY,
        model_registry=model_registry,
    )
    codes = {item.code for item in result.report.errors()}
    assert CODES.DANGLING_REF in codes
    assert CODES.STRUCTURE in codes


def test_bundle_hash_is_order_independent():
    first = _bundle()
    second = first.model_copy(deep=True)
    second.layers.reverse()
    second.bindings.reverse()
    assert first.compute_content_hash() == second.compute_content_hash()


def test_bundle_hash_excludes_envelope_and_embedded_graph_volatility():
    first = _bundle()
    second = first.model_copy(deep=True)
    second.bundle_id = "reminted-bundle"
    second.layers[0].graph.created_at = datetime(2030, 1, 1, tzinfo=UTC)
    second.layers[0].graph.content_hash = "sha256:declared-but-nonsemantic"
    second.layers[0].graph.version_id = "reminted-unreferenced-version"
    assert first.compute_content_hash() == second.compute_content_hash()

    second.bindings[0].target.version_id = "different-version-assertion"
    assert first.compute_content_hash() != second.compute_content_hash()


def test_bundle_reports_dangling_overlay_delta_and_evidence_refs(model_registry):
    bundle = _bundle()
    candidate = next(layer for layer in bundle.layers if layer.id == "candidate")
    candidate.overlay_base.version_id = "missing-version"
    candidate.expected_delta.base_version_id = "wrong-expected-base"
    candidate.observed_delta = tg.SemanticPatch(
        patch_id="observed-delta",
        base_version_id="wrong-observed-base",
        intent="record observed change",
        created_by="test",
    )
    candidate.evidence_refs = ["missing-layer-evidence"]
    bundle.bindings[0].evidence_refs = ["missing-binding-evidence"]

    result = tg.compile_bundle(
        bundle,
        type_registry=tg.BUILTIN_TYPE_REGISTRY,
        model_registry=model_registry,
    )
    messages = [item.message for item in result.report.errors()]
    assert any("overlay_base" in message for message in messages)
    assert any("expected_delta" in message for message in messages)
    assert any("observed_delta" in message for message in messages)
    assert sum("evidence_ref" in message for message in messages) == 2


def test_evidence_refs_are_scoped_to_layer_or_binding_endpoints(model_registry):
    bundle = _bundle()
    observed_layer, desired_layer, candidate_layer = bundle.layers
    desired_layer.graph.evidence.append(
        tg.Evidence(id="desired-proof", kind="test_result", source_ref="test://desired")
    )
    candidate_layer.graph.evidence.append(
        tg.Evidence(id="candidate-proof", kind="test_result", source_ref="test://candidate")
    )
    observed_layer.evidence_refs = ["desired-proof"]
    bundle.bindings[0].evidence_refs = ["candidate-proof"]

    result = tg.compile_bundle(
        bundle,
        type_registry=tg.BUILTIN_TYPE_REGISTRY,
        model_registry=model_registry,
    )
    messages = [item.message for item in result.report.errors()]
    assert any("layer 'observed' evidence_ref 'desired-proof'" in item for item in messages)
    assert any("binding 'desired-realized-by-observed' evidence_ref 'candidate-proof'" in item for item in messages)

    observed_layer.evidence_refs = []
    bundle.bindings[0].evidence_refs = ["desired-proof"]
    assert tg.compile_bundle(
        bundle,
        type_registry=tg.BUILTIN_TYPE_REGISTRY,
        model_registry=model_registry,
    ).ok


def test_duplicate_layer_graph_and_binding_ids_are_reported(model_registry):
    bundle = _bundle()
    bundle.layers.append(bundle.layers[0].model_copy(deep=True))
    bundle.bindings.append(bundle.bindings[0].model_copy(deep=True))
    result = tg.compile_bundle(
        bundle,
        type_registry=tg.BUILTIN_TYPE_REGISTRY,
        model_registry=model_registry,
    )
    duplicate_messages = [
        item.message
        for item in result.report.errors()
        if item.code == CODES.DUPLICATE_ID
    ]
    assert any("graph layer id" in message for message in duplicate_messages)
    assert any("graph version" in message for message in duplicate_messages)
    assert any("binding id" in message for message in duplicate_messages)


def test_derived_from_requires_matching_object_kinds(model_registry):
    bundle = _bundle()
    desired = next(layer for layer in bundle.layers if layer.id == "desired")
    desired.graph.variables.append(
        tg.Variable(
            id="desired-state",
            owner_ref="asset-spec",
            name="desired_state",
            role="observed",
        )
    )
    binding = bundle.bindings[0]
    binding.kind = "derived_from"
    binding.target.object_kind = "variable"
    binding.target.object_id = "desired-state"
    result = tg.compile_bundle(
        bundle,
        type_registry=tg.BUILTIN_TYPE_REGISTRY,
        model_registry=model_registry,
    )
    assert any("compatible object kinds" in item.message for item in result.report.errors())


def test_compile_warns_on_stale_bundle_hash(model_registry):
    bundle = _bundle()
    bundle.content_hash = "sha256:stale"
    result = tg.compile_bundle(
        bundle,
        type_registry=tg.BUILTIN_TYPE_REGISTRY,
        model_registry=model_registry,
    )
    assert any(
        item.code == CODES.HASH_MISMATCH and item.severity == "warning"
        for item in result.report.diagnostics
    )


def test_promote_candidate_rejects_missing_and_unaccepted_layers():
    bundle = _bundle()
    with pytest.raises(KeyError):
        bundle.promote_candidate("missing", role="desired")
    bundle.layers[2].candidate_state = "evaluated"
    with pytest.raises(ValueError, match="accepted candidate"):
        bundle.promote_candidate("candidate", role="observed")


def test_committed_bundle_schema_matches_models_and_validates_example(model_registry):
    committed = json.loads(
        (_ROOT / "schema" / "twingraph-bundle-0.1.schema.json").read_text()
    )
    assert committed == build_bundle_schema()
    example = json.loads(
        (_ROOT / "examples" / "public_graph_layers_01.twingraph-bundle.json").read_text()
    )
    jsonschema.validate(example, committed)
    bundle = tg.GraphBundle.model_validate(example)
    assert tg.compile_bundle(
        bundle,
        type_registry=tg.BUILTIN_TYPE_REGISTRY,
        model_registry=model_registry,
    ).ok
