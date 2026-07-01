"""Canonical serialization and content hashing for TwinGraph documents.

Pure-stdlib on purpose: this module is part of the open-source ``twingraph``
core and must carry no proprietary dependencies. The canonical form is the
single source of truth for hashing, versioning, and validation (spec §9.2).

Canonicalization (§9.2):
  (a) stable-id array sort — each top-level list sorted by ``id``; objective
      terms by term id; mutual_exclusion inner groups sorted. ``grain`` is left
      as authored (its order is semantic).
  (b) unit normalization — UCUM equivalence classes folded to canonical
      spelling (MWh -> MW.h, USD/MWh -> USD/MW.h) on every unit field.
  (c) float normalization — JSON's default repr-stable encoding.
  (d) RFC-3339 time — timestamps normalized to a UTC 'Z' canonical form.
  (e) unknown fields are rejected at the model layer, never here.

The HASH is *semantic identity*: two semantically-identical graphs hash equal
regardless of when they were authored or which version they are. Lineage lives
in ``version_id`` + ``parent_version_id``. Hence ``content_hash``,
``created_at``, and ``version_id`` are excluded from the hash input.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "twingraph/0.1"

# Fields excluded from the content-hash input (the hash-volatility set, §9.2).
HASH_EXCLUDED_FIELDS = frozenset({"content_hash", "created_at", "version_id"})

# Top-level document lists sorted by stable id during canonicalization.
_ID_SORTED_LISTS = (
    "entities",
    "relations",
    "variables",
    "data_bindings",
    "model_bindings",
    "actions",
    "constraints",
    "objectives",
    "validators",
    "evidence",
)

# Keys whose *value* is a unit string and should be unit-normalized.
_UNIT_KEYS = frozenset({"unit", "to_unit", "from_unit"})

# Keys whose value is an RFC-3339 timestamp.
_TIME_KEYS = frozenset({"created_at", "event_time", "available_at", "issue_time", "applied_at"})


def canonical_json(obj: Any) -> str:
    """Return the canonical JSON encoding of ``obj``.

    Rules (subset of §9.2, enough for hashing to be order-independent):
      * object keys sorted lexicographically
      * no insignificant whitespace
      * UTF-8, with non-ASCII preserved rather than escaped
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(obj: Any) -> str:
    """Return ``sha256:<hex>`` over the canonical encoding of ``obj``."""
    digest = hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _normalize_unit_str(u: str) -> str:
    # Local import to keep canonical.py importable in isolation.
    from .units import normalize_unit

    canonical, _scale = normalize_unit(u)
    return canonical


def _normalize_time_str(t: str) -> str:
    """Fold an RFC-3339 timestamp to canonical UTC 'Z' form when parseable."""
    if not isinstance(t, str):
        return t
    raw = t
    try:
        s = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
        out = dt.isoformat().replace("+00:00", "Z")
        return out
    except (ValueError, TypeError):
        return raw


def _canon_value(key: str | None, value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _canon_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_canon_value(None, v) for v in value]
    if isinstance(value, str):
        if key in _UNIT_KEYS:
            return _normalize_unit_str(value)
        if key in _TIME_KEYS:
            return _normalize_time_str(value)
    return value


def _sort_key(item: Any) -> tuple[int, str]:
    """Sort dicts by their ``id`` field; non-dicts fall back to repr."""
    if isinstance(item, dict) and "id" in item and isinstance(item["id"], str):
        return (0, item["id"])
    return (1, json.dumps(item, sort_keys=True, default=str))


def canonicalize(doc: dict) -> dict:
    """Return a canonical copy of a TwinGraph document dict (§9.2).

    Pure/functional: never mutates ``doc``. Applies unit + time normalization
    everywhere, then stable-id sorts the top-level lists, objective terms, and
    mutual_exclusion groups.
    """
    out = _canon_value(None, doc)

    for list_key in _ID_SORTED_LISTS:
        seq = out.get(list_key)
        if isinstance(seq, list):
            out[list_key] = sorted(seq, key=_sort_key)

    # Objective terms sort by their own id; action mutual_exclusion groups sort.
    for obj in out.get("objectives", []) or []:
        if isinstance(obj, dict) and isinstance(obj.get("terms"), list):
            obj["terms"] = sorted(obj["terms"], key=_sort_key)

    for action in out.get("actions", []) or []:
        if isinstance(action, dict) and isinstance(action.get("mutual_exclusion"), list):
            action["mutual_exclusion"] = [
                sorted(group) if isinstance(group, list) else group
                for group in action["mutual_exclusion"]
            ]

    return out


def hash_input(doc: dict) -> dict:
    """Return the canonical doc with the hash-volatility set removed."""
    canon = canonicalize(doc)
    return {k: v for k, v in canon.items() if k not in HASH_EXCLUDED_FIELDS}
