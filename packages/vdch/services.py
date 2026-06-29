from collections.abc import Iterable
from datetime import UTC
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vdch.adapters import AdapterError, adapter_name_for_manifest, get_adapter
from vdch.audit import write_audit_event
from vdch.config import Settings, get_settings
from vdch.manifest import ManifestValidationError, validate_manifest
from vdch.matching import create_duplicate_candidates, rebuild_duplicate_clusters
from vdch.models import (
    DuplicateCandidate,
    DuplicateCluster,
    Job,
    JobChunk,
    JobEvent,
    PersonRecord,
    PromotionRequest,
    QuarantineEvent,
    QuarantineRecord,
    RawRecord,
    ReviewCase,
    ReviewDecision,
    Source,
    SourceManifestVersion,
    utcnow,
)
from vdch.normalization import stable_json_hash
from vdch.parsers import ParserError, get_parser
from vdch.schemas import SourceManifestCreate
from vdch.security import Actor

SAFE_JOB_FAILURE_MESSAGE = "Job failed; inspect error_code and internal diagnostics."


class DomainError(RuntimeError):
    def __init__(self, message: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(message)
        self.status_code = status_code


def as_http_error(error: Exception) -> HTTPException:
    if isinstance(error, DomainError):
        return HTTPException(status_code=error.status_code, detail=str(error))
    return HTTPException(status_code=500, detail="Unexpected service error")


def create_source_manifest(
    session: Session,
    *,
    payload: SourceManifestCreate,
    actor: Actor,
    policy_decision: str,
    settings: Settings | None = None,
) -> SourceManifestVersion:
    resolved_settings = settings or get_settings()
    adapter_name = payload.adapter_name or adapter_name_for_manifest(payload.manifest_json)
    expected_adapter_name = adapter_name_for_manifest(payload.manifest_json)
    if adapter_name != expected_adapter_name:
        raise DomainError(
            f"manifest type requires adapter {expected_adapter_name}",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    try:
        get_parser(payload.parser_name, payload.parser_version)
        get_adapter(adapter_name, approved_hosts=resolved_settings.approved_manifest_hosts)
    except (AdapterError, ParserError) as exc:
        raise DomainError(str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY) from exc
    try:
        validate_manifest(
            payload.manifest_json,
            allow_sample=resolved_settings.allow_sample_manifests,
            approved_hosts=resolved_settings.approved_manifest_hosts,
        )
    except ManifestValidationError as exc:
        raise DomainError(str(exc)) from exc

    source = session.scalar(select(Source).where(Source.slug == payload.source_slug))
    if source is None:
        source = Source(
            slug=payload.source_slug,
            display_name=payload.source_display_name,
            owner=payload.owner,
            source_type=payload.source_type,
            trust_tier=payload.trust_tier,
            permission_basis=payload.permission_basis,
            allowed_domains_json=payload.allowed_domains_json,
            default_rate_limit_json=payload.rate_limit_policy_json,
        )
        session.add(source)
        session.flush()
    else:
        source.display_name = payload.source_display_name
        source.owner = payload.owner
        source.source_type = payload.source_type
        source.trust_tier = payload.trust_tier
        source.permission_basis = payload.permission_basis
        source.allowed_domains_json = payload.allowed_domains_json
        source.default_rate_limit_json = payload.rate_limit_policy_json
        source.updated_at = utcnow()

    latest_version = session.scalar(
        select(func.max(SourceManifestVersion.version)).where(
            SourceManifestVersion.source_id == source.id
        )
    )
    manifest = SourceManifestVersion(
        source_id=source.id,
        version=(latest_version or 0) + 1,
        manifest_json=payload.manifest_json,
        parser_name=payload.parser_name,
        parser_version=payload.parser_version,
        adapter_name=adapter_name,
        adapter_config_json=payload.adapter_config_json,
        field_mappings_json=payload.manifest_json["field_mappings"],
        approval_status="draft",
        rate_limit_policy_json=payload.rate_limit_policy_json,
        required_keywords_json=payload.required_keywords_json,
        sample_payload_redacted_json=_sample_payload_snapshot(payload.manifest_json),
        sensitive_fields_json=payload.sensitive_fields_json,
        review_notes=payload.review_notes,
    )
    session.add(manifest)
    session.flush()
    write_audit_event(
        session,
        actor=actor,
        operation="source_manifest.create",
        resource_type="source_manifest_version",
        resource_id=manifest.id,
        policy_decision=policy_decision,
        metadata={"source_slug": source.slug, "version": manifest.version},
    )
    return manifest


def approve_manifest(
    session: Session,
    *,
    manifest_id: str,
    actor: Actor,
    policy_decision: str,
    reason: str,
) -> SourceManifestVersion:
    manifest = session.get(SourceManifestVersion, manifest_id)
    if manifest is None:
        raise DomainError("Manifest version not found", status.HTTP_404_NOT_FOUND)
    source = session.get(Source, manifest.source_id)
    if source is None:
        raise DomainError("Manifest source not found", status.HTTP_404_NOT_FOUND)
    if source.status != "active":
        raise DomainError("Only active sources can be approved", status.HTTP_409_CONFLICT)
    if not source.permission_basis:
        raise DomainError("Source permission basis is required before approval")
    try:
        get_parser(manifest.parser_name, manifest.parser_version)
        get_adapter(manifest.adapter_name, approved_hosts=get_settings().approved_manifest_hosts)
        validate_manifest(
            manifest.manifest_json,
            allow_sample=get_settings().allow_sample_manifests,
            approved_hosts=get_settings().approved_manifest_hosts,
        )
        _validate_source_domain_policy(source, manifest.manifest_json)
    except (AdapterError, ParserError, ManifestValidationError) as exc:
        raise DomainError(str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY) from exc
    manifest.approval_status = "approved"
    manifest.approved_by = actor.actor_id
    manifest.approved_at = utcnow()
    source.reviewed_by = actor.actor_id
    source.reviewed_at = manifest.approved_at
    source.updated_at = utcnow()
    write_audit_event(
        session,
        actor=actor,
        operation="source_manifest.approve",
        resource_type="source_manifest_version",
        resource_id=manifest.id,
        policy_decision=policy_decision,
        metadata={"reason": reason},
    )
    return manifest


def list_manifests(session: Session) -> list[SourceManifestVersion]:
    return list(
        session.scalars(
            select(SourceManifestVersion).order_by(SourceManifestVersion.created_at.desc())
        ).all()
    )


def list_sources(session: Session, *, status_filter: str = "all") -> list[Source]:
    query = select(Source)
    if status_filter != "all":
        query = query.where(Source.status == status_filter)
    return list(session.scalars(query.order_by(Source.slug.asc())).all())


def get_source(session: Session, *, source_ref: str) -> Source:
    source = session.get(Source, source_ref)
    if source is None:
        source = session.scalar(select(Source).where(Source.slug == source_ref))
    if source is None:
        raise DomainError("Source not found", status.HTTP_404_NOT_FOUND)
    return source


def update_source_status(
    session: Session,
    *,
    source_ref: str,
    new_status: str,
    reason: str,
    actor: Actor,
    policy_decision: str,
) -> Source:
    if new_status not in {"active", "disabled", "archived"}:
        raise DomainError("Invalid source status", status.HTTP_422_UNPROCESSABLE_ENTITY)
    source = get_source(session, source_ref=source_ref)
    old_status = source.status
    source.status = new_status
    source.updated_at = utcnow()
    write_audit_event(
        session,
        actor=actor,
        operation="source.update_status",
        resource_type="source",
        resource_id=source.id,
        policy_decision=policy_decision,
        metadata={"old_status": old_status, "new_status": new_status, "reason": reason},
    )
    return source


def create_ingestion_job(
    session: Session,
    *,
    manifest_id: str,
    actor: Actor,
    policy_decision: str,
    idempotency_key: str | None = None,
    metadata: dict | None = None,
) -> Job:
    manifest = session.get(SourceManifestVersion, manifest_id)
    if manifest is None:
        raise DomainError("Manifest version not found", status.HTTP_404_NOT_FOUND)
    if manifest.approval_status != "approved":
        raise DomainError(
            "Only approved manifest versions can be executed",
            status.HTTP_409_CONFLICT,
        )
    source = session.get(Source, manifest.source_id)
    if source is None:
        raise DomainError("Manifest source not found", status.HTTP_404_NOT_FOUND)
    if source.status != "active":
        raise DomainError("Only active sources can be executed", status.HTTP_409_CONFLICT)

    if idempotency_key:
        existing_job = session.scalar(
            select(Job).where(
                Job.type == "approved_manifest_ingestion",
                Job.requested_by == actor.actor_id,
                Job.idempotency_key == idempotency_key,
            )
        )
        if existing_job:
            if existing_job.source_manifest_version_id != manifest.id:
                raise DomainError(
                    "Idempotency key was already used for a different manifest",
                    status.HTTP_409_CONFLICT,
                )
            existing_job._vdch_created = False
            append_job_event(
                session,
                existing_job,
                event_type="job.idempotent_reuse",
                phase=existing_job.progress_json.get("phase"),
                message="Existing job returned for idempotency key.",
                metadata={"idempotency_key": idempotency_key},
            )
            return existing_job

    job = Job(
        type="approved_manifest_ingestion",
        status="queued",
        requested_by=actor.actor_id,
        idempotency_key=idempotency_key,
        source_manifest_version_id=manifest.id,
        progress_json={"phase": "queued", "records_seen": 0},
        summary_json={},
    )
    session.add(job)
    session.flush()
    job._vdch_created = True
    append_job_event(
        session,
        job,
        event_type="job.queued",
        phase="queued",
        message="Approved manifest ingestion job queued.",
        metadata={"manifest_id": manifest.id, **(metadata or {})},
    )
    write_audit_event(
        session,
        actor=actor,
        operation="job.create.approved_manifest_ingestion",
        resource_type="job",
        resource_id=job.id,
        policy_decision=policy_decision,
        metadata=metadata or {"manifest_id": manifest.id},
    )
    return job


def append_job_event(
    session: Session,
    job: Job,
    *,
    event_type: str,
    phase: str | None = None,
    message: str | None = None,
    metadata: dict | None = None,
) -> JobEvent:
    session.flush()
    latest_sequence = session.scalar(
        select(func.max(JobEvent.sequence)).where(JobEvent.job_id == job.id)
    )
    event = JobEvent(
        job_id=job.id,
        sequence=(latest_sequence or 0) + 1,
        event_type=event_type,
        phase=phase,
        message=message,
        metadata_json=metadata or {},
    )
    session.add(event)
    return event


def list_job_events(session: Session, *, job_id: str) -> list[JobEvent]:
    return list(
        session.scalars(
            select(JobEvent).where(JobEvent.job_id == job_id).order_by(JobEvent.sequence.asc())
        ).all()
    )


def _redact_record(record: dict[str, Any], sensitive_fields: Iterable[str]) -> dict[str, Any]:
    redacted = dict(record)
    for field in sensitive_fields:
        if field in redacted:
            redacted[field] = "[REDACTED]"
    return redacted


def _sample_payload_snapshot(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("type") != "sample_json":
        return {}
    records = manifest.get("sample_records")
    if not isinstance(records, list):
        return {}
    return {"record_count": len(records), "payload_hash": stable_json_hash(records[:5])}


def _source_allowed_hosts(source: Source) -> set[str]:
    hosts = source.allowed_domains_json.get("hosts")
    if not isinstance(hosts, list):
        return set()
    return {str(host).strip().lower().rstrip(".") for host in hosts if str(host).strip()}


def _validate_source_domain_policy(source: Source, manifest: dict[str, Any]) -> None:
    if manifest.get("type") != "http_json":
        return
    hosts = _source_allowed_hosts(source)
    if not hosts:
        raise DomainError("Source allowed_domains_json.hosts is required for http_json approval")
    hostname = urlparse(str(manifest.get("base_url", ""))).hostname
    normalized = hostname.lower().rstrip(".") if hostname else ""
    if normalized not in hosts:
        raise DomainError("Manifest base_url host is outside source allowed domains")


def _write_quarantine_record(
    session: Session,
    *,
    job: Job,
    chunk: JobChunk | None,
    source: Source | None,
    record: Any,
    source_record_id: str | None,
    reason_code: str,
    reason_message: str,
    sensitive_fields: Iterable[str],
) -> QuarantineRecord:
    redacted = _redact_record(record, sensitive_fields) if isinstance(record, dict) else {}
    quarantine = QuarantineRecord(
        job_id=job.id,
        job_chunk_id=chunk.id if chunk else None,
        source_id=source.id if source else None,
        source_record_id=source_record_id,
        reason_code=reason_code,
        reason_message=reason_message,
        payload_hash=stable_json_hash(record),
        payload_json_redacted=redacted,
        status="open",
    )
    session.add(quarantine)
    session.flush()
    session.add(
        QuarantineEvent(
            quarantine_record_id=quarantine.id,
            event_type="quarantine.created",
            message=reason_message,
            metadata_json={"reason_code": reason_code},
        )
    )
    return quarantine


def list_job_chunks(session: Session, *, job_id: str) -> list[JobChunk]:
    return list(
        session.scalars(
            select(JobChunk).where(JobChunk.job_id == job_id).order_by(JobChunk.sequence.asc())
        ).all()
    )


def list_quarantine_records(
    session: Session,
    *,
    status_filter: str = "open",
    job_id: str | None = None,
) -> list[QuarantineRecord]:
    query = select(QuarantineRecord)
    if status_filter != "all":
        query = query.where(QuarantineRecord.status == status_filter)
    if job_id:
        query = query.where(QuarantineRecord.job_id == job_id)
    return list(
        session.scalars(query.order_by(QuarantineRecord.created_at.desc())).all()
    )


def build_ops_job_diagnostics(session: Session, *, job_id: str) -> dict[str, Any]:
    job = session.get(Job, job_id)
    if job is None:
        raise DomainError("Job not found", status.HTTP_404_NOT_FOUND)
    chunks = list_job_chunks(session, job_id=job.id)
    events = list_job_events(session, job_id=job.id)
    summary = job.summary_json or {}
    progress = job.progress_json or {}
    open_review_cases = session.scalar(
        select(func.count()).select_from(ReviewCase).where(ReviewCase.status == "open")
    )
    return {
        "job_id": job.id,
        "status": job.status,
        "type": job.type,
        "attempt_count": job.attempt_count,
        "phase": progress.get("phase"),
        "records_seen": int(summary.get("records_seen") or progress.get("records_seen") or 0),
        "raw_records_created": int(summary.get("raw_records_created") or 0),
        "person_records_created": int(summary.get("person_records_created") or 0),
        "quarantine_records_created": int(summary.get("quarantine_records_created") or 0),
        "duplicate_candidates_created": int(summary.get("duplicate_candidates_created") or 0),
        "duplicate_clusters_created": int(summary.get("duplicate_clusters_created") or 0),
        "open_review_cases": int(open_review_cases or 0),
        "chunk_count": len(chunks),
        "failed_chunk_count": sum(1 for chunk in chunks if chunk.status == "failed"),
        "latest_event_types": [event.event_type for event in events[-10:]],
        "error_code": job.error_code,
        "safe_for_agent": True,
    }


def build_daily_quality_summary(session: Session) -> dict[str, Any]:
    jobs = list(session.scalars(select(Job)).all())
    quarantine_records_open = session.scalar(
        select(func.count())
        .select_from(QuarantineRecord)
        .where(QuarantineRecord.status == "open")
    )
    open_review_cases = session.scalar(
        select(func.count()).select_from(ReviewCase).where(ReviewCase.status == "open")
    )
    duplicate_candidates = session.scalar(select(func.count()).select_from(DuplicateCandidate))
    duplicate_clusters_open = session.scalar(
        select(func.count())
        .select_from(DuplicateCluster)
        .where(DuplicateCluster.status == "open")
    )
    return {
        "jobs_total": len(jobs),
        "jobs_completed": sum(1 for job in jobs if job.status == "completed"),
        "jobs_failed": sum(1 for job in jobs if job.status == "failed"),
        "records_seen": sum(int((job.summary_json or {}).get("records_seen") or 0) for job in jobs),
        "raw_records_created": sum(
            int((job.summary_json or {}).get("raw_records_created") or 0) for job in jobs
        ),
        "person_records_created": sum(
            int((job.summary_json or {}).get("person_records_created") or 0) for job in jobs
        ),
        "quarantine_records_open": int(quarantine_records_open or 0),
        "open_review_cases": int(open_review_cases or 0),
        "duplicate_candidates": int(duplicate_candidates or 0),
        "duplicate_clusters_open": int(duplicate_clusters_open or 0),
        "safe_for_agent": True,
    }


def _promotion_summary(job: Job) -> dict[str, Any]:
    summary = job.summary_json or {}
    return {
        "job_id": job.id,
        "job_type": job.type,
        "records_seen": int(summary.get("records_seen") or 0),
        "raw_records_created": int(summary.get("raw_records_created") or 0),
        "person_records_created": int(summary.get("person_records_created") or 0),
        "quarantine_records_created": int(summary.get("quarantine_records_created") or 0),
        "duplicate_candidates_created": int(summary.get("duplicate_candidates_created") or 0),
        "duplicate_clusters_created": int(summary.get("duplicate_clusters_created") or 0),
        "open_review_cases": int(summary.get("open_review_cases") or 0),
    }


def create_promotion_request(
    session: Session,
    *,
    job_id: str,
    reason: str,
    actor: Actor,
    policy_decision: str,
) -> PromotionRequest:
    job = session.get(Job, job_id)
    if job is None:
        raise DomainError("Job not found", status.HTTP_404_NOT_FOUND)
    if job.status != "completed":
        raise DomainError("Only completed ingestion jobs can be promoted", status.HTTP_409_CONFLICT)
    existing_pending = session.scalar(
        select(PromotionRequest).where(
            PromotionRequest.job_id == job.id,
            PromotionRequest.status == "pending",
        )
    )
    if existing_pending is not None:
        raise DomainError(
            "A pending promotion request already exists for this job",
            status.HTTP_409_CONFLICT,
        )
    promotion = PromotionRequest(
        job_id=job.id,
        status="pending",
        requested_by=actor.actor_id,
        request_reason=reason,
        summary_json=_promotion_summary(job),
    )
    session.add(promotion)
    session.flush()
    write_audit_event(
        session,
        actor=actor,
        operation="promotion.request",
        resource_type="promotion_request",
        resource_id=promotion.id,
        policy_decision=policy_decision,
        metadata={"job_id": job.id, "status": promotion.status},
    )
    return promotion


def list_promotion_requests(
    session: Session,
    *,
    status_filter: str = "all",
) -> list[PromotionRequest]:
    query = select(PromotionRequest)
    if status_filter != "all":
        query = query.where(PromotionRequest.status == status_filter)
    return list(
        session.scalars(query.order_by(PromotionRequest.created_at.desc())).all()
    )


def decide_promotion_request(
    session: Session,
    *,
    promotion_id: str,
    decision: str,
    reason: str,
    actor: Actor,
    policy_decision: str,
) -> PromotionRequest:
    if decision not in {"approved", "rejected"}:
        raise DomainError("Invalid promotion decision", status.HTTP_422_UNPROCESSABLE_ENTITY)
    promotion = session.get(PromotionRequest, promotion_id)
    if promotion is None:
        raise DomainError("Promotion request not found", status.HTTP_404_NOT_FOUND)
    if promotion.status != "pending":
        raise DomainError(
            "Only pending promotion requests can be decided",
            status.HTTP_409_CONFLICT,
        )
    promotion.status = decision
    promotion.decided_by = actor.actor_id
    promotion.decided_at = utcnow()
    promotion.decision_reason = reason
    write_audit_event(
        session,
        actor=actor,
        operation="promotion.decide",
        resource_type="promotion_request",
        resource_id=promotion.id,
        policy_decision=policy_decision,
        metadata={"job_id": promotion.job_id, "decision": decision},
    )
    return promotion


def resolve_quarantine_record(
    session: Session,
    *,
    quarantine_record_id: str,
    new_status: str,
    reason: str,
    actor: Actor,
    policy_decision: str,
) -> QuarantineRecord:
    if new_status not in {"resolved", "dismissed"}:
        raise DomainError("Invalid quarantine status", status.HTTP_422_UNPROCESSABLE_ENTITY)
    quarantine = session.get(QuarantineRecord, quarantine_record_id)
    if quarantine is None:
        raise DomainError("Quarantine record not found", status.HTTP_404_NOT_FOUND)
    if quarantine.status != "open":
        raise DomainError("Only open quarantine records can be resolved", status.HTTP_409_CONFLICT)
    quarantine.status = new_status
    quarantine.resolved_at = utcnow()
    session.add(
        QuarantineEvent(
            quarantine_record_id=quarantine.id,
            event_type=f"quarantine.{new_status}",
            actor_id=actor.actor_id,
            message=reason,
            metadata_json={"status": new_status},
        )
    )
    write_audit_event(
        session,
        actor=actor,
        operation="quarantine.resolve",
        resource_type="quarantine_record",
        resource_id=quarantine.id,
        policy_decision=policy_decision,
        metadata={"status": new_status, "reason": reason},
    )
    return quarantine


def assign_review_case(
    session: Session,
    *,
    review_case_id: str,
    assigned_to: str,
    reason: str,
    actor: Actor,
    policy_decision: str,
) -> ReviewCase:
    review_case = session.get(ReviewCase, review_case_id)
    if review_case is None:
        raise DomainError("Review case not found", status.HTTP_404_NOT_FOUND)
    if review_case.status != "open":
        raise DomainError("Only open review cases can be assigned", status.HTTP_409_CONFLICT)
    review_case.assigned_to = assigned_to
    review_case.assigned_at = utcnow()
    write_audit_event(
        session,
        actor=actor,
        operation="review_case.assign",
        resource_type="review_case",
        resource_id=review_case.id,
        policy_decision=policy_decision,
        metadata={"assigned_to": assigned_to, "reason": reason},
    )
    return review_case


def run_manifest_ingestion(session: Session, *, job_id: str) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise DomainError("Job not found", status.HTTP_404_NOT_FOUND)
    if job.status == "completed":
        append_job_event(
            session,
            job,
            event_type="job.execution_skipped",
            phase=job.progress_json.get("phase"),
            message="Completed job execution was skipped.",
        )
        return job
    if job.status != "queued":
        raise DomainError(
            f"Job execution requires queued status; current status is {job.status}",
            status.HTTP_409_CONFLICT,
        )
    manifest_version = session.get(SourceManifestVersion, job.source_manifest_version_id)
    if manifest_version is None:
        raise DomainError("Job manifest version not found", status.HTTP_404_NOT_FOUND)

    source = session.get(Source, manifest_version.source_id)
    if source is None:
        raise DomainError("Job source not found", status.HTTP_404_NOT_FOUND)
    manifest = manifest_version.manifest_json
    mappings = manifest_version.field_mappings_json or manifest["field_mappings"]
    sensitive_fields = manifest_version.sensitive_fields_json.get("fields", [])
    parser = get_parser(manifest_version.parser_name, manifest_version.parser_version)
    adapter = get_adapter(
        manifest_version.adapter_name,
        approved_hosts=get_settings().approved_manifest_hosts,
    )

    job.status = "running"
    job.attempt_count += 1
    job.started_at = utcnow()
    job.progress_json = {
        "phase": "ingestion",
        "records_seen": 0,
        "attempt": job.attempt_count,
    }
    append_job_event(
        session,
        job,
        event_type="job.started",
        phase="ingestion",
        message="Ingestion workflow started.",
        metadata={"attempt": job.attempt_count},
    )
    session.flush()

    try:
        chunks = list(adapter.fetch_chunks(manifest))
        raw_created = 0
        person_created = 0
        quarantine_created = 0
        records_seen = 0
        for chunk_payload in chunks:
            chunk = JobChunk(
                job_id=job.id,
                sequence=chunk_payload.sequence,
                status="running",
                source_uri=chunk_payload.source_uri,
                checkpoint_json=chunk_payload.checkpoint_json or {},
                records_seen=0,
                raw_records_created=0,
                person_records_created=0,
                quarantine_records_created=0,
                started_at=utcnow(),
            )
            session.add(chunk)
            session.flush()
            append_job_event(
                session,
                job,
                event_type="job.chunk_started",
                phase="ingestion",
                message="Ingestion chunk started.",
                metadata={"chunk_id": chunk.id, "sequence": chunk.sequence},
            )
            for record in chunk_payload.records:
                records_seen += 1
                chunk.records_seen += 1
                if not isinstance(record, dict):
                    _write_quarantine_record(
                        session,
                        job=job,
                        chunk=chunk,
                        source=source,
                        record=record,
                        source_record_id=None,
                        reason_code="invalid_record_type",
                        reason_message="Record is not a JSON object.",
                        sensitive_fields=sensitive_fields,
                    )
                    quarantine_created += 1
                    chunk.quarantine_records_created += 1
                    continue
                try:
                    parsed = parser.parse(record, mappings)
                except ParserError as exc:
                    _write_quarantine_record(
                        session,
                        job=job,
                        chunk=chunk,
                        source=source,
                        record=record,
                        source_record_id=None,
                        reason_code="parser_error",
                        reason_message=str(exc),
                        sensitive_fields=sensitive_fields,
                    )
                    quarantine_created += 1
                    chunk.quarantine_records_created += 1
                    continue
                source_record_id = parsed.source_record_id

                raw = session.scalar(
                    select(RawRecord).where(
                        RawRecord.source_id == source.id,
                        RawRecord.source_record_id == source_record_id,
                    )
                )
                if raw is None:
                    raw = RawRecord(
                        source_id=source.id,
                        source_record_id=source_record_id,
                        ingestion_job_id=job.id,
                        job_chunk_id=chunk.id,
                        source_url=manifest.get("base_url"),
                        payload_hash=stable_json_hash(record),
                        payload_json_redacted=_redact_record(record, sensitive_fields),
                    )
                    session.add(raw)
                    session.flush()
                    raw_created += 1
                    chunk.raw_records_created += 1

                existing_person = session.scalar(
                    select(PersonRecord).where(PersonRecord.raw_record_id == raw.id)
                )
                if existing_person is None:
                    session.add(
                        PersonRecord(
                            raw_record_id=raw.id,
                            source_id=source.id,
                            source_record_id=source_record_id,
                            **parsed.person_fields,
                        )
                    )
                    person_created += 1
                    chunk.person_records_created += 1

                if chunk.records_seen % 100 == 0:
                    job.progress_json = {
                        "phase": "ingestion",
                        "records_seen": records_seen,
                        "attempt": job.attempt_count,
                    }
                    append_job_event(
                        session,
                        job,
                        event_type="job.checkpoint",
                        phase="ingestion",
                        message="Ingestion checkpoint recorded.",
                        metadata={"records_seen": records_seen, "chunk_id": chunk.id},
                    )
                    session.flush()
            chunk.status = "completed"
            chunk.completed_at = utcnow()
            append_job_event(
                session,
                job,
                event_type="job.chunk_completed",
                phase="ingestion",
                message="Ingestion chunk completed.",
                metadata={
                    "chunk_id": chunk.id,
                    "sequence": chunk.sequence,
                    "records_seen": chunk.records_seen,
                    "quarantine_records_created": chunk.quarantine_records_created,
                },
            )
            session.flush()

        job.progress_json = {
            "phase": "matching",
            "records_seen": records_seen,
            "attempt": job.attempt_count,
        }
        append_job_event(
            session,
            job,
            event_type="job.phase_started",
            phase="matching",
            message="Duplicate candidate matching started.",
            metadata={"records_seen": records_seen},
        )
        session.flush()
        candidates_created = create_duplicate_candidates(session)
        job.progress_json = {
            "phase": "clustering",
            "records_seen": records_seen,
            "attempt": job.attempt_count,
        }
        append_job_event(
            session,
            job,
            event_type="job.phase_started",
            phase="clustering",
            message="Duplicate cluster rebuilding started.",
            metadata={"duplicate_candidates_created": candidates_created},
        )
        session.flush()
        clusters_created = rebuild_duplicate_clusters(session)
        review_cases_open = session.scalar(
            select(func.count()).select_from(ReviewCase).where(ReviewCase.status == "open")
        )
        job.status = "completed"
        job.completed_at = utcnow()
        job.progress_json = {
            "phase": "completed",
            "records_seen": records_seen,
            "attempt": job.attempt_count,
        }
        job.summary_json = {
            "records_seen": records_seen,
            "raw_records_created": raw_created,
            "person_records_created": person_created,
            "quarantine_records_created": quarantine_created,
            "duplicate_candidates_created": candidates_created,
            "duplicate_clusters_created": clusters_created,
            "open_review_cases": review_cases_open or 0,
            "attempt": job.attempt_count,
        }
        if source is not None:
            source.last_successful_job_id = job.id
            source.updated_at = utcnow()
        append_job_event(
            session,
            job,
            event_type="job.completed",
            phase="completed",
            message="Ingestion workflow completed.",
            metadata=job.summary_json,
        )
        session.flush()
        return job
    except Exception as exc:
        job.status = "failed"
        job.completed_at = utcnow()
        job.error_code = exc.__class__.__name__
        job.error_message = SAFE_JOB_FAILURE_MESSAGE
        job.progress_json = {**(job.progress_json or {}), "phase": "failed"}
        append_job_event(
            session,
            job,
            event_type="job.failed",
            phase="failed",
            message=SAFE_JOB_FAILURE_MESSAGE,
            metadata={"error_code": job.error_code},
        )
        if source is not None:
            source.last_failed_job_id = job.id
            source.updated_at = utcnow()
        session.flush()
        raise


def decide_review_case(
    session: Session,
    *,
    review_case_id: str,
    decision: str,
    reason: str,
    actor: Actor,
    policy_decision: str,
) -> ReviewDecision:
    review_case = session.get(ReviewCase, review_case_id)
    if review_case is None:
        raise DomainError("Review case not found", status.HTTP_404_NOT_FOUND)
    if review_case.status != "open":
        raise DomainError("Review case is already closed", status.HTTP_409_CONFLICT)
    candidate = session.get(DuplicateCandidate, review_case.duplicate_candidate_id)
    evidence = {
        "duplicate_candidate_id": candidate.id if candidate else None,
        "evidence": candidate.evidence_json if candidate else {},
        "confidence": candidate.confidence if candidate else None,
        "conflicts": candidate.conflict_flags_json if candidate else {},
    }
    review_case.status = "closed"
    review_case.closed_at = utcnow().astimezone(UTC)
    review_decision = ReviewDecision(
        review_case_id=review_case.id,
        decision=decision,
        reason=reason,
        decided_by=actor.actor_id,
        evidence_snapshot_json=evidence,
    )
    session.add(review_decision)
    write_audit_event(
        session,
        actor=actor,
        operation="review_case.decide",
        resource_type="review_case",
        resource_id=review_case.id,
        policy_decision=policy_decision,
        metadata={"decision": decision},
    )
    return review_decision
