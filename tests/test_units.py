"""Extensible UnitRegistry tests (§1 unit-registry)."""

from __future__ import annotations

import twingraph as tg
from twingraph.units import (
    DEFAULT_UNIT_REGISTRY,
    UNIT_TABLE_VERSION,
    CANONICAL_UNITS,
    UnitRegistry,
)

from helpers import build_solar_twin


def _compile(graph, model_registry, **kw):
    return tg.compile_graph(
        graph,
        type_registry=tg.BUILTIN_TYPE_REGISTRY,
        model_registry=model_registry,
        **kw,
    )


def test_default_table_and_version_unchanged():
    # The default table is now the operational core table, but intentionally still
    # excludes arbitrary adopter-specific units such as cycles.
    assert UNIT_TABLE_VERSION == "ucum-subset/0.3"
    assert DEFAULT_UNIT_REGISTRY.is_known("kV")
    assert DEFAULT_UNIT_REGISTRY.is_known("request/s")
    assert DEFAULT_UNIT_REGISTRY.is_known("USD/MW")
    assert DEFAULT_UNIT_REGISTRY.is_known("count")
    assert DEFAULT_UNIT_REGISTRY.compatible("kW", "MW")
    assert DEFAULT_UNIT_REGISTRY.compatible("$/MW", "USD/MW")
    assert DEFAULT_UNIT_REGISTRY.compatible("probability", "ratio")
    assert "cycles" not in CANONICAL_UNITS
    assert not DEFAULT_UNIT_REGISTRY.is_known("cycles")


def test_unregistered_domain_unit_errors_under_default(model_registry):
    # A solar twin whose generation var uses an unknown domain unit 'cycles'
    # fails under the default registry (TG_UNKNOWN_UNIT).
    solar = build_solar_twin()
    solar.variables[0].unit = "cycles"
    solar.data_bindings[0].unit = "cycles"
    res = _compile(solar, model_registry)
    assert not res.ok
    codes = {d.code for d in res.report.errors()}
    assert tg.CODES.UNKNOWN_UNIT in codes


def test_same_twin_compiles_clean_with_registered_unit(model_registry):
    # Register 'cycles' into a fresh registry; the same twin now compiles clean
    # and the data_binding in 'cycles' validates compatible with the variable.
    solar = build_solar_twin()
    solar.variables[0].unit = "cycles"
    solar.data_bindings[0].unit = "cycles"

    registry = UnitRegistry()
    registry.register_canonical("cycles")
    res = _compile(solar, model_registry, unit_registry=registry)
    assert res.ok, [d.message for d in res.report.errors()]
    codes = {d.code for d in res.report.errors()}
    assert tg.CODES.UNKNOWN_UNIT not in codes
    assert tg.CODES.UNIT_MISMATCH not in codes


def test_registry_alias_folds_to_canonical():
    registry = UnitRegistry()
    registry.register_canonical("cycles")
    registry.register_alias("cyc", "cycles", 1.0)
    assert registry.is_known("cyc")
    assert registry.compatible("cyc", "cycles")
    assert registry.normalize("cyc") == ("cycles", 1.0)


def test_default_free_functions_delegate():
    assert tg.units_compatible("MWh", "MW.h")
    assert tg.normalize_unit("kWh") == ("MW.h", 1e-3)
    assert tg.units_compatible("USD/MMBtu", "$/MMBtu")
    assert tg.units_compatible("W.h/m^2", "W.h/m2")
