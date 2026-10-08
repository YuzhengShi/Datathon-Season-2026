"""SQLAlchemy implementation of the repository ports used by the importer, pipelines and API.

Writes only happen inside :meth:`SqlRepository.transaction` (one database transaction); every
read opens its own short session. Instances hold per-call state, so create one per request/run.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from navigator.ingestion.planner import PlanItem
from navigator.ingestion.rows import RecordRows, rows_to_record
from navigator.models import (
    ApplicationCycle,
    ApplicationGroup,
    ApplicationGroupMember,
    Evidence,
    Fetch,
    Opportunity,
    OpportunityRevision,
    Run,
    Snapshot,
    Source,
)

_SCALAR_COLUMNS = (
    "schema_version", "id", "source_record_key", "title", "opportunity_type", "official_url", "summary",
    "review_status", "publication_status", "extraction_method", "last_fetched_at", "last_verified_at",
    "content_fingerprint", "is_demo",
)
_JSON_COLUMNS = ("provider", "application", "required_documents", "source_refs", "review")
_EXTRACTOR_RE = re.compile(r"\.([a-z][a-z-]*)-(\d+\.\d+\.\d+)\.txt$")
_CHUNK = 400


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _chunks(items: list[str]) -> Iterator[list[str]]:
    for start in range(0, len(items), _CHUNK):
        yield items[start: start + _CHUNK]


class SqlRepository:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._factory = factory
        self._tx: Session | None = None

    # ------------------------------------------------------------------ sessions
    @contextmanager
    def transaction(self) -> Iterator[Session]:
        if self._tx is not None:
            raise RuntimeError("nested transactions are not supported")
        session = self._factory()
        self._tx = session
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            self._tx = None
            session.close()

    @contextmanager
    def _read(self) -> Iterator[Session]:
        if self._tx is not None:
            yield self._tx
            return
        session = self._factory()
        try:
            yield session
        finally:
            session.close()

    @contextmanager
    def _write(self) -> Iterator[Session]:
        """Join the active transaction, or run one small transaction of its own."""
        if self._tx is not None:
            yield self._tx
            return
        with self.transaction() as session:
            yield session

    # --------------------------------------------------------------- reference rows
    def ensure_sources(self, sources: Sequence[dict]) -> None:
        now = _now()
        with self._write() as session:
            for item in sources:
                row = session.get(Source, item["source_id"])
                if row is None:
                    row = Source(source_id=item["source_id"], created_at=now)
                    session.add(row)
                row.url, row.provider_id, row.provider_name = item["url"], item["provider_id"], item["provider_name"]
                row.role, row.parser = item["role"], item["parser"]
                row.language = item.get("language", "en")
                row.access_status = item.get("access_status", "unreviewed")
                row.updated_at = now

    def ensure_snapshot_rows(self, entries: Sequence[dict]) -> None:
        """Create snapshot rows from fetch-index entries (so fetch audit rows can reference them)."""
        with self._write() as session:
            for entry in entries:
                if session.get(Snapshot, entry["snapshot_id"]) is None:
                    session.add(Snapshot(
                        snapshot_id=entry["snapshot_id"], source_id=entry["source_id"], url=entry["final_url"],
                        raw_sha256=entry["raw_sha256"], raw_path=entry["raw_path"], media_type=entry["media_type"],
                        text_path=entry.get("text_path"), text_sha256=entry.get("text_sha256"),
                        extractor=entry.get("extractor"), extractor_version=entry.get("extractor_version"),
                        extraction_status=entry.get("extraction_status"), fetched_at=entry["fetched_at"],
                        source_modified_at=entry.get("source_modified_at"),
                    ))
            session.flush()

    def record_fetches(self, rows: Sequence[dict], *, run_id: str, mode: str) -> None:
        """Persist fetch audit rows (one per HTTP attempt sequence), creating the run row if needed."""
        with self._write() as session:
            if session.get(Run, run_id) is None:
                session.add(Run(run_id=run_id, kind="fetch", data_mode=mode, status="running"))
                session.flush()
            for row in rows:
                session.add(Fetch(
                    run_id=run_id, source_id=row["source_id"], url=row["url"], final_url=row.get("final_url"),
                    http_status=row.get("http_status"), etag=row.get("etag"), last_modified=row.get("last_modified"),
                    requested_at=row["requested_at"], duration_ms=row.get("duration_ms"), bytes=row.get("bytes"),
                    outcome=row["outcome"], failure_reason=row.get("reason"), robots_status=row.get("robots_status"),
                    snapshot_id=row.get("snapshot_id"),
                ))

    def record_run(self, run: dict) -> None:
        with self._write() as session:
            row = session.get(Run, run["run_id"])
            summary = {k: v for k, v in run.items() if k not in {"run_id", "kind", "mode", "status", "finished_at"}}
            if row is None:
                session.add(Run(run_id=run["run_id"], kind=run["kind"], data_mode=run["mode"], status=run["status"],
                                summary=summary, finished_at=run.get("finished_at")))
            else:
                merged = dict(row.summary or {})
                merged.update(summary)
                row.summary, row.status, row.finished_at = merged, run["status"], run.get("finished_at")

    def latest_run_context(self, mode: str) -> dict:
        with self._read() as session:
            runs = session.scalars(select(Run).where(Run.data_mode == mode).order_by(Run.finished_at.desc()).limit(25)).all()
            for run in runs:
                if run.summary and "context" in run.summary:
                    return dict(run.summary["context"])
        return {}

    # ------------------------------------------------------------------- reading
    def _assemble(self, session: Session, opps: list[Opportunity], with_meta: bool) -> dict[str, dict]:
        ids = [o.id for o in opps]
        cycles: dict[str, list[dict]] = {i: [] for i in ids}
        evidence: dict[str, list[dict]] = {i: [] for i in ids}
        for chunk in _chunks(ids):
            for c in session.scalars(select(ApplicationCycle).where(ApplicationCycle.opportunity_id.in_(chunk))):
                cycles[c.opportunity_id].append({"opportunity_id": c.opportunity_id, "cycle_key": c.cycle_key,
                                                 "position": c.position, "label_raw": c.label_raw,
                                                 "starts_on": c.starts_on, "ends_on": c.ends_on, "data": c.data})
            for e in session.scalars(select(Evidence).where(Evidence.opportunity_id.in_(chunk))):
                evidence[e.opportunity_id].append({
                    "opportunity_id": e.opportunity_id, "evidence_id": e.evidence_id, "position": e.position,
                    "field_path": e.field_path, "source_id": e.source_id, "snapshot_id": e.snapshot_id,
                    "source_url": e.source_url, "quote": e.quote, "locator": e.locator,
                    "raw_sha256": e.raw_sha256, "text_sha256": e.text_sha256})
        out: dict[str, dict] = {}
        for o in opps:
            scalar = {name: getattr(o, name) for name in _SCALAR_COLUMNS}
            scalar.update({name: getattr(o, name) for name in _JSON_COLUMNS})
            record = rows_to_record(RecordRows(scalar, cycles[o.id], evidence[o.id]))
            if with_meta:
                changed = bool(o.content_changed_at and (not o.last_verified_at or o.content_changed_at > o.last_verified_at))
                record["_meta"] = {"version": o.version, "updated_at": o.updated_at, "changed_since_verified": changed}
            out[o.id] = record
        return out

    def load_existing(self, ids: Sequence[str]) -> dict[str, tuple[dict, int]]:
        result: dict[str, tuple[dict, int]] = {}
        with self._read() as session:
            for chunk in _chunks(list(ids)):
                opps = list(session.scalars(select(Opportunity).where(Opportunity.id.in_(chunk))))
                for opp_id, record in self._assemble(session, opps, False).items():
                    result[opp_id] = (record, next(o.version for o in opps if o.id == opp_id))
        return result

    def list_records(self, *, published_only: bool, is_demo: bool, with_meta: bool = False) -> list[dict]:
        with self._read() as session:
            query = select(Opportunity).where(Opportunity.is_demo == is_demo)
            if published_only:
                query = query.where(Opportunity.publication_status == "published")
            opps = list(session.scalars(query.order_by(Opportunity.id)))
            assembled = self._assemble(session, opps, with_meta)
        return [assembled[o.id] for o in opps]

    def get_record(self, record_id: str, *, published_only: bool = True, with_meta: bool = False) -> dict | None:
        with self._read() as session:
            opp = session.get(Opportunity, record_id)
            if opp is None or (published_only and opp.publication_status != "published"):
                return None
            return self._assemble(session, [opp], with_meta)[opp.id]

    # ------------------------------------------------------------------- writing
    def _ensure_snapshot(self, session: Session, ref: dict) -> None:
        if session.get(Snapshot, ref["snapshot_id"]) is not None:
            return
        match = _EXTRACTOR_RE.search(ref.get("text_path") or "")
        session.add(Snapshot(
            snapshot_id=ref["snapshot_id"], source_id=ref["source_id"], url=ref["url"], raw_sha256=ref["raw_sha256"],
            raw_path=ref["raw_path"], media_type=ref["media_type"], text_path=ref.get("text_path"),
            text_sha256=ref.get("text_sha256"), extractor=match.group(1) if match else None,
            extractor_version=match.group(2) if match else None, fetched_at=ref["fetched_at"],
            source_modified_at=ref.get("source_modified_at"), source_published_at=ref.get("source_published_at"),
        ))
        session.flush()

    def apply_item(self, item: PlanItem, run_id: str, now_iso: str) -> None:
        """Write one planned record (opportunity, cycles, groups, evidence, revision). Needs ``transaction()``."""
        session = self._tx
        if session is None:
            raise RuntimeError("apply_item must run inside transaction()")
        if item.rows is None or item.record is None:
            return
        rows: RecordRows = item.rows
        for ref in rows.snapshot_refs:
            self._ensure_snapshot(session, ref)

        values: dict[str, Any] = dict(rows.opportunity)
        opp = session.get(Opportunity, item.id)
        if opp is None:
            opp = Opportunity(**values, version=item.version, created_at=now_iso, updated_at=now_iso,
                              first_run_id=run_id, last_run_id=run_id)
            session.add(opp)
        else:
            for key, value in values.items():
                setattr(opp, key, value)
            if item.action == "updated":
                opp.version = item.version
                if "content changed" in item.reasons:
                    opp.content_changed_at = now_iso
            opp.updated_at, opp.last_run_id = now_iso, run_id
        session.flush()

        existing = {c.cycle_key: c for c in session.scalars(
            select(ApplicationCycle).where(ApplicationCycle.opportunity_id == item.id))}
        for cycle in rows.cycles:  # cycles are upserted, never deleted: old cycles survive
            row = existing.get(cycle["cycle_key"])
            if row is None:
                session.add(ApplicationCycle(**cycle))
            else:
                row.position, row.label_raw = cycle["position"], cycle["label_raw"]
                row.starts_on, row.ends_on, row.data = cycle["starts_on"], cycle["ends_on"], cycle["data"]
        session.flush()

        session.execute(delete(ApplicationGroupMember).where(ApplicationGroupMember.opportunity_id == item.id))
        for member in rows.group_members:
            group = session.get(ApplicationGroup, (member["group_id"], member["cycle_key"]))
            if group is None:
                group = ApplicationGroup(group_id=member["group_id"], cycle_key=member["cycle_key"], created_at=now_iso)
                session.add(group)
            group.label, group.url = member["label"], member["url"]
            session.flush()
            session.add(ApplicationGroupMember(group_id=member["group_id"], cycle_key=member["cycle_key"],
                                               opportunity_id=item.id))

        session.execute(delete(Evidence).where(Evidence.opportunity_id == item.id))
        session.flush()
        for ev in rows.evidence:
            session.add(Evidence(**ev))
        if item.action == "updated":
            session.add(OpportunityRevision(opportunity_id=item.id, version=item.version, run_id=run_id,
                                            changed_at=now_iso, diff=item.diff))
        session.flush()
