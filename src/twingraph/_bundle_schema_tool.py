"""Emit the public JSON Schema for the graph-bundle envelope."""

from __future__ import annotations

import json

from .layers import GraphBundle

SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID = "https://twingraph.parisi-labs.com/schema/twingraph-bundle-0.1.schema.json"


def build_bundle_schema() -> dict:
    schema = GraphBundle.model_json_schema()
    schema = {"$schema": SCHEMA_DRAFT, "$id": SCHEMA_ID, **schema}
    schema["title"] = "TwinGraph Bundle 0.1"
    schema["description"] = (
        "Graph-layer, overlay, and cross-graph association envelope for "
        "independently versioned TwinGraph documents."
    )
    return schema


def dumps() -> str:
    return json.dumps(build_bundle_schema(), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.stdout.write(dumps())
