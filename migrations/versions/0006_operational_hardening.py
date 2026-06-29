"""Add operational hardening fields.

Revision ID: 0006_operational_hardening
Revises: 0005_promotion_requests
Create Date: 2026-06-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_operational_hardening"
down_revision: str | None = "0005_promotion_requests"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("parent_job_id", sa.String(length=36), nullable=True))
    op.create_foreign_key("fk_jobs_parent_job_id_jobs", "jobs", "jobs", ["parent_job_id"], ["id"])
    op.create_index("ix_jobs_parent_job_id", "jobs", ["parent_job_id"])
    op.add_column("job_events", sa.Column("trace_id", sa.String(length=120), nullable=True))
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_raw_record_update()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'raw_records are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_prevent_raw_record_update
        BEFORE UPDATE ON raw_records
        FOR EACH ROW EXECUTE FUNCTION prevent_raw_record_update();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_prevent_raw_record_update ON raw_records")
    op.execute("DROP FUNCTION IF EXISTS prevent_raw_record_update")
    op.drop_column("job_events", "trace_id")
    op.drop_index("ix_jobs_parent_job_id", table_name="jobs")
    op.drop_constraint("fk_jobs_parent_job_id_jobs", "jobs", type_="foreignkey")
    op.drop_column("jobs", "parent_job_id")
