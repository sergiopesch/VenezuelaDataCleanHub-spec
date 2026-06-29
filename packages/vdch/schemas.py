from typing import Any, Literal

from pydantic import BaseModel, Field


class SourceManifestCreate(BaseModel):
    source_slug: str = Field(min_length=2, max_length=120)
    source_display_name: str = Field(min_length=2, max_length=240)
    owner: str = Field(min_length=2, max_length=240)
    source_type: Literal[
        "api_json",
        "csv",
        "json",
        "jsonl",
        "html_static",
        "rss",
        "pdf",
        "manual_upload",
        "mobile_submission",
        "webapp_js",
    ] = "api_json"
    trust_tier: Literal["unreviewed", "trusted", "partner", "experimental"] = "unreviewed"
    permission_basis: str | None = Field(default=None, max_length=2000)
    allowed_domains_json: dict[str, Any] = Field(default_factory=dict)
    manifest_json: dict[str, Any]
    parser_name: str = Field(default="person_json_v1", min_length=2, max_length=120)
    parser_version: str = Field(default="1", min_length=1, max_length=80)
    adapter_name: str | None = Field(default=None, max_length=120)
    adapter_config_json: dict[str, Any] = Field(default_factory=dict)
    rate_limit_policy_json: dict[str, Any] = Field(default_factory=dict)
    required_keywords_json: dict[str, Any] = Field(default_factory=dict)
    sensitive_fields_json: dict[str, Any] = Field(default_factory=dict)
    review_notes: str | None = Field(default=None, max_length=4000)


class SourceResponse(BaseModel):
    id: str
    slug: str
    display_name: str
    owner: str
    status: str
    trust_tier: str
    source_type: str
    permission_basis: str | None = None
    allowed_domains_json: dict[str, Any]
    default_rate_limit_json: dict[str, Any]
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    last_successful_job_id: str | None = None
    last_failed_job_id: str | None = None


class SourceStatusUpdateRequest(BaseModel):
    status: Literal["active", "disabled", "archived"]
    reason: str = Field(min_length=3, max_length=500)


class SourceManifestResponse(BaseModel):
    id: str
    source_id: str
    source_slug: str
    source_status: str
    source_type: str
    trust_tier: str
    permission_basis: str | None = None
    version: int
    approval_status: str
    parser_name: str
    parser_version: str
    adapter_name: str
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


class JobChunkResponse(BaseModel):
    id: str
    job_id: str
    sequence: int
    status: str
    source_uri: str | None = None
    checkpoint_json: dict[str, Any]
    records_seen: int
    raw_records_created: int
    person_records_created: int
    quarantine_records_created: int
    error_code: str | None = None
    error_message: str | None = None


class ReviewDecisionRequest(BaseModel):
    decision: Literal["confirm_duplicate", "reject_duplicate", "insufficient_data", "escalate"]
    reason: str = Field(min_length=3, max_length=2000)


class ReviewAssignmentRequest(BaseModel):
    assigned_to: str = Field(min_length=2, max_length=240)
    reason: str = Field(min_length=3, max_length=500)


class ReviewCaseResponse(BaseModel):
    id: str
    duplicate_candidate_id: str
    cluster_id: str | None = None
    queue: str
    status: str
    assigned_to: str | None = None
    priority: int


class PromotionCreateRequest(BaseModel):
    job_id: str = Field(min_length=1, max_length=36)
    reason: str = Field(min_length=3, max_length=2000)


class PromotionDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    reason: str = Field(min_length=3, max_length=2000)


class PromotionResponse(BaseModel):
    id: str
    job_id: str
    status: str
    requested_by: str
    summary_json: dict[str, Any]
    decided_by: str | None = None
    decided_at: str | None = None
    created_at: str


class QuarantineRecordResponse(BaseModel):
    id: str
    job_id: str
    job_chunk_id: str | None = None
    source_id: str | None = None
    source_record_id: str | None = None
    reason_code: str
    reason_message: str
    status: str
    created_at: str


class QuarantineResolveRequest(BaseModel):
    status: Literal["resolved", "dismissed"]
    reason: str = Field(min_length=3, max_length=1000)


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


class OpsJobDiagnosticsResponse(BaseModel):
    job_id: str
    status: str
    type: str
    attempt_count: int
    phase: str | None = None
    records_seen: int
    raw_records_created: int
    person_records_created: int
    quarantine_records_created: int
    duplicate_candidates_created: int
    duplicate_clusters_created: int
    open_review_cases: int
    chunk_count: int
    failed_chunk_count: int
    latest_event_types: list[str]
    error_code: str | None = None
    safe_for_agent: bool = True


class OpsDailyQualitySummaryResponse(BaseModel):
    jobs_total: int
    jobs_completed: int
    jobs_failed: int
    records_seen: int
    raw_records_created: int
    person_records_created: int
    quarantine_records_open: int
    open_review_cases: int
    duplicate_candidates: int
    duplicate_clusters_open: int
    safe_for_agent: bool = True
