---
name: twingraph-create
description: Use this skill when creating a new TwinGraph JSON document or Python-authored TwinGraph for a facility, power asset, data center, warehouse, factory, port, logistics network, or other digital twin. Use it when the user asks to model assets, build a draft twin from specs/PDFs/notes, define entities, relations, ports, variables, data/model bindings, constraints, objectives, evidence, or produce a valid `.twingraph.json` artifact.
---

# TwinGraph Create

Create draft TwinGraph documents that are explicit, typed, auditable, and ready
for compile validation.

## Workflow

1. Read the local API surface before authoring if working in the repo:
   `twingraph/src/twingraph/primitives.py`, `registry.py`, and `SPEC.md`.
   Use `README.md` for quick examples.
2. Identify the twin boundary first: one facility/site/system per atomic twin.
   Use a stable namespace such as `metis.demo.site_a` or an adopter namespace.
3. Create a draft graph with `TwinGraph.new(...)`; keep `status="draft"` until
   validation passes. Do not hand-author IDs that collide across twins.
4. Add entities for physical/logical assets. Prefer built-in type packs:
   power assets first, then data-center and operations types when relevant.
5. Add concrete `Entity.ports` for any interface that another twin or subsystem
   may connect to. Use local port IDs like `poi_34_5kv`, `truck_in`, or
   `cooling_supply`; set `kind`, `unit`, `direction`, and `variable_id` when a
   variable measures that interface.
6. Add relations with `source_entity_id`, `target_entity_id`, and ports when the
   endpoints expose ports. Put capacity, loss, distance, throughput, or thermal
   limits on relation `properties` with explicit units.
7. Add variables owned by the entity or relation they describe. Use roles
   consistently: `state`, `control`, `exogenous`, `observed`, `derived`,
   `parameter`, or `outcome`.
8. Add evidence/provenance for inferred facts. Do not invent certainty: use
   `confirmation_state="inferred"` or `"proposed"` and `confidence < 1.0` for
   facts extracted from incomplete specs.
9. Add data bindings, model bindings, actions, constraints, objectives, and
   validators only when they are known enough to be meaningful. It is better to
   create a structurally valid descriptive twin than a fake executable twin.
10. Validate before delivery. At minimum parse with `TwinGraph.model_validate`
    or `TwinGraph.load`; when a model registry exists, run `compile_graph`.

## Authoring Rules

- Keep TwinGraph open-core clean: references to executable models use
  `registry://...` model refs; do not import application runtime code into
  `twingraph`.
- Use quantity objects for units when there is any chance of ambiguity:
  `{"value": 20.0, "unit": "MW"}`.
- Use relation verbs from the built-in relation pack when possible:
  `connected_to`, `feeds_into`, `supplies`, `transports_to`, `ships_to`,
  `cools`, `settles_at`, `constrained_by`.
- Keep independent twins independent. A solar plant twin should expose a POI;
  a grid twin should expose substation/line ports; composition creates the
  cross-relations later.
- If the user provides PDFs/spec sheets, preserve extracted claims as evidence
  and mark uncertain fields as proposed until confirmed.

## Minimal Pattern

```python
import twingraph as tg

g = tg.TwinGraph.new(
    "Solar_A",
    namespace="metis.demo.solar_a",
    created_by="agent",
)
g.entities.append(
    tg.Entity(
        id="solar",
        type_ref="metis.energy.SolarArray@1",
        name="Solar array",
        properties={"capacity_mw": {"value": 20.0, "unit": "MW"}},
        ports={
            "ac_out": tg.EntityPort(kind="ac_power", unit="MW", direction="output")
        },
    )
)
g.variables.append(
    tg.Variable(id="generation", owner_ref="solar", name="generation", role="observed", unit="MW")
)
```
