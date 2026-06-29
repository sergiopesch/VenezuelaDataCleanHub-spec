"""Add duplicate clusters.

Revision ID: 0002_duplicate_clusters
Revises: 0001_initial_foundation
Create Date: 2026-06-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_duplicate_clusters"
down_revision: str | None = "0001_initial_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "duplicate_clusters",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("cluster_key", sa.String(length=160), nullable=False),
        sa.Column("canonical_person_record_id", sa.String(length=36), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=60), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["canonical_person_record_id"], ["person_records.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cluster_key"),
    )
    op.create_index("ix_duplicate_clusters_cluster_key", "duplicate_clusters", ["cluster_key"])
    op.create_index("ix_duplicate_clusters_status", "duplicate_clusters", ["status"])

    op.create_table(
        "duplicate_cluster_members",
        sa.Column("cluster_id", sa.String(length=36), nullable=False),
        sa.Column("person_record_id", sa.String(length=36), nullable=False),
        sa.Column("membership_confidence", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["cluster_id"], ["duplicate_clusters.id"]),
        sa.ForeignKeyConstraint(["person_record_id"], ["person_records.id"]),
        sa.PrimaryKeyConstraint("cluster_id", "person_record_id"),
        sa.UniqueConstraint("cluster_id", "person_record_id", name="uq_cluster_member"),
    )


def downgrade() -> None:
    op.drop_table("duplicate_cluster_members")
    op.drop_index("ix_duplicate_clusters_status", table_name="duplicate_clusters")
    op.drop_index("ix_duplicate_clusters_cluster_key", table_name="duplicate_clusters")
    op.drop_table("duplicate_clusters")
