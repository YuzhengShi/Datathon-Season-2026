"""Add a mode-isolated read model; no runtime DDL or personal profile storage."""

import sqlalchemy as sa
from alembic import op

revision = "0001_query_read_model"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "opportunities",
        sa.Column("data_mode", sa.String(8), primary_key=True),
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("publication_status", sa.String(16), nullable=False),
        sa.Column("body", sa.JSON(), nullable=False),
    )
    op.create_index("ix_opportunities_title", "opportunities", ["title"])
    op.create_index("ix_opportunities_publication_status", "opportunities", ["publication_status"])


def downgrade():
    op.drop_table("opportunities")
