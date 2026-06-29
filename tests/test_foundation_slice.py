import pytest
from sqlalchemy import select
from vdch.config import Settings
from vdch.models import (
    AuditEvent,
    DuplicateCandidate,
    DuplicateCluster,
    DuplicateClusterMember,
    Job,
    JobChunk,
    JobEvent,
    PersonRecord,
    QuarantineRecord,
    RawRecord,
    ReviewCase,
    ReviewDecision,
    Source,
)
from vdch.normalization import fingerprint_digits, normalize_identifier
from vdch.schemas import SourceManifestCreate
from vdch.security import Actor
from vdch.services import (
    DomainError,
    approve_manifest,
    create_ingestion_job,
    create_promotion_request,
    create_source_manifest,
    decide_review_case,
    run_manifest_ingestion,
)


def sample_manifest_payload() -> SourceManifestCreate:
    return SourceManifestCreate(
        source_slug="sample-registry",
        source_display_name="Sample Registry",
        owner="data-team",
        permission_basis="synthetic test fixture",
        sensitive_fields_json={"fields": ["phone"]},
        manifest_json={
            "type": "sample_json",
            "sample_records": [
                {
                    "id": "a-1",
                    "name": "Jose Perez",
                    "cedula": "V-12345678",
                    "phone": "0412 555 0000",
                    "status": "active",
                    "age": 40,
                    "location": "Caracas",
                },
                {
                    "id": "b-2",
                    "name": "José Pérez",
                    "cedula": "V-12345678",
                    "phone": "04125550000",
                    "status": "active",
                    "age": 40,
                    "location": "Caracas",
                },
                {
                    "id": "c-3",
                    "name": "Maria Gomez",
                    "cedula": "87654321",
                    "phone": "04125559999",
                    "status": "active",
                    "age": 33,
                    "location": "Valencia",
                },
            ],
            "field_mappings": {
                "source_record_id": "id",
                "display_name": "name",
                "cedula": "cedula",
                "phone": "phone",
                "status": "status",
                "age": "age",
                "location_general": "location",
            },
        },
    )


def test_approved_manifest_ingestion_to_review_queue(session):
    actor = Actor(
        actor_id="steward-1",
        actor_type="user",
        scopes=frozenset({"operator", "data_steward", "reviewer"}),
    )
    settings = Settings(database_url="sqlite:///:memory:", allow_sample_manifests=True)

    manifest = create_source_manifest(
        session,
        payload=sample_manifest_payload(),
        actor=actor,
        policy_decision="allow:test",
        settings=settings,
    )
    approve_manifest(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
        reason="test approval",
    )
    job = create_ingestion_job(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
    )
    run_manifest_ingestion(session, job_id=job.id)
    session.commit()

    raw_records = session.scalars(select(RawRecord)).all()
    candidates = session.scalars(select(DuplicateCandidate)).all()
    clusters = session.scalars(select(DuplicateCluster)).all()
    cluster_members = session.scalars(select(DuplicateClusterMember)).all()
    review_cases = session.scalars(select(ReviewCase)).all()
    audit_events = session.scalars(select(AuditEvent)).all()

    assert job.status == "completed"
    assert job.summary_json["records_seen"] == 3
    assert job.summary_json["raw_records_created"] == 3
    assert len(raw_records) == 3
    assert raw_records[0].payload_json_redacted["phone"] == "[REDACTED]"
    assert session.scalar(select(PersonRecord)).identity_token_version == "hmac-sha256-v1"
    assert len(candidates) == 1
    assert candidates[0].confidence == 0.995
    assert candidates[0].evidence_json["signals"] == ["cedula", "phone", "name_last"]
    assert len(clusters) == 1
    assert len(cluster_members) == 2
    assert len(review_cases) == 1
    assert review_cases[0].queue == "alta_confianza"
    assert review_cases[0].cluster_id == clusters[0].id
    assert job.summary_json["duplicate_clusters_created"] == 1
    assert job.summary_json["quarantine_records_created"] == 0
    assert {event.operation for event in audit_events} == {
        "source_manifest.create",
        "source_manifest.approve",
        "job.create.approved_manifest_ingestion",
    }


def test_rerun_is_idempotent_for_raw_and_person_records(session):
    actor = Actor(
        actor_id="operator-1",
        actor_type="user",
        scopes=frozenset({"operator", "data_steward"}),
    )
    settings = Settings(database_url="sqlite:///:memory:", allow_sample_manifests=True)
    manifest = create_source_manifest(
        session,
        payload=sample_manifest_payload(),
        actor=actor,
        policy_decision="allow:test",
        settings=settings,
    )
    approve_manifest(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
        reason="test approval",
    )
    first_job = create_ingestion_job(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
    )
    second_job = create_ingestion_job(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
    )

    run_manifest_ingestion(session, job_id=first_job.id)
    run_manifest_ingestion(session, job_id=second_job.id)
    session.commit()

    assert len(session.scalars(select(RawRecord)).all()) == 3
    assert second_job.summary_json["raw_records_created"] == 0


def test_duplicate_clusters_are_stable_across_rebuilds(session):
    actor = Actor(
        actor_id="operator-1",
        actor_type="user",
        scopes=frozenset({"operator", "data_steward"}),
    )
    settings = Settings(database_url="sqlite:///:memory:", allow_sample_manifests=True)
    manifest = create_source_manifest(
        session,
        payload=sample_manifest_payload(),
        actor=actor,
        policy_decision="allow:test",
        settings=settings,
    )
    approve_manifest(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
        reason="test approval",
    )
    first_job = create_ingestion_job(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
    )
    second_job = create_ingestion_job(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
    )

    run_manifest_ingestion(session, job_id=first_job.id)
    first_cluster_id = session.scalar(select(DuplicateCluster)).id
    run_manifest_ingestion(session, job_id=second_job.id)
    session.commit()

    clusters = session.scalars(select(DuplicateCluster)).all()
    assert len(clusters) == 1
    assert clusters[0].id == first_cluster_id
    assert clusters[0].status == "open"


def test_ingestion_job_creation_is_idempotent_with_key(session):
    actor = Actor(
        actor_id="operator-1",
        actor_type="user",
        scopes=frozenset({"operator", "data_steward"}),
    )
    settings = Settings(database_url="sqlite:///:memory:", allow_sample_manifests=True)
    manifest = create_source_manifest(
        session,
        payload=sample_manifest_payload(),
        actor=actor,
        policy_decision="allow:test",
        settings=settings,
    )
    approve_manifest(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
        reason="test approval",
    )

    first_job = create_ingestion_job(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
        idempotency_key="source-sample-2026-06-29",
    )
    second_job = create_ingestion_job(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
        idempotency_key="source-sample-2026-06-29",
    )
    session.commit()

    jobs = session.scalars(select(Job)).all()
    events = session.scalars(
        select(JobEvent).where(JobEvent.job_id == first_job.id).order_by(JobEvent.sequence)
    ).all()

    assert first_job.id == second_job.id
    assert len(jobs) == 1
    assert [event.event_type for event in events] == ["job.queued", "job.idempotent_reuse"]


def test_ingestion_job_events_record_lifecycle(session):
    actor = Actor(
        actor_id="operator-1",
        actor_type="user",
        scopes=frozenset({"operator", "data_steward"}),
    )
    settings = Settings(database_url="sqlite:///:memory:", allow_sample_manifests=True)
    manifest = create_source_manifest(
        session,
        payload=sample_manifest_payload(),
        actor=actor,
        policy_decision="allow:test",
        settings=settings,
    )
    approve_manifest(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
        reason="test approval",
    )
    job = create_ingestion_job(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
    )
    run_manifest_ingestion(session, job_id=job.id)
    session.commit()

    events = session.scalars(
        select(JobEvent).where(JobEvent.job_id == job.id).order_by(JobEvent.sequence)
    ).all()

    assert job.attempt_count == 1
    assert job.summary_json["attempt"] == 1
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert "job.queued" in {event.event_type for event in events}
    assert "job.started" in {event.event_type for event in events}
    assert "job.completed" in {event.event_type for event in events}
    assert events[-1].phase == "completed"


def test_promotion_request_requires_completed_job(session):
    actor = Actor(
        actor_id="operator-1",
        actor_type="user",
        scopes=frozenset({"operator", "data_steward"}),
    )
    settings = Settings(database_url="sqlite:///:memory:", allow_sample_manifests=True)
    manifest = create_source_manifest(
        session,
        payload=sample_manifest_payload(),
        actor=actor,
        policy_decision="allow:test",
        settings=settings,
    )
    approve_manifest(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
        reason="test approval",
    )
    queued_job = create_ingestion_job(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
    )

    with pytest.raises(DomainError, match="Only completed ingestion jobs can be promoted"):
        create_promotion_request(
            session,
            job_id=queued_job.id,
            reason="Synthetic early promotion",
            actor=actor,
            policy_decision="allow:test",
        )

    run_manifest_ingestion(session, job_id=queued_job.id)
    promotion = create_promotion_request(
        session,
        job_id=queued_job.id,
        reason="Synthetic completed promotion",
        actor=actor,
        policy_decision="allow:test",
    )

    assert promotion.status == "pending"
    assert promotion.summary_json["records_seen"] == 3
    assert "cedula_fingerprint" not in str(promotion.summary_json)


def test_failed_job_cannot_bypass_retry_control(session):
    actor = Actor(
        actor_id="operator-1",
        actor_type="user",
        scopes=frozenset({"operator", "data_steward"}),
    )
    settings = Settings(database_url="sqlite:///:memory:", allow_sample_manifests=True)
    manifest = create_source_manifest(
        session,
        payload=sample_manifest_payload(),
        actor=actor,
        policy_decision="allow:test",
        settings=settings,
    )
    approve_manifest(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
        reason="test approval",
    )
    job = create_ingestion_job(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
    )
    job.status = "failed"
    session.flush()

    try:
        run_manifest_ingestion(session, job_id=job.id)
    except Exception as exc:
        assert "requires queued status" in str(exc)
    else:
        raise AssertionError("failed job execution should have been rejected")


def test_fingerprints_require_secret_by_default(monkeypatch):
    from vdch.config import get_settings

    monkeypatch.delenv("VDCH_FINGERPRINT_SECRET", raising=False)
    monkeypatch.setenv("VDCH_ALLOW_INSECURE_FINGERPRINTS_FOR_LOCAL_DEV", "false")
    get_settings.cache_clear()

    try:
        fingerprint_digits("12345678")
    except RuntimeError as exc:
        assert "VDCH_FINGERPRINT_SECRET" in str(exc)
    else:
        raise AssertionError("fingerprint generation should require a secret")
    finally:
        get_settings.cache_clear()


def test_identity_tokens_preserve_cedula_prefixes():
    assert normalize_identifier("V-12.345.678") == "v12345678"
    assert normalize_identifier("E-12.345.678") == "e12345678"
    assert fingerprint_digits("V-12.345.678") != fingerprint_digits("E-12.345.678")


def test_manifest_approval_requires_permission_basis(session):
    actor = Actor(
        actor_id="steward-1",
        actor_type="user",
        scopes=frozenset({"operator", "data_steward"}),
    )
    payload = sample_manifest_payload().model_copy(update={"permission_basis": None})
    manifest = create_source_manifest(
        session,
        payload=payload,
        actor=actor,
        policy_decision="allow:test",
    )

    try:
        approve_manifest(
            session,
            manifest_id=manifest.id,
            actor=actor,
            policy_decision="allow:test",
            reason="test approval",
        )
    except Exception as exc:
        assert "permission basis" in str(exc)
    else:
        raise AssertionError("manifest approval should require permission basis")


def test_http_manifest_approval_requires_source_allowed_domain(session, monkeypatch):
    from vdch.config import get_settings

    monkeypatch.setenv("VDCH_MANIFEST_HOST_ALLOWLIST", "api.example.org")
    get_settings.cache_clear()
    actor = Actor(
        actor_id="steward-1",
        actor_type="user",
        scopes=frozenset({"operator", "data_steward"}),
    )
    payload = SourceManifestCreate(
        source_slug="http-source",
        source_display_name="HTTP Source",
        owner="data-team",
        permission_basis="synthetic source contract",
        allowed_domains_json={"hosts": ["other.example.org"]},
        manifest_json={
            "type": "http_json",
            "base_url": "https://api.example.org/records",
            "allowed_hosts": ["api.example.org"],
            "records_path": "items",
            "field_mappings": {"source_record_id": "id"},
        },
    )
    settings = Settings(
        database_url="sqlite:///:memory:",
        manifest_host_allowlist="api.example.org",
    )
    manifest = create_source_manifest(
        session,
        payload=payload,
        actor=actor,
        policy_decision="allow:test",
        settings=settings,
    )

    try:
        approve_manifest(
            session,
            manifest_id=manifest.id,
            actor=actor,
            policy_decision="allow:test",
            reason="test approval",
        )
    except Exception as exc:
        assert "outside source allowed domains" in str(exc)
    else:
        raise AssertionError("manifest approval should enforce source domains")
    finally:
        get_settings.cache_clear()


def test_unparseable_records_go_to_quarantine_and_chunks(session):
    actor = Actor(
        actor_id="operator-1",
        actor_type="user",
        scopes=frozenset({"operator", "data_steward"}),
    )
    manifest_payload = sample_manifest_payload()
    manifest_payload.manifest_json["sample_records"].append(
        {"name": "Missing synthetic id", "phone": "0412 000 0000"}
    )
    settings = Settings(database_url="sqlite:///:memory:", allow_sample_manifests=True)
    manifest = create_source_manifest(
        session,
        payload=manifest_payload,
        actor=actor,
        policy_decision="allow:test",
        settings=settings,
    )
    approve_manifest(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
        reason="test approval",
    )
    job = create_ingestion_job(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
    )
    run_manifest_ingestion(session, job_id=job.id)
    session.commit()

    chunks = session.scalars(select(JobChunk)).all()
    quarantine_records = session.scalars(select(QuarantineRecord)).all()
    source = session.scalar(select(Source))

    assert len(chunks) == 1
    assert chunks[0].records_seen == 4
    assert chunks[0].quarantine_records_created == 1
    assert len(quarantine_records) == 1
    assert quarantine_records[0].reason_code == "parser_error"
    assert quarantine_records[0].payload_json_redacted["phone"] == "[REDACTED]"
    assert job.summary_json["quarantine_records_created"] == 1
    assert source.last_successful_job_id == job.id


def test_review_decision_closes_case_and_snapshots_evidence(session):
    actor = Actor(
        actor_id="reviewer-1",
        actor_type="user",
        scopes=frozenset({"operator", "data_steward", "reviewer"}),
    )
    settings = Settings(database_url="sqlite:///:memory:", allow_sample_manifests=True)
    manifest = create_source_manifest(
        session,
        payload=sample_manifest_payload(),
        actor=actor,
        policy_decision="allow:test",
        settings=settings,
    )
    approve_manifest(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
        reason="test approval",
    )
    job = create_ingestion_job(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
    )
    run_manifest_ingestion(session, job_id=job.id)
    review_case = session.scalar(select(ReviewCase))

    decision = decide_review_case(
        session,
        review_case_id=review_case.id,
        decision="confirm_duplicate",
        reason="Same cedula and normalized name",
        actor=actor,
        policy_decision="allow:test",
    )
    session.commit()

    assert review_case.status == "closed"
    assert session.get(ReviewDecision, decision.id).evidence_snapshot_json["confidence"] == 0.995
