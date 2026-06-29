"""Add job control events and idempotency.

Revision ID: 0003_job_control_events
Revises: 0002_duplicate_clusters
Create Date: 2026-06-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_job_control_events"
down_revision: str | None = "0002_duplicate_clusters"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column("jobs", sa.Column("idempotency_key", sa.String(length=160), nullable=True))
    op.add_column(
        "jobs",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_jobs_idempotency_key", "jobs", ["idempotency_key"])
    op.create_unique_constraint(
        "uq_job_idempotency",
        "jobs",
        ["type", "requested_by", "idempotency_key"],
    )

    op.create_table(
        "job_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("phase", sa.String(length=80), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("metadata_json", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "sequence", name="uq_job_event_sequence"),
    )
    op.create_index("ix_job_events_event_type", "job_events", ["event_type"])
    op.create_index("ix_job_events_job_id", "job_events", ["job_id"])
    op.create_index("ix_job_events_phase", "job_events", ["phase"])


def downgrade() -> None:
    op.drop_index("ix_job_events_phase", table_name="job_events")
    op.drop_index("ix_job_events_job_id", table_name="job_events")
    op.drop_index("ix_job_events_event_type", table_name="job_events")
    op.drop_table("job_events")
    op.drop_constraint("uq_job_idempotency", "jobs", type_="unique")
    op.drop_index("ix_jobs_idempotency_key", table_name="jobs")
    op.drop_column("jobs", "attempt_count")
    op.drop_column("jobs", "idempotency_key")
