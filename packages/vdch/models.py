from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from vdch.db import Base


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


JsonType = MutableDict.as_mutable(JSON().with_variant(JSONB, "postgresql"))


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(240), nullable=False)
    owner: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    trust_tier: Mapped[str] = mapped_column(String(40), nullable=False, default="unreviewed")
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, default="api_json")
    permission_basis: Mapped[str | None] = mapped_column(Text)
    allowed_domains_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    default_rate_limit_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    reviewed_by: Mapped[str | None] = mapped_column(String(240))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_successful_job_id: Mapped[str | None] = mapped_column(String(36))
    last_failed_job_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    manifests: Mapped[list["SourceManifestVersion"]] = relationship(back_populates="source")


class SourceManifestVersion(Base):
    __tablename__ = "source_manifest_versions"
    __table_args__ = (UniqueConstraint("source_id", "version", name="uq_manifest_source_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest_json: Mapped[dict] = mapped_column(JsonType, nullable=False)
    parser_name: Mapped[str] = mapped_column(String(120), nullable=False, default="person_json_v1")
    parser_version: Mapped[str] = mapped_column(String(80), nullable=False, default="1")
    adapter_name: Mapped[str] = mapped_column(String(120), nullable=False, default="http_json")
    adapter_config_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    field_mappings_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    approval_status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft")
    approved_by: Mapped[str | None] = mapped_column(String(240))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rate_limit_policy_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    required_keywords_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    sample_payload_redacted_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    sensitive_fields_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    review_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    source: Mapped[Source] = relationship(back_populates="manifests")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("type", "requested_by", "idempotency_key", name="uq_job_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="queued", index=True)
    requested_by: Mapped[str] = mapped_column(String(240), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_manifest_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_manifest_versions.id"), index=True
    )
    parent_job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id"), index=True)
    input_object_uri: Mapped[str | None] = mapped_column(Text)
    progress_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    summary_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class JobEvent(Base):
    __tablename__ = "job_events"
    __table_args__ = (UniqueConstraint("job_id", "sequence", name="uq_job_event_sequence"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    phase: Mapped[str | None] = mapped_column(String(80), index=True)
    message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    trace_id: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JobChunk(Base):
    __tablename__ = "job_chunks"
    __table_args__ = (UniqueConstraint("job_id", "sequence", name="uq_job_chunk_sequence"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="queued", index=True)
    source_uri: Mapped[str | None] = mapped_column(Text)
    checkpoint_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    records_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    raw_records_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    person_records_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quarantine_records_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(120))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RawRecord(Base):
    __tablename__ = "raw_records"
    __table_args__ = (
        UniqueConstraint("source_id", "source_record_id", name="uq_raw_source_record"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    source_record_id: Mapped[str] = mapped_column(String(240), nullable=False)
    ingestion_job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)
    job_chunk_id: Mapped[str | None] = mapped_column(ForeignKey("job_chunks.id"), index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    payload_object_uri: Mapped[str | None] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json_redacted: Mapped[dict] = mapped_column(JsonType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(RawRecord, "before_update")
def prevent_raw_record_update(*_args) -> None:
    raise ValueError("Raw records are immutable")


class PersonRecord(Base):
    __tablename__ = "person_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    raw_record_id: Mapped[str] = mapped_column(ForeignKey("raw_records.id"), unique=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    source_record_id: Mapped[str] = mapped_column(String(240), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(300))
    normalized_name: Mapped[str | None] = mapped_column(String(300), index=True)
    first_name: Mapped[str | None] = mapped_column(String(120))
    last_name: Mapped[str | None] = mapped_column(String(160))
    cedula_display: Mapped[str | None] = mapped_column(String(80))
    cedula_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    phone_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    photo_url: Mapped[str | None] = mapped_column(Text)
    photo_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    identity_token_version: Mapped[str] = mapped_column(
        String(80), nullable=False, default="hmac-sha256-v1"
    )
    status: Mapped[str | None] = mapped_column(String(120))
    age: Mapped[int | None] = mapped_column(Integer)
    location_general: Mapped[str | None] = mapped_column(String(240))
    source_date: Mapped[str | None] = mapped_column(String(80))
    quality_score: Mapped[float | None] = mapped_column(Float)
    quality_evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DuplicateCandidate(Base):
    __tablename__ = "duplicate_candidates"
    __table_args__ = (
        UniqueConstraint(
            "left_person_record_id",
            "right_person_record_id",
            name="uq_candidate_pair",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    left_person_record_id: Mapped[str] = mapped_column(ForeignKey("person_records.id"), index=True)
    right_person_record_id: Mapped[str] = mapped_column(ForeignKey("person_records.id"), index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    review_bucket: Mapped[str] = mapped_column(String(80), nullable=False)
    conflict_flags_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    model_version: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DuplicateCluster(Base):
    __tablename__ = "duplicate_clusters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    cluster_key: Mapped[str] = mapped_column(String(160), unique=True, nullable=False, index=True)
    canonical_person_record_id: Mapped[str | None] = mapped_column(ForeignKey("person_records.id"))
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(60), nullable=False, default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DuplicateClusterMember(Base):
    __tablename__ = "duplicate_cluster_members"
    __table_args__ = (
        UniqueConstraint("cluster_id", "person_record_id", name="uq_cluster_member"),
    )

    cluster_id: Mapped[str] = mapped_column(
        ForeignKey("duplicate_clusters.id"), primary_key=True
    )
    person_record_id: Mapped[str] = mapped_column(ForeignKey("person_records.id"), primary_key=True)
    membership_confidence: Mapped[float] = mapped_column(Float, nullable=False)


class ReviewCase(Base):
    __tablename__ = "review_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    duplicate_candidate_id: Mapped[str] = mapped_column(
        ForeignKey("duplicate_candidates.id"), unique=True
    )
    cluster_id: Mapped[str | None] = mapped_column(String(36))
    queue: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="open", index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(240))
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    review_case_id: Mapped[str] = mapped_column(ForeignKey("review_cases.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(80), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    decided_by: Mapped[str] = mapped_column(String(240), nullable=False)
    evidence_snapshot_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PromotionRequest(Base):
    __tablename__ = "promotion_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending", index=True)
    requested_by: Mapped[str] = mapped_column(String(240), nullable=False)
    request_reason: Mapped[str] = mapped_column(Text, nullable=False)
    summary_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    decided_by: Mapped[str | None] = mapped_column(String(240))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QuarantineRecord(Base):
    __tablename__ = "quarantine_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)
    job_chunk_id: Mapped[str | None] = mapped_column(ForeignKey("job_chunks.id"), index=True)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"), index=True)
    source_record_id: Mapped[str | None] = mapped_column(String(240), index=True)
    reason_code: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    reason_message: Mapped[str] = mapped_column(Text, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json_redacted: Mapped[dict] = mapped_column(JsonType, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuarantineEvent(Base):
    __tablename__ = "quarantine_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    quarantine_record_id: Mapped[str] = mapped_column(
        ForeignKey("quarantine_records.id"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(240))
    message: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_type: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(240), nullable=False)
    operation: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(120))
    policy_decision: Mapped[str] = mapped_column(String(80), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    trace_id: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
