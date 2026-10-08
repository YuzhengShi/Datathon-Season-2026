"""initial schema: sources, runs, snapshots, fetches, opportunities, cycles, groups, evidence, revisions

Revision ID: 0001
Revises:
Create Date: 2026-10-07
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TYPES = "'award','funding_channel','award_collection'"
REVIEWS = "'pending','machine_checked','human_reviewed','rejected'"
PUBLICATIONS = "'draft','published','archived'"


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("source_id", sa.String(80), primary_key=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("provider_id", sa.String(80), nullable=False),
        sa.Column("provider_name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(60), nullable=False),
        sa.Column("parser", sa.String(60), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("access_status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    op.create_table(
        "runs",
        sa.Column("run_id", sa.String(120), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("data_mode", sa.String(8), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.String(32), nullable=True),
        sa.Column("finished_at", sa.String(32), nullable=True),
        sa.CheckConstraint("data_mode IN ('live','demo')", name="ck_runs_data_mode"),
    )
    op.create_table(
        "snapshots",
        sa.Column("snapshot_id", sa.String(40), primary_key=True),
        sa.Column("source_id", sa.String(80), sa.ForeignKey("sources.source_id"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("raw_sha256", sa.String(64), nullable=False),
        sa.Column("raw_path", sa.Text(), nullable=False),
        sa.Column("media_type", sa.String(100), nullable=False),
        sa.Column("text_path", sa.Text(), nullable=True),
        sa.Column("text_sha256", sa.String(64), nullable=True),
        sa.Column("extractor", sa.String(60), nullable=True),
        sa.Column("extractor_version", sa.String(30), nullable=True),
        sa.Column("extraction_status", sa.String(20), nullable=True),
        sa.Column("fetched_at", sa.String(32), nullable=False),
        sa.Column("source_modified_at", sa.String(32), nullable=True),
        sa.Column("source_published_at", sa.String(32), nullable=True),
    )
    op.create_index("ix_snapshots_raw_sha256", "snapshots", ["raw_sha256"])
    op.create_table(
        "fetches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(120), sa.ForeignKey("runs.run_id"), nullable=True),
        sa.Column("source_id", sa.String(80), sa.ForeignKey("sources.source_id"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("etag", sa.Text(), nullable=True),
        sa.Column("last_modified", sa.Text(), nullable=True),
        sa.Column("requested_at", sa.String(32), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("bytes", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("failure_reason", sa.String(80), nullable=True),
        sa.Column("robots_status", sa.String(20), nullable=True),
        sa.Column("snapshot_id", sa.String(40), sa.ForeignKey("snapshots.snapshot_id"), nullable=True),
    )
    op.create_index("ix_fetches_source_requested", "fetches", ["source_id", "requested_at"])
    op.create_table(
        "opportunities",
        sa.Column("id", sa.String(200), primary_key=True),
        sa.Column("source_record_key", sa.String(400), nullable=False),
        sa.Column("schema_version", sa.String(10), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("opportunity_type", sa.String(30), nullable=False),
        sa.Column("provider_id", sa.String(80), nullable=False),
        sa.Column("provider_name", sa.String(200), nullable=False),
        sa.Column("official_url", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("provider", sa.JSON(), nullable=False),
        sa.Column("application", sa.JSON(), nullable=False),
        sa.Column("required_documents", sa.JSON(), nullable=False),
        sa.Column("source_refs", sa.JSON(), nullable=False),
        sa.Column("review_status", sa.String(20), nullable=False),
        sa.Column("review", sa.JSON(), nullable=True),
        sa.Column("publication_status", sa.String(20), nullable=False),
        sa.Column("extraction_method", sa.String(40), nullable=False),
        sa.Column("last_fetched_at", sa.String(32), nullable=False),
        sa.Column("last_verified_at", sa.String(32), nullable=True),
        sa.Column("content_fingerprint", sa.String(80), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
        sa.Column("content_changed_at", sa.String(32), nullable=True),
        sa.Column("first_run_id", sa.String(120), nullable=True),
        sa.Column("last_run_id", sa.String(120), nullable=True),
        sa.UniqueConstraint("source_record_key", name="uq_opportunities_source_record_key"),
        sa.CheckConstraint(f"opportunity_type IN ({TYPES})", name="ck_opportunities_type"),
        sa.CheckConstraint(f"review_status IN ({REVIEWS})", name="ck_opportunities_review"),
        sa.CheckConstraint(f"publication_status IN ({PUBLICATIONS})", name="ck_opportunities_publication"),
    )
    op.create_index("ix_opportunities_mode_publication", "opportunities", ["is_demo", "publication_status"])
    op.create_index("ix_opportunities_provider", "opportunities", ["provider_id"])
    op.create_index("ix_opportunities_type", "opportunities", ["opportunity_type"])
    op.create_table(
        "application_cycles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "opportunity_id", sa.String(200), sa.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("cycle_key", sa.String(60), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("label_raw", sa.Text(), nullable=False),
        sa.Column("starts_on", sa.String(10), nullable=True),
        sa.Column("ends_on", sa.String(10), nullable=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.UniqueConstraint("opportunity_id", "cycle_key", name="uq_cycles_opportunity_cycle"),
    )
    op.create_index("ix_cycles_opportunity", "application_cycles", ["opportunity_id"])
    op.create_table(
        "application_groups",
        sa.Column("group_id", sa.String(120), nullable=False),
        sa.Column("cycle_key", sa.String(60), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("group_id", "cycle_key"),
    )
    op.create_table(
        "application_group_members",
        sa.Column("group_id", sa.String(120), nullable=False),
        sa.Column("cycle_key", sa.String(60), nullable=False),
        sa.Column(
            "opportunity_id", sa.String(200), sa.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False
        ),
        sa.PrimaryKeyConstraint("group_id", "cycle_key", "opportunity_id"),
        sa.ForeignKeyConstraint(
            ["group_id", "cycle_key"],
            ["application_groups.group_id", "application_groups.cycle_key"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id", "cycle_key"],
            ["application_cycles.opportunity_id", "application_cycles.cycle_key"],
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "evidence",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "opportunity_id", sa.String(200), sa.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("evidence_id", sa.String(40), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("field_path", sa.Text(), nullable=False),
        sa.Column("source_id", sa.String(80), sa.ForeignKey("sources.source_id"), nullable=False),
        sa.Column("snapshot_id", sa.String(40), sa.ForeignKey("snapshots.snapshot_id"), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("locator", sa.JSON(), nullable=False),
        sa.Column("raw_sha256", sa.String(64), nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.UniqueConstraint("opportunity_id", "evidence_id", name="uq_evidence_opportunity_evidence"),
    )
    op.create_index("ix_evidence_opportunity", "evidence", ["opportunity_id"])
    op.create_index("ix_evidence_snapshot", "evidence", ["snapshot_id"])
    op.create_table(
        "opportunity_revisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "opportunity_id", sa.String(200), sa.ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(120), nullable=True),
        sa.Column("changed_at", sa.String(32), nullable=False),
        sa.Column("diff", sa.JSON(), nullable=False),
        sa.UniqueConstraint("opportunity_id", "version", name="uq_revisions_opportunity_version"),
    )


def downgrade() -> None:
    for table in (
        "opportunity_revisions",
        "evidence",
        "application_group_members",
        "application_groups",
        "application_cycles",
        "opportunities",
        "fetches",
        "snapshots",
        "runs",
        "sources",
    ):
        op.drop_table(table)
