# Changelog

All notable changes to `twingraph` are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
semantic versioning.

## [Unreleased]

## [0.0.3] — 2026-07-08

### Added

- Dependabot weekly version-update configuration for GitHub Actions and Python
  dependency manifests.
- FMI modelDescription parsing now rejects XML ``DOCTYPE`` and ``ENTITY``
  declarations before stdlib XML parsing.
- Compiler diagnostics now reject duplicate primitive ids, multiple objectives
  in the 0.1 plan shape, action-bound unit mismatches, and model binding kind
  mismatches against the registry's `ModelSpec`.

### Changed

- README installation guidance now points at the current GitHub release tag and
  clarifies the PyPI handoff status.
- Multi-twin qualify-mode expression remapping now uses the shared metis_expr
  tokenizer instead of a hand-rolled identifier boundary scanner.
- The load-time legacy alias normalizer now documents its public-version removal
  target.
- Patch immutability guards now cover data bindings, actions, validators, and
  evidence as material operations.
- Primitive validation now constrains confidence/risk probability fields and
  rejects inverted numeric ranges.

## [0.0.2] — 2026-07-02

### Added

- **FMI interop module (`twingraph.fmi`)** — `parse_model_description()` and
  `read_fmu_model_description()` parse an FMU's `modelDescription.xml` (FMI 2.x
  and 3.x, including `declaredType` unit lookups, stdlib-only), and
  `io_contract_from_fmu()` derives a foreign `fmu` binding's io_contract
  mechanically instead of hand-transcription. New `FmiParseError` misuse error.
- **Unit table `ucum-subset/0.4`** — SI physical units for FMI/Modelica ports:
  `K` and `Pa` canonical (with `kelvin`, `kPa`, `MPa`, `bar` aliases), joule
  family (`J`/`kJ`/`MJ`/`GJ`) folded into `MW.h`, and `kg`/`g` folded into
  `tonne`. `K` is intentionally NOT scale-linked to `degC`: affine conversions
  are out of table scope, so a degC/K pairing reports `TG_UNIT_MISMATCH`.

## [0.0.1] — 2026-07-02

Initial public release. Version numbering restarts at 0.0.1 for the public
line; the 0.x entries below document internal pre-release history and were
never published or tagged.

### Added

- **Agent Skills pack** — portable Agent Skills under `skills/` for authoring,
  ingesting, editing, validating, composing, and extending TwinGraph documents
  and type packs.
- **Analysis/audit type pack** — public `PLATFORM_ANALYSIS_TYPE_PACK` export
  with data-only nodes for counterfactual settlement, backtests, shadow runs,
  readiness gates, physical models, notebooks, rare-event engines,
  co-optimization engines, and explanation surfaces.
- **Data-lineage dataset nodes** — `metis.data.Dataset@1` is part of the
  built-in data pack for warehouse/table lineage in auditable twins.
- **Decision-analysis relation verbs** — `simulates`, `evaluates`, `observes`,
  `explains`, `gates`, `annotates`, and `uses_data`.
- **Unit table `ucum-subset/0.3`** — adds `USD/MW`, `count`, and the
  `probability -> ratio` alias.
- **CI and release automation** — Python 3.11–3.13 test matrix, stricter ruff
  rule set, version-parity tests, and a tag-driven release workflow that builds
  and attaches the sdist and wheel.

## [0.3.0] — 2026-06-22 (internal pre-release)

From a composable battery/solar IR to a power-first operational twin kernel.
`schema_version` stays `twingraph/0.1`; this release broadens registries and
compile checks without changing the document envelope.

### Added

- **Built-in type packs** — data-only `TypePack`s with `register_type_pack()` and
  `build_type_registry()` so adopters can use the full built-in vocabulary or a
  narrower pack set:
  - `RELATION_TYPE_PACK`: shared operational relation verbs.
  - `POWER_TYPE_PACK`: batteries, solar, wind, generators, inverters,
    interconnects, transformers, transmission lines, substations, loads, fuel
    supply, and weather regions.
  - `DATA_CENTER_TYPE_PACK`: facilities, racks, cooling loops, UPS, and
    workloads.
  - `OPERATIONS_TYPE_PACK`: warehouses, factories, production lines, port
    terminals, logistics nodes, transport routes, and fleet vehicles.
- **Operational unit vocabulary** (`UNIT_TABLE_VERSION = ucum-subset/0.2`) for
  power, electrical, thermal, fuel, data-center, and logistics units such as
  `kV`, `MVA`, `MW/min`, `W/m2`, `m/s`, `degC`, `kW`, `request/s`, `TEU/h`,
  `item/h`, and `tonne`.
- **Relation port validation** — if a relation declares `source_port` or
  `target_port`, compile checks it against the endpoint entity's registered
  `TypeDef.ports` and emits `TG_STRUCTURE` on mismatch.
- **Entity property unit validation** — Quantity-valued entity properties are
  checked against their `TypeDef` property unit and emit `TG_UNKNOWN_UNIT` or
  `TG_UNIT_MISMATCH`.
- **Model IO unit validation** — `ModelSpec.io_contract` port units are checked
  against bound variable units and emit `TG_IO_CONTRACT` on mismatch.

### Verified

- Added cross-domain compile tests for a power-plus-warehouse graph, a
  data-center thermal/power/workload graph, invalid relation ports, invalid
  property units, and invalid model IO units.

## [0.2.0] — 2026-06-21 (internal pre-release)

From a single-battery IR that *structurally* generalizes to a real composable,
cross-domain operational IR. Fully backward-compatible: the golden
`ny_demo_bess_01` example still compiles and produces byte-identical
ExecutablePlan output. `schema_version` stays `twingraph/0.1` (doc-format
version, distinct from the package version), `UNIT_TABLE_VERSION` and
`COMPILER_VERSION` are unchanged.

### Added

- **Multi-twin composition (§9.14)** — pure `compose(twins, …) →
  (TwinGraph, CompositionReport)` merges N atomic twins into one composite draft:
  globally-unique-id handling (`id_policy="reject"` rejects collisions,
  `"qualify"` namespace-prefixes + remaps every reference), merged ten lists +
  `extensions` + cross-twin `cross_relations`, a new draft lineage recording
  every component in `provenance.composed_from`. The composite COMPILES via the
  unchanged `compile_graph`. Demo: a `metis.energy.SolarArray@1` twin composed
  with the battery twin (`feeds_into` cross-relation) → `ExecutablePlan`.
  `CompositionError` (id-collision misuse).
- **Open, registry-resolved relation types** — `Relation.type_ref` is now a
  permissive string (`RELATION_TYPE_REF_PATTERN`) validated at COMPILE against
  the registry's relation TypeDefs (a bare verb → `metis.relation.<x>@1`; a
  namespaced foreign ref resolved as-is), unblocking cross-domain `feeds_into`/
  `ships_to`. The P0 set stays registered in `BUILTIN` for back-compat; bare
  spellings still normalize. An unregistered relation type now COMPILE-errors
  `TG_UNKNOWN_TYPE` instead of parse-rejecting.
- **Program-profile registry** — stage 10 is no longer hardcoded to the battery
  `tomorrow_dispatch` program. `ProgramProfile`/`ProfileRequirement` +
  `ProgramRegistry`/`InMemoryProgramRegistry`/`BUILTIN_PROGRAM_REGISTRY` (one
  profile: `tomorrow_dispatch`, reproducing the legacy five labels in the legacy
  order). Compile checks the graph against every registered profile generically;
  a non-battery twin reports ITS profiles' compatibility.
- **Foreign-reference model kinds done right (§31.3)** — `fmu` and
  `modelica_class` are back in `ModelBindingKind`, but as RETAINED, VALIDATED
  foreign references: compile resolves the `model_ref`, checks the io_contract
  (port-name match or ≥1 output → `TG_IO_CONTRACT`), and flags the component
  `external=True` (NOT in `EXECUTABLE_MODEL_KINDS`; no `MODEL_NOT_EXECUTABLE`
  warning). `FOREIGN_MODEL_KINDS` exported.
- **Extensible `UnitRegistry`** — domain units register so cross-domain unit
  checks validate instead of passing opaque. `DEFAULT_UNIT_REGISTRY` (the P0
  table, NOT extended) backs the free functions; `compile_graph(unit_registry=…)`
  takes an adopter registry.
- **`metis.energy.SolarArray@1`** TypeDef + cross-domain `feeds_into`/`ships_to`
  relation TypeDefs registered in `BUILTIN_TYPE_REGISTRY`.

### Changed

- `Relation.type_ref`: closed `RelationType` Literal → registry-resolved string
  (the Literal is RETAINED + exported as a documented P0-vocabulary alias, but no
  longer constrains the field). The relation-vocabulary contract MOVED from
  parse-reject to compile-error `TG_UNKNOWN_TYPE`.
- `ResolvedComponent` gains an additive `external: bool = False` field.
- `compile_graph` gains `program_registry` + `unit_registry` kwargs (both default
  to the builtins, so the existing 2-kwarg call site is unchanged).

### Resolved from 0.1 follow-ups

- **Foreign-standard model-binding kinds** — `fmu`/`modelica_class` are now
  retained + validated external references (see Added), not dead enums.
- **Multi-twin composition/merge** — shipped via `compose()` (see Added).

## [0.1.0] — 2026-06-20 (internal pre-release)

The thin scaffold becomes the full TwinGraph 0.1 IR: typed primitives,
canonicalization + content hashing, a type registry, a model-registry seam, a
deterministic compile pipeline that emits an executable plan, and the semantic
patch *format*. Published JSON Schema (draft 2020-12) generated from the models.

### Added

- **All ten primitives at full 0.1 shape** — Entity, Relation, Variable,
  DataBinding, ModelBinding, Action, Constraint, Objective, Validator, Evidence,
  plus Provenance / ConfirmationState (5) / LifecycleState.
- **Document envelope** (`TwinGraph`) with the four new members vs the scaffold:
  `version_id`, `workspace_id`, `data_bindings`, `model_bindings`, `evidence`;
  `TwinGraph.new(...)` factory and `SENTINEL_WORKSPACE`.
- **Data binding** — the leakage primitive: `event_time_column` required,
  `available_at_column` / conservative-policy root validator (availability can
  never be silently omitted).
- **Compile pipeline** (`compile_graph`) — 11 stages collecting `Diagnostic`s
  with stable `TG_*` codes; emits an immutable `CompileReport` + a data-only
  `ExecutablePlan` carrying `callable_key`s.
- **Type registry** (`BUILTIN_TYPE_REGISTRY`) seeded with the energy P0
  (`metis.energy.Battery@1` / `MarketNode@1` / `Interconnect@1` + the
  `metis.relation.*@1` set).
- **Model registry** protocol + `IOContract`/`ModelSpec` (references/registers
  seam; no implementations ship in the core).
- **Semantic patch** format + pure `apply_patch` (forks a new draft; immutability
  guard; parent chain) + `PatchLog`.
- **Canonicalization** — stable-id array sort, unit normalization, RFC-3339 UTC
  time folding; hash-volatility set `{content_hash, created_at, version_id}`
  excluded from `content_hash` (semantic identity).
- **Pure-stdlib ULID** generation/validation (`ids.py`) — no `python-ulid` dep.
- **UCUM-subset unit model** (`units.py`) with alias folding.
- **`metis_expr/0.1`** tokenizer + reference extractor — parsed, never
  evaluated.
- **Published JSON Schema** (`schema/twingraph-0.1.schema.json`) with the two
  hand-added one-ofs (constraint expression-XOR-evaluator; binding availability);
  `make schema` / `make schema-check` and a parity test guard drift.

### Leakage-safety hardening (§12.4)

- **Compile `leakage_safe` now matches runtime behavior.** A horizon-feeding
  binding is certified leakage-safe only when it has an `available_at_column`
  **and** `query_policy.as_of_required=true`. A binding that keeps the column but
  disables the as-of cutoff (`as_of_required=false`) now emits `TG_LEAKAGE` and
  fails the `issue_time_leakage` validator, instead of silently passing.
- **QueryPlan carries the runtime-honored policy fields**:
  `latest_before_issue_time`, `missing_value_policy`, `expected_resolution`.
- **Relation `type_ref`s are now resolved against the type registry** (bare
  spelling mapped to `metis.relation.<x>@1`); previously only entity type_refs
  were resolved and the registered relation TypeDefs were dead.
- **Immutability-after-activation enforced on load**: a document loaded with
  `status='active'` must carry a `content_hash` matching its computed identity
  and is returned frozen (previously only the in-process `.activate()` path
  froze; loaded active docs were freely mutable and could ship without a hash).
  The golden example is stamped with its computed `content_hash`.

> The runtime as-of/leakage enforcement (trusted run `issue_time`, instant-based
> timestamp comparison, deterministic dedup tie-break, `fail_required_horizon`,
> the §12.4 verification report) lives in the **product** connector
> outside this OSS core. See SPEC §8b.

### Advisory (declared-but-not-yet-enforced) controls

`latest_before_issue_time`, `max_lookback`, `max_staleness`,
`allowed_min`/`allowed_max` are present in the schema for forward compatibility
but are **not enforced** in 0.1 — adopters must not assume range/staleness
protection from them (documented in SPEC §8b).

### Changed (breaking 0.1 renames)

Spec field names are now canonical. Old scaffold spellings are accepted for
**one version** via a load-time normalizer (`TwinGraph.load`) and will be removed
in 0.2:

| Scaffold | 0.1 |
|----------|-----|
| `Relation.source_id` / `target_id` | `source_entity_id` / `target_entity_id` |
| relation `connects_to` / `limited_by` | `connected_to` / `constrained_by` |
| `Variable.entity_id` | `owner_ref` |
| `Variable.kind` | `role` (now an 8-value enum) |
| `Action.entity_id` | `controller_entity_id` |
| `Validator.pattern_ref` | `evaluator_ref` |
| `Action{unit, lower, upper}` | structured `bounds: {key: ActionBound}` |
| `Constraint{kind, expr}` | typed `class` + `expression` XOR `evaluator_ref` |
| `Objective{sense, expr}` | structured `terms[]` + `aggregation` |
| `TwinGraph.content_hash()` | `compute_content_hash()` (volatile-field-aware) |

### Follow-ups (not in 0.1)

- **Foreign-standard model-binding kinds** (`fmu`, `modelica_class`): in 0.1
  these were deliberately removed as dead warn-only enums. **Resolved in 0.2** —
  re-added as retained, *validated* foreign references (io_contract checked,
  flagged `external`), NOT executable enums (spec §31.3). The remaining planned
  kinds (`remote_service`, `physics_surrogate`, `learned_transition_model`,
  `python_package`) stay an additive extension for when a real runtime backs
  them.
- **TypeScript types**: deferred — no `json-schema-to-typescript` in the
  dependency-clean budget. Run `npx json-schema-to-typescript
  twingraph/schema/twingraph-0.1.schema.json > twingraph.d.ts` (also `make
  types-ts`). The JSON Schema is the canonical cross-language contract.
- **Multi-twin composition/merge**: **resolved in 0.2** (`compose()`). The
  remaining cross-domain primitives and the LLM patch **agent runtime** (the
  patch *format* is built here; agents are not) stay out of scope.
