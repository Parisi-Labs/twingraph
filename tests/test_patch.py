import pytest
import twingraph as tg
from twingraph import (
    Constraint,
    SemanticPatch,
    TwinGraph,
    apply_patch,
)
from twingraph.errors import ImmutableGraphError, OutOfOrderPatchError, TwinGraphError
from twingraph.patch import PatchStatus
from twingraph.primitives import ConstraintExpression


def _draft(demo_doc) -> TwinGraph:
    # The example is 'active'; make a draft copy so material edits are allowed.
    doc = dict(demo_doc)
    doc["status"] = "draft"
    return TwinGraph.load(doc)


def test_set_property_and_add_constraint(demo_doc, model_registry):
    g = _draft(demo_doc)
    base_version = g.version_id
    base_hash = g.compute_content_hash()

    patch = SemanticPatch(
        base_version_id=g.version_id,
        intent="raise degradation cost and add a terminal-reserve constraint",
        created_by="tester",
        operations=[
            {"op": "set_property", "entity_id": "bat", "key": "degradation_cost_per_mwh", "value": 5.0},
            {
                "op": "add_constraint",
                "constraint": Constraint(
                    id="c_reserve_extra",
                    name="Extra terminal reserve",
                    **{"class": "soft_risk"},
                    expression=ConstraintExpression(value="soc >= 0"),
                ),
            },
        ],
    )

    new_g, report = apply_patch(g, patch)

    assert new_g.version_id != base_version
    assert new_g.parent_version_id == base_version
    assert new_g.status == "draft"
    assert new_g.compute_content_hash() != base_hash
    assert new_g.entity("bat").properties["degradation_cost_per_mwh"] == 5.0
    assert new_g.by_id("c_reserve_extra").class_ == "soft_risk"
    assert report.status == PatchStatus.applied
    assert report.applied_ops == 2
    assert new_g.provenance["applied_patch_id"] == patch.patch_id

    # Original is untouched (pure/functional).
    assert g.entity("bat").properties["degradation_cost_per_mwh"] == 2.0


def test_base_version_mismatch_rejected(demo_doc):
    g = _draft(demo_doc)
    patch = SemanticPatch(
        base_version_id="01JZWRONGBASE0000000000000",
        intent="x",
        created_by="tester",
        operations=[{"op": "set_property", "entity_id": "bat", "key": "dt_h", "value": 0.5}],
    )
    with pytest.raises(OutOfOrderPatchError):
        apply_patch(g, patch)


def test_active_graph_material_edit_rejected(demo_doc):
    g = TwinGraph.load(demo_doc)  # status active
    patch = SemanticPatch(
        base_version_id=g.version_id,
        intent="mutate frozen",
        created_by="tester",
        operations=[{"op": "set_property", "entity_id": "bat", "key": "dt_h", "value": 0.5}],
    )
    with pytest.raises(ImmutableGraphError):
        apply_patch(g, patch)


def test_op_order_matters(demo_doc):
    g = _draft(demo_doc)
    patch = SemanticPatch(
        base_version_id=g.version_id,
        intent="add then remove must succeed; remove-before-add must fail",
        created_by="tester",
        operations=[
            {
                "op": "add_constraint",
                "constraint": Constraint(
                    id="c_tmp",
                    name="tmp",
                    **{"class": "informational"},
                    expression=ConstraintExpression(value="soc >= 0"),
                ),
            },
            {"op": "remove_constraint", "constraint_id": "c_tmp"},
        ],
    )
    new_g, _ = apply_patch(g, patch)
    with pytest.raises(KeyError):
        new_g.by_id("c_tmp")

    # Reverse order: remove before add -> the remove fails (id not present).
    bad = SemanticPatch(
        base_version_id=g.version_id,
        intent="bad order",
        created_by="tester",
        operations=[
            {"op": "remove_constraint", "constraint_id": "c_tmp2"},
            {
                "op": "add_constraint",
                "constraint": Constraint(
                    id="c_tmp2",
                    name="tmp2",
                    **{"class": "informational"},
                    expression=ConstraintExpression(value="soc >= 0"),
                ),
            },
        ],
    )
    with pytest.raises(TwinGraphError):
        apply_patch(g, bad)


def test_recompile_after_apply_ok(demo_doc, model_registry):
    g = _draft(demo_doc)
    patch = SemanticPatch(
        base_version_id=g.version_id,
        intent="bump degradation",
        created_by="tester",
        operations=[
            {"op": "set_property", "entity_id": "bat", "key": "degradation_cost_per_mwh", "value": 3.0}
        ],
    )
    new_g, _ = apply_patch(g, patch)
    res = tg.compile_graph(
        new_g, type_registry=tg.BUILTIN_TYPE_REGISTRY, model_registry=model_registry
    )
    assert res.ok, [d.message for d in res.report.errors()]
    comp = next(
        c for c in res.plan.components if c.model_ref.endswith("battery_linear@1.0.0")
    )
    assert comp.params["_entity_properties"]["degradation_cost_per_mwh"] == 3.0
