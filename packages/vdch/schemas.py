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
    progress_json: dict[str, Any]
    summary_json: dict[str, Any]
    error_code: str | None = None
    error_message: str | None = None


class ReviewDecisionRequest(BaseModel):
    decision: Literal["confirm_duplicate", "reject_duplicate", "insufficient_data", "escalate"]
    reason: str = Field(min_length=3, max_length=2000)


class ReviewCaseResponse(BaseModel):
    id: str
    duplicate_candidate_id: str
    queue: str
    status: str
    priority: int


class OpsStartApprovedIngestionRequest(BaseModel):
    source_manifest_version_id: str
    runbook_reason: str = Field(min_length=3, max_length=500)


class OpsRetryJobRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
