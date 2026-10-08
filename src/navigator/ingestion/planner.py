"""Import planning: decide created / updated / unchanged / rejected / pending_review.

Pure functions over plain dicts, so idempotency, version precedence and cycle preservation are
testable without a database. The planner never deletes or withdraws anything: an opportunity the
source no longer lists simply isn't touched.

Rules in short
--------------
* Same stable ``id`` -> same opportunity (never keyed by URL, title, amount, date or UUID).
* Cycles merge by ``(opportunity id, cycle_key)``. A cycle absent from the input is *retained*;
  a cycle present is replaced. Re-importing the same input yields an identical merged record, so
  the second import is ``unchanged``.
* An older input (earlier ``last_fetched_at``) that would change already-stored content does not
  overwrite it: it becomes ``pending_review`` unless it carries a *later* verification.
* ``last_verified_at`` is never moved backwards and is only set by an input that carries it.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field

from navigator.core.fingerprint import compute_fingerprint, diff_records, business_view
from navigator.ingestion.rows import RecordRows, canonicalize_record, record_to_rows

REVIEW_RANK = {"pending": 0, "machine_checked": 1, "human_reviewed": 2}
ACTIONS = ("created", "updated", "unchanged", "rejected", "pending_review")


@dataclass
class PlanItem:
    id: str
    action: str
    reasons: list[str] = field(default_factory=list)
    diff: list[dict] = field(default_factory=list)
    cycles: dict[str, str] = field(default_factory=dict)
    record: dict | None = None  # the record to persist (created/updated)
    rows: RecordRows | None = None
    touched: bool = False  # unchanged content, but fetch/verification time moved forward
    version: int = 1

    def summary(self) -> dict:
        return {"id": self.id, "action": self.action, "reasons": self.reasons, "cycles": self.cycles,
                "changes": len(self.diff), "touched": self.touched, "version": self.version}


@dataclass
class ImportPlan:
    items: list[PlanItem] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        counts = {a: 0 for a in ACTIONS}
        for item in self.items:
            counts[item.action] += 1
        return counts

    @property
    def has_rejections(self) -> bool:
        return any(i.action == "rejected" for i in self.items)

    def writable(self) -> list[PlanItem]:
        return [i for i in self.items if i.action in {"created", "updated"} or (i.action == "unchanged" and i.touched)]


def _cycle_of(field_path: str) -> str | None:
    parts = field_path.split("/")
    return parts[2] if len(parts) > 2 and parts[1] == "cycles" else None


def _keyed(view: dict) -> dict:
    """Diff view with cycles keyed by cycle_key so paths read ``/cycles/2026-27/amount/fixed``."""
    out = dict(view)
    out["cycles"] = {c["cycle_key"]: c for c in view.get("cycles", [])}
    return out


def merge_records(existing: dict, incoming: dict) -> dict:
    """Merge ``incoming`` over ``existing`` (see module docstring); statuses are settled later."""
    merged = copy.deepcopy(incoming)
    old = {c["cycle_key"]: c for c in existing["cycles"]}
    new = {c["cycle_key"]: c for c in incoming["cycles"]}
    order = [c["cycle_key"] for c in existing["cycles"]] + [k for k in new if k not in old]
    merged["cycles"] = [copy.deepcopy(new.get(k) or old[k]) for k in order]
    retained = {k for k in old if k not in new}
    incoming_ids = {e["id"] for e in incoming["evidence"]}
    kept = [e for e in existing["evidence"] if _cycle_of(e["field_path"]) in retained and e["id"] not in incoming_ids]
    merged["evidence"] = list(incoming["evidence"]) + copy.deepcopy(kept)
    refs = {r["snapshot_id"]: r for r in existing["source_refs"]}
    refs.update({r["snapshot_id"]: r for r in incoming["source_refs"]})
    merged["source_refs"] = copy.deepcopy(list(refs.values()))
    merged["last_fetched_at"] = max(existing["last_fetched_at"], incoming["last_fetched_at"])
    return merged


def _settle_status(existing: dict, incoming: dict, merged: dict, content_changed: bool) -> None:
    """Fill review/publication/verification fields of ``merged`` in place."""
    if content_changed:
        # new content has only the verification level of the input that brought it
        return
    in_review, ex_review = incoming["review_status"], existing["review_status"]
    if in_review == "rejected":
        merged["review_status"], merged["publication_status"] = "rejected", "draft"
    else:
        keep_existing = REVIEW_RANK.get(ex_review, 0) >= REVIEW_RANK.get(in_review, 0)
        merged["review_status"] = ex_review if keep_existing else in_review
        merged["review"] = (existing.get("review") if keep_existing else incoming.get("review")) or incoming.get("review") or existing.get("review")
        if "archived" in (incoming["publication_status"], existing["publication_status"]):
            merged["publication_status"] = "archived"
        elif "published" in (incoming["publication_status"], existing["publication_status"]) and merged["review_status"] in {"machine_checked", "human_reviewed"}:
            merged["publication_status"] = "published"
        else:
            merged["publication_status"] = incoming["publication_status"]
    verified = [v for v in (existing.get("last_verified_at"), incoming.get("last_verified_at")) if v]
    merged["last_verified_at"] = max(verified) if verified else None


def plan_one(incoming_raw: dict, existing_raw: dict | None, *, expected_mode: str, version: int = 1) -> PlanItem:
    incoming = canonicalize_record(incoming_raw)
    rid = incoming["id"]
    mode = "demo" if incoming["is_demo"] else "live"
    if mode != expected_mode:
        return PlanItem(rid, "rejected", [f"mode_mismatch: a {mode} record cannot be imported in {expected_mode} mode"])
    if existing_raw is None:
        item = PlanItem(rid, "created", ["new opportunity"], record=incoming, rows=record_to_rows(incoming))
        item.cycles = {c["cycle_key"]: "created" for c in incoming["cycles"]}
        return item

    existing = canonicalize_record(existing_raw)
    if existing["source_record_key"] != incoming["source_record_key"]:
        return PlanItem(rid, "pending_review", [
            f"source_record_key changed from {existing['source_record_key']!r} to {incoming['source_record_key']!r}"],
            version=version)
    if existing["is_demo"] != incoming["is_demo"]:
        return PlanItem(rid, "rejected", ["is_demo differs from the stored record"], version=version)

    merged = merge_records(existing, incoming)
    new_fp = compute_fingerprint(merged)
    content_changed = new_fp != existing["content_fingerprint"]

    if content_changed:
        stale = incoming["last_fetched_at"] < existing["last_fetched_at"]
        later_verification = bool(
            incoming.get("last_verified_at") and existing.get("last_verified_at")
            and incoming["last_verified_at"] > existing["last_verified_at"]
        )
        if stale and not later_verification:
            return PlanItem(rid, "pending_review", [
                "older_input_would_overwrite_newer: the input was fetched before the stored version "
                "and carries no later verification"], version=version)

    _settle_status(existing, incoming, merged, content_changed)
    merged["content_fingerprint"] = new_fp
    cycle_actions = {}
    old = {c["cycle_key"]: c for c in existing["cycles"]}
    new = {c["cycle_key"]: c for c in incoming["cycles"]}
    for key in {c["cycle_key"] for c in merged["cycles"]}:
        if key not in new:
            cycle_actions[key] = "retained"
        elif key not in old:
            cycle_actions[key] = "created"
        else:
            cycle_actions[key] = "unchanged" if old[key] == new[key] else "updated"

    status_fields = ("review_status", "publication_status", "review")
    status_changed = any(merged.get(f) != existing.get(f) for f in status_fields)
    if not content_changed and not status_changed:
        touched = (merged["last_fetched_at"], merged.get("last_verified_at")) != (
            existing["last_fetched_at"], existing.get("last_verified_at"))
        item = PlanItem(rid, "unchanged", ["no business change"], cycles=cycle_actions, touched=touched, version=version)
        if touched:
            item.record, item.rows = merged, record_to_rows(merged)
        return item

    diff = [c for c in diff_records(_keyed(business_view(existing)), _keyed(business_view(merged)))
            if not c["path"].startswith(("/evidence", "/source_refs"))]
    diff += [{"path": f"/{f}", "change": "modified", "old": existing.get(f), "new": merged.get(f)}
             for f in status_fields if merged.get(f) != existing.get(f)]
    reasons = (["content changed"] if content_changed else []) + (["review/publication status changed"] if status_changed else [])
    if content_changed and (merged["evidence"] != existing["evidence"]):
        reasons.append("evidence pointers changed")
    return PlanItem(rid, "updated", reasons, diff, cycle_actions, merged, record_to_rows(merged),
                    version=version + 1)


def plan_import(incoming: list[dict], existing: dict[str, tuple[dict, int]], *, expected_mode: str) -> ImportPlan:
    """Plan a batch. ``existing`` maps id -> (stored record, version)."""
    items: list[PlanItem] = []
    seen: set[str] = set()
    for record in incoming:
        if record["id"] in seen:
            items.append(PlanItem(record["id"], "rejected", ["duplicate id inside the batch"]))
            continue
        seen.add(record["id"])
        stored = existing.get(record["id"])
        items.append(plan_one(record, stored[0] if stored else None, expected_mode=expected_mode,
                              version=stored[1] if stored else 1))
    return ImportPlan(items)
