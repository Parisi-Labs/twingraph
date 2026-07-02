"""UCUM-subset unit model for TwinGraph (spec §9.2 / §9.5).

A hand-maintained operational unit vocabulary with alias folding to a canonical
spelling. It is deliberately NOT a full UCUM parser -- that remains out of the
dependency-clean budget -- but the default table is broad enough for power,
industrial facilities, data centers, ports, logistics, and supply-chain twins.
stdlib + pydantic only.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

UNIT_TABLE_VERSION = "ucum-subset/0.3"

# Canonical spellings the IR hashes and compiles against.
CANONICAL_UNITS: frozenset[str] = frozenset(
    {
        # Power / energy / economics.
        "MW",
        "MW.h",
        "USD",
        "USD/MW.h",
        "USD/MW",
        "USD/MMBtu",
        "USD/h",
        "USD/item",
        # Electrical engineering.
        "kV",
        "A",
        "MVA",
        "MVAr",
        "Hz",
        "MW/min",
        # Weather / thermal / fuel.
        "W/m2",
        "W.h/m2",
        "m/s",
        "degC",
        "MW_th",
        "ton_refrigeration",
        "MMBtu",
        "MMBtu/h",
        "MMBtu/MW.h",
        "kg/s",
        "m3/s",
        "m3",
        # Operations / logistics / data centers.
        "m",
        "km",
        "tonne",
        "item",
        "item/h",
        "TEU",
        "TEU/h",
        "pallet",
        "container",
        "vehicle",
        "request/s",
        "Gb/s",
        "TB",
        "rack_unit",
        "server",
        "count",
        "%",
        "h",
        "min",
        "s",
        "dimensionless",
        "ratio",
    }
)

# alias -> (canonical_unit, scale_to_canonical)
# A value in the alias unit times ``scale`` yields the value in canonical units.
_ALIASES: dict[str, tuple[str, float]] = {
    # Power / energy.
    "W": ("MW", 1e-6),
    "w": ("MW", 1e-6),
    "kW": ("MW", 1e-3),
    "kw": ("MW", 1e-3),
    "MWh": ("MW.h", 1.0),
    "mwh": ("MW.h", 1.0),
    "MW.h": ("MW.h", 1.0),
    "Wh": ("MW.h", 1e-6),
    "wh": ("MW.h", 1e-6),
    "kWh": ("MW.h", 1e-3),
    "kwh": ("MW.h", 1e-3),
    "MW": ("MW", 1.0),
    "mw": ("MW", 1.0),
    "GW": ("MW", 1e3),
    "GWh": ("MW.h", 1e3),
    "USD/MWh": ("USD/MW.h", 1.0),
    "USD/MW.h": ("USD/MW.h", 1.0),
    "$/MWh": ("USD/MW.h", 1.0),
    "usd/mwh": ("USD/MW.h", 1.0),
    "USD/MW": ("USD/MW", 1.0),
    "$/MW": ("USD/MW", 1.0),
    "usd/mw": ("USD/MW", 1.0),
    "USD/MMBtu": ("USD/MMBtu", 1.0),
    "$/MMBtu": ("USD/MMBtu", 1.0),
    "usd/mmbtu": ("USD/MMBtu", 1.0),
    "USD/h": ("USD/h", 1.0),
    "USD/hr": ("USD/h", 1.0),
    "USD/item": ("USD/item", 1.0),
    "USD": ("USD", 1.0),
    "$": ("USD", 1.0),
    # Electrical.
    "V": ("kV", 1e-3),
    "kV": ("kV", 1.0),
    "kv": ("kV", 1.0),
    "A": ("A", 1.0),
    "amp": ("A", 1.0),
    "amps": ("A", 1.0),
    "kA": ("A", 1e3),
    "MVA": ("MVA", 1.0),
    "kVA": ("MVA", 1e-3),
    "MVAr": ("MVAr", 1.0),
    "MVAR": ("MVAr", 1.0),
    "Hz": ("Hz", 1.0),
    "MW/min": ("MW/min", 1.0),
    "MW.h/MW": ("h", 1.0),
    # Weather / thermal / fuel.
    "W/m2": ("W/m2", 1.0),
    "W/m^2": ("W/m2", 1.0),
    "W.h/m2": ("W.h/m2", 1.0),
    "W.h/m^2": ("W.h/m2", 1.0),
    "Wh/m2": ("W.h/m2", 1.0),
    "Wh/m^2": ("W.h/m2", 1.0),
    "m/s": ("m/s", 1.0),
    "degC": ("degC", 1.0),
    "C": ("degC", 1.0),
    "celsius": ("degC", 1.0),
    "MW_th": ("MW_th", 1.0),
    "kW_th": ("MW_th", 1e-3),
    "ton_refrigeration": ("ton_refrigeration", 1.0),
    "TR": ("ton_refrigeration", 1.0),
    "MMBtu": ("MMBtu", 1.0),
    "MMBtu/h": ("MMBtu/h", 1.0),
    "MMBtu/hr": ("MMBtu/h", 1.0),
    "MMBtu/MWh": ("MMBtu/MW.h", 1.0),
    "MMBtu/MW.h": ("MMBtu/MW.h", 1.0),
    "kg/s": ("kg/s", 1.0),
    "m3/s": ("m3/s", 1.0),
    "m^3/s": ("m3/s", 1.0),
    "m3": ("m3", 1.0),
    "m^3": ("m3", 1.0),
    # Operations / logistics / data centers.
    "m": ("m", 1.0),
    "meter": ("m", 1.0),
    "km": ("km", 1.0),
    "kilometer": ("km", 1.0),
    "tonne": ("tonne", 1.0),
    "metric_ton": ("tonne", 1.0),
    "item": ("item", 1.0),
    "items": ("item", 1.0),
    "item/h": ("item/h", 1.0),
    "item/hr": ("item/h", 1.0),
    "items/hour": ("item/h", 1.0),
    "TEU": ("TEU", 1.0),
    "TEU/h": ("TEU/h", 1.0),
    "TEU/hr": ("TEU/h", 1.0),
    "pallet": ("pallet", 1.0),
    "pallets": ("pallet", 1.0),
    "container": ("container", 1.0),
    "containers": ("container", 1.0),
    "vehicle": ("vehicle", 1.0),
    "vehicles": ("vehicle", 1.0),
    "request/s": ("request/s", 1.0),
    "requests/s": ("request/s", 1.0),
    "req/s": ("request/s", 1.0),
    "Gb/s": ("Gb/s", 1.0),
    "Gbps": ("Gb/s", 1.0),
    "TB": ("TB", 1.0),
    "terabyte": ("TB", 1.0),
    "rack_unit": ("rack_unit", 1.0),
    "RU": ("rack_unit", 1.0),
    "server": ("server", 1.0),
    "servers": ("server", 1.0),
    "count": ("count", 1.0),
    "counts": ("count", 1.0),
    # Dimensionless / time.
    "%": ("%", 1.0),
    "percent": ("%", 1.0),
    "h": ("h", 1.0),
    "hr": ("h", 1.0),
    "hour": ("h", 1.0),
    "min": ("min", 1.0),
    "minute": ("min", 1.0),
    "s": ("s", 1.0),
    "sec": ("s", 1.0),
    "second": ("s", 1.0),
    "ratio": ("ratio", 1.0),
    "probability": ("ratio", 1.0),
    "dimensionless": ("dimensionless", 1.0),
    "1": ("dimensionless", 1.0),
}

# ISO-8601 PT-durations are treated as opaque canonical strings (resolution fields).
_ISO_DURATION_PREFIX = "PT"

UNIT_TABLE = dict(_ALIASES)  # exported view of the recognised vocabulary


class UnitRegistry:
    """An extensible unit vocabulary (canonical set + alias→canonical map).

    The free functions (``normalize_unit``/``is_known_unit``/
    ``units_compatible``) delegate to ``DEFAULT_UNIT_REGISTRY``, which is seeded
    from the built-in operational table. Adopters that need a narrower table or
    extra domain units (e.g. ``cycles`` for a PdM twin) construct their own
    ``UnitRegistry``, register the units, and pass it to
    ``compile_graph(unit_registry=…)``.

    The matching logic is byte-for-byte the original module behavior: exact
    alias hit, then exact canonical hit, then ISO-8601 ``PT`` passthrough, then
    unknown → opaque (returned as-is with scale 1.0).
    """

    def __init__(
        self,
        canonical: frozenset[str] | None = None,
        aliases: dict[str, tuple[str, float]] | None = None,
    ) -> None:
        self._canonical: set[str] = set(
            CANONICAL_UNITS if canonical is None else canonical
        )
        self._aliases: dict[str, tuple[str, float]] = dict(
            _ALIASES if aliases is None else aliases
        )

    def register_canonical(self, unit: str) -> None:
        """Add a canonical unit spelling (its own identity alias is implied)."""
        self._canonical.add(unit)

    def register_alias(self, alias: str, canonical: str, scale: float = 1.0) -> None:
        """Map ``alias`` onto a canonical unit (registering it if new)."""
        self._canonical.add(canonical)
        self._aliases[alias] = (canonical, scale)

    def normalize(self, u: str) -> tuple[str, float]:
        if u is None:
            return ("dimensionless", 1.0)
        s = u.strip()
        if s in self._aliases:
            return self._aliases[s]
        if s in self._canonical:
            return (s, 1.0)
        if s.startswith(_ISO_DURATION_PREFIX):
            return (s, 1.0)
        # Unknown unit: return as-is (compile reports the incompatibility).
        return (s, 1.0)

    def is_known(self, u: str) -> bool:
        if u is None:
            return False
        s = u.strip()
        return s in self._aliases or s in self._canonical or s.startswith(_ISO_DURATION_PREFIX)

    def compatible(self, a: str, b: str) -> bool:
        ca, _ = self.normalize(a)
        cb, _ = self.normalize(b)
        return ca == cb


DEFAULT_UNIT_REGISTRY = UnitRegistry()


def normalize_unit(u: str) -> tuple[str, float]:
    """Return ``(canonical_unit, scale)`` for ``u`` via the default registry.

    ``scale`` multiplies a value expressed in ``u`` to express it in the
    canonical unit (e.g. kWh -> MW.h has scale 1e-3). Unknown opaque ISO-8601
    durations pass through unchanged with scale 1.0.
    """
    return DEFAULT_UNIT_REGISTRY.normalize(u)


def is_known_unit(u: str) -> bool:
    """True iff ``u`` folds to a canonical unit (or is an ISO-8601 duration)."""
    return DEFAULT_UNIT_REGISTRY.is_known(u)


def units_compatible(a: str, b: str) -> bool:
    """True iff ``a`` and ``b`` normalize to the same canonical unit."""
    return DEFAULT_UNIT_REGISTRY.compatible(a, b)


class Quantity(BaseModel):
    """A typed scalar with an explicit unit (spec §9.5).

    Properties may carry EITHER a bare scalar OR a Quantity; units are enforced
    at compile against the type registry, not at parse.
    """

    model_config = ConfigDict(extra="forbid")

    value: float
    unit: str
