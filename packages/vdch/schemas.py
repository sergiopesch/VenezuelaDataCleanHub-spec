from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceManifestCreate(StrictRequestModel):
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


class SourceStatusUpdateRequest(StrictRequestModel):
    status: Literal["active", "disabled", "archived"]
    reason: str = Field(min_length=3, max_length=500)


class PaginationMeta(BaseModel):
    limit: int
    offset: int
    total: int


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
    manifest_summary: dict[str, Any]


class SourceListResponse(BaseModel):
    items: list[SourceResponse]
    meta: PaginationMeta


class SourceManifestListResponse(BaseModel):
    items: list[SourceManifestResponse]
    meta: PaginationMeta


class ApproveManifestRequest(StrictRequestModel):
    reason: str = Field(min_length=3, max_length=500)


class CreateIngestionJobRequest(StrictRequestModel):
    source_manifest_version_id: str
    idempotency_key: str | None = Field(default=None, max_length=120)


class JobResponse(BaseModel):
    id: str
    type: str
    status: str
    parent_job_id: str | None = None
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
    trace_id: str | None = None
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


class JobEventListResponse(BaseModel):
    items: list[JobEventResponse]
    meta: PaginationMeta


class JobChunkListResponse(BaseModel):
    items: list[JobChunkResponse]
    meta: PaginationMeta


class ReviewDecisionRequest(StrictRequestModel):
    decision: Literal["confirm_duplicate", "reject_duplicate", "insufficient_data", "escalate"]
    reason: str = Field(min_length=3, max_length=2000)


class ReviewAssignmentRequest(StrictRequestModel):
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


class ReviewCaseListResponse(BaseModel):
    items: list[ReviewCaseResponse]
    meta: PaginationMeta


class PromotionCreateRequest(StrictRequestModel):
    job_id: str = Field(min_length=1, max_length=36)
    reason: str = Field(min_length=3, max_length=2000)


class PromotionDecisionRequest(StrictRequestModel):
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


class PromotionListResponse(BaseModel):
    items: list[PromotionResponse]
    meta: PaginationMeta


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


class QuarantineRecordListResponse(BaseModel):
    items: list[QuarantineRecordResponse]
    meta: PaginationMeta


class QuarantineResolveRequest(StrictRequestModel):
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


class DuplicateClusterListResponse(BaseModel):
    items: list[DuplicateClusterResponse]
    meta: PaginationMeta


class OpsStartApprovedIngestionRequest(StrictRequestModel):
    source_manifest_version_id: str
    runbook_reason: str = Field(min_length=3, max_length=500)


class OpsRetryJobRequest(StrictRequestModel):
    job_id: str = Field(min_length=1, max_length=36)
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
