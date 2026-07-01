"""Generate the published TwinGraph JSON Schema (draft 2020-12).

Pydantic v2 is the single source of truth: ``model_json_schema()`` emits the
oneOf+discriminator for the patch-op union and ``additionalProperties:false``
for the ``extra="forbid"`` models. We then POST-PROCESS to add the draft
2020-12 ``$schema``/``$id``, a title/description, and the two ``oneOf``
constraints that pydantic cannot express natively:

  * Constraint: EXACTLY ONE of ``expression`` / ``evaluator_ref``.
  * DataBinding: ``available_at_column`` present, OR ``as_of_required=false``
    WITH a ``conservative_availability_policy``.

``make schema`` re-emits this; ``make schema-check`` (and a pytest) fail on drift.

stdlib + pydantic only.
"""

from __future__ import annotations

import json
from typing import Any

from .document import TwinGraph

SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID = "https://twingraph.parisi-labs.com/schema/twingraph-0.1.schema.json"


def _add_constraint_oneof(defs: dict[str, Any]) -> None:
    constraint = defs.get("Constraint")
    if not constraint:
        return
    constraint["oneOf"] = [
        {"required": ["expression"], "not": {"required": ["evaluator_ref"]}},
        {"required": ["evaluator_ref"], "not": {"required": ["expression"]}},
    ]


def _add_binding_oneof(defs: dict[str, Any]) -> None:
    binding = defs.get("DataBinding")
    if not binding:
        return
    binding["anyOf"] = [
        {"required": ["available_at_column"]},
        {
            "required": ["conservative_availability_policy", "query_policy"],
            "properties": {
                "query_policy": {
                    "required": ["as_of_required"],
                    "properties": {"as_of_required": {"const": False}},
                }
            },
        },
    ]


def build_schema() -> dict[str, Any]:
    schema = TwinGraph.model_json_schema(by_alias=True)
    schema = {"$schema": SCHEMA_DRAFT, "$id": SCHEMA_ID, **schema}
    schema["title"] = "TwinGraph 0.1"
    schema["description"] = (
        "Canonical JSON Schema for a twingraph/0.1 decision-twin document. "
        "Open-source IR (Apache-2.0). Source of truth: the pydantic models in "
        "the `twingraph` package."
    )
    defs = schema.get("$defs", {})
    _add_constraint_oneof(defs)
    _add_binding_oneof(defs)
    return schema


def dumps() -> str:
    return json.dumps(build_schema(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.stdout.write(dumps())
