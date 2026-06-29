from collections.abc import Generator

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from vdch.config import get_settings
from vdch.db import get_session
from vdch.matching import review_case_query
from vdch.models import Job, ReviewCase, Source, SourceManifestVersion
from vdch.schemas import (
    ApproveManifestRequest,
    CreateIngestionJobRequest,
    JobResponse,
    OpsRetryJobRequest,
    OpsStartApprovedIngestionRequest,
    ReviewCaseResponse,
    ReviewDecisionRequest,
    SourceManifestCreate,
    SourceManifestResponse,
)
from vdch.security import Actor, check_policy, get_actor, require_scope
from vdch.services import (
    approve_manifest,
    as_http_error,
    create_ingestion_job,
    create_source_manifest,
    decide_review_case,
    list_manifests,
    run_manifest_ingestion,
)
from vdch.workflow_client import start_ingestion_workflow

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
        version=manifest.version,
        approval_status=manifest.approval_status,
        manifest_json=manifest.manifest_json,
    )


def job_response(job: Job) -> JobResponse:
    return JobResponse(
        id=job.id,
        type=job.type,
        status=job.status,
        progress_json=job.progress_json or {},
        summary_json=job.summary_json or {},
        error_code=job.error_code,
        error_message=job.error_message,
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
            metadata={"idempotency_key": payload.idempotency_key},
        )
        session.commit()
        settings = get_settings()
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
            queue=case.queue,
            status=case.status,
            priority=case.priority,
        )
        for case in cases
    ]


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
    session.commit()
    settings = get_settings()
    if settings.temporal_enabled:
        await start_ingestion_workflow(job.id, settings)
    else:
        background_tasks.add_task(run_job_background, job.id)
    return job_response(job)


@app.get("/v1/ops/jobs/{job_id}/diagnostics")
async def ops_job_diagnostics_endpoint(
    job_id: str,
    actor: Actor = Depends(get_actor),
    session: Session = Depends(get_session),
) -> dict:
    await require_scope(actor, "openclaw:diagnostics")
    await check_policy(actor, "ops.job.diagnostics", {"type": "job", "id": job_id})
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    review_count = session.scalar(
        select(func.count()).select_from(ReviewCase).where(ReviewCase.status == "open")
    )
    return {
        "job": job_response(job).model_dump(),
        "open_review_cases": review_count,
        "safe_for_agent": True,
    }
