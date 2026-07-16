from datetime import UTC, datetime, timedelta

import pytest
import twingraph as tg
from pydantic import ValidationError


def test_component_callable_contract_is_runtime_checkable():
    def component(*, inputs, params, context):
        return {"dispatch": inputs["price"] * params["scale"]}

    context = tg.ExecutionContext(
        execution_id="run-01",
        graph_id="graph-01",
        version_id="version-01",
        content_hash="sha256:abc",
        issue_time=datetime(2026, 7, 15, tzinfo=UTC),
    )

    assert isinstance(component, tg.ComponentCallable)
    assert component(inputs={"price": 5}, params={"scale": 2}, context=context) == {"dispatch": 10}
    with pytest.raises(ValidationError):
        context.graph_id = "other"


def test_execution_result_wire_round_trip():
    started = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    result = tg.ExecutionResult(
        compiler_version=tg.COMPILER_VERSION,
        execution_id="run-01",
        graph_id="graph-01",
        version_id="version-01",
        content_hash="sha256:abc",
        issue_time=started,
        started_at=started,
        finished_at=started + timedelta(seconds=3),
        status="succeeded",
        outputs={"dispatch_mw": [1.0, 2.0]},
        model_versions={"dispatch": "1.2.3"},
        input_artifacts=[
            tg.ArtifactRef(
                uri="s3://example/snapshot.json",
                media_type="application/json",
                content_hash="sha256:def",
            )
        ],
    )

    payload = result.to_wire()

    assert payload["result_schema_version"] == tg.EXECUTION_RESULT_SCHEMA_VERSION
    assert payload["plan_schema_version"] == tg.PLAN_SCHEMA_VERSION
    assert payload["issue_time"] == "2026-07-15T12:00:00Z"
    assert tg.ExecutionResult.from_wire(payload) == result

    payload["result_schema_version"] = "twingraph-execution-result/99"
    with pytest.raises(ValidationError):
        tg.ExecutionResult.from_wire(payload)


def test_execution_result_rejects_non_json_outputs():
    now = datetime(2026, 7, 15, tzinfo=UTC)

    with pytest.raises(ValidationError):
        tg.ExecutionResult(
            compiler_version=tg.COMPILER_VERSION,
            execution_id="run-01",
            graph_id="graph-01",
            version_id="version-01",
            content_hash="sha256:abc",
            issue_time=now,
            started_at=now,
            finished_at=now,
            status="succeeded",
            outputs={"not_wire_safe": object()},
        )


def test_execution_result_enforces_outcome_and_time_invariants():
    now = datetime(2026, 7, 15, tzinfo=UTC)
    base = {
        "compiler_version": tg.COMPILER_VERSION,
        "execution_id": "run-01",
        "graph_id": "graph-01",
        "version_id": "version-01",
        "content_hash": "sha256:abc",
        "issue_time": now,
        "started_at": now,
        "finished_at": now,
    }

    with pytest.raises(ValidationError, match="require error"):
        tg.ExecutionResult(**base, status="failed")
    with pytest.raises(ValidationError, match="cannot carry error"):
        tg.ExecutionResult(**base, status="succeeded", error="unexpected")
    with pytest.raises(ValidationError, match="must not precede"):
        tg.ExecutionResult(
            **{**base, "finished_at": now - timedelta(seconds=1)},
            status="succeeded",
        )
    with pytest.raises(ValidationError):
        tg.ExecutionContext(
            execution_id="run-01",
            graph_id="graph-01",
            version_id="version-01",
            content_hash="sha256:abc",
            issue_time=datetime(2026, 7, 15),
        )
