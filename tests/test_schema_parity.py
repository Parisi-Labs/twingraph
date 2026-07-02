"""Schema parity: the committed JSON Schema must validate the corpus, round-trip
the models, and stay in sync with the pydantic source of truth (the
``make schema-check`` drift guard, asserted as a test).
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from twingraph import TwinGraph
from twingraph._schema_tool import build_schema

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schema" / "twingraph-0.1.schema.json"
)
_EXAMPLE_PATH = (
    Path(__file__).resolve().parents[1] / "examples" / "ny_demo_bess_01.twingraph.json"
)


def _committed_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text())


def test_committed_schema_matches_models():
    """The committed schema is byte-identical to a fresh emit (no drift)."""
    fresh = build_schema()
    committed = _committed_schema()
    assert committed == fresh, (
        "twingraph schema is stale — run `make schema` to regenerate it"
    )


def test_committed_schema_validates_demo_corpus(demo_doc):
    schema = _committed_schema()
    # The demo is already in spec shape; validate as-is.
    jsonschema.validate(instance=demo_doc, schema=schema)


def test_committed_schema_validates_public_example_file():
    schema = _committed_schema()
    jsonschema.validate(instance=json.loads(_EXAMPLE_PATH.read_text()), schema=schema)


def test_demo_roundtrips_through_models(demo_doc):
    g = TwinGraph.load(demo_doc)
    dumped = g.model_dump(mode="json", by_alias=True)
    again = TwinGraph.model_validate(dumped)
    assert again.compute_content_hash() == g.compute_content_hash()


def test_schema_has_draft_and_id():
    schema = _committed_schema()
    assert schema["$schema"].endswith("2020-12/schema")
    assert schema["$id"].endswith("twingraph-0.1.schema.json")
    assert schema["title"] == "TwinGraph 0.1"


def test_constraint_oneof_present():
    schema = _committed_schema()
    constraint = schema["$defs"]["Constraint"]
    assert "oneOf" in constraint
    assert len(constraint["oneOf"]) == 2


def test_binding_availability_anyof_present():
    schema = _committed_schema()
    binding = schema["$defs"]["DataBinding"]
    assert "anyOf" in binding


def test_binding_schema_requires_as_of_disabled_for_conservative_policy(demo_doc):
    schema = _committed_schema()
    bad = json.loads(json.dumps(demo_doc))
    binding = bad["data_bindings"][0]
    binding.pop("available_at_column")
    binding["conservative_availability_policy"] = "source publishes before operation"
    binding["query_policy"]["as_of_required"] = True

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=schema)


def test_binding_schema_rejects_implicit_as_of_default_for_conservative_policy(demo_doc):
    schema = _committed_schema()
    bad = json.loads(json.dumps(demo_doc))
    binding = bad["data_bindings"][0]
    binding.pop("available_at_column")
    binding.pop("query_policy")
    binding["conservative_availability_policy"] = "source publishes before operation"

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=schema)
