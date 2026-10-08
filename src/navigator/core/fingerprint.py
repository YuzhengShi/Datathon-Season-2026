"""Canonical content fingerprint of an opportunity record.

The fingerprint covers *business content* only. Fetch times and workflow status
(review/publication/verification) are excluded, so re-importing the same facts after a
fresh download is ``unchanged`` while a real change in any fact, rule, amount, deadline or
evidence pointer is not.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

#: Record keys that describe workflow state rather than business content.
STATUS_FIELDS = ("review_status", "publication_status", "last_verified_at", "review")
VOLATILE_FIELDS = ("content_fingerprint", "last_fetched_at")
_VOLATILE_SOURCE_REF_FIELDS = ("fetched_at",)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def business_view(record: dict) -> dict:
    """Record minus workflow/volatile fields, with order-insensitive lists put in a stable order."""
    view = copy.deepcopy(record)
    for key in (*STATUS_FIELDS, *VOLATILE_FIELDS):
        view.pop(key, None)
    for ref in view.get("source_refs") or []:
        for key in _VOLATILE_SOURCE_REF_FIELDS:
            ref.pop(key, None)
    if isinstance(view.get("evidence"), list):
        view["evidence"] = sorted(view["evidence"], key=lambda e: e.get("id", ""))
    if isinstance(view.get("source_refs"), list):
        view["source_refs"] = sorted(view["source_refs"], key=lambda r: r.get("snapshot_id", ""))
    if isinstance(view.get("cycles"), list):
        view["cycles"] = sorted(view["cycles"], key=lambda c: c.get("cycle_key", ""))
    return view


def compute_fingerprint(record: dict) -> str:
    digest = hashlib.sha256(canonical_json(business_view(record)).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def status_view(record: dict) -> dict:
    return {key: record.get(key) for key in STATUS_FIELDS}


def diff_records(old: dict, new: dict, *, _prefix: str = "") -> list[dict]:
    """Field-level differences between two records as JSON-Pointer paths."""
    changes: list[dict] = []
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            path = f"{_prefix}/{str(key).replace('~', '~0').replace('/', '~1')}"
            if key not in old:
                changes.append({"path": path, "change": "added", "new": new[key]})
            elif key not in new:
                changes.append({"path": path, "change": "removed", "old": old[key]})
            else:
                changes.extend(diff_records(old[key], new[key], _prefix=path))
    elif old != new:
        changes.append({"path": _prefix or "/", "change": "modified", "old": old, "new": new})
    return changes
