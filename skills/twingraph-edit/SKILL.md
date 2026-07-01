---
name: twingraph-edit
description: Use this skill when editing, updating, repairing, or versioning an existing TwinGraph document. Use it for semantic patches, property changes, adding/removing/replacing entities, relations, variables, ports, bindings, constraints, objectives, evidence, correcting compile diagnostics, or safely forking active `.twingraph.json` versions into new drafts.
---

# TwinGraph Edit

Update TwinGraphs through explicit versioned changes instead of silent in-place
mutation.

## Workflow

1. Load and inspect the graph. If it is `status="active"`, do not edit it in
   place. Create a draft fork with a new `version_id`, `parent_version_id` set
   to the active version, `status="draft"`, and no stale `content_hash`.
2. Represent material changes as a `SemanticPatch` when possible. Use
   operations from `twingraph/src/twingraph/patch.py`:
   `add_*`, `remove_*`, `replace_*`, `set_property`, and `resolve_assumption`.
3. Keep patch intent human-readable. Include evidence refs and a validation
   plan when the change came from a source document or user confirmation.
4. Apply the patch with `apply_patch` only against a draft base for material
   edits. The patch machinery mints a new draft version, chains
   `parent_version_id`, and records `provenance.applied_patch_id`.
5. Re-run validation after the update. Do not declare the update done if the
   result has dangling refs, unknown types, unit mismatches, bad ports, stale
   hashes, or model IO contract errors.
6. If a fix changes an entity interface, update every relation that uses that
   port and every variable referenced by `EntityPort.variable_id`.

## Editing Rules

- Prefer `replace_entity` or `replace_relation` for structured object changes;
  prefer `set_property` for a single property change.
- Remove dependent primitives deliberately. Removing an entity may require
  removing or replacing relations, variables, actions, bindings, constraints,
  validators, and evidence refs.
- Use `confirmation_state` and `confidence` to represent uncertainty instead of
  deleting useful but unconfirmed facts.
- Preserve open-source boundaries: update model refs and IO contracts as data;
  do not embed runtime callables in the graph.
- Preserve human auditability: each material edit should answer why it changed,
  what evidence supports it, and how it was validated.

## Draft Fork Pattern

Use this pattern when the input graph is active/frozen and needs material edits:

```python
import twingraph as tg
from twingraph.ids import new_ulid

draft = active_graph.model_copy(deep=True)
object.__setattr__(draft, "_frozen", False)
draft.status = "draft"
draft.parent_version_id = active_graph.version_id
draft.version_id = new_ulid()
draft.content_hash = None
```

Then apply a `SemanticPatch` to `draft` and validate the result.
