import pytest
from pydantic import ValidationError
from twingraph import (
    Action,
    Constraint,
    DataBinding,
    Entity,
    ModelBinding,
    Objective,
    Relation,
    TwinGraph,
    Variable,
)
from twingraph.primitives import (
    ConstraintEvaluator,
    ConstraintExpression,
    DataSource,
    ObjectiveAggregation,
    ObjectiveTerm,
    QueryPolicy,
)


def test_entity_positive():
    e = Entity(id="bat", type_ref="metis.energy.Battery@1", name="BESS")
    assert e.confirmation_state.value == "confirmed"
    assert e.lifecycle_state.value == "active"


def test_entity_bad_type_ref_rejected():
    with pytest.raises(ValidationError):
        Entity(id="bat", type_ref="NOT-A-TYPE-REF", name="BESS")


def test_extra_forbidden_on_entity():
    with pytest.raises(ValidationError):
        Entity(id="bat", type_ref="metis.energy.Battery@1", name="BESS", bogus=1)


def test_relation_uses_spec_field_names():
    r = Relation(id="r", type_ref="connected_to", source_entity_id="a", target_entity_id="b")
    assert r.source_entity_id == "a"


def test_relation_type_ref_contract_moved_from_parse_to_compile():
    # As of 0.2 the relation vocabulary is registry-resolved, not a closed
    # parse-time Literal. Two halves of the moved contract:
    # (a) a STRUCTURALLY-malformed type_ref still ValidationErrors at parse.
    for bad in ("Bad-Type!", "Uppercase", "has space", "1leading_digit"):
        with pytest.raises(ValidationError):
            Relation(id="r", type_ref=bad, source_entity_id="a", target_entity_id="b")
    # (b) a well-formed-but-unregistered verb now PARSES (it is resolved against
    # the registry at compile, where an unknown one errors TG_UNKNOWN_TYPE).
    r = Relation(
        id="r", type_ref="never_registered_verb", source_entity_id="a", target_entity_id="b"
    )
    assert r.type_ref == "never_registered_verb"
    # A namespaced foreign ref is also accepted at parse.
    r2 = Relation(
        id="r2", type_ref="acme.logistics.ships_to@1", source_entity_id="a", target_entity_id="b"
    )
    assert r2.type_ref == "acme.logistics.ships_to@1"


def test_variable_role_and_owner():
    v = Variable(id="soc", owner_ref="bat", name="state_of_charge", role="state", unit="MW.h")
    assert v.role == "state"


def test_data_binding_availability_root_validator_requires_availability():
    # Missing available_at_column AND as_of_required True (default) -> reject.
    with pytest.raises(ValidationError):
        DataBinding(
            id="db",
            variable_id="price",
            source=DataSource(semantic_view="fixture:x"),
            event_time_column="t",
            value_column="p",
            unit="USD/MW.h",
        )


def test_data_binding_conservative_policy_path_ok():
    b = DataBinding(
        id="db",
        variable_id="price",
        source=DataSource(semantic_view="fixture:x"),
        event_time_column="t",
        value_column="p",
        unit="USD/MW.h",
        query_policy=QueryPolicy(as_of_required=False),
        conservative_availability_policy="assume published at event_time + 1h, justified offline",
    )
    assert b.available_at_column is None


def test_data_binding_with_availability_column_ok():
    b = DataBinding(
        id="db",
        variable_id="price",
        source=DataSource(semantic_view="fixture:x"),
        event_time_column="t",
        available_at_column="pub",
        value_column="p",
        unit="USD/MW.h",
    )
    assert b.available_at_column == "pub"


def test_constraint_expression_xor_evaluator_both_rejected():
    with pytest.raises(ValidationError):
        Constraint(
            id="c",
            name="x",
            **{"class": "hard_physical"},
            expression=ConstraintExpression(value="soc >= 0"),
            evaluator_ref=ConstraintEvaluator(pattern_ref="soc_bounds"),
        )


def test_constraint_neither_rejected():
    with pytest.raises(ValidationError):
        Constraint(id="c", name="x", **{"class": "hard_physical"})


def test_constraint_class_alias_roundtrip():
    c = Constraint(
        id="c",
        name="x",
        **{"class": "hard_physical"},
        expression=ConstraintExpression(value="soc >= 0"),
    )
    dumped = c.model_dump(by_alias=True)
    assert dumped["class"] == "hard_physical"
    again = Constraint.model_validate(dumped)
    assert again.class_ == "hard_physical"


def test_objective_lambda_alias():
    o = Objective(
        id="o",
        name="x",
        terms=[ObjectiveTerm(id="t", direction="maximize", measure_ref="metric:ev")],
        aggregation=ObjectiveAggregation.model_validate(
            {"kind": "expected_value_plus_risk", "risk_measure": "CVaR", "alpha": 0.1, "lambda": 0.5}
        ),
    )
    assert o.aggregation.lambda_ == 0.5
    assert o.aggregation.model_dump(by_alias=True)["lambda"] == 0.5


def test_legacy_alias_normalization(demo_doc):
    # Re-spell the loaded demo back to legacy names and ensure load() folds them.
    # Editing forks a draft, so drop the active doc's identity hash/status.
    doc = demo_doc
    doc.pop("content_hash", None)
    doc["status"] = "draft"
    # Convert one relation + variable + action + validator to legacy spelling.
    doc["relations"].append(
        {"id": "r_legacy", "type_ref": "connects_to", "source_id": "bat", "target_id": "node"}
    )
    doc["variables"].append(
        {"id": "v_legacy", "entity_id": "bat", "name": "aux", "kind": "derived", "unit": "MW"}
    )
    g = TwinGraph.load(doc)
    rel = g.by_id("r_legacy")
    assert rel.type_ref == "connected_to"
    assert rel.source_entity_id == "bat"
    var = g.by_id("v_legacy")
    assert var.owner_ref == "bat"
    assert var.role == "derived"


def test_model_binding_ref_pattern():
    mb = ModelBinding(
        id="mb",
        kind="native_component",
        model_ref="registry://metis.components.battery_linear@1.0.0",
    )
    assert mb.kind == "native_component"
    with pytest.raises(ValidationError):
        ModelBinding(id="mb", kind="native_component", model_ref="not-a-registry-ref")


def test_action_uses_controller_field():
    a = Action(id="a", name="dispatch", target_entity_id="bat", controller_entity_id="bat")
    assert a.requires_approval is True
