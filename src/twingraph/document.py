"""TwinGraph document envelope (spec §9.2).

The root, versioned, hashable container for one operating system. Carries the
full required envelope, the ten primitive lists (including the four added in
0.1: data_bindings, model_bindings, evidence — plus version_id/workspace_id),
and the stable adopter surface (hashing, lineage, lookup, activation/freeze).

stdlib + pydantic only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from .canonical import SCHEMA_VERSION, content_hash, hash_input
from .compat import normalize_legacy_document
from .errors import FrozenGraphError
from .ids import new_ulid
from .primitives import (
    Action,
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

# Documented single-tenant sentinel for OSS adopters.
SENTINEL_WORKSPACE = "00000000000000000000000000"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TwinGraph(BaseModel):
    """A versioned, hashable representation of one operating system (§9.2)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal["twingraph/0.1"] = SCHEMA_VERSION
    graph_id: str
    version_id: str
    workspace_id: str
    name: str
    namespace: str = "metis.demo"
    status: Literal["draft", "active", "deprecated"] = "draft"
    created_at: datetime
    created_by: str
    parent_version_id: str | None = None
    content_hash: str | None = None  # EXCLUDED from its own hash input
    provenance: dict[str, Any] = Field(default_factory=dict)  # OPEN map

    entities: list[Entity] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    variables: list[Variable] = Field(default_factory=list)
    data_bindings: list[DataBinding] = Field(default_factory=list)
    model_bindings: list[ModelBinding] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    objectives: list[Objective] = Field(default_factory=list)
    validators: list[Validator] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    extensions: dict[str, Any] = Field(default_factory=dict)

    _frozen: bool = PrivateAttr(default=False)

    SENTINEL_WORKSPACE: ClassVar[str] = SENTINEL_WORKSPACE

    # ----- construction ----------------------------------------------------
    @classmethod
    def new(
        cls,
        name: str,
        *,
        namespace: str = "metis.demo",
        created_by: str,
        workspace_id: str = SENTINEL_WORKSPACE,
        created_at: datetime | None = None,
    ) -> TwinGraph:
        """Mint a fresh draft graph (graph_id + version_id generated)."""
        return cls(
            graph_id=new_ulid(),
            version_id=new_ulid(),
            workspace_id=workspace_id,
            name=name,
            namespace=namespace,
            created_at=created_at or _utcnow(),
            created_by=created_by,
        )

    @classmethod
    def load(cls, doc: dict[str, Any]) -> TwinGraph:
        """Validate a document dict, folding legacy field spellings first.

        Immutability-after-activation (§9.2) is enforced on load, not only via
        the in-process ``.activate()`` path: a document loaded with
        ``status == 'active'`` MUST carry a ``content_hash`` that matches its
        computed identity, and is returned frozen. This closes the gap where a
        loaded active document was freely mutable and could ship without the
        identity hash its status implies.
        """
        graph = cls.model_validate(normalize_legacy_document(doc))
        if graph.status == "active":
            computed = graph.compute_content_hash()
            if graph.content_hash is None:
                raise FrozenGraphError(
                    "loaded document is status='active' but carries no "
                    "content_hash — an active version must record its identity "
                    f"(expected {computed})"
                )
            if graph.content_hash != computed:
                raise FrozenGraphError(
                    f"loaded active document content_hash {graph.content_hash} "
                    f"does not match computed {computed}"
                )
            object.__setattr__(graph, "_frozen", True)
        return graph

    # ----- hashing ---------------------------------------------------------
    def compute_content_hash(self) -> str:
        """Semantic-identity hash (excludes content_hash/created_at/version_id)."""
        return content_hash(hash_input(self.model_dump(mode="json")))

    def with_content_hash(self) -> TwinGraph:
        """Return a copy with ``content_hash`` set to the computed value."""
        copy_ = self.model_copy(deep=True)
        object.__setattr__(copy_, "content_hash", self.compute_content_hash())
        return copy_

    # ----- lifecycle -------------------------------------------------------
    def is_active(self) -> bool:
        return self.status == "active"

    def is_frozen(self) -> bool:
        return self._frozen

    def activate(self) -> TwinGraph:
        """One-way freeze: status -> active; later in-place mutation raises."""
        self.status = "active"
        if self.content_hash is None:
            self.content_hash = self.compute_content_hash()
        object.__setattr__(self, "_frozen", True)
        return self

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_frozen", False) and name != "_frozen":
            raise FrozenGraphError(
                f"cannot mutate field '{name}': graph is active/frozen — "
                "fork a new draft via apply_patch (§10.5)"
            )
        super().__setattr__(name, value)

    # ----- lookup ----------------------------------------------------------
    def entity(self, entity_id: str) -> Entity:
        for e in self.entities:
            if e.id == entity_id:
                return e
        raise KeyError(entity_id)

    def variable(self, variable_id: str) -> Variable:
        for v in self.variables:
            if v.id == variable_id:
                return v
        raise KeyError(variable_id)

    def binding(self, binding_id: str) -> DataBinding:
        for b in self.data_bindings:
            if b.id == binding_id:
                return b
        raise KeyError(binding_id)

    def by_id(self, ident: str) -> Any:
        """Return any primitive in the document by id (KeyError on miss)."""
        for seq in (
            self.entities,
            self.relations,
            self.variables,
            self.data_bindings,
            self.model_bindings,
            self.actions,
            self.constraints,
            self.objectives,
            self.validators,
            self.evidence,
        ):
            for item in seq:
                if item.id == ident:
                    return item
        raise KeyError(ident)

    def lineage(self) -> dict[str, str | None]:
        return {
            "graph_id": self.graph_id,
            "version_id": self.version_id,
            "parent_version_id": self.parent_version_id,
        }
