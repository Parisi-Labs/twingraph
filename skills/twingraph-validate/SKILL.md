---
name: twingraph-validate
description: Use this skill when validating, linting, compiling, diagnosing, or preparing to activate a TwinGraph document. Use it for `.twingraph.json` files, schema validation, content-hash checks, active/draft lifecycle checks, unit compatibility, relation port checks, data/model binding checks, compile diagnostics, and regression tests before publishing or using a twin.
---

# TwinGraph Validate

Validate a TwinGraph in layers. Be explicit about which layer passed.

## Validation Layers

1. **Parse/model validation**: load JSON and construct `TwinGraph`. This catches
   malformed fields and unknown extra fields.
2. **Active hash validation**: if `status="active"`, load with
   `TwinGraph.load(doc)` so stale or missing `content_hash` fails.
3. **Schema drift**: in the repo, run `make schema-check` or regenerate with
   `python -m twingraph._schema_tool` only when model changes justify it.
4. **Compile validation**: run `compile_graph` with a real `TypeRegistry`,
   `ModelRegistry`, and optional program/validator registries. Compile is the
   only step that certifies refs, units, type packs, port compatibility, model
   IO contracts, leakage policy, dependency order, and executable plan shape.
5. **Tests**: in this repo, run focused `twingraph/tests` after changing core
   graph behavior or public fixtures.

## Commands

From the TwinGraph repository root:

```bash
python -m pip install -e ".[dev]"
pytest -q
python -m twingraph._schema_tool > /tmp/twingraph.schema.json
```

For a quick document parse:

```python
import json
import twingraph as tg

doc = json.load(open("path/to/file.twingraph.json"))
graph = tg.TwinGraph.load(doc) if doc.get("status") == "active" else tg.TwinGraph.model_validate(doc)
print(graph.compute_content_hash())
```

## Diagnostic Handling

- Report diagnostics by `code`, `stage`, `ref`, and message. Do not collapse
  all errors into "invalid graph".
- Fix root causes in this order: parse errors, active hash errors, dangling
  references, unknown types, required fields, unit mismatches, port mismatches,
  model binding/IO errors, leakage/data binding errors, program compatibility.
- If no model registry is available, say that full compile validation was not
  run. Do not claim a graph is executable from schema validation alone.
- If validation changes a public example, recompute its `content_hash` only
  after the semantic payload is final.

## Activation Gate

Only activate a graph when:

- model validation passes,
- compile has no error-severity diagnostics for the intended runtime,
- `content_hash == compute_content_hash()`,
- uncertain fields are marked with provenance/confirmation state,
- the user or owning workflow has approved activation.
