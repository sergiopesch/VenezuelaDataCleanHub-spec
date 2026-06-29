"""Initial production-shaped foundation.

Revision ID: 0001_initial_foundation
Revises:
Create Date: 2026-06-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


json_type = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=240), nullable=False),
        sa.Column("owner", sa.String(length=240), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_sources_slug", "sources", ["slug"])

    op.create_table(
        "source_manifest_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("manifest_json", json_type, nullable=False),
        sa.Column("approval_status", sa.String(length=40), nullable=False),
        sa.Column("approved_by", sa.String(length=240), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rate_limit_policy_json", json_type, nullable=False),
        sa.Column("sensitive_fields_json", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "version", name="uq_manifest_source_version"),
    )
    op.create_index(
        "ix_source_manifest_versions_source_id",
        "source_manifest_versions",
        ["source_id"],
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("type", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("requested_by", sa.String(length=240), nullable=False),
        sa.Column("source_manifest_version_id", sa.String(length=36), nullable=True),
        sa.Column("input_object_uri", sa.Text(), nullable=True),
        sa.Column("progress_json", json_type, nullable=False),
        sa.Column("summary_json", json_type, nullable=False),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_manifest_version_id"], ["source_manifest_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_source_manifest_version_id", "jobs", ["source_manifest_version_id"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index("ix_jobs_type", "jobs", ["type"])

    op.create_table(
        "raw_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("source_record_id", sa.String(length=240), nullable=False),
        sa.Column("ingestion_job_id", sa.String(length=36), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("payload_object_uri", sa.Text(), nullable=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_json_redacted", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ingestion_job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "source_record_id", name="uq_raw_source_record"),
    )
    op.create_index("ix_raw_records_ingestion_job_id", "raw_records", ["ingestion_job_id"])
    op.create_index("ix_raw_records_source_id", "raw_records", ["source_id"])

    op.create_table(
        "person_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("raw_record_id", sa.String(length=36), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("source_record_id", sa.String(length=240), nullable=False),
        sa.Column("display_name", sa.String(length=300), nullable=True),
        sa.Column("normalized_name", sa.String(length=300), nullable=True),
        sa.Column("first_name", sa.String(length=120), nullable=True),
        sa.Column("last_name", sa.String(length=160), nullable=True),
        sa.Column("cedula_display", sa.String(length=80), nullable=True),
        sa.Column("cedula_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("phone_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("photo_url", sa.Text(), nullable=True),
        sa.Column("photo_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=120), nullable=True),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("location_general", sa.String(length=240), nullable=True),
        sa.Column("source_date", sa.String(length=80), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("quality_evidence_json", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["raw_record_id"], ["raw_records.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("raw_record_id"),
    )
    op.create_index(
        "ix_person_records_cedula_fingerprint",
        "person_records",
        ["cedula_fingerprint"],
    )
    op.create_index("ix_person_records_normalized_name", "person_records", ["normalized_name"])
    op.create_index("ix_person_records_phone_fingerprint", "person_records", ["phone_fingerprint"])
    op.create_index("ix_person_records_photo_fingerprint", "person_records", ["photo_fingerprint"])
    op.create_index("ix_person_records_source_id", "person_records", ["source_id"])
    op.create_index("ix_person_records_source_record_id", "person_records", ["source_record_id"])

    op.create_table(
        "duplicate_candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("left_person_record_id", sa.String(length=36), nullable=False),
        sa.Column("right_person_record_id", sa.String(length=36), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_json", json_type, nullable=False),
        sa.Column("review_bucket", sa.String(length=80), nullable=False),
        sa.Column("conflict_flags_json", json_type, nullable=False),
        sa.Column("model_version", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["left_person_record_id"], ["person_records.id"]),
        sa.ForeignKeyConstraint(["right_person_record_id"], ["person_records.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "left_person_record_id", "right_person_record_id", name="uq_candidate_pair"
        ),
    )
    op.create_index(
        "ix_duplicate_candidates_left_person_record_id",
        "duplicate_candidates",
        ["left_person_record_id"],
    )
    op.create_index(
        "ix_duplicate_candidates_right_person_record_id",
        "duplicate_candidates",
        ["right_person_record_id"],
    )

    op.create_table(
        "review_cases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("duplicate_candidate_id", sa.String(length=36), nullable=False),
        sa.Column("cluster_id", sa.String(length=36), nullable=True),
        sa.Column("queue", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("assigned_to", sa.String(length=240), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["duplicate_candidate_id"], ["duplicate_candidates.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("duplicate_candidate_id"),
    )
    op.create_index("ix_review_cases_status", "review_cases", ["status"])

    op.create_table(
        "review_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("review_case_id", sa.String(length=36), nullable=False),
        sa.Column("decision", sa.String(length=80), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("decided_by", sa.String(length=240), nullable=False),
        sa.Column("evidence_snapshot_json", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["review_case_id"], ["review_cases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("actor_type", sa.String(length=80), nullable=False),
        sa.Column("actor_id", sa.String(length=240), nullable=False),
        sa.Column("operation", sa.String(length=160), nullable=False),
        sa.Column("resource_type", sa.String(length=120), nullable=False),
        sa.Column("resource_id", sa.String(length=120), nullable=True),
        sa.Column("policy_decision", sa.String(length=80), nullable=False),
        sa.Column("metadata_json", json_type, nullable=False),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_operation", "audit_events", ["operation"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_operation", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("review_decisions")
    op.drop_index("ix_review_cases_status", table_name="review_cases")
    op.drop_table("review_cases")
    op.drop_index(
        "ix_duplicate_candidates_right_person_record_id",
        table_name="duplicate_candidates",
    )
    op.drop_index(
        "ix_duplicate_candidates_left_person_record_id",
        table_name="duplicate_candidates",
    )
    op.drop_table("duplicate_candidates")
    op.drop_index("ix_person_records_source_record_id", table_name="person_records")
    op.drop_index("ix_person_records_source_id", table_name="person_records")
    op.drop_index("ix_person_records_photo_fingerprint", table_name="person_records")
    op.drop_index("ix_person_records_phone_fingerprint", table_name="person_records")
    op.drop_index("ix_person_records_normalized_name", table_name="person_records")
    op.drop_index("ix_person_records_cedula_fingerprint", table_name="person_records")
    op.drop_table("person_records")
    op.drop_index("ix_raw_records_source_id", table_name="raw_records")
    op.drop_index("ix_raw_records_ingestion_job_id", table_name="raw_records")
    op.drop_table("raw_records")
    op.drop_index("ix_jobs_type", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_source_manifest_version_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_source_manifest_versions_source_id", table_name="source_manifest_versions")
    op.drop_table("source_manifest_versions")
    op.drop_index("ix_sources_slug", table_name="sources")
    op.drop_table("sources")
