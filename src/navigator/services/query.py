"""Read-side use cases for the API: filtered listing and detail. Pure functions over canonical records,
so every filter, sort and pagination rule is tested without a web server or database."""

from __future__ import annotations

import copy
import unicodedata
from datetime import datetime
from typing import Any

from navigator.core.evidence import normalize_text
from navigator.core.money import describe_amount
from navigator.core.timeutil import format_utc
from navigator.matching.availability import freshness_flags, select_cycle
from navigator.matching.engine import deadline_views, effective_group_id
from navigator.matching.rules import eval_predicate, iter_predicates, parse_eligibility

_AVAIL_RANK = {"open": 0, "upcoming": 1, "contact_administrator": 2, "unknown": 3, "closed": 4}
_FAR = "9999-12-31T23:59:59Z"
PROVINCE_FIELDS = ("residence_province", "institution_province")


def public_record(record: dict) -> dict:
    """The record as the API shows it: no internal storage paths, no internal metadata."""
    out = copy.deepcopy(record)
    out.pop("_meta", None)
    for ref in out.get("source_refs", []):
        ref.pop("raw_path", None)
        ref.pop("text_path", None)
    return out


def applicability(cycle: dict, fields: tuple[str, ...], value: str) -> str:
    """``applies`` | ``not_applicable`` | ``unknown`` for one geographic/level filter value.

    A record with no recorded rule on those fields is *unknown*, never silently "not applicable".
    """
    elig, _ = parse_eligibility(cycle["eligibility"], "/")
    if elig is None:
        return "unknown"
    predicates = [p for p in iter_predicates(list(elig.mandatory)) if p.field in fields]
    if not predicates:
        return "unknown"
    outcomes = [eval_predicate(p, {p.field: value}).outcome for p in predicates]
    if "pass" in outcomes:
        return "applies"
    return "not_applicable" if all(o == "fail" for o in outcomes) else "unknown"


def _fold(text: str) -> str:
    """Case- and accent-insensitive form used for search ("Metis" finds "Métis")."""
    decomposed = unicodedata.normalize("NFKD", normalize_text(text))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _matches_text(record: dict, query: str) -> bool:
    haystack = _fold(
        " ".join(
            [record["title"], record["summary"], record["provider"]["name"], record["provider"].get("donor_name") or ""]
        )
    )
    return all(term in haystack for term in _fold(query).split())


def source_kind(record: dict) -> str:
    """``directory_listing`` when every source of the record is a discovery index (a directory entry), else ``official_page``."""
    roles = {ref.get("role") for ref in record.get("source_refs", [])}
    return "directory_listing" if roles and roles <= {"discovery_index"} else "official_page"


def _summary(record: dict, cycle: dict, avail: dict, flags: list[str], applic: dict) -> dict:
    app = record["application"]
    return {
        "id": record["id"],
        "title": record["title"],
        "opportunity_type": record["opportunity_type"],
        "provider": record["provider"],
        "official_url": record["official_url"],
        "summary": record["summary"],
        "application_route": {
            "route_type": app["route_type"],
            "url": app.get("url"),
            "contact_url": app.get("contact_url"),
            "instructions": app.get("instructions"),
        },
        "current_cycle": {
            "cycle_key": cycle["cycle_key"],
            "availability_status": avail["status"],
            "next_deadline_utc": avail["next_deadline_utc"],
            "amount": describe_amount(cycle["amount"]),
            "application_group_id": effective_group_id(record, cycle),
        },
        "applicability": applic,
        "review_status": record["review_status"],
        "source_kind": source_kind(record),
        "last_verified_at": record.get("last_verified_at"),
        "freshness_flags": flags,
    }


def list_opportunities(
    records: list[dict],
    *,
    as_of: datetime,
    freshness_days: int,
    data_mode: str,
    q: str | None = None,
    province: str | None = None,
    education_level: str | None = None,
    opportunity_type: str | None = None,
    include_closed: bool = False,
    exclude_unknown_applicability: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    rows: list[tuple[tuple, dict]] = []
    for record in records:
        if record["publication_status"] != "published":
            continue
        if opportunity_type is None and record["opportunity_type"] == "award_collection":
            continue  # navigation records are hidden unless asked for explicitly
        if opportunity_type is not None and record["opportunity_type"] != opportunity_type:
            continue
        if q and not _matches_text(record, q):
            continue
        cycle, avail = select_cycle(record, as_of)
        if cycle is None or avail is None:
            continue
        if avail["status"] == "closed" and not include_closed:
            continue
        applic = {
            "province": applicability(cycle, PROVINCE_FIELDS, province) if province else None,
            "education_level": applicability(cycle, ("education_level",), education_level) if education_level else None,
        }
        values = [v for v in applic.values() if v is not None]
        if "not_applicable" in values or (exclude_unknown_applicability and "unknown" in values):
            continue
        flags = freshness_flags(record, cycle, avail, as_of, freshness_days)
        key = (
            _AVAIL_RANK[avail["status"]],
            avail["next_deadline_utc"] or _FAR,
            record["title"].casefold(),
            record["id"],
        )
        rows.append((key, _summary(record, cycle, avail, flags, applic)))
    rows.sort(key=lambda r: r[0])
    page = [r[1] for r in rows[offset : offset + limit]]
    return {
        "data_mode": data_mode,
        "as_of": format_utc(as_of),
        "total": len(rows),
        "limit": limit,
        "offset": offset,
        "count": len(page),
        "filters": {
            "q": q,
            "province": province,
            "education_level": education_level,
            "opportunity_type": opportunity_type,
            "include_closed": include_closed,
            "exclude_unknown_applicability": exclude_unknown_applicability,
        },
        "results": page,
    }


def _next_steps(record: dict, siblings: list[dict]) -> list[str]:
    app = record["application"]
    steps = [f"Read the official page: {record['official_url']}"]
    route = app["route_type"]
    if route == "contact_administrator":
        steps.append(
            f"Contact the administrator to apply or to learn the local deadline: {app.get('contact_url') or record['official_url']}"
        )
    elif app.get("url"):
        steps.append(f"Apply here: {app['url']}")
    if app.get("instructions"):
        steps.append(app["instructions"])
    docs = [d.get("label") or d["type"] for d in record["required_documents"]]
    if docs:
        steps.append("Prepare: " + ", ".join(docs))
    if siblings:
        steps.append(
            "This form is shared with: "
            + ", ".join(s["title"] for s in siblings)
            + ". Each award has its own eligibility rules."
        )
    return steps


def opportunity_detail(
    record: dict, all_records: list[dict], *, as_of: datetime, freshness_days: int, data_mode: str
) -> dict:
    current, _ = select_cycle(record, as_of)
    cycles: list[dict[str, Any]] = []
    siblings: list[dict] = []
    for cycle in record["cycles"]:
        _, avail = select_cycle(record, as_of, cycle["cycle_key"])
        assert avail is not None
        gid = effective_group_id(record, cycle)
        if gid and current is not None and cycle["cycle_key"] == current["cycle_key"]:
            siblings = [
                {"id": o["id"], "title": o["title"]}
                for o in all_records
                if o["id"] != record["id"] and o["publication_status"] == "published"
                for oc in o["cycles"]
                if oc["cycle_key"] == cycle["cycle_key"] and effective_group_id(o, oc) == gid
            ]
        cycles.append(
            {
                "cycle_key": cycle["cycle_key"],
                "label_raw": cycle["label_raw"],
                "starts_on": cycle.get("starts_on"),
                "ends_on": cycle.get("ends_on"),
                "availability": {
                    "status": avail["status"],
                    "reason": avail["reason"],
                    "next_deadline_utc": avail["next_deadline_utc"],
                },
                "deadlines": deadline_views(cycle, as_of),
                "amount": describe_amount(cycle["amount"]),
                "eligibility": cycle["eligibility"],
                "application_group_id": gid,
                "freshness_flags": freshness_flags(record, cycle, avail, as_of, freshness_days),
            }
        )
    return {
        "data_mode": data_mode,
        "as_of": format_utc(as_of),
        "opportunity": public_record(record),
        "current_cycle_key": current["cycle_key"] if current else None,
        "cycles": cycles,
        "shared_application_with": siblings,
        "next_steps": _next_steps(record, siblings),
        "verification": {
            "review_status": record["review_status"],
            "source_kind": source_kind(record),
            "last_verified_at": record.get("last_verified_at"),
            "last_fetched_at": record["last_fetched_at"],
            "note": "machine_checked means a source-specific parser and validation passed; it is not human review. "
            "Always confirm on the official page.",
        },
    }
