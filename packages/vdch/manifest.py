from ipaddress import ip_address
from typing import Any
from urllib.parse import urlparse


class ManifestValidationError(ValueError):
    pass


DISALLOWED_HEADER_NAMES = {
    "authorization",
    "cookie",
    "host",
    "proxy-authorization",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-real-ip",
}
ALLOWED_HEADER_NAMES = {
    "accept",
    "user-agent",
}


def _validate_public_host(hostname: str | None) -> str:
    if not hostname:
        raise ManifestValidationError("base_url host is required")
    normalized = hostname.lower().rstrip(".")
    if normalized == "localhost":
        raise ManifestValidationError("loopback hosts are not allowed")
    try:
        parsed_ip = ip_address(normalized)
    except ValueError:
        return normalized
    if (
        parsed_ip.is_private
        or parsed_ip.is_loopback
        or parsed_ip.is_link_local
        or parsed_ip.is_multicast
        or parsed_ip.is_reserved
        or parsed_ip.is_unspecified
    ):
        raise ManifestValidationError("private or non-routable hosts are not allowed")
    return normalized


def _validate_headers(headers: Any) -> None:
    if headers is None:
        return
    if not isinstance(headers, dict):
        raise ManifestValidationError("manifest.headers must be an object")
    for name, value in headers.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise ManifestValidationError("manifest.headers must contain string keys and values")
        normalized_name = name.lower()
        if normalized_name in DISALLOWED_HEADER_NAMES:
            raise ManifestValidationError(f"manifest header is not allowed: {name}")
        if normalized_name not in ALLOWED_HEADER_NAMES:
            raise ManifestValidationError(f"manifest header is not approved: {name}")


def validate_manifest(
    manifest: dict[str, Any],
    *,
    allow_sample: bool,
    approved_hosts: set[str] | None = None,
) -> None:
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
    hostname = _validate_public_host(parsed.hostname)
    normalized_allowed_hosts = [_validate_public_host(str(host)) for host in allowed_hosts]
    if hostname not in normalized_allowed_hosts:
        raise ManifestValidationError("base_url host must be in allowed_hosts")
    if not approved_hosts:
        raise ManifestValidationError("server-side manifest host allowlist is required")
    if hostname not in approved_hosts:
        raise ManifestValidationError("base_url host is not approved by server policy")

    method = manifest.get("method", "GET")
    if method != "GET":
        raise ManifestValidationError("milestone 1 only supports GET manifests")
    _validate_headers(manifest.get("headers"))


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
