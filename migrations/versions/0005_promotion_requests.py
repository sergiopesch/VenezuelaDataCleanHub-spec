"""Add audited promotion request boundary.

Revision ID: 0005_promotion_requests
Revises: 0004_hardening_governance
Create Date: 2026-06-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_promotion_requests"
down_revision: str | None = "0004_hardening_governance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "promotion_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("requested_by", sa.String(length=240), nullable=False),
        sa.Column("request_reason", sa.Text(), nullable=False),
        sa.Column("summary_json", json_type, nullable=False),
        sa.Column("decided_by", sa.String(length=240), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_promotion_requests_job_id", "promotion_requests", ["job_id"])
    op.create_index("ix_promotion_requests_status", "promotion_requests", ["status"])


def downgrade() -> None:
    op.drop_index("ix_promotion_requests_status", table_name="promotion_requests")
    op.drop_index("ix_promotion_requests_job_id", table_name="promotion_requests")
    op.drop_table("promotion_requests")
