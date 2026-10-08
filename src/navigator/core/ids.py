"""Stable identifiers. Nothing here uses randomness, wall-clock time, or amounts/dates."""

from __future__ import annotations

import hashlib
import re
import unicodedata

from navigator.core.evidence import normalize_text

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.:/-]{0,199}$")


def slugify(text: str, max_len: int = 80) -> str:
    """ASCII slug: ``'Métis Nation (BC)'`` -> ``'metis_nation_bc'``."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "_", folded.lower()).strip("_")
    return slug[:max_len].strip("_") or "item"


def is_valid_id(value: str) -> bool:
    return bool(_ID_PATTERN.match(value))


def make_opportunity_id(namespace: str, native_key: str) -> str:
    """``indspire`` + ``'Jane Doe Award'`` -> ``indspire:jane_doe_award``."""
    return f"{slugify(namespace, 40)}:{slugify(native_key, 140)}"


def snapshot_id_for(raw_sha256: str) -> str:
    return "snap_" + raw_sha256[:20]


def evidence_id(field_path: str, snapshot_id: str, quote: str) -> str:
    """Same snapshot + field + quote always yields the same id."""
    material = "\x1f".join([field_path, snapshot_id, normalize_text(quote)])
    return "ev_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
