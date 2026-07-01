"""Visualize a TwinGraph as a graph diagram — pure-stdlib string emitters.

A twin is a typed graph (entities = nodes, relations = edges, variables/actions
hang off their owner). These helpers emit Mermaid or Graphviz DOT *text* — no
rendering dependency, so they stay in the dependency-clean OSS core. Any tool
(GitHub markdown, mermaid.live, Graphviz, the product UI) renders the string.
"""

from __future__ import annotations

from collections import defaultdict

_ROLE_GLYPH = {
    "state": "◆", "control": "▶", "exogenous": "○",
    "observed": "◇", "derived": "·", "outcome": "★", "parameter": "=",
}


def _entity_lines(graph):
    vars_by, acts_by = defaultdict(list), defaultdict(list)
    for v in graph.variables:
        vars_by[v.owner_ref].append(f"{_ROLE_GLYPH.get(v.role, '·')} {v.name}")
    for a in graph.actions:
        acts_by[a.controller_entity_id or a.target_entity_id].append(a.name)
    return vars_by, acts_by


def to_mermaid(graph, *, direction: str = "LR") -> str:
    """A Mermaid `graph` definition: entities (with their variables/actions) and
    the typed relations between them."""
    vars_by, acts_by = _entity_lines(graph)
    out = [f"graph {direction}"]
    for e in graph.entities:
        rows = [f"<b>{e.name}</b>", e.type_ref]
        rows += vars_by.get(e.id, [])
        rows += [f"⚙ {a}" for a in acts_by.get(e.id, [])]
        out.append(f'  {e.id}["{"<br/>".join(rows)}"]')
    for r in graph.relations:
        out.append(f"  {r.source_entity_id} -->|{r.type_ref}| {r.target_entity_id}")
    # objective + model bindings as a side note (what the twin is FOR)
    obj = graph.objectives[0].name if graph.objectives else "—"
    models = ", ".join(sorted({mb.kind for mb in graph.model_bindings})) or "—"
    out.append(f'  _meta["objective: {obj}<br/>models: {models}"]')
    out.append("  style _meta fill:#f6f6f4,stroke:#d3d1c7,color:#5f5e5a")
    return "\n".join(out)


def to_dot(graph) -> str:
    """A Graphviz DOT digraph — entities as records, relations as labeled edges."""
    out = ["digraph twin {", '  rankdir=LR;', '  node [shape=box, fontname="Helvetica"];']
    vars_by, _ = _entity_lines(graph)
    for e in graph.entities:
        vs = ("\\n" + "\\n".join(vars_by.get(e.id, []))) if vars_by.get(e.id) else ""
        out.append(f'  {e.id} [label="{e.name}\\n{e.type_ref}{vs}"];')
    for r in graph.relations:
        out.append(f'  {r.source_entity_id} -> {r.target_entity_id} [label="{r.type_ref}"];')
    out.append("}")
    return "\n".join(out)
