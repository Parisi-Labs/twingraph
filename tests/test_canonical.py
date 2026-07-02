from datetime import UTC, datetime

from twingraph import TwinGraph, canonicalize, content_hash
from twingraph.canonical import canonical_json, hash_input


def _g(doc: dict) -> TwinGraph:
    return TwinGraph.load(doc)


def test_hash_is_key_order_independent():
    a = {"b": 1, "a": [3, 2, 1], "c": {"y": 1, "x": 2}}
    b = {"c": {"x": 2, "y": 1}, "a": [3, 2, 1], "b": 1}
    assert content_hash(a) == content_hash(b)
    assert canonical_json(a) == canonical_json(b)


def test_hash_changes_with_content():
    assert content_hash({"a": 1}) != content_hash({"a": 2})


def test_twingraph_roundtrip_and_hash(demo_doc):
    g = _g(demo_doc)
    dumped = g.model_dump(mode="json")
    again = TwinGraph.model_validate(dumped)
    assert again.compute_content_hash() == g.compute_content_hash()
    assert g.compute_content_hash().startswith("sha256:")


def test_canonicalize_sorts_lists_by_id():
    doc = {"entities": [{"id": "z"}, {"id": "a"}, {"id": "m"}]}
    out = canonicalize(doc)
    assert [e["id"] for e in out["entities"]] == ["a", "m", "z"]


def test_reorder_lists_hashes_equal(demo_doc):
    g1 = _g(demo_doc)
    doc2 = g1.model_dump(mode="json")
    doc2["entities"] = list(reversed(doc2["entities"]))
    doc2["constraints"] = list(reversed(doc2["constraints"]))
    h1 = content_hash(hash_input(g1.model_dump(mode="json")))
    h2 = content_hash(hash_input(doc2))
    assert h1 == h2


def test_respell_units_hashes_equal(demo_doc):
    g1 = _g(demo_doc)
    doc2 = g1.model_dump(mode="json")
    # Respell MW.h -> MWh on the soc variable + binding.
    for v in doc2["variables"]:
        if v["unit"] == "MW.h":
            v["unit"] = "MWh"
    h1 = content_hash(hash_input(g1.model_dump(mode="json")))
    h2 = content_hash(hash_input(doc2))
    assert h1 == h2


def test_reversion_and_retime_hash_equal(demo_doc):
    """A fresh version of an unchanged graph hashes equal to its parent."""
    g1 = _g(demo_doc)
    doc2 = g1.model_dump(mode="json")
    doc2["version_id"] = "01JZNEWVERSION00000000000000"
    doc2["created_at"] = "2099-01-01T00:00:00Z"
    doc2["content_hash"] = "sha256:deadbeef"
    assert content_hash(hash_input(g1.model_dump(mode="json"))) == content_hash(hash_input(doc2))


def test_value_change_flips_hash(demo_doc):
    g1 = _g(demo_doc)
    doc2 = g1.model_dump(mode="json")
    doc2["entities"][0]["properties"]["power_max_mw"] = 99.0
    assert content_hash(hash_input(g1.model_dump(mode="json"))) != content_hash(hash_input(doc2))


def test_time_normalized_to_utc_z():
    doc = {"created_at": "2026-06-20T10:00:00-04:00"}
    out = canonicalize(doc)
    assert out["created_at"] == "2026-06-20T14:00:00Z"


def test_compute_content_hash_excludes_volatile_fields(demo_doc):
    # Load as a DRAFT so the graph is mutable (an active doc freezes on load).
    draft = {**demo_doc, "status": "draft"}
    draft.pop("content_hash", None)
    g = _g(draft)
    h = g.compute_content_hash()
    # Mutating created_at / version_id must not change the hash.
    g.created_at = datetime(2050, 1, 1, tzinfo=UTC)
    g.version_id = "01JZZZZZZZZZZZZZZZZZZZZZZZZ0"
    assert g.compute_content_hash() == h
