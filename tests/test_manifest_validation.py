import pytest
from vdch.manifest import ManifestValidationError, validate_manifest


def test_http_manifest_rejects_loopback_host():
    manifest = {
        "type": "http_json",
        "base_url": "https://localhost/private",
        "allowed_hosts": ["localhost"],
        "field_mappings": {"source_record_id": "id"},
    }

    with pytest.raises(ManifestValidationError, match="loopback"):
        validate_manifest(manifest, allow_sample=True)


def test_http_manifest_requires_base_url_host_allowlist_match():
    manifest = {
        "type": "http_json",
        "base_url": "https://api.example.org/records",
        "allowed_hosts": ["other.example.org"],
        "field_mappings": {"source_record_id": "id"},
    }

    with pytest.raises(ManifestValidationError, match="host must be in allowed_hosts"):
        validate_manifest(manifest, allow_sample=True)


def test_sample_manifest_can_be_disabled():
    manifest = {
        "type": "sample_json",
        "sample_records": [],
        "field_mappings": {"source_record_id": "id"},
    }

    with pytest.raises(ManifestValidationError, match="disabled"):
        validate_manifest(manifest, allow_sample=False)

