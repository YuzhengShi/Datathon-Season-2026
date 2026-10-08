"""Lossless mapping between the canonical record (JSONL line) and normalised table rows.

``rows_to_record(record_to_rows(r)) == canonicalize_record(r)`` for every valid record, so the
database, the JSONL export and the API all share one serialisation contract and nothing
(rules, dates, amounts, evidence, application groups) is lost on the way through.
Nested objects are stored as JSON exactly as given; scalar columns exist for querying.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from navigator.core.fingerprint import compute_fingerprint


def canonicalize_record(record: dict) -> dict:
    """Copy with the always-present optional top-level keys made explicit."""
    out = copy.deepcopy(record)
    out.setdefault("review", None)
    out.setdefault("last_verified_at", None)
    return out


@dataclass
class RecordRows:
    opportunity: dict
    cycles: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    group_members: list[dict] = field(default_factory=list)
    snapshot_refs: list[dict] = field(default_factory=list)


_SCALARS = (
    "schema_version",
    "id",
    "source_record_key",
    "title",
    "opportunity_type",
    "official_url",
    "summary",
    "review_status",
    "publication_status",
    "extraction_method",
    "last_fetched_at",
    "last_verified_at",
    "content_fingerprint",
    "is_demo",
)
_JSON_COLUMNS = ("provider", "application", "required_documents", "source_refs", "review")


def record_to_rows(record: dict) -> RecordRows:
    rec = canonicalize_record(record)
    opp = {key: rec[key] for key in _SCALARS}
    opp.update({key: copy.deepcopy(rec[key]) for key in _JSON_COLUMNS})
    opp["provider_id"] = rec["provider"]["id"]
    opp["provider_name"] = rec["provider"]["name"]
    cycles, members = [], []
    for position, cycle in enumerate(rec["cycles"]):
        cycles.append(
            {
                "opportunity_id": rec["id"],
                "cycle_key": cycle["cycle_key"],
                "position": position,
                "label_raw": cycle["label_raw"],
                "starts_on": cycle.get("starts_on"),
                "ends_on": cycle.get("ends_on"),
                "data": copy.deepcopy(cycle),
            }
        )
        gid = cycle["application_group_id"] if "application_group_id" in cycle else rec["application"].get("group_id")
        if gid:
            members.append(
                {
                    "group_id": gid,
                    "cycle_key": cycle["cycle_key"],
                    "opportunity_id": rec["id"],
                    "label": rec["application"].get("group_label"),
                    "url": rec["application"].get("url"),
                }
            )
    evidence = [
        {
            "opportunity_id": rec["id"],
            "evidence_id": e["id"],
            "position": i,
            "field_path": e["field_path"],
            "source_id": e["source_id"],
            "snapshot_id": e["snapshot_id"],
            "source_url": e["source_url"],
            "quote": e["quote"],
            "locator": copy.deepcopy(e["locator"]),
            "raw_sha256": e["raw_sha256"],
            "text_sha256": e["text_sha256"],
        }
        for i, e in enumerate(rec["evidence"])
    ]
    return RecordRows(opp, cycles, evidence, members, copy.deepcopy(rec["source_refs"]))


def rows_to_record(rows: RecordRows) -> dict:
    opp = rows.opportunity
    record = {key: opp[key] for key in _SCALARS}
    record.update({key: copy.deepcopy(opp[key]) for key in _JSON_COLUMNS})
    record["cycles"] = [copy.deepcopy(c["data"]) for c in sorted(rows.cycles, key=lambda c: c["position"])]
    record["evidence"] = [
        {
            "id": e["evidence_id"],
            "field_path": e["field_path"],
            "source_id": e["source_id"],
            "snapshot_id": e["snapshot_id"],
            "source_url": e["source_url"],
            "quote": e["quote"],
            "locator": copy.deepcopy(e["locator"]),
            "raw_sha256": e["raw_sha256"],
            "text_sha256": e["text_sha256"],
        }
        for e in sorted(rows.evidence, key=lambda e: e["position"])
    ]
    return record


def verify_roundtrip(record: dict) -> bool:
    canonical = canonicalize_record(record)
    return (
        rows_to_record(record_to_rows(canonical)) == canonical
        and compute_fingerprint(canonical) == canonical["content_fingerprint"]
    )
