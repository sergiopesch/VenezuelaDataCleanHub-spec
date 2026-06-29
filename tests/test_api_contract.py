from fastapi.testclient import TestClient
from vdch.db import get_session
from vdch.models import SourceManifestVersion

from apps.api.main import app


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
