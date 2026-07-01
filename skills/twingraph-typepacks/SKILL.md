---
name: twingraph-typepacks
description: Use this skill when extending TwinGraph's graph language with new TypePacks, TypeDefs, relation vocabulary, unit aliases, port kinds, required properties, required variables, or domain primitives. Use it for adding support for new asset classes, power equipment, data-center components, factories, ports, logistics systems, supply-chain nodes, or adopter-specific domains without weakening validation.
---

# TwinGraph Typepacks

Extend the graph language deliberately. A type pack is part of the contract that
future twins and agents will rely on, so prefer narrow, well-named primitives
with clear units and ports.

## Workflow

1. Inspect current vocabulary in `twingraph/src/twingraph/registry.py` and unit
   support in `twingraph/src/twingraph/units.py`.
2. Decide whether the request needs:
   a new entity `TypeDef`, a relation verb, optional/required properties, a
   variable requirement, ports, unit aliases, or only documentation/examples.
3. Reuse existing relation verbs and units when semantically correct. Add new
   vocabulary only when reuse would misrepresent the domain.
4. Add types through a `TypePack` so adopters can build narrow registries with
   `build_type_registry((RELATION_TYPE_PACK, SOME_TYPE_PACK))`.
5. For entity types, define:
   `type_ref`, `kind="entity"`, `title`, required/optional `PropSpec`s,
   required/optional `VarSpec`s, and `ports` when relations should use typed
   interfaces.
6. For relation types, define:
   `type_ref`, `kind="relation"`, `title`, endpoint-relevant `ports` if useful,
   and relation property specs such as capacity, distance, loss, or throughput.
7. Add unit support before using a unit in a `PropSpec` or `VarSpec`. Bump
   `UNIT_TABLE_VERSION` when the public unit vocabulary changes.
8. Export new type packs from `twingraph/src/twingraph/__init__.py` when they are
   public API.
9. Add focused tests covering registry construction and compile validation for
   required properties, variables, ports, and units.
10. Update `twingraph/README.md`, `SPEC.md`, or `CHANGELOG.md` if the public
    graph language changed.

## Design Rules

- Keep power strong. Do not make generic industrial abstractions that erase
  power-specific constraints like MW/MVA/kV, POI limits, bus/line interfaces,
  settlement nodes, fuel, storage, inverter, or transformer behavior.
- Do not overload a property with multiple meanings. Prefer `capacity_mw`,
  `thermal_limit_mw`, `nominal_voltage_kv`, `throughput_capacity_items_per_h`,
  or `payload_capacity_tonne` over vague `capacity`.
- Ports are interface kinds, not display labels. Use kinds like `ac_power`,
  `dc_power`, `hv_ac`, `lv_ac`, `bus`, `fuel`, `cooling`, `network`,
  `workload`, `inbound`, `outbound`, `truck`, `rail`, `berth`.
- Required fields should be genuinely required for a useful typed object. If
  real source material often lacks the field, make it optional and rely on
  validators/program compatibility for stricter workflows.
- Unknown adopter domains should live in separate packs, not the core built-in
  pack, unless they are broadly useful and tested.

## Validation

After changing type packs or units, run:

```bash
PYTHONPATH=src:twingraph/src pytest twingraph/tests -q
PYTHONPATH=src:twingraph/src python -m twingraph._schema_tool > /tmp/twingraph.schema.json
```

If pydantic model shape changed, regenerate the committed schema. If only
registry metadata changed, schema regeneration may not be necessary.
