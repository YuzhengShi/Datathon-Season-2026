"""Freshness report: what the dataset covers, what is unknown, and what needs re-verification.

Pure over plain records, so the CLI, the API and the tests share one implementation. The 30-day
threshold is a configurable product setting, not a promise made by any source.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from navigator.core.timeutil import format_utc
from navigator.matching.availability import select_cycle

TARGET_MIN, TARGET_MAX = 20, 30


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def build_freshness_report(
    records: list[dict],
    *,
    mode: str,
    as_of: datetime,
    generated_at: datetime,
    freshness_days: int,
    run_context: dict[str, Any] | None = None,
    parameters: dict[str, Any] | None = None,
) -> dict:
    ctx = run_context or {}
    published = [r for r in records if r["publication_status"] == "published"]
    by_type = {t: sum(1 for r in records if r["opportunity_type"] == t)
               for t in ("award", "funding_channel", "award_collection")}
    administrators = sorted({r["provider"]["id"] for r in records if r["opportunity_type"] != "award_collection"})

    cycles = {"current_cycle_determined": 0, "cycle_unknown": 0, "deadline_unknown": 0, "expired": 0,
              "rolling": 0, "local_administrator": 0, "annual_rule_unconfirmed": 0, "open": 0}
    gaps = {"amount_unknown": 0, "eligibility_not_structured": 0, "no_required_documents": 0,
            "records_with_unstructured_conditions": 0, "shared_application_groups": 0, "group_exceptions": 0,
            "records_with_conflicts": 0, "records_with_funder_side_conditions": 0}
    groups: set[tuple[str, str]] = set()
    never, stale, changed, stale_ids = 0, 0, 0, []
    for r in records:
        cycle, avail = select_cycle(r, as_of)
        if cycle is None or avail is None:
            continue
        kinds = {d["kind"] for d in cycle["deadlines"]}
        cycles["cycle_unknown" if cycle["cycle_key"] == "unspecified" else "current_cycle_determined"] += 1
        cycles["deadline_unknown"] += "deadline_unknown" in avail["flags"]
        cycles["expired"] += avail["status"] == "closed"
        cycles["open"] += avail["status"] == "open"
        cycles["rolling"] += "rolling" in kinds
        cycles["local_administrator"] += "local_administrator" in kinds
        cycles["annual_rule_unconfirmed"] += "annual_rule" in kinds
        if cycle["amount"]["kind"] == "unspecified":
            gaps["amount_unknown"] += 1
        elig = cycle["eligibility"]
        gaps["eligibility_not_structured"] += not elig["mandatory"] or bool(elig["unstructured"])
        gaps["records_with_unstructured_conditions"] += bool(elig["unstructured"])
        gaps["records_with_funder_side_conditions"] += bool(elig.get("funder_conditions"))
        gaps["records_with_conflicts"] += bool(r.get("conflicts"))
        gaps["no_required_documents"] += not r["required_documents"]
        gid = cycle["application_group_id"] if "application_group_id" in cycle else r["application"].get("group_id")
        if gid:
            groups.add((gid, cycle["cycle_key"]))
        if r["application"]["route_type"] == "independent_application":
            gaps["group_exceptions"] += 1
        verified = r.get("last_verified_at")
        if not verified:
            never += 1
            stale_ids.append(r["id"])
        elif as_of - _parse(verified) > timedelta(days=freshness_days):
            stale += 1
            stale_ids.append(r["id"])
        if (r.get("_meta") or {}).get("changed_since_verified"):
            changed += 1
    gaps["shared_application_groups"] = len(groups)

    live_real = [r for r in records if not r["is_demo"]]
    target: dict[str, Any] | None = None
    if mode == "live":
        counted = [r for r in live_real if r["opportunity_type"] != "award_collection"]
        actual = sum(1 for r in counted if r["publication_status"] == "published")
        target = {"minimum": TARGET_MIN, "maximum": TARGET_MAX, "actual_independent_opportunities": actual,
                  "shortfall": max(0, TARGET_MIN - actual), "unpublished_drafts_not_counted": len(counted) - actual,
                  "note": "only published real opportunities count; demo/synthetic records never do"}

    imp = ctx.get("import", {})
    return {
        "report_version": "1.0", "generated_at": format_utc(generated_at), "as_of": format_utc(as_of),
        "data_mode": mode, "parameters": {"freshness_days": freshness_days, **(parameters or {})},
        "sources": ctx.get("sources", {"attempted": 0, "succeeded": 0, "failed": 0, "skipped": 0, "details": []}),
        "discovery": ctx.get("discovery", {"entries_observed": None, "coverage": None, "pagination_complete": None,
                                           "note": "no discovery crawl in this run"}),
        "opportunities": {"total": len(records), **by_type, "distinct_administrators": len(administrators),
                          "administrators": administrators, "is_demo_dataset": mode == "demo"},
        "review": {
            "published": len(published),
            "draft": sum(r["publication_status"] == "draft" for r in records),
            "archived": sum(r["publication_status"] == "archived" for r in records),
            "machine_checked": sum(r["review_status"] == "machine_checked" for r in records),
            "human_reviewed": sum(r["review_status"] == "human_reviewed" for r in records),
            "pending": sum(r["review_status"] == "pending" for r in records),
            "rejected": sum(r["review_status"] == "rejected" for r in records),
            "quarantined": ctx.get("quarantined", 0),
            "note": "machine_checked means parser + validation passed; it is NOT human review",
        },
        "import": {"created": imp.get("created", 0), "updated": imp.get("updated", 0),
                   "unchanged": imp.get("unchanged", 0), "rejected": imp.get("rejected", 0),
                   "pending_review": imp.get("pending_review", 0),
                   "duplicates": ctx.get("duplicates", 0), "content_conflicts": ctx.get("content_conflicts", 0),
                   "evidence_failures": ctx.get("evidence_failures", 0)},
        "cycles": cycles,
        "verification": {"never_verified": never, "verification_stale": stale,
                         "source_changed_not_reverified": changed, "needs_attention_ids": sorted(stale_ids)},
        "gaps": gaps, "target": target,
        "source_failures": ctx.get("failures", []), "pending_verification": ctx.get("pending_verification", []),
        "ocr_required_documents": ctx.get("ocr_required", []),
    }


def render_markdown(report: dict) -> str:
    o, rv, c, v, g = (report[k] for k in ("opportunities", "review", "cycles", "verification", "gaps"))
    lines = [
        f"# Data freshness report ({report['data_mode']})", "",
        f"* generated: `{report['generated_at']}`  as-of: `{report['as_of']}`  "
        f"threshold: {report['parameters']['freshness_days']} days (a product setting, not a source promise)",
    ]
    if report["data_mode"] == "demo":
        lines += ["", "> **SYNTHETIC DEMO DATA.** Nothing below describes real funding."]
    t = report["target"]
    if t:
        lines += ["", "## Live target", f"* target {t['minimum']}-{t['maximum']} distinct real opportunities; "
                  f"actual **{t['actual_independent_opportunities']}**; shortfall **{t['shortfall']}**"]
    s = report["sources"]
    d = report["discovery"]
    lines += ["", "## Sources",
              f"* attempted {s['attempted']}, succeeded {s['succeeded']}, failed {s['failed']}, skipped {s['skipped']}",
              f"* discovery index: entries observed {d.get('entries_observed')}, coverage {d.get('coverage')}, "
              f"pagination complete {d.get('pagination_complete')}"]
    for item in report["source_failures"]:
        lines.append(f"* FAILED `{item.get('where')}`: {item.get('reason')}")
    lines += ["", "## Opportunities",
              f"* total {o['total']}: award {o['award']}, funding channel {o['funding_channel']}, "
              f"collection {o['award_collection']}; distinct administrators {o['distinct_administrators']}",
              "", "## Review state",
              f"* published {rv['published']}, draft {rv['draft']}; machine_checked {rv['machine_checked']}, "
              f"human_reviewed {rv['human_reviewed']}, pending {rv['pending']}; quarantined {rv['quarantined']}",
              f"* {rv['note']}", "", "## Cycles and deadlines (current cycle per opportunity)",
              f"* cycle determined {c['current_cycle_determined']}, unknown {c['cycle_unknown']}; "
              f"open {c['open']}, expired {c['expired']}",
              f"* deadline unknown {c['deadline_unknown']}, rolling {c['rolling']}, "
              f"local administrator {c['local_administrator']}, annual rule unconfirmed {c['annual_rule_unconfirmed']}",
              "", "## Verification",
              f"* never verified {v['never_verified']}, stale (> threshold) {v['verification_stale']}, "
              f"source changed since verification {v['source_changed_not_reverified']}",
              "", "## Known gaps",
              f"* amount unknown {g['amount_unknown']}; eligibility not (fully) structured {g['eligibility_not_structured']}; "
              f"no required documents recorded {g['no_required_documents']}",
              f"* shared-application groups {g['shared_application_groups']}; independent exceptions {g['group_exceptions']}",
              f"* records with conflicting official statements awaiting review {g['records_with_conflicts']}; "
              f"records with funder-side conditions recorded {g['records_with_funder_side_conditions']}"]
    for item in report["pending_verification"]:
        lines.append(f"* pending: {item.get('item')} - {item.get('reason')}")
    for item in report["ocr_required_documents"]:
        lines.append(f"* OCR required (not parsed): {item}")
    return "\n".join(lines) + "\n"
