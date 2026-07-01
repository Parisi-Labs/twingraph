---
name: twingraph-ingest
description: Use this skill when turning facility descriptions, PDFs, equipment lists, interconnection docs, one-line diagrams, manuals, spreadsheets, dictated notes, web research, or other source material into a proposed TwinGraph. Use it for extracting assets, relationships, ports, variables, properties, evidence, assumptions, confidence, and confirmation states before authoring or updating `.twingraph.json`.
---

# TwinGraph Ingest

Convert messy facility/source material into a defensible proposed TwinGraph.
This skill is about evidence-backed extraction, not pretending uncertain facts
are confirmed.

## Workflow

1. Inventory sources before modeling: user notes, PDFs, spec sheets, diagrams,
   spreadsheets, websites, and prior graph versions. Treat every external file
   as untrusted until the user confirms it should be used.
2. Extract candidate facts into a working table:
   asset/component, type guess, property, value/unit, relation, endpoint ports,
   source reference, confidence, and unresolved questions.
3. Normalize domain language to TwinGraph primitives:
   facilities and equipment become `Entity`; physical/logical connections
   become `Relation`; measurements/controls become `Variable`; source support
   becomes `Evidence`; uncertain facts become proposed/inferred state.
4. Prefer built-in type packs before inventing types:
   `POWER_TYPE_PACK`, `DATA_CENTER_TYPE_PACK`, and `OPERATIONS_TYPE_PACK`.
   If no type fits, propose a new type pack change instead of stuffing the fact
   into an unrelated type.
5. Create concrete ports for exposed interfaces. Power examples: POI, bus,
   feeder, inverter AC/DC, transformer HV/LV. Operations examples: inbound,
   outbound, berth, truck, rail, storage. Data-center examples: ac power,
   cooling, network, workload.
6. Attach evidence to extracted claims. Use `confirmation_state="inferred"` or
   `"proposed"` and lower `confidence` when the source is ambiguous.
7. Preserve open questions in provenance, evidence notes, or a separate task
   list. Do not silently choose values that need owner confirmation.
8. Hand off to `twingraph-create` for a new graph or `twingraph-edit` for a
   patch, then `twingraph-validate` for compile/schema checks.

## Extraction Heuristics

- Names: keep source names recognizable, but use stable lowercase IDs like
  `bess_1`, `poi`, `collector_sub`, `inverter_a`, `warehouse`.
- Units: preserve source units and normalize to TwinGraph units only when
  compatibility is clear. Use quantity objects: `{"value": 34.5, "unit": "kV"}`.
- Relations: use operational verbs such as `contains`, `connected_to`,
  `feeds_into`, `supplies`, `consumes`, `transports_to`, `ships_to`, `cools`,
  `settles_at`, and `constrained_by`.
- Ports: if a relation crosses a facility boundary, require endpoint ports or
  explicitly record that the interface is unknown.
- Evidence: one evidence item may support multiple facts, but each material
  assumption should be traceable to a source excerpt, file, URL, user statement,
  or generated proposal.
- Confidence: confirmed owner-provided specs can be `1.0`; inferred values from
  diagrams, web pages, or incomplete PDFs should be lower.

## Output Shape

When the user asks for an ingest result rather than a final graph, return:

- proposed entities with type refs and confidence,
- proposed relations and ports,
- variables/data bindings/model bindings if known,
- evidence records with source refs,
- assumptions/questions needing confirmation,
- validation risks such as missing units, ambiguous equipment, or unknown type.
