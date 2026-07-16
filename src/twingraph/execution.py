"""Runtime-neutral contracts for consuming an :class:`ExecutablePlan`.

TwinGraph does not execute plans. This module only fixes the portable boundary
between the data-only plan and an application-owned runtime: callable shape,
trusted run context, artifact references, and auditable result envelopes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Protocol, Self, runtime_checkable

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, model_validator

from .compile import PLAN_SCHEMA_VERSION
from .errors import Diagnostic

EXECUTION_RESULT_SCHEMA_VERSION = "twingraph-execution-result/0.1"


class ArtifactRef(BaseModel):
    """Reference to an input or output artifact kept outside the result envelope."""

    model_config = ConfigDict(extra="forbid")

    uri: str
    media_type: str | None = None
    content_hash: str | None = None


class ExecutionContext(BaseModel):
    """Trusted, run-level context supplied to every native component callable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_id: str
    graph_id: str
    version_id: str
    content_hash: str
    issue_time: AwareDatetime
    trace_id: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


@runtime_checkable
class ComponentCallable(Protocol):
    """Invocation contract for a natively executable resolved component.

    Runtimes call components with keyword arguments. ``inputs`` is keyed by the
    component's declared input ports, ``params`` contains its compiled parameter
    values, and the return mapping is keyed by declared output ports.
    """

    def __call__(
        self,
        *,
        inputs: Mapping[str, Any],
        params: Mapping[str, Any],
        context: ExecutionContext,
    ) -> Mapping[str, Any]: ...


class ExecutionResult(BaseModel):
    """Portable, auditable envelope emitted by an application-owned runtime."""

    model_config = ConfigDict(extra="forbid")

    result_schema_version: Literal["twingraph-execution-result/0.1"] = (
        EXECUTION_RESULT_SCHEMA_VERSION
    )
    plan_schema_version: Literal["twingraph-plan/0.1"] = PLAN_SCHEMA_VERSION
    compiler_version: str
    execution_id: str
    graph_id: str
    version_id: str
    content_hash: str
    issue_time: AwareDatetime
    started_at: AwareDatetime
    finished_at: AwareDatetime
    status: Literal["succeeded", "failed"]
    outputs: dict[str, JsonValue] = Field(default_factory=dict)
    model_versions: dict[str, str] = Field(default_factory=dict)
    input_artifacts: list[ArtifactRef] = Field(default_factory=list)
    output_artifacts: list[ArtifactRef] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    error: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must not precede started_at")
        if self.status == "failed" and not self.error:
            raise ValueError("failed execution results require error")
        if self.status == "succeeded" and self.error is not None:
            raise ValueError("succeeded execution results cannot carry error")
        return self

    def to_wire(self) -> dict[str, Any]:
        """Return the stable, JSON-compatible execution-result envelope."""
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> ExecutionResult:
        """Validate and reconstruct an execution result received from a runtime."""
        return cls.model_validate(payload)


__all__ = [
    "EXECUTION_RESULT_SCHEMA_VERSION",
    "ArtifactRef",
    "ComponentCallable",
    "ExecutionContext",
    "ExecutionResult",
]
