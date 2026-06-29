"""Add hardening governance primitives.

Revision ID: 0004_hardening_governance
Revises: 0003_job_control_events
Create Date: 2026-06-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_hardening_governance"
down_revision: str | None = "0003_job_control_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

json_type = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("trust_tier", sa.String(length=40), nullable=False, server_default="unreviewed"),
    )
    op.add_column(
        "sources",
        sa.Column("source_type", sa.String(length=40), nullable=False, server_default="api_json"),
    )
    op.add_column("sources", sa.Column("permission_basis", sa.Text(), nullable=True))
    op.add_column(
        "sources", sa.Column("allowed_domains_json", json_type, nullable=False, server_default="{}")
    )
    op.add_column(
        "sources",
        sa.Column("default_rate_limit_json", json_type, nullable=False, server_default="{}"),
    )
    op.add_column("sources", sa.Column("reviewed_by", sa.String(length=240), nullable=True))
    op.add_column("sources", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "sources",
        sa.Column("last_successful_job_id", sa.String(length=36), nullable=True),
    )
    op.add_column("sources", sa.Column("last_failed_job_id", sa.String(length=36), nullable=True))

    op.add_column(
        "source_manifest_versions",
        sa.Column(
            "parser_name",
            sa.String(length=120),
            nullable=False,
            server_default="person_json_v1",
        ),
    )
    op.add_column(
        "source_manifest_versions",
        sa.Column("parser_version", sa.String(length=80), nullable=False, server_default="1"),
    )
    op.add_column(
        "source_manifest_versions",
        sa.Column(
            "adapter_name",
            sa.String(length=120),
            nullable=False,
            server_default="http_json",
        ),
    )
    op.add_column(
        "source_manifest_versions",
        sa.Column("adapter_config_json", json_type, nullable=False, server_default="{}"),
    )
    op.add_column(
        "source_manifest_versions",
        sa.Column("field_mappings_json", json_type, nullable=False, server_default="{}"),
    )
    op.add_column(
        "source_manifest_versions",
        sa.Column("required_keywords_json", json_type, nullable=False, server_default="{}"),
    )
    op.add_column(
        "source_manifest_versions",
        sa.Column("sample_payload_redacted_json", json_type, nullable=False, server_default="{}"),
    )
    op.add_column("source_manifest_versions", sa.Column("review_notes", sa.Text(), nullable=True))

    op.create_table(
        "job_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("checkpoint_json", json_type, nullable=False),
        sa.Column("records_seen", sa.Integer(), nullable=False),
        sa.Column("raw_records_created", sa.Integer(), nullable=False),
        sa.Column("person_records_created", sa.Integer(), nullable=False),
        sa.Column("quarantine_records_created", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "sequence", name="uq_job_chunk_sequence"),
    )
    op.create_index("ix_job_chunks_job_id", "job_chunks", ["job_id"])
    op.create_index("ix_job_chunks_status", "job_chunks", ["status"])

    op.add_column("raw_records", sa.Column("job_chunk_id", sa.String(length=36), nullable=True))
    op.create_index("ix_raw_records_job_chunk_id", "raw_records", ["job_chunk_id"])
    op.create_foreign_key(
        "fk_raw_records_job_chunk_id_job_chunks",
        "raw_records",
        "job_chunks",
        ["job_chunk_id"],
        ["id"],
    )

    op.add_column(
        "person_records",
        sa.Column(
            "identity_token_version",
            sa.String(length=80),
            nullable=False,
            server_default="hmac-sha256-v1",
        ),
    )

    op.add_column(
        "review_cases",
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "quarantine_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("job_chunk_id", sa.String(length=36), nullable=True),
        sa.Column("source_id", sa.String(length=36), nullable=True),
        sa.Column("source_record_id", sa.String(length=240), nullable=True),
        sa.Column("reason_code", sa.String(length=120), nullable=False),
        sa.Column("reason_message", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_json_redacted", json_type, nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_chunk_id"], ["job_chunks.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quarantine_records_job_id", "quarantine_records", ["job_id"])
    op.create_index("ix_quarantine_records_job_chunk_id", "quarantine_records", ["job_chunk_id"])
    op.create_index("ix_quarantine_records_source_id", "quarantine_records", ["source_id"])
    op.create_index(
        "ix_quarantine_records_source_record_id", "quarantine_records", ["source_record_id"]
    )
    op.create_index("ix_quarantine_records_reason_code", "quarantine_records", ["reason_code"])
    op.create_index("ix_quarantine_records_status", "quarantine_records", ["status"])

    op.create_table(
        "quarantine_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("quarantine_record_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("actor_id", sa.String(length=240), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("metadata_json", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["quarantine_record_id"], ["quarantine_records.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_quarantine_events_quarantine_record_id",
        "quarantine_events",
        ["quarantine_record_id"],
    )
    op.create_index("ix_quarantine_events_event_type", "quarantine_events", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_quarantine_events_event_type", table_name="quarantine_events")
    op.drop_index(
        "ix_quarantine_events_quarantine_record_id", table_name="quarantine_events"
    )
    op.drop_table("quarantine_events")
    op.drop_index("ix_quarantine_records_status", table_name="quarantine_records")
    op.drop_index("ix_quarantine_records_reason_code", table_name="quarantine_records")
    op.drop_index("ix_quarantine_records_source_record_id", table_name="quarantine_records")
    op.drop_index("ix_quarantine_records_source_id", table_name="quarantine_records")
    op.drop_index("ix_quarantine_records_job_chunk_id", table_name="quarantine_records")
    op.drop_index("ix_quarantine_records_job_id", table_name="quarantine_records")
    op.drop_table("quarantine_records")

    op.drop_column("review_cases", "assigned_at")
    op.drop_column("person_records", "identity_token_version")

    op.drop_constraint(
        "fk_raw_records_job_chunk_id_job_chunks", "raw_records", type_="foreignkey"
    )
    op.drop_index("ix_raw_records_job_chunk_id", table_name="raw_records")
    op.drop_column("raw_records", "job_chunk_id")

    op.drop_index("ix_job_chunks_status", table_name="job_chunks")
    op.drop_index("ix_job_chunks_job_id", table_name="job_chunks")
    op.drop_table("job_chunks")

    op.drop_column("source_manifest_versions", "review_notes")
    op.drop_column("source_manifest_versions", "sample_payload_redacted_json")
    op.drop_column("source_manifest_versions", "required_keywords_json")
    op.drop_column("source_manifest_versions", "field_mappings_json")
    op.drop_column("source_manifest_versions", "adapter_config_json")
    op.drop_column("source_manifest_versions", "adapter_name")
    op.drop_column("source_manifest_versions", "parser_version")
    op.drop_column("source_manifest_versions", "parser_name")

    op.drop_column("sources", "last_failed_job_id")
    op.drop_column("sources", "last_successful_job_id")
    op.drop_column("sources", "reviewed_at")
    op.drop_column("sources", "reviewed_by")
    op.drop_column("sources", "default_rate_limit_json")
    op.drop_column("sources", "allowed_domains_json")
    op.drop_column("sources", "permission_basis")
    op.drop_column("sources", "source_type")
    op.drop_column("sources", "trust_tier")
