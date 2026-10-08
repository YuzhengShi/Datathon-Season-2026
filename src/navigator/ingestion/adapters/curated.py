"""Evidence-checked curated mapping (``data/curated/<source_id>.yaml``).

For sources whose pages are free text (SFU, MNBC, ISC channels) a person - or an agent - records
the structured facts and, for each one, the exact quote that supports it. The same validator then
verifies every quote against the stored snapshot. A curated record is ``extraction_method=curated``,
``machine_checked`` at most; it is never ``human_reviewed`` unless a ``review`` block is supplied.

Quote markers: wherever an ``evidence_ids`` list is expected write ``quotes: ["...", ...]`` (items may
also be ``{quote, url, pdf_page}``); ``url`` selects which fetched page the quote comes from.
"""

from __future__ import annotations

import copy
from typing import Any

from navigator.core.ids import make_opportunity_id
from navigator.core.timeutil import canonical_deadline_utc, format_utc
from navigator.ingestion.adapters.base import Adapter, AdapterResult, ParseContext
from navigator.ingestion.adapters.common import base_record, empty_amount
from navigator.ingestion.builder import Q, SnapshotView, attach_evidence, finalize
from navigator.ingestion.sources import SourceConfig

_PRECISION = {"date": "day", "datetime": "minute", "annual_rule": "month_day"}


def _markers(node: Any, by_url: dict[str, str], default_key: str) -> Any:
    """Replace every ``quotes`` list by ``evidence_ids`` made of :class:`Q` markers (recursively)."""
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key in {"quotes", "quote"}:
                items = value if isinstance(value, list) else [value]
                markers = []
                for item in items:
                    spec = {"quote": item} if isinstance(item, str) else dict(item)
                    markers.append(
                        Q(
                            spec["quote"],
                            snap=by_url.get(spec.get("url", ""), default_key),
                            pdf_page=spec.get("pdf_page"),
                            paragraph_index=spec.get("paragraph_index"),
                        )
                    )
                target = {"quotes": "evidence_ids", "quote": "evidence_ids"}[key]
                out.setdefault(target, []).extend(markers)
            elif key in {"window_quotes", "group_quotes"}:
                items = value if isinstance(value, list) else [value]
                target = {"window_quotes": "window_evidence_ids", "group_quotes": "group_evidence_ids"}[key]
                out[target] = [
                    Q(i, snap=default_key)
                    if isinstance(i, str)
                    else Q(i["quote"], snap=by_url.get(i.get("url", ""), default_key), pdf_page=i.get("pdf_page"))
                    for i in items
                ]
            else:
                out[key] = _markers(value, by_url, default_key)
        return out
    if isinstance(node, list):
        return [_markers(item, by_url, default_key) for item in node]
    return node


def _finish_deadline(d: dict) -> dict:
    d.setdefault("precision", _PRECISION.get(d.get("kind"), "none"))
    d.setdefault("raw_text", "")
    d.setdefault("evidence_ids", [])
    if d.get("kind") in {"date", "datetime"} and d.get("date") and (exact := canonical_deadline_utc(d)):
        d["deadline_at_utc"] = exact
    return d


def curated_record(entry: dict, snaps: list[SnapshotView], source: SourceConfig, now_iso: str) -> dict:
    """Build one validated-later record from a curated entry (raises KeyError/ValueError on malformed input)."""
    by_key = {s.key: s for s in snaps}
    by_url = {s.url: s.key for s in snaps}
    default_key = by_url.get(entry.get("snapshot", source.url), snaps[0].key)
    body = _markers(copy.deepcopy(entry), by_url, default_key)
    cycles = []
    for cycle in body["cycles"]:
        cycle.setdefault("label_raw", cycle["cycle_key"])
        cycle.setdefault("starts_on", None)
        cycle.setdefault("ends_on", None)
        cycle["deadlines"] = [_finish_deadline(d) for d in cycle.get("deadlines", [])]
        amount = {**empty_amount(), **cycle.get("amount", {})}
        amount.setdefault("evidence_ids", [])
        cycle["amount"] = amount
        elig = cycle.get("eligibility", {})
        cycle["eligibility"] = {
            "mandatory": elig.get("mandatory", []),
            "preferences": elig.get("preferences", []),
            "unstructured": elig.get("unstructured", []),
            "rules_version": elig.get("rules_version"),
        }
        if elig.get("funder_conditions"):
            cycle["eligibility"]["funder_conditions"] = elig["funder_conditions"]
        cycles.append(cycle)
    app = body.get("application", {})
    application = {
        "url": app.get("url"),
        "route_type": app.get("route_type", "unknown"),
        "instructions": app.get("instructions"),
        "contact_url": app.get("contact_url"),
        "group_id": app.get("group_id"),
        "evidence_ids": app.get("evidence_ids", []),
    }
    if app.get("group_label"):
        application["group_label"] = app["group_label"]
    record = base_record(
        rid=body.get("id") or make_opportunity_id(source.provider_id, body["key"]),
        key=f"{source.source_id}#{body['key']}",
        title=body["title"],
        otype=body.get("opportunity_type", "award"),
        provider={"id": source.provider_id, "name": source.provider_name, "donor_name": body.get("donor_name")},
        official_url=body.get("official_url", source.url),
        summary=body.get("summary", ""),
        application=application,
        cycles=cycles,
        documents=body.get("required_documents", []),
        fetched_at=now_iso,
        method="curated",
    )
    for doc in record["required_documents"]:
        doc.setdefault("required", True)
        doc.setdefault("evidence_ids", [])
    if body.get("conflicts"):  # contradicting official statements: keep both, stay pending, never publish
        record["conflicts"] = body["conflicts"]
        record["review_status"], record["publication_status"] = "pending", "draft"
    elif body.get("review"):  # a real person's review record is the only way to human_reviewed
        record["review_status"], record["review"] = "human_reviewed", body["review"]
    return finalize(attach_evidence(record, by_key, default_key))


class CuratedAdapter(Adapter):
    name = "curated_awards"

    def parse(self, snaps: list[SnapshotView], source: SourceConfig, ctx: ParseContext) -> AdapterResult:
        result = AdapterResult()
        spec = ctx.curated.get(source.source_id)
        if not spec:
            result.pending.append(
                {
                    "item": source.source_id,
                    "reason": f"no curated mapping: add data/curated/{source.source_id}.yaml "
                    "with evidence quotes (see docs/DATA_SOURCES.md); nothing is guessed",
                }
            )
            return result
        if not snaps:
            result.pending.append({"item": source.source_id, "reason": "no snapshot to cite (source not fetched)"})
            return result
        now_iso = format_utc(ctx.now)
        for entry in spec.get("records", []):
            try:
                result.candidates.append(curated_record(entry, snaps, source, now_iso))
            except (KeyError, ValueError) as exc:
                result.pending.append(
                    {
                        "item": f"{source.source_id}:{entry.get('key', '?')}",
                        "reason": f"curated entry malformed or quote not found: {type(exc).__name__}: {exc}",
                    }
                )
        result.stats = {"curated_entries": len(spec.get("records", [])), "records": len(result.candidates)}
        return result


class CuratedChannelAdapter(CuratedAdapter):
    name = "curated_channel"
