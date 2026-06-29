from typing import Any, Literal

from pydantic import BaseModel, Field


class SourceManifestCreate(BaseModel):
    source_slug: str = Field(min_length=2, max_length=120)
    source_display_name: str = Field(min_length=2, max_length=240)
    owner: str = Field(min_length=2, max_length=240)
    manifest_json: dict[str, Any]
    rate_limit_policy_json: dict[str, Any] = Field(default_factory=dict)
    sensitive_fields_json: dict[str, Any] = Field(default_factory=dict)


class SourceManifestResponse(BaseModel):
    id: str
    source_id: str
    source_slug: str
    version: int
    approval_status: str
    manifest_json: dict[str, Any]


class ApproveManifestRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class CreateIngestionJobRequest(BaseModel):
    source_manifest_version_id: str
    idempotency_key: str | None = Field(default=None, max_length=120)


class JobResponse(BaseModel):
    id: str
    type: str
    status: str
    idempotency_key: str | None = None
    attempt_count: int
    progress_json: dict[str, Any]
    summary_json: dict[str, Any]
    error_code: str | None = None
    error_message: str | None = None


class JobEventResponse(BaseModel):
    id: str
    job_id: str
    sequence: int
    event_type: str
    phase: str | None = None
    message: str | None = None
    metadata_json: dict[str, Any]
    created_at: str


class ReviewDecisionRequest(BaseModel):
    decision: Literal["confirm_duplicate", "reject_duplicate", "insufficient_data", "escalate"]
    reason: str = Field(min_length=3, max_length=2000)


class ReviewCaseResponse(BaseModel):
    id: str
    duplicate_candidate_id: str
    cluster_id: str | None = None
    queue: str
    status: str
    priority: int


class PersonRecordSummary(BaseModel):
    id: str
    source_id: str
    source_record_id: str
    display_name: str | None = None
    normalized_name: str | None = None
    status: str | None = None
    age: int | None = None
    location_general: str | None = None
    quality_score: float | None = None


class DuplicateCandidateDetailResponse(BaseModel):
    id: str
    confidence: float
    review_bucket: str
    evidence_json: dict[str, Any]
    conflict_flags_json: dict[str, Any]
    left: PersonRecordSummary
    right: PersonRecordSummary


class DuplicateClusterResponse(BaseModel):
    id: str
    cluster_key: str
    canonical_person_record_id: str | None = None
    confidence: float
    status: str
    member_count: int


class DuplicateClusterDetailResponse(DuplicateClusterResponse):
    members: list[PersonRecordSummary]


class OpsStartApprovedIngestionRequest(BaseModel):
    source_manifest_version_id: str
    runbook_reason: str = Field(min_length=3, max_length=500)


class OpsRetryJobRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
