from fastapi.testclient import TestClient
from vdch.db import get_session
from vdch.models import DuplicateCandidate, DuplicateCluster, SourceManifestVersion
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
    assert body["approval_status"] == "draft"
    assert session.get(SourceManifestVersion, body["id"]) is not None


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
