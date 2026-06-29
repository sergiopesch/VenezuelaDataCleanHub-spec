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


def test_http_manifest_rejects_private_and_link_local_hosts():
    private_manifest = {
        "type": "http_json",
        "base_url": "https://10.0.0.5/records",
        "allowed_hosts": ["10.0.0.5"],
        "field_mappings": {"source_record_id": "id"},
    }
    metadata_manifest = {
        "type": "http_json",
        "base_url": "https://169.254.169.254/latest/meta-data",
        "allowed_hosts": ["169.254.169.254"],
        "field_mappings": {"source_record_id": "id"},
    }

    with pytest.raises(ManifestValidationError, match="private or non-routable"):
        validate_manifest(private_manifest, allow_sample=True)
    with pytest.raises(ManifestValidationError, match="private or non-routable"):
        validate_manifest(metadata_manifest, allow_sample=True)


def test_http_manifest_rejects_unapproved_or_secret_headers():
    secret_header_manifest = {
        "type": "http_json",
        "base_url": "https://api.example.org/records",
        "allowed_hosts": ["api.example.org"],
        "headers": {"Authorization": "Bearer secret"},
        "field_mappings": {"source_record_id": "id"},
    }
    custom_header_manifest = {
        "type": "http_json",
        "base_url": "https://api.example.org/records",
        "allowed_hosts": ["api.example.org"],
        "headers": {"X-Api-Key": "secret"},
        "field_mappings": {"source_record_id": "id"},
    }

    with pytest.raises(ManifestValidationError, match="not allowed"):
        validate_manifest(
            secret_header_manifest,
            allow_sample=True,
            approved_hosts={"api.example.org"},
        )
    with pytest.raises(ManifestValidationError, match="not approved"):
        validate_manifest(
            custom_header_manifest,
            allow_sample=True,
            approved_hosts={"api.example.org"},
        )


def test_http_manifest_requires_base_url_host_allowlist_match():
    manifest = {
        "type": "http_json",
        "base_url": "https://api.example.org/records",
        "allowed_hosts": ["other.example.org"],
        "field_mappings": {"source_record_id": "id"},
    }

    with pytest.raises(ManifestValidationError, match="host must be in allowed_hosts"):
        validate_manifest(manifest, allow_sample=True)


def test_http_manifest_requires_server_side_host_approval():
    manifest = {
        "type": "http_json",
        "base_url": "https://api.example.org/records",
        "allowed_hosts": ["api.example.org"],
        "field_mappings": {"source_record_id": "id"},
    }

    with pytest.raises(ManifestValidationError, match="server-side manifest host allowlist"):
        validate_manifest(manifest, allow_sample=True)
    with pytest.raises(ManifestValidationError, match="not approved by server policy"):
        validate_manifest(manifest, allow_sample=True, approved_hosts={"other.example.org"})


def test_http_csv_and_jsonl_manifests_use_same_host_and_header_controls():
    jsonl_manifest = {
        "type": "http_jsonl",
        "base_url": "https://api.example.org/records.jsonl",
        "allowed_hosts": ["api.example.org"],
        "field_mappings": {"source_record_id": "id"},
    }
    csv_manifest = {
        "type": "http_csv",
        "base_url": "https://api.example.org/records.csv",
        "allowed_hosts": ["api.example.org"],
        "delimiter": ",",
        "field_mappings": {"source_record_id": "id"},
    }
    invalid_csv_manifest = {**csv_manifest, "delimiter": "::"}

    validate_manifest(jsonl_manifest, allow_sample=True, approved_hosts={"api.example.org"})
    validate_manifest(csv_manifest, allow_sample=True, approved_hosts={"api.example.org"})
    with pytest.raises(ManifestValidationError, match="single character"):
        validate_manifest(
            invalid_csv_manifest,
            allow_sample=True,
            approved_hosts={"api.example.org"},
        )


def test_sample_manifest_can_be_disabled():
    manifest = {
        "type": "sample_json",
        "sample_records": [],
        "field_mappings": {"source_record_id": "id"},
    }

    with pytest.raises(ManifestValidationError, match="disabled"):
        validate_manifest(manifest, allow_sample=False)
