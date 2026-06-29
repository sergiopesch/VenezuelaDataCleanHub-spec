from typing import Any
from urllib.parse import urlparse


class ManifestValidationError(ValueError):
    pass


def validate_manifest(manifest: dict[str, Any], *, allow_sample: bool) -> None:
    manifest_type = manifest.get("type")
    if manifest_type not in {"http_json", "sample_json"}:
        raise ManifestValidationError("manifest.type must be http_json or sample_json")

    mappings = manifest.get("field_mappings")
    if not isinstance(mappings, dict) or "source_record_id" not in mappings:
        raise ManifestValidationError("manifest.field_mappings.source_record_id is required")

    if manifest_type == "sample_json":
        if not allow_sample:
            raise ManifestValidationError("sample_json manifests are disabled")
        records = manifest.get("sample_records")
        if not isinstance(records, list):
            raise ManifestValidationError("sample_json manifests require sample_records list")
        return

    base_url = manifest.get("base_url")
    allowed_hosts = manifest.get("allowed_hosts")
    if not isinstance(base_url, str):
        raise ManifestValidationError("http_json manifests require base_url")
    if not isinstance(allowed_hosts, list) or not allowed_hosts:
        raise ManifestValidationError("http_json manifests require allowed_hosts")

    parsed = urlparse(base_url)
    if parsed.scheme != "https":
        raise ManifestValidationError("http_json base_url must use https")
    if parsed.hostname not in allowed_hosts:
        raise ManifestValidationError("base_url host must be in allowed_hosts")
    if parsed.hostname in {"localhost", "127.0.0.1", "0.0.0.0"}:
        raise ManifestValidationError("loopback hosts are not allowed")

    method = manifest.get("method", "GET")
    if method != "GET":
        raise ManifestValidationError("milestone 1 only supports GET manifests")


def get_by_path(payload: Any, path: str | None) -> Any:
    if not path:
        return payload
    current = payload
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def mapped_value(record: dict[str, Any], mappings: dict[str, str], key: str) -> Any:
    source_key = mappings.get(key)
    if not source_key:
        return None
    return get_by_path(record, source_key)
