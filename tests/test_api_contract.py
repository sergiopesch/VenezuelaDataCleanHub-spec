import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from vdch.config import get_settings
from vdch.db import get_session
from vdch.models import (
    AuditEvent,
    DuplicateCandidate,
    DuplicateCluster,
    Job,
    JobEvent,
    PromotionRequest,
    QuarantineEvent,
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


def test_write_endpoints_reject_unknown_fields(session):
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
                "unexpected_role_override": "admin",
                "manifest_json": {
                    "type": "sample_json",
                    "sample_records": [],
                    "field_mappings": {"source_record_id": "id"},
                },
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "extra_forbidden"


def test_request_body_size_limit_is_enforced(session, monkeypatch):
    monkeypatch.setenv("VDCH_MAX_API_REQUEST_BYTES", "200")
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
                "review_notes": "x" * 500,
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

    assert response.status_code == 413


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
    assert list_response.json()["items"][0]["slug"] == "sample-registry"
    assert list_response.json()["meta"]["limit"] == 50
    assert get_response.status_code == 200
    assert get_response.json()["id"] == manifest.source_id
    assert update_response.status_code == 200
    assert update_response.json()["status"] == "disabled"
    assert session.scalar(select(AuditEvent).where(AuditEvent.operation == "source.update_status"))


def test_paginated_endpoints_reject_unbounded_limits(session):
    manifest = create_source_manifest(
        session,
        payload=sample_manifest_payload(),
        actor=Actor("operator-1", "user", frozenset({"operator"})),
        policy_decision="allow:test",
    )
    approve_manifest(
        session,
        manifest_id=manifest.id,
        actor=Actor("steward-1", "user", frozenset({"data_steward"})),
        policy_decision="allow:test",
        reason="Synthetic approval",
    )
    job = create_ingestion_job(
        session,
        manifest_id=manifest.id,
        actor=Actor("operator-1", "user", frozenset({"operator"})),
        policy_decision="allow:test",
    )
    run_manifest_ingestion(session, job_id=job.id)
    session.commit()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        responses = [
            client.get(path, headers=headers)
            for path, headers in [
                ("/v1/sources?limit=101", {"X-Scopes": "operator"}),
                ("/v1/source-manifests?limit=101", {"X-Scopes": "operator"}),
                (f"/v1/jobs/{job.id}/events?limit=101", {"X-Scopes": "operator"}),
                (f"/v1/jobs/{job.id}/chunks?limit=101", {"X-Scopes": "operator"}),
                ("/v1/quarantine-records?limit=101", {"X-Scopes": "operator"}),
                ("/v1/review-cases?limit=101", {"X-Scopes": "reviewer"}),
                ("/v1/duplicate-clusters?limit=101", {"X-Scopes": "reviewer"}),
                ("/v1/promotions?limit=101", {"X-Scopes": "data_steward"}),
            ]
        ]
    finally:
        app.dependency_overrides.clear()

    assert {response.status_code for response in responses} == {422}


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


def test_production_settings_disable_docs_by_default_and_parse_trusted_hosts():
    settings = get_settings()
    production_settings = settings.model_copy(
        update={
            "environment": "production",
            "api_docs_enabled": None,
            "trusted_hosts": "api.test,*.api.test",
        }
    )
    override_settings = settings.model_copy(
        update={"environment": "production", "api_docs_enabled": True}
    )

    assert production_settings.resolved_api_docs_enabled is False
    assert production_settings.approved_trusted_hosts == ["api.test", "*.api.test"]
    assert override_settings.resolved_api_docs_enabled is True


def test_oidc_auth_is_fail_closed_without_bearer_or_config(session, monkeypatch):
    monkeypatch.setenv("VDCH_AUTH_MODE", "oidc")
    monkeypatch.setenv("VDCH_DEV_AUTH_ENABLED", "true")
    monkeypatch.delenv("VDCH_OIDC_ISSUER", raising=False)
    monkeypatch.delenv("VDCH_OIDC_AUDIENCE", raising=False)
    monkeypatch.delenv("VDCH_OIDC_JWKS_URL", raising=False)
    get_settings.cache_clear()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        missing_token = client.get(
            "/v1/source-manifests",
            headers={"X-Scopes": "operator"},
        )
        unconfigured = client.get(
            "/v1/source-manifests",
            headers={
                "Authorization": "Bearer synthetic.invalid.token",
                "X-Scopes": "operator",
            },
        )
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()

    assert missing_token.status_code == 401
    assert unconfigured.status_code == 503


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


def test_oidc_auth_ignores_header_spoofing_for_openclaw(session, monkeypatch):
    monkeypatch.setenv("VDCH_AUTH_MODE", "oidc")
    monkeypatch.setenv("VDCH_DEV_AUTH_ENABLED", "false")
    monkeypatch.setenv("VDCH_OIDC_ISSUER", "https://issuer.example.test")
    monkeypatch.setenv("VDCH_OIDC_AUDIENCE", "vdch-api")
    monkeypatch.setenv("VDCH_OIDC_ALGORITHMS", "HS256")
    monkeypatch.setenv("VDCH_OIDC_HS256_SECRET", "synthetic-oidc-secret")
    monkeypatch.setenv("VDCH_ALLOW_INSECURE_OIDC_HS256_FOR_LOCAL_DEV", "true")
    monkeypatch.setenv("VDCH_ALLOW_POLICY_BYPASS_FOR_LOCAL_DEV", "true")
    monkeypatch.setenv("VDCH_OPA_ENABLED", "false")
    get_settings.cache_clear()
    token = jwt.encode(
        {
            "iss": "https://issuer.example.test",
            "aud": "vdch-api",
            "sub": "user-1",
            "preferred_username": "user-1",
            "scope": "operator",
        },
        "synthetic-oidc-secret",
        algorithm="HS256",
    )

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        response = client.post(
            "/v1/ops/reports/daily-quality-summary",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Actor-Type": "agent",
                "X-Scopes": "openclaw:diagnostics openclaw_operator_agent",
            },
        )
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()

    assert response.status_code == 403


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
        list_response = client.get(
            "/v1/source-manifests",
            headers={"X-Scopes": "operator"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert "manifest_json" not in body
    assert body["manifest_summary"]["type"] == "sample_json"
    assert "sample_records" not in str(body)
    assert "Bearer SECRET" not in str(body)
    assert list_response.status_code == 200
    assert "sample_records" not in str(list_response.json())
    assert "Bearer SECRET" not in str(list_response.json())


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
    assert events_response.json()["items"][-1]["message"] == safe_failure_message
    assert events_response.json()["items"][-1]["metadata_json"]["reason"] == "[REDACTED]"


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
            f"/v1/review-cases/{review_cases_response.json()['items'][0]['id']}/assign",
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
    assert cluster_list_response.json()["items"][0]["member_count"] == 2
    assert cluster_detail_response.status_code == 200
    assert len(cluster_detail_response.json()["members"]) == 2
    assert events_response.status_code == 200
    assert events_response.json()["items"][-1]["event_type"] == "job.completed"
    assert chunks_response.status_code == 200
    assert chunks_response.json()["items"][0]["records_seen"] == 3
    assert quarantine_response.status_code == 200
    assert quarantine_response.json()["items"] == []
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
    assert "payload_json_redacted" not in list_response.json()["items"][0]
    assert resolve_response.status_code == 200
    assert resolve_response.json()["status"] == "resolved"
    assert "payload_json_redacted" not in resolve_response.json()
    assert session.scalar(select(AuditEvent).where(AuditEvent.operation == "quarantine.resolve"))


def test_sensitive_values_do_not_surface_in_audit_events_or_diagnostics(session):
    sensitive_value = "V-12345678 synthetic@example.test token=secret"
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
        reason="Synthetic approval",
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
        resolve_response = client.post(
            f"/v1/quarantine-records/{quarantine.id}/resolve",
            headers={"X-Scopes": "operator", "X-Request-ID": "sensitive-regression-1"},
            json={"status": "resolved", "reason": sensitive_value},
        )
        events_response = client.get(
            f"/v1/jobs/{job.id}/events",
            headers={"X-Scopes": "operator"},
        )
        diagnostics_response = client.get(
            f"/v1/ops/jobs/{job.id}/diagnostics",
            headers={
                "X-Actor-Type": "agent",
                "X-Scopes": "openclaw:diagnostics",
            },
        )
    finally:
        app.dependency_overrides.clear()

    audit_event = session.scalar(
        select(AuditEvent).where(AuditEvent.operation == "quarantine.resolve")
    )
    quarantine_event = session.scalar(select(QuarantineEvent))

    assert resolve_response.status_code == 200
    assert events_response.status_code == 200
    assert diagnostics_response.status_code == 200
    assert sensitive_value not in str(audit_event.metadata_json)
    assert sensitive_value not in str(quarantine_event.metadata_json)
    assert sensitive_value not in str(quarantine_event.message)
    assert sensitive_value not in str(events_response.json())
    assert sensitive_value not in str(diagnostics_response.json())


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
            headers={"X-Scopes": "operator", "X-Request-ID": "promotion-request-1"},
            json={
                "job_id": job.id,
                "reason": "Synthetic promotion readiness review V-12345678",
            },
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
    assert list_response.json()["items"][0]["id"] == created["id"]
    assert agent_response.status_code == 403
    assert decision_response.status_code == 200
    assert decision_response.json()["status"] == "approved"
    assert session.scalar(select(PromotionRequest)).status == "approved"
    request_audit = session.scalar(
        select(AuditEvent).where(AuditEvent.operation == "promotion.request")
    )
    decision_audit = session.scalar(
        select(AuditEvent).where(AuditEvent.operation == "promotion.decide")
    )
    assert request_audit
    assert decision_audit
    assert request_audit.trace_id == "promotion-request-1"
    assert request_audit.metadata_json["reason"] == "[REDACTED]"
    assert "V-12345678" not in str(request_audit.metadata_json)


def test_agent_cannot_call_non_ops_mutations_with_broad_scopes(session):
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
        approve_response = client.post(
            f"/v1/source-manifests/{manifest.id}/approve",
            headers={
                "X-Actor-Type": "agent",
                "X-Scopes": "operator data_steward reviewer admin openclaw:runbook",
            },
            json={"reason": "Synthetic agent misuse"},
        )
        source_status_response = client.patch(
            f"/v1/sources/{manifest.source_id}/status",
            headers={
                "X-Actor-Type": "agent",
                "X-Scopes": "operator data_steward reviewer admin openclaw:runbook",
            },
            json={"status": "disabled", "reason": "Synthetic agent misuse"},
        )
    finally:
        app.dependency_overrides.clear()

    assert approve_response.status_code == 403
    assert source_status_response.status_code == 403


def test_openclaw_retry_endpoint_creates_child_retry_job(session, monkeypatch):
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
    failed_job = create_ingestion_job(
        session,
        manifest_id=manifest.id,
        actor=actor,
        policy_decision="allow:test",
    )

    import vdch.services as services

    original_matching = services.create_duplicate_candidates

    def fail_matching(_session):
        raise RuntimeError("synthetic matching failure")

    monkeypatch.setattr("vdch.services.create_duplicate_candidates", fail_matching)
    with pytest.raises(RuntimeError):
        run_manifest_ingestion(session, job_id=failed_job.id)
    monkeypatch.setattr("vdch.services.create_duplicate_candidates", original_matching)
    session.commit()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        response = client.post(
            "/v1/ops/runbooks/retry-job",
            headers={
                "X-Actor-Type": "agent",
                "X-Scopes": "openclaw:runbook openclaw_operator_agent",
                "X-Request-ID": "retry-api-request-1",
                "X-OpenClaw-Agent-ID": "agent-synthetic-2",
                "X-Runbook-ID": "retry-failed-ingestion",
            },
            json={"job_id": failed_job.id, "reason": "Synthetic retry"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    retry_job = session.get(Job, body["id"])
    assert body["parent_job_id"] == failed_job.id
    assert retry_job.parent_job_id == failed_job.id
    assert failed_job.status == "failed"
    audit_event = session.scalar(
        select(AuditEvent).where(AuditEvent.operation == "ops.runbook.retry_job")
    )
    assert audit_event.trace_id == "retry-api-request-1"
    assert audit_event.metadata_json["reason"] == "[REDACTED]"


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
                "X-Request-ID": "req-openclaw-1",
                "X-OpenClaw-Agent-ID": "agent-synthetic-1",
                "X-OpenClaw-Session-ID": "session-synthetic-1",
                "X-Invoking-User-ID": "operator-synthetic-1",
                "X-Runbook-ID": "diagnostics-summary",
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
    audit_event = session.scalar(
        select(AuditEvent).where(AuditEvent.operation == "ops.job.diagnostics")
    )
    assert audit_event.trace_id == "req-openclaw-1"
    assert audit_event.metadata_json["openclaw_agent_id"] == "agent-synthetic-1"
    assert audit_event.metadata_json["openclaw_session_id"] == "session-synthetic-1"
