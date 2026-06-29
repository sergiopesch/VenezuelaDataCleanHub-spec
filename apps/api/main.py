from collections.abc import Generator

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from vdch.config import get_settings
from vdch.db import get_session
from vdch.matching import review_case_query
from vdch.models import (
    DuplicateCandidate,
    DuplicateCluster,
    DuplicateClusterMember,
    Job,
    JobChunk,
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
    DuplicateClusterResponse,
    JobChunkResponse,
    JobEventResponse,
    JobResponse,
    OpsDailyQualitySummaryResponse,
    OpsJobDiagnosticsResponse,
    OpsRetryJobRequest,
    OpsStartApprovedIngestionRequest,
    PersonRecordSummary,
    PromotionCreateRequest,
    PromotionDecisionRequest,
    PromotionResponse,
    QuarantineRecordResponse,
    QuarantineResolveRequest,
    ReviewAssignmentRequest,
    ReviewCaseResponse,
    ReviewDecisionRequest,
    SourceManifestCreate,
    SourceManifestResponse,
    SourceResponse,
    SourceStatusUpdateRequest,
)
from vdch.security import Actor, check_policy, get_actor, require_scope
from vdch.services import (
    SAFE_JOB_FAILURE_MESSAGE,
    append_job_event,
    approve_manifest,
    as_http_error,
    assign_review_case,
    build_daily_quality_summary,
    build_ops_job_diagnostics,
    create_ingestion_job,
    create_promotion_request,
    create_source_manifest,
    decide_promotion_request,
    decide_review_case,
    get_source,
    list_job_chunks,
    list_job_events,
    list_manifests,
    list_promotion_requests,
    list_quarantine_records,
    list_sources,
    resolve_quarantine_record,
    run_manifest_ingestion,
    update_source_status,
)
from vdch.workflow_client import start_ingestion_workflow

SENSITIVE_EVENT_METADATA_KEYS = {"reason", "runbook_reason"}

app = FastAPI(
    title="VenezuelaDataCleanHub API",
    version="0.1.0",
    description="Production-shaped foundation API for approved ingestion and review workflows.",
)


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
        manifest_json=redacted_manifest(manifest.manifest_json),
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


def redacted_manifest(manifest: dict) -> dict:
    redacted = dict(manifest)
    if isinstance(redacted.get("headers"), dict):
        redacted["headers"] = {name: "[REDACTED]" for name in redacted["headers"]}
    return redacted


def job_response(job: Job) -> JobResponse:
    error_message = SAFE_JOB_FAILURE_MESSAGE if job.error_message else None
    return JobResponse(
        id=job.id,
        type=job.type,
        status=job.status,
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
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> SourceManifestResponse:
    await require_scope(actor, "operator")
    policy_decision = await check_policy(actor, "source_manifest.create", {"type": "manifest"})
    try:
        manifest = create_source_manifest(
            session,
            payload=payload,
            actor=actor,
            policy_decision=policy_decision,
            settings=get_settings(),
        )
        session.commit()
        return manifest_response(session, manifest)
    except Exception as exc:
        session.rollback()
        raise as_http_error(exc) from exc


@app.get("/v1/sources", response_model=list[SourceResponse])
async def list_sources_endpoint(
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
    status_filter: str = Query(default="all", alias="status"),
) -> list[SourceResponse]:
    await require_scope(actor, "operator")
    sources = list_sources(session, status_filter=status_filter)
    return [source_response(source) for source in sources]


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
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> SourceResponse:
    await require_scope(actor, "data_steward")
    policy_decision = await check_policy(
        actor, "source.update_status", {"type": "source", "id": source_ref}
    )
    try:
        source = update_source_status(
            session,
            source_ref=source_ref,
            new_status=payload.status,
            reason=payload.reason,
            actor=actor,
            policy_decision=policy_decision,
        )
        session.commit()
        return source_response(source)
    except Exception as exc:
        session.rollback()
        raise as_http_error(exc) from exc


@app.get("/v1/source-manifests", response_model=list[SourceManifestResponse])
async def list_source_manifests_endpoint(
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> list[SourceManifestResponse]:
    await require_scope(actor, "operator")
    return [manifest_response(session, manifest) for manifest in list_manifests(session)]


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
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> SourceManifestResponse:
    await require_scope(actor, "data_steward")
    policy_decision = await check_policy(
        actor, "source_manifest.approve", {"type": "manifest", "id": manifest_id}
    )
    try:
        manifest = approve_manifest(
            session,
            manifest_id=manifest_id,
            actor=actor,
            policy_decision=policy_decision,
            reason=payload.reason,
        )
        session.commit()
        return manifest_response(session, manifest)
    except Exception as exc:
        session.rollback()
        raise as_http_error(exc) from exc


@app.post("/v1/ingestion-jobs", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_ingestion_job_endpoint(
    payload: CreateIngestionJobRequest,
    background_tasks: BackgroundTasks,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> JobResponse:
    await require_scope(actor, "operator")
    policy_decision = await check_policy(
        actor,
        "job.create.approved_manifest_ingestion",
        {"type": "source_manifest_version", "id": payload.source_manifest_version_id},
    )
    try:
        job = create_ingestion_job(
            session,
            manifest_id=payload.source_manifest_version_id,
            actor=actor,
            policy_decision=policy_decision,
            idempotency_key=payload.idempotency_key,
            metadata={"idempotency_key": payload.idempotency_key},
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


@app.get("/v1/jobs/{job_id}/events", response_model=list[JobEventResponse])
async def get_job_events_endpoint(
    job_id: str,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> list[JobEventResponse]:
    await require_scope(actor, "operator")
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return [job_event_response(event) for event in list_job_events(session, job_id=job.id)]


@app.get("/v1/jobs/{job_id}/chunks", response_model=list[JobChunkResponse])
async def get_job_chunks_endpoint(
    job_id: str,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> list[JobChunkResponse]:
    await require_scope(actor, "operator")
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return [job_chunk_response(chunk) for chunk in list_job_chunks(session, job_id=job.id)]


@app.get("/v1/quarantine-records", response_model=list[QuarantineRecordResponse])
async def list_quarantine_records_endpoint(
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
    status_filter: str = Query(default="open", alias="status"),
    job_id: str | None = Query(default=None),
) -> list[QuarantineRecordResponse]:
    await require_scope(actor, "operator")
    records = list_quarantine_records(session, status_filter=status_filter, job_id=job_id)
    return [quarantine_record_response(record) for record in records]


@app.post(
    "/v1/quarantine-records/{quarantine_record_id}/resolve",
    response_model=QuarantineRecordResponse,
)
async def resolve_quarantine_record_endpoint(
    quarantine_record_id: str,
    payload: QuarantineResolveRequest,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> QuarantineRecordResponse:
    await require_scope(actor, "operator")
    policy_decision = await check_policy(
        actor,
        "quarantine.resolve",
        {"type": "quarantine_record", "id": quarantine_record_id},
    )
    try:
        record = resolve_quarantine_record(
            session,
            quarantine_record_id=quarantine_record_id,
            new_status=payload.status,
            reason=payload.reason,
            actor=actor,
            policy_decision=policy_decision,
        )
        session.commit()
        return quarantine_record_response(record)
    except Exception as exc:
        session.rollback()
        raise as_http_error(exc) from exc


@app.get("/v1/review-cases", response_model=list[ReviewCaseResponse])
async def list_review_cases_endpoint(
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
    status_filter: str = Query(default="open", alias="status"),
) -> list[ReviewCaseResponse]:
    await require_scope(actor, "reviewer")
    cases = session.scalars(review_case_query(status_filter)).all()
    return [
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
    ]


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


@app.get("/v1/duplicate-clusters", response_model=list[DuplicateClusterResponse])
async def list_duplicate_clusters_endpoint(
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
    status_filter: str = Query(default="open", alias="status"),
) -> list[DuplicateClusterResponse]:
    await require_scope(actor, "reviewer")
    query = select(DuplicateCluster)
    if status_filter != "all":
        query = query.where(DuplicateCluster.status == status_filter)
    clusters = session.scalars(query.order_by(DuplicateCluster.confidence.desc())).all()
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
    return responses


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
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> ReviewCaseResponse:
    await require_scope(actor, "reviewer")
    policy_decision = await check_policy(
        actor, "review_case.assign", {"type": "review_case", "id": review_case_id}
    )
    try:
        review_case = assign_review_case(
            session,
            review_case_id=review_case_id,
            assigned_to=payload.assigned_to,
            reason=payload.reason,
            actor=actor,
            policy_decision=policy_decision,
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
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    await require_scope(actor, "reviewer")
    policy_decision = await check_policy(
        actor, "review_case.decide", {"type": "review_case", "id": review_case_id}
    )
    try:
        decision = decide_review_case(
            session,
            review_case_id=review_case_id,
            decision=payload.decision,
            reason=payload.reason,
            actor=actor,
            policy_decision=policy_decision,
        )
        session.commit()
        return {"id": decision.id, "status": "created"}
    except Exception as exc:
        session.rollback()
        raise as_http_error(exc) from exc


@app.post("/v1/promotions", response_model=PromotionResponse, status_code=status.HTTP_201_CREATED)
async def create_promotion_request_endpoint(
    payload: PromotionCreateRequest,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> PromotionResponse:
    await require_scope(actor, "operator")
    policy_decision = await check_policy(
        actor,
        "promotion.request",
        {"type": "job", "id": payload.job_id},
    )
    try:
        promotion = create_promotion_request(
            session,
            job_id=payload.job_id,
            reason=payload.reason,
            actor=actor,
            policy_decision=policy_decision,
        )
        session.commit()
        return promotion_response(promotion)
    except Exception as exc:
        session.rollback()
        raise as_http_error(exc) from exc


@app.get("/v1/promotions", response_model=list[PromotionResponse])
async def list_promotion_requests_endpoint(
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
    status_filter: str = Query(default="all", alias="status"),
) -> list[PromotionResponse]:
    await require_scope(actor, "data_steward")
    promotions = list_promotion_requests(session, status_filter=status_filter)
    return [promotion_response(promotion) for promotion in promotions]


@app.post("/v1/promotions/{promotion_id}/decision", response_model=PromotionResponse)
async def decide_promotion_request_endpoint(
    promotion_id: str,
    payload: PromotionDecisionRequest,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> PromotionResponse:
    await require_scope(actor, "data_steward")
    policy_decision = await check_policy(
        actor,
        "promotion.decide",
        {"type": "promotion_request", "id": promotion_id},
    )
    try:
        promotion = decide_promotion_request(
            session,
            promotion_id=promotion_id,
            decision=payload.decision,
            reason=payload.reason,
            actor=actor,
            policy_decision=policy_decision,
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
    background_tasks: BackgroundTasks,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> JobResponse:
    await require_scope(actor, "openclaw:runbook")
    policy_decision = await check_policy(
        actor,
        "ops.runbook.start_approved_ingestion",
        {"type": "source_manifest_version", "id": payload.source_manifest_version_id},
    )
    try:
        job = create_ingestion_job(
            session,
            manifest_id=payload.source_manifest_version_id,
            actor=actor,
            policy_decision=policy_decision,
            metadata={"runbook_reason": payload.runbook_reason},
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
    job_id: str,
    background_tasks: BackgroundTasks,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> JobResponse:
    await require_scope(actor, "openclaw:runbook")
    policy_decision = await check_policy(
        actor,
        "ops.runbook.retry_job",
        {"type": "job", "id": job_id},
    )
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "failed":
        raise HTTPException(status_code=409, detail="Only failed jobs can be retried")
    job.status = "queued"
    job.error_code = None
    job.error_message = None
    job.progress_json = {"phase": "retry_queued"}
    from vdch.audit import write_audit_event

    write_audit_event(
        session,
        actor=actor,
        operation="ops.runbook.retry_job",
        resource_type="job",
        resource_id=job.id,
        policy_decision=policy_decision,
        metadata={"reason": payload.reason},
    )
    append_job_event(
        session,
        job,
        event_type="job.retry_queued",
        phase="retry_queued",
        message="Failed job queued for retry.",
        metadata={"reason": payload.reason},
    )
    session.commit()
    settings = get_settings()
    if settings.temporal_enabled:
        await start_ingestion_workflow(job.id, settings)
    else:
        background_tasks.add_task(run_job_background, job.id)
    return job_response(job)


@app.get("/v1/ops/jobs/{job_id}/diagnostics", response_model=OpsJobDiagnosticsResponse)
async def ops_job_diagnostics_endpoint(
    job_id: str,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> OpsJobDiagnosticsResponse:
    await require_scope(actor, "openclaw:diagnostics")
    await check_policy(actor, "ops.job.diagnostics", {"type": "job", "id": job_id})
    try:
        return OpsJobDiagnosticsResponse(**build_ops_job_diagnostics(session, job_id=job_id))
    except Exception as exc:
        raise as_http_error(exc) from exc


@app.post("/v1/ops/reports/daily-quality-summary", response_model=OpsDailyQualitySummaryResponse)
async def ops_daily_quality_summary_endpoint(
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> OpsDailyQualitySummaryResponse:
    await require_scope(actor, "openclaw:diagnostics")
    await check_policy(actor, "ops.report.daily_quality_summary", {"type": "ops_report"})
    return OpsDailyQualitySummaryResponse(**build_daily_quality_summary(session))
