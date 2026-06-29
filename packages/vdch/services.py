from collections.abc import Iterable
from datetime import UTC
from typing import Any

import httpx
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vdch.audit import write_audit_event
from vdch.config import Settings, get_settings
from vdch.manifest import ManifestValidationError, get_by_path, mapped_value, validate_manifest
from vdch.matching import create_duplicate_candidates
from vdch.models import (
    DuplicateCandidate,
    Job,
    PersonRecord,
    RawRecord,
    ReviewCase,
    ReviewDecision,
    Source,
    SourceManifestVersion,
    utcnow,
)
from vdch.normalization import build_person_fields, stable_json_hash
from vdch.schemas import SourceManifestCreate
from vdch.security import Actor


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
    try:
        validate_manifest(
            payload.manifest_json,
            allow_sample=resolved_settings.allow_sample_manifests,
        )
    except ManifestValidationError as exc:
        raise DomainError(str(exc)) from exc

    source = session.scalar(select(Source).where(Source.slug == payload.source_slug))
    if source is None:
        source = Source(
            slug=payload.source_slug,
            display_name=payload.source_display_name,
            owner=payload.owner,
        )
        session.add(source)
        session.flush()

    latest_version = session.scalar(
        select(func.max(SourceManifestVersion.version)).where(
            SourceManifestVersion.source_id == source.id
        )
    )
    manifest = SourceManifestVersion(
        source_id=source.id,
        version=(latest_version or 0) + 1,
        manifest_json=payload.manifest_json,
        approval_status="draft",
        rate_limit_policy_json=payload.rate_limit_policy_json,
        sensitive_fields_json=payload.sensitive_fields_json,
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
    manifest.approval_status = "approved"
    manifest.approved_by = actor.actor_id
    manifest.approved_at = utcnow()
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


def create_ingestion_job(
    session: Session,
    *,
    manifest_id: str,
    actor: Actor,
    policy_decision: str,
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

    job = Job(
        type="approved_manifest_ingestion",
        status="queued",
        requested_by=actor.actor_id,
        source_manifest_version_id=manifest.id,
        progress_json={"phase": "queued", "records_seen": 0},
        summary_json={},
    )
    session.add(job)
    session.flush()
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


def _redact_record(record: dict[str, Any], sensitive_fields: Iterable[str]) -> dict[str, Any]:
    redacted = dict(record)
    for field in sensitive_fields:
        if field in redacted:
            redacted[field] = "[REDACTED]"
    return redacted


def _records_from_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    if manifest["type"] == "sample_json":
        return list(manifest["sample_records"])

    response = httpx.get(
        manifest["base_url"],
        params=manifest.get("query_params") or {},
        headers=manifest.get("headers") or {},
        timeout=manifest.get("timeout_seconds", 30),
        follow_redirects=False,
    )
    response.raise_for_status()
    payload = response.json()
    records = get_by_path(payload, manifest.get("records_path"))
    if not isinstance(records, list):
        raise DomainError("Manifest records_path did not resolve to a list")
    return records


def run_manifest_ingestion(session: Session, *, job_id: str) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise DomainError("Job not found", status.HTTP_404_NOT_FOUND)
    manifest_version = session.get(SourceManifestVersion, job.source_manifest_version_id)
    if manifest_version is None:
        raise DomainError("Job manifest version not found", status.HTTP_404_NOT_FOUND)

    source = session.get(Source, manifest_version.source_id)
    manifest = manifest_version.manifest_json
    mappings = manifest["field_mappings"]
    sensitive_fields = manifest_version.sensitive_fields_json.get("fields", [])

    job.status = "running"
    job.started_at = utcnow()
    job.progress_json = {"phase": "ingestion", "records_seen": 0}
    session.flush()

    try:
        records = _records_from_manifest(manifest)
        raw_created = 0
        person_created = 0
        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                continue
            source_record_id = mapped_value(record, mappings, "source_record_id")
            if source_record_id in (None, ""):
                continue
            source_record_id = str(source_record_id)
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
                    source_url=manifest.get("base_url"),
                    payload_hash=stable_json_hash(record),
                    payload_json_redacted=_redact_record(record, sensitive_fields),
                )
                session.add(raw)
                session.flush()
                raw_created += 1

            existing_person = session.scalar(
                select(PersonRecord).where(PersonRecord.raw_record_id == raw.id)
            )
            if existing_person is None:
                fields = build_person_fields(record, mappings)
                session.add(
                    PersonRecord(
                        raw_record_id=raw.id,
                        source_id=source.id,
                        source_record_id=source_record_id,
                        **fields,
                    )
                )
                person_created += 1

            if index % 100 == 0:
                job.progress_json = {"phase": "ingestion", "records_seen": index}
                session.flush()

        job.progress_json = {"phase": "matching", "records_seen": len(records)}
        session.flush()
        candidates_created = create_duplicate_candidates(session)
        review_cases_open = session.scalar(
            select(func.count()).select_from(ReviewCase).where(ReviewCase.status == "open")
        )
        job.status = "completed"
        job.completed_at = utcnow()
        job.progress_json = {"phase": "completed", "records_seen": len(records)}
        job.summary_json = {
            "records_seen": len(records),
            "raw_records_created": raw_created,
            "person_records_created": person_created,
            "duplicate_candidates_created": candidates_created,
            "open_review_cases": review_cases_open or 0,
        }
        session.flush()
        return job
    except Exception as exc:
        job.status = "failed"
        job.completed_at = utcnow()
        job.error_code = exc.__class__.__name__
        job.error_message = str(exc)
        job.progress_json = {**(job.progress_json or {}), "phase": "failed"}
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
