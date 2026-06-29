from collections.abc import Generator
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware
from vdch.audit import write_audit_event
from vdch.config import get_settings
from vdch.db import get_session
from vdch.matching import review_case_query
from vdch.models import (
    DuplicateCandidate,
    DuplicateCluster,
    DuplicateClusterMember,
    Job,
    JobChunk,
    JobEvent,
    PersonRecord,
    PromotionRequest,
    QuarantineRecord,
    Source,
    SourceManifestVersion,
)
from vdch.schemas import (
    ApproveManifestRequest,
    CreateIngestionJobRequest,
    DuplicateCandidateDetailResponse,
    DuplicateClusterDetailResponse,
    DuplicateClusterListResponse,
    DuplicateClusterResponse,
    JobChunkListResponse,
    JobChunkResponse,
    JobEventListResponse,
    JobEventResponse,
    JobResponse,
    OpsDailyQualitySummaryResponse,
    OpsJobDiagnosticsResponse,
    OpsRetryJobRequest,
    OpsStartApprovedIngestionRequest,
    PersonRecordSummary,
    PromotionCreateRequest,
    PromotionDecisionRequest,
    PromotionListResponse,
    PromotionResponse,
    QuarantineRecordListResponse,
    QuarantineRecordResponse,
    QuarantineResolveRequest,
    ReviewAssignmentRequest,
    ReviewCaseListResponse,
    ReviewCaseResponse,
    ReviewDecisionRequest,
    SourceListResponse,
    SourceManifestCreate,
    SourceManifestListResponse,
    SourceManifestResponse,
    SourceResponse,
    SourceStatusUpdateRequest,
)
from vdch.security import (
    Actor,
    RequestContext,
    check_policy,
    get_actor,
    get_request_context,
    require_actor_type,
    require_scope,
)
from vdch.services import (
    SAFE_JOB_FAILURE_MESSAGE,
    approve_manifest,
    as_http_error,
    assign_review_case,
    build_daily_quality_summary,
    build_ops_job_diagnostics,
    create_ingestion_job,
    create_promotion_request,
    create_retry_job,
    create_source_manifest,
    decide_promotion_request,
    decide_review_case,
    get_source,
    resolve_quarantine_record,
    run_manifest_ingestion,
    update_source_status,
)
from vdch.workflow_client import start_ingestion_workflow

SENSITIVE_EVENT_METADATA_KEYS = {"idempotency_key", "reason", "runbook_reason"}
MAX_PAGE_LIMIT = 100

_settings = get_settings()
_docs_enabled = _settings.resolved_api_docs_enabled

app = FastAPI(
    title="VenezuelaDataCleanHub API",
    version="0.1.0",
    description="Production-shaped foundation API for approved ingestion and review workflows.",
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

if _settings.approved_trusted_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_settings.approved_trusted_hosts)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            request_size = int(content_length)
        except ValueError:
            request_size = 0
        if request_size > get_settings().max_api_request_bytes:
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body exceeds configured maximum size."},
            )
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


async def require_user(actor: Actor) -> None:
    await require_actor_type(actor, "user")


async def require_openclaw_agent(actor: Actor) -> None:
    await require_actor_type(actor, "agent")


def with_context_metadata(
    context: RequestContext,
    metadata: dict | None = None,
) -> dict:
    return {**(metadata or {}), **context.audit_metadata()}


def page_meta(*, limit: int, offset: int, total: int) -> dict:
    return {"limit": limit, "offset": offset, "total": total}


def manifest_policy_resource(session: Session, manifest_id: str) -> dict:
    manifest = session.get(SourceManifestVersion, manifest_id)
    if manifest is None:
        return {"type": "source_manifest_version", "id": manifest_id, "exists": False}
    source = session.get(Source, manifest.source_id)
    return {
        "type": "source_manifest_version",
        "id": manifest.id,
        "exists": True,
        "approval_status": manifest.approval_status,
        "source_id": manifest.source_id,
        "source_status": source.status if source else None,
        "source_trust_tier": source.trust_tier if source else None,
    }


def source_policy_resource(session: Session, source_ref: str) -> dict:
    source = session.get(Source, source_ref)
    if source is None:
        source = session.scalar(select(Source).where(Source.slug == source_ref))
    return {
        "type": "source",
        "id": source_ref,
        "exists": source is not None,
        "source_id": source.id if source else None,
        "source_status": source.status if source else None,
        "source_trust_tier": source.trust_tier if source else None,
    }


def manifest_response(session: Session, manifest: SourceManifestVersion) -> SourceManifestResponse:
    source = session.get(Source, manifest.source_id)
    return SourceManifestResponse(
        id=manifest.id,
        source_id=manifest.source_id,
        source_slug=source.slug if source else "",
        source_status=source.status if source else "",
        source_type=source.source_type if source else "",
        trust_tier=source.trust_tier if source else "",
        permission_basis=source.permission_basis if source else None,
        version=manifest.version,
        approval_status=manifest.approval_status,
        parser_name=manifest.parser_name,
        parser_version=manifest.parser_version,
        adapter_name=manifest.adapter_name,
        manifest_summary=manifest_summary(manifest),
    )


def source_response(source: Source) -> SourceResponse:
    return SourceResponse(
        id=source.id,
        slug=source.slug,
        display_name=source.display_name,
        owner=source.owner,
        status=source.status,
        trust_tier=source.trust_tier,
        source_type=source.source_type,
        permission_basis=source.permission_basis,
        allowed_domains_json=source.allowed_domains_json or {},
        default_rate_limit_json=source.default_rate_limit_json or {},
        reviewed_by=source.reviewed_by,
        reviewed_at=source.reviewed_at.isoformat() if source.reviewed_at else None,
        last_successful_job_id=source.last_successful_job_id,
        last_failed_job_id=source.last_failed_job_id,
    )


def manifest_summary(manifest: SourceManifestVersion) -> dict:
    manifest_json = manifest.manifest_json or {}
    field_mappings = manifest.field_mappings_json or manifest_json.get("field_mappings") or {}
    summary = {
        "type": manifest_json.get("type"),
        "parser_name": manifest.parser_name,
        "parser_version": manifest.parser_version,
        "adapter_name": manifest.adapter_name,
        "field_mapping_keys": sorted(field_mappings.keys()),
        "sample_payload": manifest.sample_payload_redacted_json or {},
    }
    if manifest_json.get("type") in {"http_json", "http_jsonl", "http_csv"}:
        from urllib.parse import urlparse

        parsed = urlparse(str(manifest_json.get("base_url") or ""))
        summary["host"] = parsed.hostname
        summary["records_path"] = manifest_json.get("records_path")
        if manifest_json.get("type") == "http_csv":
            summary["delimiter"] = manifest_json.get("delimiter", ",")
        summary["headers"] = sorted((manifest_json.get("headers") or {}).keys())
    return summary


def job_response(job: Job) -> JobResponse:
    error_message = SAFE_JOB_FAILURE_MESSAGE if job.error_message else None
    return JobResponse(
        id=job.id,
        type=job.type,
        status=job.status,
        parent_job_id=job.parent_job_id,
        idempotency_key=job.idempotency_key,
        attempt_count=job.attempt_count,
        progress_json=job.progress_json or {},
        summary_json=job.summary_json or {},
        error_code=job.error_code,
        error_message=error_message,
    )


def safe_event_metadata(metadata: dict) -> dict:
    return {
        key: "[REDACTED]" if key in SENSITIVE_EVENT_METADATA_KEYS else value
        for key, value in (metadata or {}).items()
    }


def job_event_response(event) -> JobEventResponse:
    return JobEventResponse(
        id=event.id,
        job_id=event.job_id,
        sequence=event.sequence,
        event_type=event.event_type,
        phase=event.phase,
        message=SAFE_JOB_FAILURE_MESSAGE if event.event_type == "job.failed" else event.message,
        metadata_json=safe_event_metadata(event.metadata_json or {}),
        trace_id=event.trace_id,
        created_at=event.created_at.isoformat(),
    )


def job_chunk_response(chunk: JobChunk) -> JobChunkResponse:
    return JobChunkResponse(
        id=chunk.id,
        job_id=chunk.job_id,
        sequence=chunk.sequence,
        status=chunk.status,
        source_uri=chunk.source_uri,
        checkpoint_json=chunk.checkpoint_json or {},
        records_seen=chunk.records_seen,
        raw_records_created=chunk.raw_records_created,
        person_records_created=chunk.person_records_created,
        quarantine_records_created=chunk.quarantine_records_created,
        error_code=chunk.error_code,
        error_message=SAFE_JOB_FAILURE_MESSAGE if chunk.error_message else None,
    )


def quarantine_record_response(record: QuarantineRecord) -> QuarantineRecordResponse:
    return QuarantineRecordResponse(
        id=record.id,
        job_id=record.job_id,
        job_chunk_id=record.job_chunk_id,
        source_id=record.source_id,
        source_record_id=record.source_record_id,
        reason_code=record.reason_code,
        reason_message=record.reason_message,
        status=record.status,
        created_at=record.created_at.isoformat(),
    )


def promotion_response(promotion: PromotionRequest) -> PromotionResponse:
    return PromotionResponse(
        id=promotion.id,
        job_id=promotion.job_id,
        status=promotion.status,
        requested_by=promotion.requested_by,
        summary_json=promotion.summary_json or {},
        decided_by=promotion.decided_by,
        decided_at=promotion.decided_at.isoformat() if promotion.decided_at else None,
        created_at=promotion.created_at.isoformat(),
    )


def person_summary(person: PersonRecord) -> PersonRecordSummary:
    return PersonRecordSummary(
        id=person.id,
        source_id=person.source_id,
        source_record_id=person.source_record_id,
        display_name=person.display_name,
        normalized_name=person.normalized_name,
        status=person.status,
        age=person.age,
        location_general=person.location_general,
        quality_score=person.quality_score,
    )


def run_job_background(job_id: str) -> None:
    session_gen: Generator[Session, None, None] = get_session()
    session = next(session_gen)
    try:
        run_manifest_ingestion(session, job_id=job_id)
        session.commit()
    except Exception:
        session.commit()
    finally:
        session.close()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz(session: Session = Depends(get_session)) -> dict[str, str]:
    session.execute(select(1))
    return {"status": "ready"}


@app.post(
    "/v1/source-manifests",
    response_model=SourceManifestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_source_manifest_endpoint(
    payload: SourceManifestCreate,
    request: Request,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> SourceManifestResponse:
    context = get_request_context(request)
    await require_user(actor)
    await require_scope(actor, "operator")
    policy_decision = await check_policy(
        actor,
        "source_manifest.create",
        {"type": "manifest", "operation_risk": "medium"},
        context=context,
    )
    try:
        manifest = create_source_manifest(
            session,
            payload=payload,
            actor=actor,
            policy_decision=policy_decision,
            settings=get_settings(),
            metadata=context.audit_metadata(),
        )
        session.commit()
        return manifest_response(session, manifest)
    except Exception as exc:
        session.rollback()
        raise as_http_error(exc) from exc


@app.get("/v1/sources", response_model=SourceListResponse)
async def list_sources_endpoint(
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
    status_filter: str = Query(default="all", alias="status"),
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> SourceListResponse:
    await require_scope(actor, "operator")
    query = select(Source)
    if status_filter != "all":
        query = query.where(Source.status == status_filter)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    sources = session.scalars(query.order_by(Source.slug.asc()).limit(limit).offset(offset)).all()
    return SourceListResponse(
        items=[source_response(source) for source in sources],
        meta=page_meta(limit=limit, offset=offset, total=total),
    )


@app.get("/v1/sources/{source_ref}", response_model=SourceResponse)
async def get_source_endpoint(
    source_ref: str,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> SourceResponse:
    await require_scope(actor, "operator")
    try:
        return source_response(get_source(session, source_ref=source_ref))
    except Exception as exc:
        raise as_http_error(exc) from exc


@app.patch("/v1/sources/{source_ref}/status", response_model=SourceResponse)
async def update_source_status_endpoint(
    source_ref: str,
    payload: SourceStatusUpdateRequest,
    request: Request,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> SourceResponse:
    context = get_request_context(request)
    await require_user(actor)
    await require_scope(actor, "data_steward")
    policy_decision = await check_policy(
        actor,
        "source.update_status",
        source_policy_resource(session, source_ref) | {"operation_risk": "high"},
        context=context,
    )
    try:
        source = update_source_status(
            session,
            source_ref=source_ref,
            new_status=payload.status,
            reason=payload.reason,
            actor=actor,
            policy_decision=policy_decision,
            metadata=context.audit_metadata(),
        )
        session.commit()
        return source_response(source)
    except Exception as exc:
        session.rollback()
        raise as_http_error(exc) from exc


@app.get("/v1/source-manifests", response_model=SourceManifestListResponse)
async def list_source_manifests_endpoint(
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> SourceManifestListResponse:
    await require_scope(actor, "operator")
    query = select(SourceManifestVersion)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    manifests = session.scalars(
        query.order_by(SourceManifestVersion.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return SourceManifestListResponse(
        items=[manifest_response(session, manifest) for manifest in manifests],
        meta=page_meta(limit=limit, offset=offset, total=total),
    )


@app.get("/v1/source-manifests/{manifest_id}", response_model=SourceManifestResponse)
async def get_source_manifest_endpoint(
    manifest_id: str,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> SourceManifestResponse:
    await require_scope(actor, "operator")
    manifest = session.get(SourceManifestVersion, manifest_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Manifest version not found")
    return manifest_response(session, manifest)


@app.post("/v1/source-manifests/{manifest_id}/approve", response_model=SourceManifestResponse)
async def approve_source_manifest_endpoint(
    manifest_id: str,
    payload: ApproveManifestRequest,
    request: Request,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> SourceManifestResponse:
    context = get_request_context(request)
    await require_user(actor)
    await require_scope(actor, "data_steward")
    policy_decision = await check_policy(
        actor,
        "source_manifest.approve",
        manifest_policy_resource(session, manifest_id) | {"operation_risk": "high"},
        context=context,
    )
    try:
        manifest = approve_manifest(
            session,
            manifest_id=manifest_id,
            actor=actor,
            policy_decision=policy_decision,
            reason=payload.reason,
            metadata=context.audit_metadata(),
        )
        session.commit()
        return manifest_response(session, manifest)
    except Exception as exc:
        session.rollback()
        raise as_http_error(exc) from exc


@app.post("/v1/ingestion-jobs", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_ingestion_job_endpoint(
    payload: CreateIngestionJobRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> JobResponse:
    context = get_request_context(request)
    await require_user(actor)
    await require_scope(actor, "operator")
    policy_decision = await check_policy(
        actor,
        "job.create.approved_manifest_ingestion",
        manifest_policy_resource(session, payload.source_manifest_version_id)
        | {"operation_risk": "medium"},
        context=context,
    )
    try:
        job = create_ingestion_job(
            session,
            manifest_id=payload.source_manifest_version_id,
            actor=actor,
            policy_decision=policy_decision,
            idempotency_key=payload.idempotency_key,
            metadata=with_context_metadata(context, {"idempotency_key": payload.idempotency_key}),
        )
        session.commit()
        settings = get_settings()
        if not getattr(job, "_vdch_created", True):
            return job_response(job)
        if settings.temporal_enabled:
            await start_ingestion_workflow(job.id, settings)
        else:
            background_tasks.add_task(run_job_background, job.id)
        return job_response(job)
    except Exception as exc:
        session.rollback()
        raise as_http_error(exc) from exc


@app.get("/v1/jobs/{job_id}", response_model=JobResponse)
async def get_job_endpoint(
    job_id: str,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> JobResponse:
    await require_scope(actor, "operator")
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_response(job)


@app.get("/v1/jobs/{job_id}/summary")
async def get_job_summary_endpoint(
    job_id: str,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict:
    await require_scope(actor, "operator")
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job.id, "status": job.status, "summary": job.summary_json or {}}


@app.get("/v1/jobs/{job_id}/events", response_model=JobEventListResponse)
async def get_job_events_endpoint(
    job_id: str,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> JobEventListResponse:
    await require_scope(actor, "operator")
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    query = select(JobEvent).where(JobEvent.job_id == job.id)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    events = session.scalars(
        query.order_by(JobEvent.sequence.asc()).limit(limit).offset(offset)
    ).all()
    return JobEventListResponse(
        items=[job_event_response(event) for event in events],
        meta=page_meta(limit=limit, offset=offset, total=total),
    )


@app.get("/v1/jobs/{job_id}/chunks", response_model=JobChunkListResponse)
async def get_job_chunks_endpoint(
    job_id: str,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> JobChunkListResponse:
    await require_scope(actor, "operator")
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    query = select(JobChunk).where(JobChunk.job_id == job.id)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    chunks = session.scalars(
        query.order_by(JobChunk.sequence.asc()).limit(limit).offset(offset)
    ).all()
    return JobChunkListResponse(
        items=[job_chunk_response(chunk) for chunk in chunks],
        meta=page_meta(limit=limit, offset=offset, total=total),
    )


@app.get("/v1/quarantine-records", response_model=QuarantineRecordListResponse)
async def list_quarantine_records_endpoint(
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
    status_filter: str = Query(default="open", alias="status"),
    job_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> QuarantineRecordListResponse:
    await require_scope(actor, "operator")
    query = select(QuarantineRecord)
    if status_filter != "all":
        query = query.where(QuarantineRecord.status == status_filter)
    if job_id:
        query = query.where(QuarantineRecord.job_id == job_id)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    records = session.scalars(
        query.order_by(QuarantineRecord.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return QuarantineRecordListResponse(
        items=[quarantine_record_response(record) for record in records],
        meta=page_meta(limit=limit, offset=offset, total=total),
    )


@app.post(
    "/v1/quarantine-records/{quarantine_record_id}/resolve",
    response_model=QuarantineRecordResponse,
)
async def resolve_quarantine_record_endpoint(
    quarantine_record_id: str,
    payload: QuarantineResolveRequest,
    request: Request,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> QuarantineRecordResponse:
    context = get_request_context(request)
    await require_user(actor)
    await require_scope(actor, "operator")
    policy_decision = await check_policy(
        actor,
        "quarantine.resolve",
        {"type": "quarantine_record", "id": quarantine_record_id, "operation_risk": "medium"},
        context=context,
    )
    try:
        record = resolve_quarantine_record(
            session,
            quarantine_record_id=quarantine_record_id,
            new_status=payload.status,
            reason=payload.reason,
            actor=actor,
            policy_decision=policy_decision,
            metadata=context.audit_metadata(),
        )
        session.commit()
        return quarantine_record_response(record)
    except Exception as exc:
        session.rollback()
        raise as_http_error(exc) from exc


@app.get("/v1/review-cases", response_model=ReviewCaseListResponse)
async def list_review_cases_endpoint(
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
    status_filter: str = Query(default="open", alias="status"),
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> ReviewCaseListResponse:
    await require_scope(actor, "reviewer")
    query = review_case_query(status_filter)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    cases = session.scalars(query.limit(limit).offset(offset)).all()
    return ReviewCaseListResponse(
        items=[
            ReviewCaseResponse(
                id=case.id,
                duplicate_candidate_id=case.duplicate_candidate_id,
                cluster_id=case.cluster_id,
                queue=case.queue,
                status=case.status,
                assigned_to=case.assigned_to,
                priority=case.priority,
            )
            for case in cases
        ],
        meta=page_meta(limit=limit, offset=offset, total=total),
    )


@app.get("/v1/duplicate-candidates/{candidate_id}", response_model=DuplicateCandidateDetailResponse)
async def get_duplicate_candidate_endpoint(
    candidate_id: str,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> DuplicateCandidateDetailResponse:
    await require_scope(actor, "reviewer")
    candidate = session.get(DuplicateCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Duplicate candidate not found")
    left = session.get(PersonRecord, candidate.left_person_record_id)
    right = session.get(PersonRecord, candidate.right_person_record_id)
    if left is None or right is None:
        raise HTTPException(status_code=500, detail="Candidate person records are missing")
    return DuplicateCandidateDetailResponse(
        id=candidate.id,
        confidence=candidate.confidence,
        review_bucket=candidate.review_bucket,
        evidence_json=candidate.evidence_json,
        conflict_flags_json=candidate.conflict_flags_json,
        left=person_summary(left),
        right=person_summary(right),
    )


@app.get("/v1/duplicate-clusters", response_model=DuplicateClusterListResponse)
async def list_duplicate_clusters_endpoint(
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
    status_filter: str = Query(default="open", alias="status"),
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> DuplicateClusterListResponse:
    await require_scope(actor, "reviewer")
    query = select(DuplicateCluster)
    if status_filter != "all":
        query = query.where(DuplicateCluster.status == status_filter)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    clusters = session.scalars(
        query.order_by(DuplicateCluster.confidence.desc()).limit(limit).offset(offset)
    ).all()
    responses = []
    for cluster in clusters:
        member_count = session.scalar(
            select(func.count())
            .select_from(DuplicateClusterMember)
            .where(DuplicateClusterMember.cluster_id == cluster.id)
        )
        responses.append(
            DuplicateClusterResponse(
                id=cluster.id,
                cluster_key=cluster.cluster_key,
                canonical_person_record_id=cluster.canonical_person_record_id,
                confidence=cluster.confidence,
                status=cluster.status,
                member_count=member_count or 0,
            )
        )
    return DuplicateClusterListResponse(
        items=responses,
        meta=page_meta(limit=limit, offset=offset, total=total),
    )


@app.get("/v1/duplicate-clusters/{cluster_id}", response_model=DuplicateClusterDetailResponse)
async def get_duplicate_cluster_endpoint(
    cluster_id: str,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> DuplicateClusterDetailResponse:
    await require_scope(actor, "reviewer")
    cluster = session.get(DuplicateCluster, cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail="Duplicate cluster not found")
    members = list(
        session.scalars(
            select(PersonRecord)
            .join(
                DuplicateClusterMember,
                PersonRecord.id == DuplicateClusterMember.person_record_id,
            )
            .where(DuplicateClusterMember.cluster_id == cluster.id)
            .order_by(PersonRecord.quality_score.desc(), PersonRecord.created_at.asc())
        )
    )
    return DuplicateClusterDetailResponse(
        id=cluster.id,
        cluster_key=cluster.cluster_key,
        canonical_person_record_id=cluster.canonical_person_record_id,
        confidence=cluster.confidence,
        status=cluster.status,
        member_count=len(members),
        members=[person_summary(member) for member in members],
    )


@app.post("/v1/review-cases/{review_case_id}/assign", response_model=ReviewCaseResponse)
async def assign_review_case_endpoint(
    review_case_id: str,
    payload: ReviewAssignmentRequest,
    request: Request,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> ReviewCaseResponse:
    context = get_request_context(request)
    await require_user(actor)
    await require_scope(actor, "reviewer")
    policy_decision = await check_policy(
        actor,
        "review_case.assign",
        {"type": "review_case", "id": review_case_id, "operation_risk": "medium"},
        context=context,
    )
    try:
        review_case = assign_review_case(
            session,
            review_case_id=review_case_id,
            assigned_to=payload.assigned_to,
            reason=payload.reason,
            actor=actor,
            policy_decision=policy_decision,
            metadata=context.audit_metadata(),
        )
        session.commit()
        return ReviewCaseResponse(
            id=review_case.id,
            duplicate_candidate_id=review_case.duplicate_candidate_id,
            cluster_id=review_case.cluster_id,
            queue=review_case.queue,
            status=review_case.status,
            assigned_to=review_case.assigned_to,
            priority=review_case.priority,
        )
    except Exception as exc:
        session.rollback()
        raise as_http_error(exc) from exc


@app.post("/v1/review-cases/{review_case_id}/decision", status_code=status.HTTP_201_CREATED)
async def decide_review_case_endpoint(
    review_case_id: str,
    payload: ReviewDecisionRequest,
    request: Request,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    context = get_request_context(request)
    await require_user(actor)
    await require_scope(actor, "reviewer")
    policy_decision = await check_policy(
        actor,
        "review_case.decide",
        {"type": "review_case", "id": review_case_id, "operation_risk": "high"},
        context=context,
    )
    try:
        decision = decide_review_case(
            session,
            review_case_id=review_case_id,
            decision=payload.decision,
            reason=payload.reason,
            actor=actor,
            policy_decision=policy_decision,
            metadata=context.audit_metadata(),
        )
        session.commit()
        return {"id": decision.id, "status": "created"}
    except Exception as exc:
        session.rollback()
        raise as_http_error(exc) from exc


@app.post("/v1/promotions", response_model=PromotionResponse, status_code=status.HTTP_201_CREATED)
async def create_promotion_request_endpoint(
    payload: PromotionCreateRequest,
    request: Request,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> PromotionResponse:
    context = get_request_context(request)
    await require_user(actor)
    await require_scope(actor, "operator")
    policy_decision = await check_policy(
        actor,
        "promotion.request",
        {"type": "job", "id": payload.job_id, "operation_risk": "high"},
        context=context,
    )
    try:
        promotion = create_promotion_request(
            session,
            job_id=payload.job_id,
            reason=payload.reason,
            actor=actor,
            policy_decision=policy_decision,
            metadata=context.audit_metadata(),
        )
        session.commit()
        return promotion_response(promotion)
    except Exception as exc:
        session.rollback()
        raise as_http_error(exc) from exc


@app.get("/v1/promotions", response_model=PromotionListResponse)
async def list_promotion_requests_endpoint(
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
    status_filter: str = Query(default="all", alias="status"),
    limit: int = Query(default=50, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> PromotionListResponse:
    await require_scope(actor, "data_steward")
    query = select(PromotionRequest)
    if status_filter != "all":
        query = query.where(PromotionRequest.status == status_filter)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    promotions = session.scalars(
        query.order_by(PromotionRequest.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return PromotionListResponse(
        items=[promotion_response(promotion) for promotion in promotions],
        meta=page_meta(limit=limit, offset=offset, total=total),
    )


@app.post("/v1/promotions/{promotion_id}/decision", response_model=PromotionResponse)
async def decide_promotion_request_endpoint(
    promotion_id: str,
    payload: PromotionDecisionRequest,
    request: Request,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> PromotionResponse:
    context = get_request_context(request)
    await require_user(actor)
    await require_scope(actor, "data_steward")
    policy_decision = await check_policy(
        actor,
        "promotion.decide",
        {"type": "promotion_request", "id": promotion_id, "operation_risk": "high"},
        context=context,
    )
    try:
        promotion = decide_promotion_request(
            session,
            promotion_id=promotion_id,
            decision=payload.decision,
            reason=payload.reason,
            actor=actor,
            policy_decision=policy_decision,
            metadata=context.audit_metadata(),
        )
        session.commit()
        return promotion_response(promotion)
    except Exception as exc:
        session.rollback()
        raise as_http_error(exc) from exc


@app.post(
    "/v1/ops/runbooks/start-approved-ingestion",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ops_start_approved_ingestion_endpoint(
    payload: OpsStartApprovedIngestionRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> JobResponse:
    context = get_request_context(request)
    await require_openclaw_agent(actor)
    await require_scope(actor, "openclaw:runbook")
    policy_decision = await check_policy(
        actor,
        "ops.runbook.start_approved_ingestion",
        manifest_policy_resource(session, payload.source_manifest_version_id)
        | {"operation_risk": "medium"},
        context=context,
    )
    try:
        job = create_ingestion_job(
            session,
            manifest_id=payload.source_manifest_version_id,
            actor=actor,
            policy_decision=policy_decision,
            metadata=with_context_metadata(context, {"runbook_reason": payload.runbook_reason}),
        )
        session.commit()
        settings = get_settings()
        if not getattr(job, "_vdch_created", True):
            return job_response(job)
        if settings.temporal_enabled:
            await start_ingestion_workflow(job.id, settings)
        else:
            background_tasks.add_task(run_job_background, job.id)
        return job_response(job)
    except Exception as exc:
        session.rollback()
        raise as_http_error(exc) from exc


@app.post("/v1/ops/runbooks/retry-job", response_model=JobResponse)
async def ops_retry_job_endpoint(
    payload: OpsRetryJobRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> JobResponse:
    context = get_request_context(request)
    await require_openclaw_agent(actor)
    await require_scope(actor, "openclaw:runbook")
    policy_decision = await check_policy(
        actor,
        "ops.runbook.retry_job",
        {"type": "job", "id": payload.job_id, "operation_risk": "medium"},
        context=context,
    )
    try:
        job = create_retry_job(
            session,
            failed_job_id=payload.job_id,
            actor=actor,
            policy_decision=policy_decision,
            reason=payload.reason,
            metadata=context.audit_metadata(),
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        raise as_http_error(exc) from exc
    settings = get_settings()
    if getattr(job, "_vdch_created", True):
        if settings.temporal_enabled:
            await start_ingestion_workflow(job.id, settings)
        else:
            background_tasks.add_task(run_job_background, job.id)
    return job_response(job)


@app.get("/v1/ops/jobs/{job_id}/diagnostics", response_model=OpsJobDiagnosticsResponse)
async def ops_job_diagnostics_endpoint(
    job_id: str,
    request: Request,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> OpsJobDiagnosticsResponse:
    context = get_request_context(request)
    await require_openclaw_agent(actor)
    await require_scope(actor, "openclaw:diagnostics")
    policy_decision = await check_policy(
        actor,
        "ops.job.diagnostics",
        {"type": "job", "id": job_id, "operation_risk": "low"},
        context=context,
    )
    try:
        diagnostics = OpsJobDiagnosticsResponse(**build_ops_job_diagnostics(session, job_id=job_id))
        write_audit_event(
            session,
            actor=actor,
            operation="ops.job.diagnostics",
            resource_type="job",
            resource_id=job_id,
            policy_decision=policy_decision,
            metadata=context.audit_metadata(),
            trace_id=context.request_id,
        )
        session.commit()
        return diagnostics
    except Exception as exc:
        session.rollback()
        raise as_http_error(exc) from exc


@app.post("/v1/ops/reports/daily-quality-summary", response_model=OpsDailyQualitySummaryResponse)
async def ops_daily_quality_summary_endpoint(
    request: Request,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> OpsDailyQualitySummaryResponse:
    context = get_request_context(request)
    await require_openclaw_agent(actor)
    await require_scope(actor, "openclaw:diagnostics")
    policy_decision = await check_policy(
        actor,
        "ops.report.daily_quality_summary",
        {"type": "ops_report", "operation_risk": "low"},
        context=context,
    )
    summary = OpsDailyQualitySummaryResponse(**build_daily_quality_summary(session))
    write_audit_event(
        session,
        actor=actor,
        operation="ops.report.daily_quality_summary",
        resource_type="ops_report",
        resource_id=None,
        policy_decision=policy_decision,
        metadata=context.audit_metadata(),
        trace_id=context.request_id,
    )
    session.commit()
    return summary
