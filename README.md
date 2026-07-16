# twingraph

The typed, executable, versioned **decision-twin intermediate representation**.

TwinGraph is a small Python package for describing real operating systems in a
form that humans, agents, and runtimes can all inspect. A graph records what
exists, how assets connect, what state is measured, what can be controlled, what
data is available at decision time, which model references are bound, and what
constraints/objectives make a decision valid.

It is an intermediate representation, not an optimizer, simulator, database, or
UI. The core is deliberately dependency-clean: **stdlib + pydantic only**.

```bash
pip install "twingraph @ git+https://github.com/parisi-labs/twingraph.git@v0.0.3"
```

> **Note**: TwinGraph is not yet published to PyPI — the `twingraph` name there
> currently belongs to an unrelated placeholder package, so `pip install
> twingraph` will NOT install this project. Install from GitHub (above) or from
> the sdist/wheel attached to a [GitHub
> release](https://github.com/parisi-labs/twingraph/releases).

To install from a local checkout:

```bash
git clone https://github.com/parisi-labs/twingraph.git
cd twingraph
python -m pip install .
```

## Why This Exists

Operational AI systems need a stable artifact between messy real-world sources
and proprietary decision engines. TwinGraph gives you that artifact:

- **Typed**: entities, variables, actions, constraints, evidence, bindings, and
  relations are validated with pydantic models.
- **Compilable**: `compile_graph()` resolves types, references, model contracts,
  units, leakage safety, dependency order, and program compatibility.
- **Hashable**: canonical JSON plus semantic content hashes make graph identity
  auditable and reproducible.
- **Extensible**: type packs, model registries, unit registries, and program
  profiles are passed in as interfaces.
- **Portable**: documents are plain JSON with a published JSON Schema.

The proprietary part of a production system should live outside this package:
model implementations, data connectors, forecasting systems, optimizers,
settlement logic, serving APIs, and customer-specific workflows.

For a complete storage example—not just an asset diagram—see the [public
physical BESS walkthrough](examples/public_physical_bess_01.md). It traces the
same typed graph from physical topology and decision-time data through external
health models, health-aware dispatch, approval gates, shadow evaluation, and
operator explanation.

## Quickstart

Load the included illustrative battery twin and compile it against a small model
registry. The registry does not provide code here; it tells TwinGraph which
model references are valid and what units their ports expect.

```python
import json
from pathlib import Path

import twingraph as tg
from twingraph.registry import IOContract, ModelSpec
from twingraph.errors import UnknownModelRefError


class DemoModelCatalog:
    def __init__(self):
        self._models = {
            "registry://metis.components.battery_linear@1.0.0": ModelSpec(
                model_ref="registry://metis.components.battery_linear@1.0.0",
                kind="native_component",
                io_contract=IOContract(
                    inputs={"price": {"unit": "USD/MW.h"}},
                    outputs={"state_of_charge": {"unit": "MW.h"}},
                ),
                callable_key="battery_linear",
            )
        }

    def get(self, model_ref: str) -> ModelSpec:
        try:
            return self._models[model_ref]
        except KeyError as exc:
            raise UnknownModelRefError(model_ref) from exc

    def has(self, model_ref: str) -> bool:
        return model_ref in self._models

doc = json.loads(Path("examples/ny_demo_bess_01.twingraph.json").read_text())
graph = tg.TwinGraph.load(doc)

result = tg.compile_graph(
    graph,
    type_registry=tg.BUILTIN_TYPE_REGISTRY,
    model_registry=DemoModelCatalog(),
)

assert result.ok, result.report.errors()
print(result.report.graph_content_hash)
print([component.model_ref for component in result.plan.components])
```

## Core Concepts

**A TwinGraph document has ten primitive lists.**

- `entities`: physical, market, data, or analysis objects.
- `relations`: typed links between entities.
- `variables`: state, control, observed, exogenous, derived, parameter, latent,
  or outcome values.
- `data_bindings`: source-to-variable bindings with event-time and availability
  semantics.
- `model_bindings`: references to model implementations, never code.
- `actions`: controllable variables and bounds.
- `constraints`: expression or evaluator-ref constraints.
- `objectives`: structured optimization targets.
- `validators`: registered validation patterns.
- `evidence`: claims and source references.

**Compile is a contract check, not execution.**

`compile_graph()` collects every graph-content issue as a stable diagnostic code
such as `TG_UNKNOWN_TYPE`, `TG_DANGLING_REF`, `TG_UNIT_MISMATCH`,
`TG_IO_CONTRACT`, `TG_LEAKAGE`, or `TG_CYCLE`. If the graph compiles, the result
contains a data-only `ExecutablePlan` that your runtime can execute.

When a model registry declares an `IOContract`, TwinGraph checks its port names
as well as units for every model kind. Declared input/output ports are required
by default; set `{"required": False}` on an optional port. Declared parameters
reject unknown names and are optional by default so an FMI or Modelica model can
use its own defaults (set `{"required": True}` to require a binding). The plan
also carries the source adapter, query freshness/range policy, and variable
initialization/uncertainty metadata needed by a runtime.

**The core references models; your application registers them.**

Model references look like `registry://metis.components.battery_linear@1.0.0`.
The `metis.*` built-in namespace is just the default vocabulary shipped with the
package. You can register your own type packs and model refs without importing
any application code into `twingraph`.

## Runtime Contract

TwinGraph does not execute an `ExecutablePlan`, but it defines versioned,
runtime-neutral JSON plan, context, and result contracts for runtimes that do:

- `ModelCatalog` supplies compile-time `ModelSpec` metadata without requiring
  executable code.
- `CallableResolver` resolves a compiled `callable_key` inside an
  application-owned runtime. The combined `ModelRegistry` protocol remains for
  applications that intentionally provide both capabilities.
- `PythonComponentCallable` is an optional synchronous, in-process Python ABI
  with keyword-only `inputs`, `params`, and `ExecutionContext`. It is not the
  portable boundary; containers, RPC services, queues, and foreign runtimes use
  the JSON contracts.
- `ExecutionResult` records exact `plan_hash` identity, issue time, runtime and
  implementation versions, external artifact references, JSON-compatible
  outputs, and diagnostics.

Plans and results expose `to_wire()` / `from_wire()` methods. Plan wire fields
are JSON-constrained, `dependency_order` is the authoritative component order,
and every plan carries a canonical hash that its result must repeat. Independent
schema versions let a runtime reject unsupported formats before execution.
Large datasets and binary outputs should remain in application-owned storage
and travel as `ArtifactRef` values.

Deployment policy—containers, resource requests, retries, queues, and
scheduling—is intentionally not graph semantics and remains outside this
package.

## Built-In Type Packs

The built-in registry is assembled from data-only type packs:

- `POWER_TYPE_PACK`: batteries, market nodes, interconnects, solar, wind,
  generators, transformers, transmission lines, substations, loads, inverters,
  fuel supply, and weather regions.
- `BESS_TYPE_PACK`: container and module fleets, power conversion, battery
  management, and thermal management subsystems for physically legible storage
  twins.
- `DATA_CENTER_TYPE_PACK`: facilities, racks, cooling loops, UPS, and workloads.
- `OPERATIONS_TYPE_PACK`: warehouses, factories, production lines, port
  terminals, logistics nodes, transport routes, and fleet vehicles.
- `DATA_TYPE_PACK`: data sources and warehouse/table datasets.
- `PLATFORM_ANALYSIS_TYPE_PACK`: counterfactual settlement, backtests, shadow
  runs, readiness gates, audit trails, physical models, notebooks, rare-event
  engines, co-optimization engines, and explanation surfaces.
- `RELATION_TYPE_PACK`: relation verbs such as `connected_to`, `feeds_into`,
  `supplies`, `depends_on`, `uses_data`, `evaluates`, `simulates`, and `gates`.

Use the full registry:

```python
type_registry = tg.BUILTIN_TYPE_REGISTRY
```

Or construct a narrower one:

```python
type_registry = tg.build_type_registry((tg.RELATION_TYPE_PACK, tg.POWER_TYPE_PACK))
```

## Leakage Safety

TwinGraph treats data availability as a first-class part of the graph. A
horizon-feeding `DataBinding` is considered leakage-safe only when it declares
an availability column and keeps `query_policy.as_of_required=true`.

Compile-time leakage checks are structural. Runtime connectors still must apply
the issue-time cutoff, parse timestamps as instants, deduplicate deterministically,
and report rejected future rows. Those runtime connectors are intentionally
outside this package.

## Semantic Patches

TwinGraph includes a pure semantic patch format for versioned graph edits:

```python
from twingraph import Constraint, SemanticPatch, apply_patch
from twingraph.primitives import ConstraintExpression

patch = SemanticPatch(
    base_version_id=graph.version_id,
    intent="add a terminal reserve constraint",
    created_by="operator",
    operations=[
        {
            "op": "add_constraint",
            "constraint": Constraint(
                id="c_terminal_reserve",
                name="Terminal reserve",
                **{"class": "hard_commercial"},
                expression=ConstraintExpression(value="soc >= 1.0"),
            ),
        }
    ],
)

draft, report = apply_patch(graph, patch)
```

`apply_patch()` never mutates the input graph. Active graphs are frozen; normal
edits fork a new draft and preserve lineage.

## JSON Schema And TypeScript

The published schema is generated from the pydantic models:

- [`schema/twingraph-0.1.schema.json`](schema/twingraph-0.1.schema.json)
- Document `schema_version`: `twingraph/0.1`

Regenerate and check drift:

```bash
python -m twingraph._schema_tool > schema/twingraph-0.1.schema.json
pytest tests/test_schema_parity.py
```

Generate TypeScript types from the schema:

```bash
npx json-schema-to-typescript schema/twingraph-0.1.schema.json > twingraph.d.ts
```

## Agent Skills

The [`skills/`](skills/) directory contains portable Agent Skills for AI agents
working with TwinGraph documents:

- `twingraph-create`
- `twingraph-edit`
- `twingraph-validate`
- `twingraph-compose`
- `twingraph-ingest`
- `twingraph-typepacks`

Use them to configure agents around an existing system without putting that
system into the open-source package:

1. `twingraph-ingest`: read specs, PDFs, spreadsheets, diagrams, notes, or
   existing system metadata into evidence-backed candidate entities, relations,
   ports, variables, and assumptions.
2. `twingraph-typepacks`: extend the vocabulary for adopter-specific asset
   classes, ports, units, and relation verbs.
3. `twingraph-create`: produce a first `.twingraph.json` boundary for a site,
   facility, workflow, or subsystem.
4. `twingraph-compose`: connect independent twins through typed ports.
5. `twingraph-validate`: parse, hash-check, compile, and diagnose the result
   against the adopter's registries.
6. `twingraph-edit`: make auditable versioned changes as the real system
   evolves.

These are optional authoring aids. The Python package does not depend on any
agent runtime. Source distributions and GitHub checkouts expose them at
`skills/`; wheels also include them as package resources under
`twingraph/skills`.

## What Is Not Included

TwinGraph intentionally does not ship:

- proprietary model implementations
- data warehouse connectors
- forecasting or optimization engines
- settlement replay logic
- live control systems
- persistence APIs or UI components
- customer- or asset-specific evidence packets

That separation is the point: the IR can be public and inspectable while the
runtime, data, models, and operations remain application-owned.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check src/twingraph tests
python -m twingraph._schema_tool > schema/twingraph-0.1.schema.json
```

The dependency invariant is tested: the core package must not import application
code and must remain stdlib + pydantic.

## Maintenance Status

- Releases are currently distributed through GitHub Releases while PyPI package
  ownership is being resolved.
- Dependabot is configured for weekly GitHub Actions and Python dependency
  checks.
- Runtime dependencies remain intentionally narrow: stdlib plus `pydantic`.

## License

Apache-2.0. See [LICENSE](LICENSE).
