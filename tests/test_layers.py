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
                    object_id="asset",
                ),
                target=tg.GraphObjectRef(
                    graph_id="desired",
                    version_id="desired-v1",
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


def test_committed_bundle_schema_matches_models_and_validates_example():
    committed = json.loads(
        (_ROOT / "schema" / "twingraph-bundle-0.1.schema.json").read_text()
    )
    assert committed == build_bundle_schema()
    example = json.loads(
        (_ROOT / "examples" / "public_graph_layers_01.twingraph-bundle.json").read_text()
    )
    jsonschema.validate(example, committed)
    tg.GraphBundle.model_validate(example)
