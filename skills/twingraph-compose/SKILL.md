---
name: twingraph-compose
description: Use this skill when composing, merging, or federating multiple independent TwinGraph digital twins into a larger system. Use it for connecting solar plants to grids, batteries to markets, data centers to power/cooling systems, factories to warehouses/ports, resolving ID collisions, adding cross-relations, validating entity ports/interfaces, and producing a composite twin.
---

# TwinGraph Compose

Compose independent twins through explicit typed interfaces. Composition should
preserve each component twin's boundary and then add cross-twin relations.

## Workflow

1. Load each input twin as its own `TwinGraph`. Confirm it represents a coherent
   atomic boundary such as a plant, substation, data center, factory, warehouse,
   port, or market node.
2. Inspect exposed `Entity.ports`. Cross-twin relations should connect concrete
   entity ports whenever possible, not vague entity-to-entity edges.
3. Create cross-relations with `Relation(type_ref=..., source_entity_id=...,
   target_entity_id=..., source_port=..., target_port=...)`. Put interface
   capacities, losses, distances, throughput, or transit time on relation
   `properties` with explicit units.
4. Call `compose(twins, name=..., created_by=..., cross_relations=...)`.
   Use `id_policy="reject"` by default. Use `id_policy="qualify"` only when
   preserving both colliding twins is intentional.
5. Inspect the `CompositionReport`: `id_collisions`, `qualified_ids`,
   `cross_relations`, `merged_counts`, and `interface_conflicts`.
6. Compile the composite with the runtime's registries. Composition alone does
   not certify the graph as valid or executable.

## Interface Rules

- Source ports cannot be `input`; target ports cannot be `output`.
- Units on both endpoint ports must be compatible.
- Entity-level port IDs are local names; `EntityPort.kind` should align with
  the endpoint type's port vocabulary when the type pack declares ports.
- Cross-twin relations should reference stable component IDs. If a component
  might be reused in a larger federation, avoid generic IDs like `node` or
  `line` unless namespaces or qualify mode make them unambiguous.
- Keep provenance: `compose` records `provenance.composed_from`; do not erase
  component graph/version identity.

## Pattern

```python
import twingraph as tg

xrel = tg.Relation(
    id="plant_a_poi_to_sub",
    type_ref="feeds_into",
    source_entity_id="plant_a_poi",
    target_entity_id="collector_sub",
    source_port="export",
    target_port="plant_a",
    properties={"capacity_mw": {"value": 20.0, "unit": "MW"}},
)

composite, report = tg.compose(
    [plant_a, plant_b, grid],
    name="plants-plus-grid",
    created_by="agent",
    cross_relations=[xrel],
    id_policy="reject",
)
assert not report.interface_conflicts
```
