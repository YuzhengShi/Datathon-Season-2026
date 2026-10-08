"""Profile -> opportunity matching. Results are rule outcomes, never award probabilities.

Eligibility and availability are computed separately: a closed cycle is ``closed``, not
``not_eligible``. Each opportunity is matched individually; grouping by shared application form
happens afterwards and never turns one member's result into another's.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from navigator.core.money import describe_amount
from navigator.core.timeutil import format_utc, resolve_close_window
from navigator.matching.availability import freshness_flags, select_cycle
from navigator.matching.rules import (
    FIELD_SPECS,
    INFO_KINDS,
    PROVIDER_KINDS,
    Leaf,
    parse_eligibility,
    evaluate_eligibility,
)

DISCLAIMER = (
    "These results show whether your answers meet the conditions recorded from official sources. "
    "They are not a prediction of whether you will receive funding and not a decision by the "
    "provider. Always confirm on the official page."
)
_STATUS_RANK = {"potential_fit": 0, "needs_information": 1, "needs_provider_confirmation": 2, "not_eligible": 3}
_FAR = "9999-12-31T23:59:59Z"
_QUESTION_FIELD = {"gpa_scale": "gpa", "institution_name": "institution_id"}


@dataclass(frozen=True)
class MatchOptions:
    as_of: datetime
    cycle_key: str | None = None
    group_by_application: bool = False
    include_closed: bool = False
    limit: int = 20
    offset: int = 0
    freshness_days: int = 30


def effective_group_id(record: dict, cycle: dict) -> str | None:
    """Group of this cycle: an explicit per-cycle value (even null) wins over the record's."""
    return cycle["application_group_id"] if "application_group_id" in cycle else record["application"].get("group_id")


def deadline_views(cycle: dict, as_of: datetime) -> list[dict]:
    views = []
    for d in cycle.get("deadlines") or []:
        window = resolve_close_window(d)
        closing = {"state": "unresolved", "earliest_utc": None, "latest_utc": None, "flags": [], "basis": None}
        if window is not None:
            closing = {"state": window.state(as_of), "earliest_utc": format_utc(window.earliest_utc),
                       "latest_utc": format_utc(window.latest_utc), "flags": list(window.flags), "basis": window.basis}
        views.append({**{k: v for k, v in d.items() if k != "evidence_ids"}, "evidence_ids": d["evidence_ids"],
                      "closing": closing})
    return views


def _evidence_refs(record: dict, cycle: dict, leaves: list[Leaf], extra_ids: tuple[str, ...] = ()) -> list[dict]:
    by_id = {e["id"]: e for e in record.get("evidence", [])}
    ids: list[str] = list(extra_ids)
    for leaf in leaves:
        ids.extend(leaf.evidence_ids)
    ids.extend(cycle["amount"].get("evidence_ids") or [])
    for d in cycle.get("deadlines") or []:
        ids.extend(d.get("evidence_ids") or [])
    ids.extend(record["application"].get("evidence_ids") or [])
    seen: set[str] = set()
    refs = []
    for eid in ids:
        if eid in seen or eid not in by_id:
            continue
        seen.add(eid)
        e = by_id[eid]
        refs.append({"id": eid, "field_path": e["field_path"], "quote": e["quote"],
                     "source_url": e["source_url"], "snapshot_id": e["snapshot_id"], "locator": e["locator"]})
    return refs


def _next_action(status: str, availability: str, record: dict) -> str:
    app = record["application"]
    where = app.get("url") or app.get("contact_url") or record["official_url"]
    if status == "not_eligible":
        return ("You do not appear to meet the recorded conditions. Check the failed rules and the official "
                f"page in case your situation is an exception: {record['official_url']}")
    if status == "needs_information":
        return "Answer the clarification questions so the remaining conditions can be checked."
    if status == "needs_provider_confirmation":
        contact = app.get("contact_url") or record["official_url"]
        return f"Some conditions can only be confirmed by the provider or administrator. Contact them via {contact}."
    return {
        "open": f"You appear to meet the recorded conditions and the application window looks open. Review the official page and apply: {where}",
        "upcoming": f"You appear to meet the recorded conditions, but applications have not opened yet. Check {record['official_url']} for the opening date.",
        "closed": f"You appear to meet the recorded conditions, but this cycle has closed. Check {record['official_url']} for the next intake.",
        "contact_administrator": f"You appear to meet the recorded conditions. The deadline is set locally; contact the administrator: {where}",
    }.get(availability, f"You appear to meet the recorded conditions. Confirm the current application window on the official page: {record['official_url']}")


def _describe_uncertainty(leaf: Leaf) -> str:
    if leaf.reason_kind == "mapping_ambiguous":
        return f"{leaf.field}: your answer could not be matched to the rule by name; the provider must confirm ({leaf.description})."
    return f"The source leaves this open: {leaf.description}"


def evaluate_record(record: dict, profile: Mapping[str, Any], options: MatchOptions,
                    resolver: Callable[[str], str | None] | None = None) -> dict | None:
    """One result for the chosen cycle of ``record`` (``None`` if the cycle does not exist)."""
    cycle, avail = select_cycle(record, options.as_of, options.cycle_key)
    if cycle is None or avail is None:
        return None
    elig, _ = parse_eligibility(cycle["eligibility"], "/cycles/?/eligibility")
    if elig is None:  # invalid rules must never read as "eligible"
        from navigator.matching.rules import Eligibility, Unstructured
        elig = Eligibility((), (), (Unstructured("/", "rules could not be read", ()),))
    outcome = evaluate_eligibility(elig, profile, resolver)

    if outcome.value is False:
        result, status = "fail", "not_eligible"
    elif outcome.value is True:
        result, status = "pass", "potential_fit"
    else:
        result = "unknown"
        kinds = {leaf.reason_kind for leaf in outcome.unknown}
        status = "needs_provider_confirmation" if kinds & PROVIDER_KINDS else "needs_information"

    missing: list[str] = []
    for leaf in outcome.unknown:
        if leaf.reason_kind in INFO_KINDS:
            for name in leaf.missing_fields:
                if name not in missing:
                    missing.append(name)
    questions = []
    for name in missing:
        question = FIELD_SPECS[_QUESTION_FIELD.get(name, name)].question
        if question not in questions:
            questions.append(question)

    gid = effective_group_id(record, cycle)
    app = record["application"]
    all_leaves = [*outcome.passed, *outcome.failed, *outcome.unknown]
    funder_conditions = [{"text": f.text, "evidence_ids": list(f.evidence_ids)} for f in elig.funder_conditions]
    funder_ids = tuple(eid for f in elig.funder_conditions for eid in f.evidence_ids)
    return {
        "opportunity_id": record["id"], "title": record["title"],
        "opportunity_type": record["opportunity_type"], "cycle_key": cycle["cycle_key"],
        "eligibility_result": result, "match_status": status,
        "passed_rules": [leaf.to_dict() for leaf in outcome.passed],
        "failed_rules": [leaf.to_dict() for leaf in outcome.failed],
        "unknown_rules": [leaf.to_dict() for leaf in outcome.unknown],
        "missing_profile_fields": missing, "clarification_questions": questions,
        "source_uncertainties": [_describe_uncertainty(leaf) for leaf in outcome.unknown
                                 if leaf.reason_kind in PROVIDER_KINDS],
        "preference_matches": outcome.preference_matches,
        "funder_side_conditions": funder_conditions,
        "evidence_refs": _evidence_refs(record, cycle, all_leaves, funder_ids),
        "amount": describe_amount(cycle["amount"]),
        "deadlines": deadline_views(cycle, options.as_of),
        "availability_status": avail["status"],
        "availability": {"reason": avail["reason"], "next_deadline_utc": avail["next_deadline_utc"]},
        "official_url": record["official_url"],
        "application_route": {"route_type": app["route_type"], "url": app.get("url"),
                              "contact_url": app.get("contact_url"), "instructions": app.get("instructions")},
        "application_group_id": gid,
        "next_action": _next_action(status, avail["status"], record),
        "review_status": record["review_status"], "last_verified_at": record.get("last_verified_at"),
        "freshness_flags": freshness_flags(record, cycle, avail, options.as_of, options.freshness_days),
    }


def _sort_key(item: dict) -> tuple:
    return (_STATUS_RANK[item["match_status"]], item["availability"]["next_deadline_utc"] or _FAR,
            item["opportunity_id"], item["cycle_key"])


def match_records(records: list[dict], profile: Mapping[str, Any], options: MatchOptions,
                  resolver: Callable[[str], str | None] | None = None, *, data_mode: str) -> dict:
    items: list[dict] = []
    excluded_closed = 0
    for record in records:
        if record["opportunity_type"] == "award_collection" or record["publication_status"] != "published":
            continue
        item = evaluate_record(record, profile, options, resolver)
        if item is None:
            continue
        if item["availability_status"] == "closed" and not options.include_closed:
            excluded_closed += 1
            continue
        items.append(item)
    items.sort(key=_sort_key)

    response: dict[str, Any] = {
        "data_mode": data_mode, "as_of": format_utc(options.as_of),
        "group_by_application": options.group_by_application, "limit": options.limit,
        "offset": options.offset, "total": len(items), "total_groups": None,
        "excluded_closed_count": excluded_closed, "results": None, "groups": None,
        "disclaimer": DISCLAIMER,
    }
    if not options.group_by_application:
        response["results"] = items[options.offset: options.offset + options.limit]
        return response

    grouped: dict[tuple[str, str], list[dict]] = {}
    entries: list[tuple[tuple, dict]] = []
    for item in items:
        gid = item["application_group_id"]
        if gid:
            grouped.setdefault((gid, item["cycle_key"]), []).append(item)
        else:
            entries.append((_sort_key(item), {"group_id": None, "label": None, "cycle_key": item["cycle_key"],
                                              "application_url": item["application_route"]["url"],
                                              "members": [item], "member_status_counts": {item["match_status"]: 1}}))
    by_id = {r["id"]: r for r in records}
    for (gid, cycle_key), members in grouped.items():
        first = by_id[members[0]["opportunity_id"]]["application"]
        counts: dict[str, int] = {}
        for m in members:
            counts[m["match_status"]] = counts.get(m["match_status"], 0) + 1
        entries.append((min(_sort_key(m) for m in members),
                        {"group_id": gid, "label": first.get("group_label"), "cycle_key": cycle_key,
                         "application_url": first.get("url"), "members": members, "member_status_counts": counts,
                         "notice": "These awards share one application form, but each award has its own "
                                   "eligibility result. A fit for one is not a fit for the others."}))
    entries.sort(key=lambda e: (e[0], e[1]["group_id"] or ""))
    response["total_groups"] = len(entries)
    response["groups"] = [e[1] for e in entries[options.offset: options.offset + options.limit]]
    return response
