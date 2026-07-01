# TwinGraph 0.1 — Normative Specification

A **TwinGraph** is a canonical, hashable, versioned description of one operating
system: what exists, what state it has, how the parts connect, what can be
controlled, what constraints hold, what objectives a recurring decision
optimises, and where each fact came from. It is an *intermediate
representation* — explicit enough for humans and agents to inspect, executable
enough to bind forecasts/constraints/decision models, portable enough to
serialise as JSON and hash.

`schema_version` MUST be `"twingraph/0.1"`. The published JSON Schema
(`schema/twingraph-0.1.schema.json`, draft 2020-12) is generated from the
pydantic models and is the canonical cross-language contract.

Open-source core (Apache-2.0): **stdlib + pydantic only**. No proprietary
dependencies; the IR *references* models and types, the application *registers*
implementations.

---

## 1. Shared value types

- **ULID** (`ids.py`): 26-char Crockford-Base32 (48-bit ms time + 80 random
  bits), process-monotonic. `graph_id`/`version_id`/`workspace_id`/`patch_id`
  are minted as ULIDs when not supplied. Authoring ids (`bat`, `soc`) are also
  legal — the id pattern is permissive (`^[A-Za-z0-9_.:-]+$`). Lineage identity
  = the ULIDs; human ids are convenience.
- **Quantity** (`units.py`): `{value, unit}`. Properties accept EITHER a bare
  scalar OR a Quantity; units are enforced at **compile** against the type
  registry's declared unit, not at parse.
- **Units** (`units.py`): a hand-maintained operational UCUM **subset** for power
  and adjacent domains (`MW`, `MW.h`, `USD/MW.h`, `USD/MW`, `count`, `kV`, `MVA`,
  `MW/min`, `W/m2`, `m/s`, `degC`, `kW`, `request/s`, `TEU/h`, `item/h`,
  `tonne`, `%`, `h`, `dimensionless`, `ratio`, ISO-8601 PT-durations opaque).
  `normalize_unit` folds `MWh→MW.h`, `USD/MWh→USD/MW.h`, `$/MW` spellings to
  `USD/MW`, `probability→ratio`, `kWh→MW.h (1e-3)`, `kW→MW (1e-3)`, and common
  operational aliases. `UNIT_TABLE_VERSION` is recorded in every compile report.
  The vocabulary remains an **extensible `UnitRegistry`**: adopters needing
  narrower or extra domain units (e.g. `cycles` for a PdM twin) construct their
  own `UnitRegistry`, `register_canonical`/`register_alias` the units, and pass
  `compile_graph(unit_registry=…)`.
- **Provenance** (optional everywhere): `{source_kind, source_ref?, …}`.
- **ConfirmationState** (5): `inferred | proposed | confirmed | disputed |
  deprecated`.
- **LifecycleState** (entity): `planned | active | degraded | offline |
  retired`.

## 2. Primitives (§9.3–9.12)

| Primitive | Key fields |
|-----------|-----------|
| **Entity** | `id`, `type_ref` (`^[a-z][A-Za-z0-9_.]*@\d+$`), `name`, `lifecycle_state`, `properties` (OPEN: scalar\|Quantity), `confirmation_state` |
| **Relation** | `id`, `type_ref` (registry-resolved string, `RELATION_TYPE_REF_PATTERN`: bare verb → `metis.relation.<x>@1`, or a namespaced foreign ref; validated at **compile** → `TG_UNKNOWN_TYPE`), `source_entity_id`, `target_entity_id`, `directionality` |
| **Variable** | `id`, `owner_ref` (entity\|relation), `role` (8: state/control/exogenous/observed/derived/latent/parameter/outcome), `data_type`, `unit`, `temporal_semantics`, `bounds?`, `uncertainty?` |
| **DataBinding** | `id`, `variable_id`, `source{semantic_view, filters}`, `event_time_column` (**required**), `available_at_column?`, `value_column`, `unit`, `unit_transform?`, `grain`, `query_policy`. Root rule: `available_at_column` set **OR** `as_of_required=false` with a `conservative_availability_policy` — availability is never silently omitted (§9.6/§12.4). |
| **ModelBinding** | `id`, `kind` (executable P0 set + foreign `fmu`/`modelica_class`), `model_ref` (`^registry://…@\d+\.\d+\.\d+$`), `inputs`, `outputs`, `parameters`. References only — no code. |
| **Action** | `id`, `controller_entity_id?`, `target_entity_id`, `control_variables` (must be role=control), `bounds` (`ActionBound{min,max,min_from,max_from}`), `mutual_exclusion`, `requires_approval` |
| **Constraint** | `id`, `class` (typed kinds), EXACTLY-ONE-OF `expression{language=metis_expr/0.1, value}` **or** `evaluator_ref{pattern_ref, params}`, `enforcement.stages`, `on_violation` |
| **Objective** | `id`, `terms[]` (`{direction, measure_ref, weight}`), `aggregation{kind, risk_measure, alpha?, lambda?}` — λ is the weight on the `metric:cvar_*` term |
| **Validator** | `id`, `evaluator_ref` (registered pattern), `params`, `required` |
| **Evidence** | `id`, `kind`, `source_ref`, `claim?` |

`metis_expr/0.1` is **parsed** (refs extracted and checked) but **never
evaluated** by compile; runtime enforcement is the registered evaluator or
native component.

## 3. Document envelope (§9.2)

Required: `schema_version`, `graph_id`, `version_id`, `workspace_id`, `name`,
`created_at`, `created_by`. Plus `namespace`, `status` (`draft|active|
deprecated`), `parent_version_id?`, `content_hash?` (excluded from its own
hash), `provenance` (OPEN), the ten primitive lists, and `extensions`.

Adopter surface: `TwinGraph.new(...)`, `.load(doc)` (folds legacy spellings),
`.compute_content_hash()`, `.with_content_hash()`, `.activate()` (one-way
freeze), `.is_active()/.is_frozen()`, `.entity/.variable/.binding/.by_id`,
`.lineage()`. `SENTINEL_WORKSPACE` is documented for single-tenant adopters.

## 4. Canonicalization & hashing (§9.2)

`canonicalize(doc)`: (a) stable-id array sort of every top-level list, objective
terms, mutual-exclusion groups; (b) unit normalization to canonical spelling;
(c) consistent floats; (d) RFC-3339 timestamps folded to UTC `Z`. `grain` order
is left as authored (semantic).

> **Unit normalization rewrites the unit STRING, never the VALUE.** Folding
> `kWh → MW.h` does **not** rescale a `12000` into `12`. Therefore **bound data
> and property values MUST already be expressed in the binding's declared unit**;
> authors should pre-normalize (or use a declared `unit_transform` on the data
> binding, which *is* applied to values at read time). Declaring values in a
> non-canonical alias is a 1000× foot-gun compile cannot catch (both spellings
> fold to the same canonical unit), so prefer canonical spellings on
> value-bearing fields.

`content_hash = sha256(canonical_json(...))`. The hash is **semantic identity**:
the **hash-volatility set** `{content_hash, created_at, version_id}` is excluded,
so a fresh version of an unchanged graph hashes equal to its parent. Lineage is
carried separately by `version_id` + `parent_version_id`.

## 5. Compile pipeline (§9.16)

`compile_graph(graph, *, type_registry, model_registry, …) → CompileResult`.
Pure and deterministic; depends only on the registry interfaces. **Collects
Diagnostics** (never raises on graph-content errors — adopters get every problem
in one pass); raises ONLY on misuse (null registry). Eleven stages:

1. **canonicalize** — normalize + content hash (declared mismatch = warning).
2. **resolve_types** — entity AND relation `type_ref`s resolved against the
   registry (`TG_UNKNOWN_TYPE` on miss). A bare relation verb (`connected_to`,
   `feeds_into`) is namespaced to `metis.relation.<verb>@1`; an
   already-namespaced ref (`acme.logistics.ships_to@1`) is resolved as-is. The
   vocabulary is now **open** (registry-resolved, not a closed Literal): an
   unregistered relation type COMPILE-errors `TG_UNKNOWN_TYPE` rather than being
   parse-rejected, which is what opens cross-domain relation vocabularies.
3. **validate_required_fields** — `TG_MISSING_REQUIRED` for the type's required
   properties/variables/actions.
4. **resolve_refs** — every cross-ref + `property:`/`entity:` indirection;
   `TG_DANGLING_REF` on miss.
5. **validate_units** — `TG_UNIT_MISMATCH` / `TG_UNKNOWN_UNIT` for variables,
   data bindings, action bounds, and Quantity-valued entity properties checked
   against their registered `TypeDef` property units.
6. **resolve_models** — `TG_UNKNOWN_MODEL`; forecast outputs must map to
   `forecast_distribution` variables. If a `ModelSpec.io_contract` declares port
   units, bound variable units are checked and mismatches emit `TG_IO_CONTRACT`.
   **Foreign-reference kinds** (`fmu`,
   `modelica_class`, §31.3) are VALIDATED — `model_ref` resolved, io_contract
   checked (port-name sets must match the contract bidirectionally, or, for an
   empty contract, the binding must write ≥1 output; violation → `TG_IO_CONTRACT`)
   — and the resulting component is flagged `external=True` (NOT in
   `EXECUTABLE_MODEL_KINDS`; an FMI/Modelica runtime executes it, twingraph does
   not, so no `MODEL_NOT_EXECUTABLE` warning is emitted for them).
7. **structural_validators** — `reference_integrity`, `unit_compatibility`,
   `data_binding_availability`, `issue_time_leakage` → `ValidatorResult`s.
8. **build_dependency_graph** — topo-order executable components (NOT drawing
   order); `TG_CYCLE` on an unresolvable cycle.
9. **build_query_plan** — leakage-safe plan per binding; `TG_LEAKAGE` if a
   horizon-feeding variable's binding lacks an explicit availability column
   **OR sets `as_of_required=false`** (which would tell the runtime to skip the
   issue-time filter — so column-presence alone is not sufficient; the
   compile-time `leakage_safe` flag matches what the connector actually does).
10. **decision_compatibility** — check the graph against every registered
    **program profile** (`program_registry`, default `BUILTIN_PROGRAM_REGISTRY`
    = one profile, `tomorrow_dispatch`) and REPORT each one's compatibility
    (never an error). Generic + domain-agnostic: each profile declares its own
    labelled requirements (entity types / variable roles / binding kinds /
    objective shape / constraint classes), so a non-battery twin reports its own
    profiles' compatibility, not a hardcoded battery check.
11. **emit** — `CompileReport` + `ExecutablePlan` (data-only; carries
    `callable_key` strings, resolved at run by `ModelRegistry.resolve`).

`CompileResult.ok` is true iff there are no error-severity diagnostics; `plan`
is `None` iff not ok. **No decision run may target a version lacking a
successful compile artifact** — the runtime consumes an `ExecutablePlan`, not a
`TwinGraph`.

## 6. Type registry

`TypeDef{type_ref, kind, required_properties/variables/actions, ports, …}`
resolved by a `TypeRegistry` protocol. `BUILTIN_TYPE_REGISTRY` is assembled from
data-only `TypePack`s:

- `POWER_TYPE_PACK`: storage, market nodes, interconnects, solar, wind,
  generators, inverters, transformers, transmission lines, substations, loads,
  fuel supply, and weather regions.
- `DATA_CENTER_TYPE_PACK`: facilities, racks, cooling loops, UPS, and workloads.
- `OPERATIONS_TYPE_PACK`: warehouses, factories, production lines, port
  terminals, logistics nodes, transport routes, and fleet vehicles.
- `DATA_TYPE_PACK`: auditable source and dataset nodes for lineage across
  external extracts, market data, telemetry, weather, documents, and warehouse
  tables.
- `PLATFORM_ANALYSIS_TYPE_PACK`: data-only analysis and decision-system
  vocabulary for counterfactual settlement, backtests, shadow runs, readiness
  gates, physical models, notebooks, rare-event engines, price-impact models,
  co-optimization engines, and operator-facing explanation surfaces.
- `RELATION_TYPE_PACK`: shared operational relation verbs including
  `connected_to`, `feeds_into`, `supplies`, `transports_to`, `ships_to`, `cools`,
  `depends_on`, `simulates`, `evaluates`, `observes`, `explains`, `gates`,
  `annotates`, and `uses_data`.

Adopters can call `build_type_registry((RELATION_TYPE_PACK, POWER_TYPE_PACK))`
for a narrower power-only registry or register additional packs into their own
registry. The registry is a **parameter to compile**, never global; nothing
proprietary lives in it. Relation endpoint `source_port`/`target_port` values are
checked against endpoint entity `TypeDef.ports` when declared.

### Program-profile registry

A **decision program** declares the structural shape a graph must have to serve
it. `ProgramProfile{name, requirements[]}` where each `ProfileRequirement`
carries its own `missing_label` + a pure predicate over the compile context; a
`ProgramRegistry` (default `BUILTIN_PROGRAM_REGISTRY`, holding ONLY
`tomorrow_dispatch`) is a **parameter to compile**. Stage 10 reports every
registered profile's compatibility generically — adopters register their own
profiles (solar, PdM, …) into their own registry instance, and a non-battery
twin is measured against ITS profiles, not a hardcoded battery check. A profile
is reported, never an error.

## 7. Model registry

`ModelSpec{model_ref, kind, io_contract, callable_key}` resolved by a
`ModelRegistry` protocol. Compile uses `get()` to type-check; the executor uses
`resolve(callable_key)` (app-side only) to obtain the callable. `twingraph`
ships the protocol and the `IOContract`/`ModelSpec` dataclasses — never an
implementation.

## 8. Semantic patch (§9.15) — FORMAT only, no agents

`SemanticPatch{patch_id, base_version_id, intent, operations[], status, …}`.
`Operation` is a discriminated union on `op` (single-twin op set:
add/remove/replace each primitive, `set_property`, `resolve_assumption`).
`PatchStatus`: `proposed → schema_validated → execution_validated →
awaiting_approval → approved → applied | rejected | superseded`.

`apply_patch(graph, patch, …) → (TwinGraph, PatchApplyReport)` is **pure** —
returns a new draft, never mutates the input. It (1) rejects on
base-version mismatch (`OutOfOrderPatchError`); (2) refuses material ops against
an active/frozen graph (`ImmutableGraphError` — the normal flow forks a new
draft); (3) applies ops in order; (4) mints a new `version_id` with
`parent_version_id` = base, status `draft`, recomputed `content_hash`,
`provenance.applied_patch_id`. It does **not** auto-compile — the caller
compiles the draft, then may `activate()` it (a one-way freeze). Patch history =
the `parent_version_id` chain plus an append-only `PatchLog`.

## 8b. Leakage safety: compile-time vs runtime (§12.4)

`leakage_safe` on a `QueryPlan` is a **structural** assertion (an availability
column exists *and* the policy will apply it). It is necessary but not
sufficient — **execution must honor it**. A runtime connector closes the loop:

- The as-of cutoff is the **run-level, trusted `issue_time`**, passed explicitly
  into the connector by the run context — **never read from the data payload**.
  An untrusted source cannot declare its own cutoff (the §12.4 leak: a value
  revised *after* issue time must not replace an earlier one in the snapshot).
- `available_at` / `event_time` are parsed to **tz-aware UTC instants** before
  comparison (`fromisoformat`, `Z → +00:00`). Comparison is by true instant, not
  lexicographic string order across heterogeneous RFC-3339 spellings.
- Dedup (`latest_available_at`) breaks `(event_time, available_at)` ties
  **deterministically** by value, so the same warehouse rows in any order yield
  the same snapshot (reproducibility, §9766).
- The read returns a **verification report**: `rows_in`, `rows_rejected_future`,
  `max_available_at`, `event_count` (§12.4 requires both the rejected-row count
  and the max surviving availability).
- `missing_value_policy = fail_required_horizon` is **enforced at read**: a
  short/partial horizon raises rather than silently truncating the decision.

### Advisory vs enforced binding controls

These `query_policy`/`validation` fields ARE enforced (compile and/or runtime):
`as_of_required`, `available_at_column`, `deduplication`,
`missing_value_policy=fail_required_horizon`, `expected_resolution` (threaded to
the plan).

These are **declared-but-advisory in 0.1** — present in the schema for forward
compatibility but **not yet enforced**: `latest_before_issue_time` (the
connector always applies the issue-time cutoff when `as_of_required`, so this is
informational), `max_lookback`, `max_staleness`, `allowed_min`/`allowed_max`.
Adopters MUST NOT assume range/staleness protection from these until a later
release wires them into compile/runtime with rejected-row accounting.

## 9.14 Multi-twin composition

`compose(twins, *, name, created_by, namespace, cross_relations=None,
id_policy="reject"|"qualify", …) → (TwinGraph, CompositionReport)` is a **pure**
function that merges N atomic twins into one composite (spec §9.14: "Atomic
twins compose by merging graph fragments under namespaces").

- **IDs are globally unique.** `id_policy="reject"` (default) raises
  `CompositionError` listing colliding ids + the twins they appear in.
  `id_policy="qualify"` deterministically prefixes EVERY id of a colliding twin
  with its namespace leaf and rewrites every reference (relation/variable/action/
  binding endpoints, model-binding `entity:`/`var:` payloads, constraint
  expression idents, objective `measure_ref`, `evidence_refs`/`required_for`).
- **Merge** concatenates the ten primitive lists across (possibly remapped)
  twins, shallow-merges `extensions` (conflicts namespaced under
  `extensions["composed"][<ns>]`), and appends `cross_relations` (cross-twin
  edges; their cross-domain `type_ref`s resolve via the open relation vocabulary,
  bad endpoints → `TG_DANGLING_REF` at compile).
- **Lineage** is a NEW draft version (`graph_id`/`version_id` minted,
  `status=draft`). N parents cannot fit `parent_version_id`, so
  `provenance.composed_from` records every component `{graph_id, version_id}`.
- compose does **no** validation beyond id-collision + pydantic construct —
  correctness (refs, units, types, leakage) is the **compiler's** job, re-run on
  the composite via the unchanged `compile_graph`. The composite COMPILES.
- A composed graph may be **partially executable**: foreign-reference components
  carried in from a component twin are listed in
  `CompositionReport.unsupported_regions` (§9.14: "unsupported regions must be
  marked"); the composite still compiles.

The P0 composition demo composes a `metis.energy.SolarArray@1` twin with the
battery twin (a `feeds_into` solar→battery cross-relation), recompiles to an
`ExecutablePlan`, and shows `tomorrow_dispatch` still compatible (battery half
intact) while a solar-only twin reports its OWN profile.

## 31.3 Foreign-reference model kinds

`fmu` and `modelica_class` are **retained, validated foreign references**, not
dead warn-only enums (spec §31.3: "TwinGraph should retain foreign references and
compile relevant pieces into its operational representation"). Compile validates
them (model_ref resolved + io_contract checked) and marks the component
`external=True`; they are deliberately **absent from `EXECUTABLE_MODEL_KINDS`** —
an FMI/Modelica runtime executes them, twingraph's native dispatch does not. The
flag, not the topo-order position, signals foreign dispatch. A well-formed `fmu`
binding compiles ok (component flagged external); a malformed io_contract errors
`TG_IO_CONTRACT`.

## 9. Out of scope for 0.2

Other cross-domain primitives beyond composition/open-relations, the SSP/SysML/
CIM/OPC-UA foreign adapters themselves (only the `fmu`/`modelica_class`
reference *kinds* are retained + validated here), and the LLM **agent runtime**
(the patch *format* is built; the agents are not). TypeScript types are a
documented one-command follow-up (`npx json-schema-to-typescript`), not
hand-maintained.
