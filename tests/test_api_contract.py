import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from vdch.config import get_settings
from vdch.db import get_session
from vdch.models import (
    AuditEvent,
    DuplicateCandidate,
    DuplicateCluster,
    JobEvent,
    PromotionRequest,
    QuarantineRecord,
    SourceManifestVersion,
)
from vdch.security import Actor
from vdch.services import (
    approve_manifest,
    create_ingestion_job,
    create_source_manifest,
    run_manifest_ingestion,
)

from apps.api.main import app
from tests.test_foundation_slice import sample_manifest_payload


def test_create_manifest_endpoint(session):
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        response = client.post(
            "/v1/source-manifests",
            headers={"X-Scopes": "operator"},
            json={
                "source_slug": "api-test",
                "source_display_name": "API Test",
                "owner": "data-team",
                "manifest_json": {
                    "type": "sample_json",
                    "sample_records": [],
                    "field_mappings": {"source_record_id": "id"},
                },
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    assert body["source_slug"] == "api-test"
    assert body["parser_name"] == "person_json_v1"
    assert body["adapter_name"] == "sample_inline"
    assert body["approval_status"] == "draft"
    assert session.get(SourceManifestVersion, body["id"]) is not None


def test_source_registry_status_endpoint_is_audited(session):
    manifest = create_source_manifest(
        session,
        payload=sample_manifest_payload(),
        actor=Actor("operator-1", "user", frozenset({"operator"})),
        policy_decision="allow:test",
    )
    session.commit()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        list_response = client.get(
            "/v1/sources",
            headers={"X-Scopes": "operator"},
        )
        get_response = client.get(
            f"/v1/sources/{manifest.source_id}",
            headers={"X-Scopes": "operator"},
        )
        update_response = client.patch(
            f"/v1/sources/{manifest.source_id}/status",
            headers={"X-Scopes": "data_steward"},
            json={"status": "disabled", "reason": "Synthetic source pause"},
        )
    finally:
        app.dependency_overrides.clear()

    assert list_response.status_code == 200
    assert list_response.json()[0]["slug"] == "sample-registry"
    assert get_response.status_code == 200
    assert get_response.json()["id"] == manifest.source_id
    assert update_response.status_code == 200
    assert update_response.json()["status"] == "disabled"
    assert session.scalar(select(AuditEvent).where(AuditEvent.operation == "source.update_status"))


def test_auth_is_fail_closed_by_default(session, monkeypatch):
    monkeypatch.setenv("VDCH_DEV_AUTH_ENABLED", "false")
    monkeypatch.setenv("VDCH_ALLOW_POLICY_BYPASS_FOR_LOCAL_DEV", "false")
    monkeypatch.setenv("VDCH_OPA_ENABLED", "false")
    get_settings.cache_clear()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        response = client.get("/v1/source-manifests")
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()

    assert response.status_code == 401


def test_policy_is_fail_closed_without_explicit_local_bypass(session, monkeypatch):
    monkeypatch.setenv("VDCH_DEV_AUTH_ENABLED", "true")
    monkeypatch.setenv("VDCH_ALLOW_POLICY_BYPASS_FOR_LOCAL_DEV", "false")
    monkeypatch.setenv("VDCH_OPA_ENABLED", "false")
    get_settings.cache_clear()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        response = client.post(
            "/v1/source-manifests",
            headers={"X-Scopes": "operator"},
            json={
                "source_slug": "api-test",
                "source_display_name": "API Test",
                "owner": "data-team",
                "manifest_json": {
                    "type": "sample_json",
                    "sample_records": [],
                    "field_mappings": {"source_record_id": "id"},
                },
            },
        )
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()

    assert response.status_code == 503


def test_manifest_response_redacts_headers(session):
    manifest = create_source_manifest(
        session,
        payload=sample_manifest_payload().model_copy(
            update={
                "manifest_json": {
                    "type": "sample_json",
                    "sample_records": [],
                    "headers": {"Authorization": "Bearer SECRET"},
                    "field_mappings": {"source_record_id": "id"},
                }
            }
        ),
        actor=Actor("operator-1", "user", frozenset({"operator"})),
        policy_decision="allow:test",
    )
    session.commit()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        response = client.get(
            f"/v1/source-manifests/{manifest.id}",
            headers={"X-Scopes": "operator"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["manifest_json"]["headers"]["Authorization"] == "[REDACTED]"


def test_job_failure_api_masks_error_messages_and_freeform_metadata(session, monkeypatch):
    actor = Actor(
        actor_id="operator-1",
        actor_type="user",
        scopes=frozenset({"operator", "data_steward"}),
    )
    manifest = create_source_manifest(
        session,
        payload=sample_manifest_payload(),
        actor=actor,
        policy_decision="allow:test",
    )
    approve_manifest(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
        reason="Synthetic approval",
    )
    job = create_ingestion_job(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
    )

    def fail_matching(_session):
        raise RuntimeError("synthetic raw identifier V-12345678 should not leak")

    monkeypatch.setattr("vdch.services.create_duplicate_candidates", fail_matching)
    with pytest.raises(RuntimeError):
        run_manifest_ingestion(session, job_id=job.id)

    failed_event = session.scalar(
        select(JobEvent).where(JobEvent.job_id == job.id, JobEvent.event_type == "job.failed")
    )
    failed_event.metadata_json = {"reason": "synthetic raw identifier V-12345678"}
    session.commit()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        job_response = client.get(
            f"/v1/jobs/{job.id}",
            headers={"X-Scopes": "operator"},
        )
        events_response = client.get(
            f"/v1/jobs/{job.id}/events",
            headers={"X-Scopes": "operator"},
        )
    finally:
        app.dependency_overrides.clear()

    assert job_response.status_code == 200
    assert events_response.status_code == 200
    assert "V-12345678" not in str(job_response.json())
    assert "V-12345678" not in str(events_response.json())
    safe_failure_message = "Job failed; inspect error_code and internal diagnostics."
    assert job_response.json()["error_message"] == safe_failure_message
    assert events_response.json()[-1]["message"] == safe_failure_message
    assert events_response.json()[-1]["metadata_json"]["reason"] == "[REDACTED]"


def test_duplicate_candidate_and_cluster_endpoints(session):
    actor = Actor(
        actor_id="reviewer-1",
        actor_type="user",
        scopes=frozenset({"operator", "data_steward", "reviewer"}),
    )
    manifest = create_source_manifest(
        session,
        payload=sample_manifest_payload(),
        actor=actor,
        policy_decision="allow:test",
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

    candidate = session.query(DuplicateCandidate).one()
    cluster = session.query(DuplicateCluster).one()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        candidate_response = client.get(
            f"/v1/duplicate-candidates/{candidate.id}",
            headers={"X-Scopes": "reviewer"},
        )
        cluster_list_response = client.get(
            "/v1/duplicate-clusters",
            headers={"X-Scopes": "reviewer"},
        )
        cluster_detail_response = client.get(
            f"/v1/duplicate-clusters/{cluster.id}",
            headers={"X-Scopes": "reviewer"},
        )
        events_response = client.get(
            f"/v1/jobs/{job.id}/events",
            headers={"X-Scopes": "operator"},
        )
        chunks_response = client.get(
            f"/v1/jobs/{job.id}/chunks",
            headers={"X-Scopes": "operator"},
        )
        quarantine_response = client.get(
            f"/v1/quarantine-records?job_id={job.id}",
            headers={"X-Scopes": "operator"},
        )
        review_case_id = candidate_response.json()["id"]
        review_cases_response = client.get(
            "/v1/review-cases",
            headers={"X-Scopes": "reviewer"},
        )
        assign_response = client.post(
            f"/v1/review-cases/{review_cases_response.json()[0]['id']}/assign",
            headers={"X-Scopes": "reviewer"},
            json={"assigned_to": "reviewer-2", "reason": "Synthetic assignment"},
        )
    finally:
        app.dependency_overrides.clear()

    assert candidate_response.status_code == 200
    assert candidate_response.json()["evidence_json"]["signals"] == [
        "cedula",
        "phone",
        "name_last",
    ]
    assert cluster_list_response.status_code == 200
    assert cluster_list_response.json()[0]["member_count"] == 2
    assert cluster_detail_response.status_code == 200
    assert len(cluster_detail_response.json()["members"]) == 2
    assert events_response.status_code == 200
    assert events_response.json()[-1]["event_type"] == "job.completed"
    assert chunks_response.status_code == 200
    assert chunks_response.json()[0]["records_seen"] == 3
    assert quarantine_response.status_code == 200
    assert quarantine_response.json() == []
    assert review_case_id == candidate.id
    assert assign_response.status_code == 200
    assert assign_response.json()["assigned_to"] == "reviewer-2"
    assert session.scalar(select(AuditEvent).where(AuditEvent.operation == "review_case.assign"))


def test_quarantine_resolution_endpoint_is_audited_and_safe(session):
    actor = Actor(
        actor_id="operator-1",
        actor_type="user",
        scopes=frozenset({"operator", "data_steward"}),
    )
    manifest_payload = sample_manifest_payload()
    manifest_payload.manifest_json["sample_records"].append(
        {"name": "Missing synthetic id", "phone": "0412 000 0000"}
    )
    manifest = create_source_manifest(
        session,
        payload=manifest_payload,
        actor=actor,
        policy_decision="allow:test",
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
    quarantine = session.scalar(select(QuarantineRecord))
    session.commit()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        list_response = client.get(
            f"/v1/quarantine-records?job_id={job.id}",
            headers={"X-Scopes": "operator"},
        )
        resolve_response = client.post(
            f"/v1/quarantine-records/{quarantine.id}/resolve",
            headers={"X-Scopes": "operator"},
            json={"status": "resolved", "reason": "Synthetic parser issue reviewed"},
        )
    finally:
        app.dependency_overrides.clear()

    assert list_response.status_code == 200
    assert "payload_json_redacted" not in list_response.json()[0]
    assert resolve_response.status_code == 200
    assert resolve_response.json()["status"] == "resolved"
    assert "payload_json_redacted" not in resolve_response.json()
    assert session.scalar(select(AuditEvent).where(AuditEvent.operation == "quarantine.resolve"))


def test_promotion_request_endpoint_is_audited_and_safe(session):
    actor = Actor(
        actor_id="operator-1",
        actor_type="user",
        scopes=frozenset({"operator", "data_steward"}),
    )
    manifest = create_source_manifest(
        session,
        payload=sample_manifest_payload(),
        actor=actor,
        policy_decision="allow:test",
    )
    approve_manifest(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
        reason="Synthetic approval",
    )
    job = create_ingestion_job(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
    )
    run_manifest_ingestion(session, job_id=job.id)
    session.commit()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        create_response = client.post(
            "/v1/promotions",
            headers={"X-Scopes": "operator"},
            json={"job_id": job.id, "reason": "Synthetic promotion readiness review"},
        )
        list_response = client.get(
            "/v1/promotions",
            headers={"X-Scopes": "data_steward"},
        )
        agent_response = client.post(
            "/v1/promotions",
            headers={"X-Actor-Type": "agent", "X-Scopes": "openclaw:runbook"},
            json={"job_id": job.id, "reason": "Synthetic agent attempt"},
        )
        decision_response = client.post(
            f"/v1/promotions/{create_response.json()['id']}/decision",
            headers={"X-Scopes": "data_steward"},
            json={"decision": "approved", "reason": "Synthetic controlled promotion"},
        )
    finally:
        app.dependency_overrides.clear()

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["status"] == "pending"
    assert created["summary_json"]["records_seen"] == 3
    assert "payload_json_redacted" not in created
    assert "cedula_fingerprint" not in str(created)
    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == created["id"]
    assert agent_response.status_code == 403
    assert decision_response.status_code == 200
    assert decision_response.json()["status"] == "approved"
    assert session.scalar(select(PromotionRequest)).status == "approved"
    assert session.scalar(select(AuditEvent).where(AuditEvent.operation == "promotion.request"))
    assert session.scalar(select(AuditEvent).where(AuditEvent.operation == "promotion.decide"))


def test_openclaw_diagnostics_and_quality_summary_are_safe(session):
    actor = Actor(
        actor_id="operator-1",
        actor_type="user",
        scopes=frozenset({"operator", "data_steward"}),
    )
    manifest_payload = sample_manifest_payload()
    manifest_payload.manifest_json["sample_records"].append(
        {"name": "Missing synthetic id", "phone": "0412 000 0000"}
    )
    manifest = create_source_manifest(
        session,
        payload=manifest_payload,
        actor=actor,
        policy_decision="allow:test",
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

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        diagnostics_response = client.get(
            f"/v1/ops/jobs/{job.id}/diagnostics",
            headers={
                "X-Actor-Type": "agent",
                "X-Scopes": "openclaw:diagnostics",
            },
        )
        summary_response = client.post(
            "/v1/ops/reports/daily-quality-summary",
            headers={
                "X-Actor-Type": "agent",
                "X-Scopes": "openclaw:diagnostics",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert diagnostics_response.status_code == 200
    diagnostics = diagnostics_response.json()
    assert diagnostics["job_id"] == job.id
    assert diagnostics["safe_for_agent"] is True
    assert diagnostics["quarantine_records_created"] == 1
    assert "job" not in diagnostics
    assert "events" not in diagnostics
    assert "error_message" not in diagnostics

    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["safe_for_agent"] is True
    assert summary["jobs_completed"] == 1
    assert summary["quarantine_records_open"] == 1
    assert "payload" not in summary
