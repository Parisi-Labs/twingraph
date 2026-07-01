"""Pure-stdlib ULID generation and validation (spec §9, "IDs SHOULD use ULIDs").

A ULID is a 128-bit identifier: 48 bits of millisecond timestamp followed by
80 bits of randomness, rendered as 26 Crockford-Base32 characters. Sortable by
creation time, globally unique, no third-party dependency.

This module is part of the open-source ``twingraph`` core: stdlib only.
"""

from __future__ import annotations

import os
import re
import threading
import time

# Crockford's Base32 alphabet: excludes I, L, O, U to avoid transcription errors.
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_CROCKFORD_INDEX = {c: i for i, c in enumerate(CROCKFORD)}

ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")

# Type alias — a ULID is just a string on the wire.
Ulid = str

# Process-monotonic state so ULIDs minted within the same millisecond still sort.
_lock = threading.Lock()
_last_ms = -1
_last_rand = 0

_TIME_MAX = (1 << 48) - 1
_RAND_MAX = (1 << 80) - 1


def _encode(value: int, length: int) -> str:
    """Encode ``value`` as ``length`` Crockford-Base32 chars (big-endian)."""
    chars = []
    for _ in range(length):
        chars.append(CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def new_ulid() -> str:
    """Return a fresh, process-monotonic 26-char Crockford-Base32 ULID."""
    global _last_ms, _last_rand
    with _lock:
        now_ms = int(time.time() * 1000) & _TIME_MAX
        if now_ms <= _last_ms:
            # Same (or backwards) millisecond: increment randomness to stay monotonic.
            now_ms = _last_ms
            rand = (_last_rand + 1) & _RAND_MAX
            if rand == 0:  # randomness overflow — bump the timestamp.
                now_ms = (_last_ms + 1) & _TIME_MAX
                rand = int.from_bytes(os.urandom(10), "big") & _RAND_MAX
        else:
            rand = int.from_bytes(os.urandom(10), "big") & _RAND_MAX
        _last_ms = now_ms
        _last_rand = rand
    return _encode(now_ms, 10) + _encode(rand, 16)


def validate_ulid(s: str) -> bool:
    """Return True iff ``s`` is a syntactically valid 26-char ULID."""
    return isinstance(s, str) and bool(ULID_RE.match(s))
