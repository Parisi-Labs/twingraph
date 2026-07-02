"""Multi-twin composition (spec §9.14) — merge N atomic twins into one composite.

``compose(twins, …)`` is a PURE function: it merges the ten primitive lists of
several atomic ``TwinGraph``s into one composite draft, mints a fresh version
lineage (recording each component in ``provenance.composed_from``), appends any
``cross_relations`` (cross-twin edges), and returns a ``CompositionReport``.

It does NO graph validation beyond globally-unique-id handling + pydantic
construction — correctness (dangling refs, units, type resolution, leakage) is
the COMPILER's job, run on the composite afterwards via the unchanged
``compile_graph``. This keeps the "compose vs compile" seam clean: §9.14 says
composition "produces a new graph version and a composition report"; it is the
recompile that certifies the result.

ID policy (§9.14 "IDs are globally unique"):
  * ``reject`` (default) — if any id appears in >=1 twin, raise
    ``CompositionError`` listing the colliding ids and the twins they appear in.
    The demo/golden path uses disjoint ids + reject.
  * ``qualify`` — deterministically prefix EVERY id of a colliding twin with its
    namespace leaf and rewrite every reference field (an explicit allowlist:
    relation/variable/action/binding endpoints, model-binding ``entity:``
    payloads, constraint expression idents, objective ``var:``/``measure_ref``,
    evidence/var ``evidence_refs``/``required_for``). Covered by an isolated
    test; never on the demo path.

stdlib + pydantic only.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .document import TwinGraph
from .errors import CompositionError
from .ids import new_ulid
from .metis_expr import ExpressionParseError, extract_references
from .primitives import FOREIGN_MODEL_KINDS, Relation
from .units import units_compatible

# The ten primitive list attributes, in canonical order.
_PRIMITIVE_LISTS = (
    "entities",
    "relations",
    "variables",
    "data_bindings",
    "model_bindings",
    "actions",
    "constraints",
    "objectives",
    "validators",
    "evidence",
)


class CompositionReport(BaseModel):
    """The §9.14 composition report (a compile-time-adjacent artifact)."""

    model_config = ConfigDict(extra="forbid")

    composite_graph_id: str
    composite_version_id: str
    component_graphs: list[dict[str, str]] = Field(default_factory=list)
    id_collisions: list[str] = Field(default_factory=list)
    qualified_ids: dict[str, str] = Field(default_factory=dict)
    cross_relations: list[str] = Field(default_factory=list)
    merged_counts: dict[str, int] = Field(default_factory=dict)
    unsupported_regions: list[str] = Field(default_factory=list)
    interface_conflicts: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Id collection / collision detection
# ---------------------------------------------------------------------------
def _twin_ids(twin: TwinGraph) -> set[str]:
    out: set[str] = set()
    for attr in _PRIMITIVE_LISTS:
        for item in getattr(twin, attr):
            out.add(item.id)
    return out


def _detect_collisions(twins: list[TwinGraph]) -> dict[str, list[int]]:
    """Map colliding id -> list of (0-based) twin indices it appears in."""
    seen: dict[str, list[int]] = {}
    for idx, twin in enumerate(twins):
        for ident in _twin_ids(twin):
            seen.setdefault(ident, []).append(idx)
    return {ident: idxs for ident, idxs in seen.items() if len(idxs) > 1}


def _namespace_leaf(twin: TwinGraph) -> str:
    leaf = (twin.namespace or "twin").rsplit(".", 1)[-1]
    return leaf or "twin"


# ---------------------------------------------------------------------------
# qualify-mode reference remap (only used when id_policy='qualify')
# ---------------------------------------------------------------------------
def _qualify_twin(
    twin: TwinGraph, prefix: str, remap: dict[str, str]
) -> TwinGraph:
    """Return a copy of ``twin`` with EVERY primitive id (and every reference to
    one) prefixed by ``prefix:``. ``remap`` is the {old_id: new_id} table.
    """

    def rid(old: str) -> str:
        return remap.get(old, old)

    def maybe_prefixed_ref(ref: str) -> str:
        """``entity:<id>`` / ``var:<id>`` payloads — rewrite the trailing id."""
        for tag in ("entity:", "var:", "property:", "metric:"):
            if ref.startswith(tag):
                head, body = ref.split(":", 1)
                if tag in ("property:", "metric:"):
                    return ref  # not an id reference
                return f"{head}:{rid(body)}"
        return ref

    def remap_expression(expr_value: str) -> str:
        try:
            refs = extract_references(expr_value)
        except ExpressionParseError:
            return expr_value
        out = expr_value
        # Replace longest idents first to avoid partial-substring clobbering.
        idents = sorted(
            {r.split(":", 1)[1] if r.startswith("var:") else r for r in refs},
            key=len,
            reverse=True,
        )
        for ident in idents:
            if ident in remap:
                out = _replace_ident(out, ident, remap[ident])
        return out

    d = twin.model_dump(mode="json", by_alias=True)

    for e in d.get("entities", []):
        e["id"] = rid(e["id"])
        for p in (e.get("ports") or {}).values():
            if p.get("variable_id"):
                p["variable_id"] = rid(p["variable_id"])
    for r in d.get("relations", []):
        r["id"] = rid(r["id"])
        r["source_entity_id"] = rid(r["source_entity_id"])
        r["target_entity_id"] = rid(r["target_entity_id"])
    for v in d.get("variables", []):
        v["id"] = rid(v["id"])
        v["owner_ref"] = rid(v["owner_ref"])
        if v.get("required_for"):
            v["required_for"] = [rid(x) for x in v["required_for"]]
    for b in d.get("data_bindings", []):
        b["id"] = rid(b["id"])
        b["variable_id"] = rid(b["variable_id"])
    for m in d.get("model_bindings", []):
        m["id"] = rid(m["id"])
        if m.get("scope_ref"):
            m["scope_ref"] = rid(m["scope_ref"])
        m["inputs"] = {k: maybe_prefixed_ref(rid(val)) for k, val in m.get("inputs", {}).items()}
        m["outputs"] = {k: rid(val) for k, val in m.get("outputs", {}).items()}
    for a in d.get("actions", []):
        a["id"] = rid(a["id"])
        a["target_entity_id"] = rid(a["target_entity_id"])
        if a.get("controller_entity_id"):
            a["controller_entity_id"] = rid(a["controller_entity_id"])
        if a.get("control_variables"):
            a["control_variables"] = [rid(x) for x in a["control_variables"]]
        if a.get("mutual_exclusion"):
            a["mutual_exclusion"] = [[rid(x) for x in grp] for grp in a["mutual_exclusion"]]
    for c in d.get("constraints", []):
        c["id"] = rid(c["id"])
        if c.get("scope_ref"):
            c["scope_ref"] = rid(c["scope_ref"])
        if c.get("expression") and c["expression"].get("value"):
            c["expression"]["value"] = remap_expression(c["expression"]["value"])
        if c.get("evidence_refs"):
            c["evidence_refs"] = [rid(x) for x in c["evidence_refs"]]
    for o in d.get("objectives", []):
        o["id"] = rid(o["id"])
        for term in o.get("terms", []):
            term["id"] = rid(term["id"])
            term["measure_ref"] = maybe_prefixed_ref(term["measure_ref"])
    for val in d.get("validators", []):
        val["id"] = rid(val["id"])
        if val.get("scope_ref"):
            val["scope_ref"] = rid(val["scope_ref"])
    for ev in d.get("evidence", []):
        ev["id"] = rid(ev["id"])

    return TwinGraph.model_validate(d)


def _replace_ident(expr: str, old: str, new: str) -> str:
    """Replace whole-token ``old`` with ``new`` in an expression string."""
    out: list[str] = []
    i = 0
    n = len(old)

    def is_ident_char(ch: str) -> bool:
        return ch.isalnum() or ch in "_."

    while i < len(expr):
        if (
            expr[i : i + n] == old
            and (i == 0 or not is_ident_char(expr[i - 1]))
            and (i + n >= len(expr) or not is_ident_char(expr[i + n]))
        ):
            out.append(new)
            i += n
        else:
            out.append(expr[i])
            i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# compose
# ---------------------------------------------------------------------------
def compose(
    twins: list[TwinGraph],
    *,
    name: str,
    created_by: str,
    namespace: str = "metis.demo",
    cross_relations: list[Relation] | None = None,
    id_policy: str = "reject",
    workspace_id: str | None = None,
    created_at: datetime | None = None,
    mint_id: Callable[[], str] = new_ulid,
) -> tuple[TwinGraph, CompositionReport]:
    """Merge ``twins`` into one composite draft (§9.14). Pure.

    Returns ``(composite_graph, report)``. The composite COMPILES via the
    unchanged ``compile_graph``; correctness is the compiler's job.
    """
    if not twins:
        raise CompositionError("compose requires at least one twin")
    if id_policy not in ("reject", "qualify"):
        raise CompositionError(f"unknown id_policy '{id_policy}'")

    collisions = _detect_collisions(twins)
    qualified_ids: dict[str, str] = {}
    working = list(twins)

    if collisions:
        if id_policy == "reject":
            detail = "; ".join(
                f"'{ident}' in twins {sorted(idxs)}"
                for ident, idxs in sorted(collisions.items())
            )
            raise CompositionError(
                f"id collision under id_policy='reject': {detail}. "
                "Supply disjoint ids or use id_policy='qualify'."
            )
        # qualify: for each colliding twin, prefix ALL of its ids.
        colliding_twin_idxs = sorted({i for idxs in collisions.values() for i in idxs})
        working = []
        for idx, twin in enumerate(twins):
            if idx in colliding_twin_idxs:
                prefix = _namespace_leaf(twin)
                remap = {old: f"{prefix}:{old}" for old in _twin_ids(twin)}
                qualified_ids.update(remap)
                working.append(_qualify_twin(twin, prefix, remap))
            else:
                working.append(twin)

    # Merge the ten primitive lists.
    merged: dict[str, list[Any]] = {attr: [] for attr in _PRIMITIVE_LISTS}
    for twin in working:
        for attr in _PRIMITIVE_LISTS:
            merged[attr].extend(getattr(twin, attr))

    # Append cross-twin relations.
    xrels = list(cross_relations or [])
    merged["relations"].extend(xrels)

    # Shallow-merge extensions; conflicts namespaced under extensions["composed"].
    extensions: dict[str, Any] = {}
    composed_conflicts: dict[str, Any] = {}
    for twin in working:
        ns = _namespace_leaf(twin)
        for k, v in (twin.extensions or {}).items():
            if k in extensions and extensions[k] != v:
                composed_conflicts.setdefault(ns, {})[k] = v
            else:
                extensions.setdefault(k, v)
    if composed_conflicts:
        extensions["composed"] = composed_conflicts

    # Lineage: a NEW draft version. N parents cannot fit parent_version_id, so
    # provenance.composed_from records every component (§9.14).
    composed_from = [
        {"graph_id": t.graph_id, "version_id": t.version_id} for t in twins
    ]
    graph_id = mint_id()
    version_id = mint_id()

    composite = TwinGraph(
        graph_id=graph_id,
        version_id=version_id,
        workspace_id=workspace_id or twins[0].workspace_id,
        name=name,
        namespace=namespace,
        status="draft",
        created_at=created_at or datetime.now(UTC),
        created_by=created_by,
        parent_version_id=None,
        provenance={"composed_from": composed_from},
        entities=merged["entities"],
        relations=merged["relations"],
        variables=merged["variables"],
        data_bindings=merged["data_bindings"],
        model_bindings=merged["model_bindings"],
        actions=merged["actions"],
        constraints=merged["constraints"],
        objectives=merged["objectives"],
        validators=merged["validators"],
        evidence=merged["evidence"],
        extensions=extensions,
    )

    # Foreign-reference components carried into the composite are flagged as
    # unsupported regions (§9.14: unsupported regions must be marked); the
    # composite still compiles.
    unsupported = [
        m.id for m in composite.model_bindings if m.kind in FOREIGN_MODEL_KINDS
    ]
    interface_conflicts = _cross_relation_interface_conflicts(composite, xrels)

    report = CompositionReport(
        composite_graph_id=graph_id,
        composite_version_id=version_id,
        component_graphs=[
            {"graph_id": t.graph_id, "version_id": t.version_id, "name": t.name}
            for t in twins
        ],
        id_collisions=sorted(collisions),
        qualified_ids=qualified_ids,
        cross_relations=[r.id for r in xrels],
        merged_counts={attr: len(merged[attr]) for attr in _PRIMITIVE_LISTS},
        unsupported_regions=unsupported,
        interface_conflicts=interface_conflicts,
    )
    return composite, report


def _cross_relation_interface_conflicts(
    composite: TwinGraph, cross_relations: list[Relation]
) -> list[dict[str, Any]]:
    """Cheap compose-time interface checks for cross-twin relations.

    Full correctness remains the compiler's job. These checks are intentionally
    limited to facts present on the composed document itself: endpoint existence,
    exposed entity-level ports, port direction, and endpoint unit compatibility.
    """

    entities = {e.id: e for e in composite.entities}
    conflicts: list[dict[str, Any]] = []

    for rel in cross_relations:
        source = entities.get(rel.source_entity_id)
        target = entities.get(rel.target_entity_id)
        if source is None:
            conflicts.append(
                {"relation": rel.id, "kind": "missing_source", "entity": rel.source_entity_id}
            )
            continue
        if target is None:
            conflicts.append(
                {"relation": rel.id, "kind": "missing_target", "entity": rel.target_entity_id}
            )
            continue

        source_port = None
        target_port = None
        if rel.source_port:
            source_port = source.ports.get(rel.source_port)
            if source.ports and source_port is None:
                conflicts.append(
                    {
                        "relation": rel.id,
                        "kind": "missing_source_port",
                        "entity": source.id,
                        "port": rel.source_port,
                    }
                )
        if rel.target_port:
            target_port = target.ports.get(rel.target_port)
            if target.ports and target_port is None:
                conflicts.append(
                    {
                        "relation": rel.id,
                        "kind": "missing_target_port",
                        "entity": target.id,
                        "port": rel.target_port,
                    }
                )

        if source_port and source_port.direction == "input":
            conflicts.append(
                {
                    "relation": rel.id,
                    "kind": "source_port_input_only",
                    "entity": source.id,
                    "port": rel.source_port,
                }
            )
        if target_port and target_port.direction == "output":
            conflicts.append(
                {
                    "relation": rel.id,
                    "kind": "target_port_output_only",
                    "entity": target.id,
                    "port": rel.target_port,
                }
            )

        if (
            source_port
            and target_port
            and source_port.unit
            and target_port.unit
            and not units_compatible(source_port.unit, target_port.unit)
        ):
            conflicts.append(
                {
                    "relation": rel.id,
                    "kind": "port_unit_mismatch",
                    "source_entity": source.id,
                    "source_port": rel.source_port,
                    "source_unit": source_port.unit,
                    "target_entity": target.id,
                    "target_port": rel.target_port,
                    "target_unit": target_port.unit,
                }
            )

    return conflicts


__all__ = [
    "CompositionReport",
    "compose",
]
