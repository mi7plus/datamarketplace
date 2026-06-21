# app/keys.py
#
# Single source of truth for the dedup key hash used across all modes (S5
# dedup-evasion hardening). Keys are NORMALIZED before hashing — trimmed, case-
# folded, internal whitespace collapsed, and type-coerced — so trivial near-dupes
# ("Acme  Inc" vs "acme inc", 5 vs "5") collapse to the same hash and can't slip
# the exact-key dedup. Every source (upload ingest, collect finalize, cross-mode
# catalog fill) MUST compute keys through here so they resolve to each other.

import hashlib
import re

_WS = re.compile(r"\s+")


def normalize_value(v) -> str:
    s = "" if v is None else str(v)
    s = s.strip().lower()
    s = _WS.sub(" ", s)
    return s


def normalized_key(row: dict, unique_key: list[str]) -> tuple:
    """The normalized key tuple for a record under the declared unique_key."""
    return tuple(normalize_value(row.get(k, "")) for k in unique_key)


def key_hash(row: dict, unique_key: list[str]) -> str:
    """Stable SHA-256 of a record's normalized key tuple."""
    return hashlib.sha256(repr(normalized_key(row, unique_key)).encode()).hexdigest()
