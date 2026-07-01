"""Load-time alias normalizer (one-version back-compat, §"open questions" #2).

The 0.1 field renames are breaking. To smooth a single migration window we
accept the old scaffold spellings and normalize them to the spec shape BEFORE
model validation. New documents should be authored in the spec shape directly;
these aliases are documented in CHANGELOG.md and will be removed in 0.2.

Renames handled:
  Relation:   source_id      -> source_entity_id
              target_id      -> target_entity_id
              connects_to    -> connected_to        (type_ref value)
              limited_by     -> constrained_by       (type_ref value)
  Variable:   entity_id      -> owner_ref
              kind           -> role
  Action:     entity_id      -> controller_entity_id
  Validator:  pattern_ref    -> evaluator_ref

Pure/functional — returns a new dict, never mutates the input.
"""

from __future__ import annotations

import copy
from typing import Any

_RELATION_TYPE_ALIASES = {
    "connects_to": "connected_to",
    "limited_by": "constrained_by",
}


def normalize_legacy_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``doc`` with legacy field/value spellings folded."""
    d = copy.deepcopy(doc)

    for rel in d.get("relations", []) or []:
        if not isinstance(rel, dict):
            continue
        if "source_id" in rel and "source_entity_id" not in rel:
            rel["source_entity_id"] = rel.pop("source_id")
        if "target_id" in rel and "target_entity_id" not in rel:
            rel["target_entity_id"] = rel.pop("target_id")
        t = rel.get("type_ref")
        if t in _RELATION_TYPE_ALIASES:
            rel["type_ref"] = _RELATION_TYPE_ALIASES[t]

    for var in d.get("variables", []) or []:
        if not isinstance(var, dict):
            continue
        if "entity_id" in var and "owner_ref" not in var:
            var["owner_ref"] = var.pop("entity_id")
        if "kind" in var and "role" not in var:
            var["role"] = var.pop("kind")

    for action in d.get("actions", []) or []:
        if not isinstance(action, dict):
            continue
        if "entity_id" in action and "controller_entity_id" not in action:
            action["controller_entity_id"] = action.pop("entity_id")

    for validator in d.get("validators", []) or []:
        if not isinstance(validator, dict):
            continue
        if "pattern_ref" in validator and "evaluator_ref" not in validator:
            validator["evaluator_ref"] = validator.pop("pattern_ref")

    return d
