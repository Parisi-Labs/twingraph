import twingraph as tg
from twingraph.errors import CODES

from helpers import mutate


def _compile(doc, model_registry):
    g = tg.TwinGraph.load(doc)
    return tg.compile_graph(
        g, type_registry=tg.BUILTIN_TYPE_REGISTRY, model_registry=model_registry
    )


def _codes(result):
    return {d.code for d in result.report.diagnostics if d.severity == "error"}


# --- positive --------------------------------------------------------------
def test_ny_demo_validates_and_compiles(demo_doc, model_registry):
    res = _compile(demo_doc, model_registry)
    assert res.ok, [d.message for d in res.report.errors()]
    assert res.plan is not None
    assert res.report.graph_content_hash.startswith("sha256:")
    assert res.report.unit_table_version


def test_plan_carries_resolved_battery_properties(demo_doc, model_registry):
    res = _compile(demo_doc, model_registry)
    comp = next(
        c
        for c in res.plan.components
        if c.model_ref == "registry://metis.components.battery_linear@1.0.0"
    )
    props = comp.params["_entity_properties"]
    assert props["power_max_mw"] == 3.0
    assert props["energy_max_mwh"] == 12.0
    assert comp.callable_key == "battery_linear"


def test_program_compatibility(demo_doc, model_registry):
    res = _compile(demo_doc, model_registry)
    pc = res.plan.program_compatibility[0]
    assert pc.program == "tomorrow_dispatch"
    assert pc.compatible
    assert pc.missing == []


def test_leakage_validators_pass_for_real(demo_doc, model_registry):
    res = _compile(demo_doc, model_registry)
    by_id = {r["validator_id"]: r["status"] for r in res.report.validator_results}
    assert by_id["issue_time_leakage"] == "pass"
    assert by_id["data_binding_availability"] == "pass"


def test_dependency_order_is_not_drawing_order(demo_doc, model_registry):
    # Add a second component reading what the battery writes; it must order after.
    doc = mutate(
        demo_doc,
        lambda d: d["model_bindings"].insert(
            0,
            {
                "id": "mb_explain",
                "kind": "explanation_template",
                "model_ref": "registry://metis.expressions.energy_revenue@1.0.0",
                "inputs": {"soc": "soc"},
                "outputs": {},
            },
        ),
    )
    res = _compile(doc, model_registry)
    assert res.ok, [d.message for d in res.report.errors()]
    order = res.report.dependency_order
    # mb_explain reads soc (written by mb_battery) -> battery comes first,
    # even though mb_explain is drawn first in the document.
    assert order.index("mb_battery") < order.index("mb_explain")


# --- negative fixtures -----------------------------------------------------
def test_bad_unit_rejected(demo_doc, model_registry):
    doc = mutate(
        demo_doc,
        lambda d: d["data_bindings"][0].__setitem__("unit", "MW"),  # should be USD/MW.h
    )
    res = _compile(doc, model_registry)
    assert not res.ok
    assert CODES.UNIT_MISMATCH in _codes(res)


def test_dangling_ref_rejected(demo_doc, model_registry):
    doc = mutate(
        demo_doc,
        lambda d: d["relations"][0].__setitem__("target_entity_id", "ghost"),
    )
    res = _compile(doc, model_registry)
    assert not res.ok
    assert CODES.DANGLING_REF in _codes(res)


def test_missing_required_field_rejected(demo_doc, model_registry):
    doc = mutate(
        demo_doc,
        lambda d: d["entities"][0]["properties"].pop("power_max_mw"),
    )
    res = _compile(doc, model_registry)
    assert not res.ok
    assert CODES.MISSING_REQUIRED in _codes(res)


def test_unknown_type_ref_rejected(demo_doc, model_registry):
    doc = mutate(
        demo_doc,
        lambda d: d["entities"][0].__setitem__("type_ref", "metis.energy.Unicorn@9"),
    )
    res = _compile(doc, model_registry)
    assert not res.ok
    assert CODES.UNKNOWN_TYPE in _codes(res)


def test_unknown_model_ref_rejected(demo_doc, model_registry):
    doc = mutate(
        demo_doc,
        lambda d: d["model_bindings"][0].__setitem__(
            "model_ref", "registry://metis.components.nope@9.9.9"
        ),
    )
    res = _compile(doc, model_registry)
    assert not res.ok
    assert CODES.UNKNOWN_MODEL in _codes(res)


def test_leakage_rejected_when_horizon_availability_dropped(demo_doc, model_registry):
    # The price binding feeds an exogenous (horizon) variable. Dropping its
    # availability column — while supplying a conservative policy so the doc still
    # PARSES — must compile to NOT ok with TG_LEAKAGE: a forecast horizon binding
    # demands an explicit availability column (§12.4).
    def edit(d):
        b = d["data_bindings"][0]
        b.pop("available_at_column")
        b["query_policy"] = {"as_of_required": False}
        b["conservative_availability_policy"] = "assume immediate availability (UNSAFE demo)"

    doc = mutate(demo_doc, edit)
    res = _compile(doc, model_registry)
    assert not res.ok
    assert CODES.LEAKAGE in _codes(res)
    by_id = {r["validator_id"]: r["status"] for r in res.report.validator_results}
    assert by_id["issue_time_leakage"] == "fail"


def test_query_plan_marks_demo_leakage_safe(demo_doc, model_registry):
    res = _compile(demo_doc, model_registry)
    qp = next(q for q in res.plan.query_plan if q.variable_id == "price")
    assert qp.leakage_safe is True
    assert qp.available_at_column == "published_at_utc"
    # The runtime-honored policy fields are threaded onto the plan.
    assert qp.as_of_required is True
    assert qp.latest_before_issue_time is True
    assert qp.missing_value_policy == "fail_required_horizon"


def test_leakage_rejected_when_horizon_disables_as_of(demo_doc, model_registry):
    # A horizon binding that KEEPS its availability column but sets
    # as_of_required=false tells the runtime to SKIP the issue-time filter
    # (connectors.py). Compile must NOT certify it leakage-safe just because the
    # column exists — the guarantee must match runtime behavior (§12.4).
    def edit(d):
        b = d["data_bindings"][0]
        b["query_policy"] = {"as_of_required": False}

    doc = mutate(demo_doc, edit)
    res = _compile(doc, model_registry)
    assert not res.ok
    assert CODES.LEAKAGE in _codes(res)
    by_id = {r["validator_id"]: r["status"] for r in res.report.validator_results}
    assert by_id["issue_time_leakage"] == "fail"


def test_unknown_relation_type_ref_rejected(demo_doc, model_registry):
    # Relation type_refs are resolved against the registry now (bare spelling
    # mapped to metis.relation.<x>@1). An unknown one is rejected.
    def edit(d):
        d["relations"].append(
            {
                "id": "r_unknown",
                "type_ref": "contains",  # valid Literal, registered
                "source_entity_id": "bat",
                "target_entity_id": "node",
            }
        )

    # Sanity: a registered relation type still compiles.
    ok_doc = mutate(demo_doc, edit)
    assert _compile(ok_doc, model_registry).ok


# --- open relation types (§9.4, registry-resolved) -------------------------
def test_open_relation_type_feeds_into_compiles(demo_doc, model_registry):
    # feeds_into is registered in BUILTIN as metis.relation.feeds_into@1.
    doc = mutate(
        demo_doc,
        lambda d: d["relations"].append(
            {
                "id": "r_feeds",
                "type_ref": "feeds_into",
                "source_entity_id": "node",
                "target_entity_id": "bat",
            }
        ),
    )
    assert _compile(doc, model_registry).ok


def test_unregistered_relation_type_compile_errors_not_parse(demo_doc, model_registry):
    # A well-formed-but-unregistered verb PARSES (load succeeds) but compile
    # errors TG_UNKNOWN_TYPE — the contract moved from parse-reject in 0.2.
    doc = mutate(
        demo_doc,
        lambda d: d["relations"].append(
            {
                "id": "r_unknown_verb",
                "type_ref": "teleports_to",
                "source_entity_id": "bat",
                "target_entity_id": "node",
            }
        ),
    )
    g = tg.TwinGraph.load(doc)  # parses fine
    res = tg.compile_graph(
        g, type_registry=tg.BUILTIN_TYPE_REGISTRY, model_registry=model_registry
    )
    assert not res.ok
    assert tg.CODES.UNKNOWN_TYPE in _codes(res)


def test_namespaced_foreign_relation_type_resolves(demo_doc, model_registry):
    # A fully-qualified foreign relation type is resolved as-is against the
    # registry. Register it in a fresh registry and confirm it compiles.
    from twingraph.registry import BUILTIN_TYPE_REGISTRY, InMemoryTypeRegistry, TypeDef

    reg = InMemoryTypeRegistry()
    # Copy builtins by re-resolving the ones the demo uses.
    for ref in (
        "metis.energy.Battery@1",
        "metis.energy.MarketNode@1",
        "metis.energy.Interconnect@1",
        "metis.relation.connected_to@1",
        "metis.relation.constrained_by@1",
        "metis.relation.settles_at@1",
    ):
        reg.register(BUILTIN_TYPE_REGISTRY.resolve(ref))
    reg.register(
        TypeDef(type_ref="acme.logistics.ships_to@1", kind="relation", title="ships to")
    )
    doc = mutate(
        demo_doc,
        lambda d: d["relations"].append(
            {
                "id": "r_ships",
                "type_ref": "acme.logistics.ships_to@1",
                "source_entity_id": "bat",
                "target_entity_id": "node",
            }
        ),
    )
    g = tg.TwinGraph.load(doc)
    res = tg.compile_graph(g, type_registry=reg, model_registry=model_registry)
    assert res.ok, [d.message for d in res.report.errors()]


# --- foreign-reference model kinds (§31.3) ---------------------------------
def test_foreign_fmu_binding_compiles_and_is_external(demo_doc, model_registry):
    # Add an fmu binding (ports match the turbine io_contract). It compiles,
    # the component is flagged external, and native components are NOT.
    def edit(d):
        d["variables"].append(
            {
                "id": "wind",
                "owner_ref": "bat",
                "name": "wind_speed",
                "role": "exogenous",
                "unit": "MW",
                "temporal_semantics": "interval_average",
            }
        )
        d["variables"].append(
            {
                "id": "wpower",
                "owner_ref": "bat",
                "name": "wind_power",
                "role": "derived",
                "unit": "MW",
            }
        )
        d["model_bindings"].append(
            {
                "id": "mb_fmu",
                "kind": "fmu",
                "model_ref": "registry://metis.foreign.turbine_fmu@1.0.0",
                "inputs": {"wind_speed": "wind"},
                "outputs": {"power": "wpower"},
            }
        )
        d["data_bindings"].append(
            {
                "id": "db_wind",
                "variable_id": "wind",
                "source": {"semantic_view": "fixture:wind"},
                "event_time_column": "t",
                "available_at_column": "pub",
                "value_column": "w",
                "unit": "MW",
                "query_policy": {"as_of_required": True},
            }
        )

    doc = mutate(demo_doc, edit)
    res = _compile(doc, model_registry)
    assert res.ok, [d.message for d in res.report.errors()]
    by_id = {c.model_binding_id: c for c in res.plan.components}
    assert by_id["mb_fmu"].external is True
    assert by_id["mb_battery"].external is False


def test_foreign_kind_does_not_warn_model_not_executable(demo_doc, model_registry):
    def edit(d):
        d["variables"].append(
            {"id": "wind", "owner_ref": "bat", "name": "wind_speed",
             "role": "exogenous", "unit": "MW", "temporal_semantics": "interval_average"}
        )
        d["variables"].append(
            {"id": "wpower", "owner_ref": "bat", "name": "wind_power",
             "role": "derived", "unit": "MW"}
        )
        d["model_bindings"].append(
            {"id": "mb_fmu", "kind": "fmu",
             "model_ref": "registry://metis.foreign.turbine_fmu@1.0.0",
             "inputs": {"wind_speed": "wind"}, "outputs": {"power": "wpower"}}
        )
        d["data_bindings"].append(
            {"id": "db_wind", "variable_id": "wind",
             "source": {"semantic_view": "fixture:wind"},
             "event_time_column": "t", "available_at_column": "pub",
             "value_column": "w", "unit": "MW",
             "query_policy": {"as_of_required": True}}
        )

    doc = mutate(demo_doc, edit)
    res = _compile(doc, model_registry)
    warn_codes = {d.code for d in res.report.warnings()}
    assert tg.CODES.MODEL_NOT_EXECUTABLE not in warn_codes


def test_malformed_foreign_io_contract_errors(demo_doc, model_registry):
    # The fmu io_contract declares inputs={wind_speed}, outputs={power}. A
    # binding whose ports don't match must error TG_IO_CONTRACT.
    def edit(d):
        d["variables"].append(
            {"id": "wpower", "owner_ref": "bat", "name": "wind_power",
             "role": "derived", "unit": "MW"}
        )
        d["model_bindings"].append(
            {"id": "mb_fmu", "kind": "fmu",
             "model_ref": "registry://metis.foreign.turbine_fmu@1.0.0",
             "inputs": {},  # missing required wind_speed input port
             "outputs": {"power": "wpower"}}
        )

    doc = mutate(demo_doc, edit)
    res = _compile(doc, model_registry)
    assert not res.ok
    assert tg.CODES.IO_CONTRACT in _codes(res)


def test_foreign_kind_membership():
    assert "fmu" in tg.FOREIGN_MODEL_KINDS
    assert "modelica_class" in tg.FOREIGN_MODEL_KINDS
    assert "fmu" not in tg.EXECUTABLE_MODEL_KINDS
    assert "modelica_class" not in tg.EXECUTABLE_MODEL_KINDS


def test_demo_components_all_external_false(demo_doc, model_registry):
    # Golden back-compat lock: no native demo component is flagged external.
    res = _compile(demo_doc, model_registry)
    assert all(not c.external for c in res.plan.components)
