"""Helpers that turn quote markers into verified, field-level evidence.

Adapters and curated mappings describe a record with :class:`Q` markers (``Q("quote")``) wherever
an ``evidence_ids`` list needs support. :func:`attach_evidence` walks the finished record,
locates every quote in the extracted text of its snapshot, and replaces each marker with a
stable evidence id whose ``field_path`` is the JSON Pointer of the object that cites it - so
the pointer can never be mistyped by hand. Under ``/cycles`` the pointer token is the cycle's
``cycle_key`` (e.g. ``/cycles/2026-27/amount``), so evidence stays valid when cycles are merged
or reordered.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from navigator.core.evidence import locate_quote
from navigator.core.fingerprint import compute_fingerprint
from navigator.core.ids import evidence_id
from navigator.core.issues import pointer_join


@dataclass(frozen=True)
class SnapshotView:
    """Everything needed to cite one stored snapshot."""

    key: str
    source_id: str
    url: str
    media_type: str
    snapshot_id: str
    raw_sha256: str
    raw_path: str
    text_sha256: str
    text_path: str
    fetched_at: str
    text: str
    role: str | None = None
    source_modified_at: str | None = None
    source_published_at: str | None = None

    def to_source_ref(self) -> dict:
        return {
            "source_id": self.source_id,
            "snapshot_id": self.snapshot_id,
            "url": self.url,
            "raw_path": self.raw_path,
            "text_path": self.text_path,
            "raw_sha256": self.raw_sha256,
            "text_sha256": self.text_sha256,
            "media_type": self.media_type,
            "fetched_at": self.fetched_at,
            "role": self.role,
            "source_published_at": self.source_published_at,
            "source_modified_at": self.source_modified_at,
        }


@dataclass(frozen=True)
class Q:
    """Placeholder for evidence: a short quote that must exist in a snapshot's text."""

    quote: str
    snap: str | None = None  # key of the snapshot; default = the record's primary snapshot
    pdf_page: int | None = None
    paragraph_index: int | None = None


def attach_evidence(record: dict, snaps: Mapping[str, SnapshotView], primary: str) -> dict:
    """Return a copy of ``record`` with every :class:`Q` resolved and evidence/source_refs filled."""
    out = copy.deepcopy(record)
    evidence: dict[str, dict] = {}
    used: list[str] = []

    def resolve(item: Any, path: str) -> Any:
        if not isinstance(item, Q):
            return item
        snap = snaps[item.snap or primary]
        if snap.key not in used:
            used.append(snap.key)
        locator = locate_quote(snap.text, item.quote, pdf_page=item.pdf_page, paragraph_index=item.paragraph_index)
        eid = evidence_id(path, snap.snapshot_id, item.quote)
        evidence.setdefault(
            eid,
            {
                "id": eid,
                "field_path": path,
                "source_id": snap.source_id,
                "snapshot_id": snap.snapshot_id,
                "source_url": snap.url,
                "quote": item.quote.strip(),
                "locator": locator,
                "raw_sha256": snap.raw_sha256,
                "text_sha256": snap.text_sha256,
            },
        )
        return eid

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            special = {"evidence_ids", "group_evidence_ids", "window_evidence_ids"}
            for key in special:
                if isinstance(node.get(key), list):
                    if key == "group_evidence_ids":
                        target = pointer_join(path, "application_group_id")
                    elif key == "window_evidence_ids":
                        target = pointer_join(path, "starts_on" if node.get("starts_on") else "ends_on")
                    else:
                        target = path
                    node[key] = [resolve(i, target) for i in node[key]]
            for key, value in node.items():
                if key not in special:
                    walk(value, pointer_join(path, key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                token = value["cycle_key"] if path == "/cycles" and isinstance(value, dict) else index
                walk(value, pointer_join(path, token))

    walk(out, "")
    out["evidence"] = list(evidence.values())
    out["source_refs"] = [snaps[k].to_source_ref() for k in used] or [snaps[primary].to_source_ref()]
    return out


def finalize(record: dict) -> dict:
    """Set ``content_fingerprint`` (call after every other field is final)."""
    record["content_fingerprint"] = compute_fingerprint(record)
    return record
