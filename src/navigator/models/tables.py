"""Tables. ``migrations/versions/0001_initial.py`` mirrors this file by hand; ``tests/test_db.py``
checks that the migrated schema and these models agree."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from navigator.models.base import Base

OPPORTUNITY_TYPES_SQL = "'award','funding_channel','award_collection'"
REVIEW_STATUSES_SQL = "'pending','machine_checked','human_reviewed','rejected'"
PUBLICATION_STATUSES_SQL = "'draft','published','archived'"


class Source(Base):
    __tablename__ = "sources"

    source_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    url: Mapped[str] = mapped_column(Text)
    provider_id: Mapped[str] = mapped_column(String(80))
    provider_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(60))
    parser: Mapped[str] = mapped_column(String(60))
    language: Mapped[str] = mapped_column(String(8), default="en")
    access_status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (CheckConstraint("data_mode IN ('live','demo')", name="ck_runs_data_mode"),)

    run_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    data_mode: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(20))
    params: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String(32), nullable=True)


class Snapshot(Base):
    __tablename__ = "snapshots"
    __table_args__ = (Index("ix_snapshots_raw_sha256", "raw_sha256"),)

    snapshot_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(80), ForeignKey("sources.source_id"))
    url: Mapped[str] = mapped_column(Text)
    raw_sha256: Mapped[str] = mapped_column(String(64))
    raw_path: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(String(100))
    text_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extractor: Mapped[str | None] = mapped_column(String(60), nullable=True)
    extractor_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    extraction_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fetched_at: Mapped[str] = mapped_column(String(32))
    source_modified_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_published_at: Mapped[str | None] = mapped_column(String(32), nullable=True)


class Fetch(Base):
    __tablename__ = "fetches"
    __table_args__ = (Index("ix_fetches_source_requested", "source_id", "requested_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String(120), ForeignKey("runs.run_id"), nullable=True)
    source_id: Mapped[str] = mapped_column(String(80), ForeignKey("sources.source_id"))
    url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_modified: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[str] = mapped_column(String(32))
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str] = mapped_column(String(20))
    failure_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    robots_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    snapshot_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("snapshots.snapshot_id"), nullable=True)


class Opportunity(Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        UniqueConstraint("source_record_key", name="uq_opportunities_source_record_key"),
        CheckConstraint(f"opportunity_type IN ({OPPORTUNITY_TYPES_SQL})", name="ck_opportunities_type"),
        CheckConstraint(f"review_status IN ({REVIEW_STATUSES_SQL})", name="ck_opportunities_review"),
        CheckConstraint(f"publication_status IN ({PUBLICATION_STATUSES_SQL})", name="ck_opportunities_publication"),
        Index("ix_opportunities_mode_publication", "is_demo", "publication_status"),
        Index("ix_opportunities_provider", "provider_id"),
        Index("ix_opportunities_type", "opportunity_type"),
    )

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    source_record_key: Mapped[str] = mapped_column(String(400))
    schema_version: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(Text)
    opportunity_type: Mapped[str] = mapped_column(String(30))
    provider_id: Mapped[str] = mapped_column(String(80))
    provider_name: Mapped[str] = mapped_column(String(200))
    official_url: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    provider: Mapped[Any] = mapped_column(JSON)
    application: Mapped[Any] = mapped_column(JSON)
    required_documents: Mapped[Any] = mapped_column(JSON)
    source_refs: Mapped[Any] = mapped_column(JSON)
    review_status: Mapped[str] = mapped_column(String(20))
    review: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    publication_status: Mapped[str] = mapped_column(String(20))
    extraction_method: Mapped[str] = mapped_column(String(40))
    last_fetched_at: Mapped[str] = mapped_column(String(32))
    last_verified_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    content_fingerprint: Mapped[str] = mapped_column(String(80))
    is_demo: Mapped[bool] = mapped_column(Boolean)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))
    content_changed_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    first_run_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_run_id: Mapped[str | None] = mapped_column(String(120), nullable=True)


class ApplicationCycle(Base):
    """One row per (opportunity, cycle). Deadlines, amount and the eligibility rule tree live in ``data``."""

    __tablename__ = "application_cycles"
    __table_args__ = (
        UniqueConstraint("opportunity_id", "cycle_key", name="uq_cycles_opportunity_cycle"),
        Index("ix_cycles_opportunity", "opportunity_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    opportunity_id: Mapped[str] = mapped_column(String(200), ForeignKey("opportunities.id", ondelete="CASCADE"))
    cycle_key: Mapped[str] = mapped_column(String(60))
    position: Mapped[int] = mapped_column(Integer)
    label_raw: Mapped[str] = mapped_column(Text)
    starts_on: Mapped[str | None] = mapped_column(String(10), nullable=True)
    ends_on: Mapped[str | None] = mapped_column(String(10), nullable=True)
    data: Mapped[Any] = mapped_column(JSON)


class ApplicationGroup(Base):
    """A shared application form for one cycle. Membership can differ from cycle to cycle."""

    __tablename__ = "application_groups"

    group_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    cycle_key: Mapped[str] = mapped_column(String(60), primary_key=True)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(32))


class ApplicationGroupMember(Base):
    __tablename__ = "application_group_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["group_id", "cycle_key"],
            ["application_groups.group_id", "application_groups.cycle_key"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["opportunity_id", "cycle_key"],
            ["application_cycles.opportunity_id", "application_cycles.cycle_key"],
            ondelete="CASCADE",
        ),
    )

    group_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    cycle_key: Mapped[str] = mapped_column(String(60), primary_key=True)
    opportunity_id: Mapped[str] = mapped_column(
        String(200), ForeignKey("opportunities.id", ondelete="CASCADE"), primary_key=True
    )


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        UniqueConstraint("opportunity_id", "evidence_id", name="uq_evidence_opportunity_evidence"),
        Index("ix_evidence_opportunity", "opportunity_id"),
        Index("ix_evidence_snapshot", "snapshot_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    opportunity_id: Mapped[str] = mapped_column(String(200), ForeignKey("opportunities.id", ondelete="CASCADE"))
    evidence_id: Mapped[str] = mapped_column(String(40))
    position: Mapped[int] = mapped_column(Integer)
    field_path: Mapped[str] = mapped_column(Text)
    source_id: Mapped[str] = mapped_column(String(80), ForeignKey("sources.source_id"))
    snapshot_id: Mapped[str] = mapped_column(String(40), ForeignKey("snapshots.snapshot_id"))
    source_url: Mapped[str] = mapped_column(Text)
    quote: Mapped[str] = mapped_column(Text)
    locator: Mapped[Any] = mapped_column(JSON)
    raw_sha256: Mapped[str] = mapped_column(String(64))
    text_sha256: Mapped[str] = mapped_column(String(64))


class OpportunityRevision(Base):
    """What changed, when, from which run: content updates never overwrite history silently."""

    __tablename__ = "opportunity_revisions"
    __table_args__ = (UniqueConstraint("opportunity_id", "version", name="uq_revisions_opportunity_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    opportunity_id: Mapped[str] = mapped_column(String(200), ForeignKey("opportunities.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    changed_at: Mapped[str] = mapped_column(String(32))
    diff: Mapped[Any] = mapped_column(JSON)
