import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import twingraph as tg
from pydantic import ValidationError

_GOLDEN_PATH = Path(__file__).parent / "fixtures" / "runtime-contracts-0.1.json"


def _runtime_contract_golden():
    issue_time = datetime(2026, 1, 1, tzinfo=UTC)
    graph_hash = "sha256:" + "b" * 64
    plan = tg.ExecutablePlan(
        graph_id="graph-01",
        version_id="version-01",
        content_hash=graph_hash,
    )
    context = tg.ExecutionContext(
        execution_id="run-01",
        graph_id=plan.graph_id,
        version_id=plan.version_id,
        content_hash=plan.content_hash,
        issue_time=issue_time,
        trace_id="trace-01",
        metadata={"mode": "shadow"},
    )
    result = tg.ExecutionResult(
        compiler_version=plan.compiler_version,
        plan_hash=plan.plan_hash,
        execution_id=context.execution_id,
        graph_id=plan.graph_id,
        version_id=plan.version_id,
        content_hash=plan.content_hash,
        issue_time=issue_time,
        started_at=issue_time,
        finished_at=issue_time + timedelta(seconds=1),
        status="succeeded",
        outputs={"recommendation": "hold"},
        runtime_version="example-runtime/1.0.0",
        implementation_versions={},
        output_artifacts=[
            tg.ArtifactRef(
                uri="s3://example/results/run-01.json",
                media_type="application/json",
                content_hash="sha256:" + "c" * 64,
            )
        ],
    )
    return {
        "context": context.model_dump(mode="json", exclude_none=True),
        "plan": plan.to_wire(),
        "result": result.to_wire(),
    }


def test_runtime_wire_contract_matches_golden_fixture():
    assert _runtime_contract_golden() == json.loads(_GOLDEN_PATH.read_text())


def test_python_component_callable_contract_can_be_invoked():
    def component(*, inputs, params, context):
        return {"dispatch": inputs["price"] * params["scale"]}

    context = tg.ExecutionContext(
        execution_id="run-01",
        graph_id="graph-01",
        version_id="version-01",
        content_hash="sha256:abc",
        issue_time=datetime(2026, 7, 15, tzinfo=UTC),
    )

    typed_component: tg.PythonComponentCallable = component
    assert typed_component(inputs={"price": 5}, params={"scale": 2}, context=context) == {
        "dispatch": 10
    }
    with pytest.raises(ValidationError):
        context.graph_id = "other"


def test_execution_result_wire_round_trip():
    started = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    result = tg.ExecutionResult(
        compiler_version=tg.COMPILER_VERSION,
        plan_hash="sha256:" + "a" * 64,
        execution_id="run-01",
        graph_id="graph-01",
        version_id="version-01",
        content_hash="sha256:abc",
        issue_time=started,
        started_at=started,
        finished_at=started + timedelta(seconds=3),
        status="succeeded",
        outputs={"dispatch_mw": [1.0, 2.0]},
        runtime_version="runtime/1.0.0",
        implementation_versions={"mb_dispatch": "1.2.3"},
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
    assert payload["plan_hash"] == "sha256:" + "a" * 64
    assert payload["issue_time"] == "2026-07-15T12:00:00Z"
    assert tg.ExecutionResult.from_wire(payload) == result

    payload["result_schema_version"] = "twingraph-execution-result/99"
    with pytest.raises(ValidationError):
        tg.ExecutionResult.from_wire(payload)


@pytest.mark.parametrize("bad_value", [object(), float("nan"), float("inf")])
def test_execution_result_rejects_non_json_outputs(bad_value):
    now = datetime(2026, 7, 15, tzinfo=UTC)

    with pytest.raises(ValidationError):
        tg.ExecutionResult(
            compiler_version=tg.COMPILER_VERSION,
            plan_hash="sha256:" + "a" * 64,
            execution_id="run-01",
            graph_id="graph-01",
            version_id="version-01",
            content_hash="sha256:abc",
            issue_time=now,
            started_at=now,
            finished_at=now,
            status="succeeded",
            outputs={"not_wire_safe": bad_value},
        )


def test_execution_result_enforces_outcome_and_time_invariants():
    now = datetime(2026, 7, 15, tzinfo=UTC)
    base = {
        "compiler_version": tg.COMPILER_VERSION,
        "plan_hash": "sha256:" + "a" * 64,
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
