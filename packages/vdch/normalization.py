import hashlib
import hmac
import json
import re
import unicodedata
from typing import Any

from vdch.config import get_settings
from vdch.manifest import mapped_value

IDENTITY_TOKEN_VERSION = "hmac-sha256-v1"


def stable_json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def normalize_identifier(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = re.sub(r"[^a-z0-9]", "", normalized)
    if not normalized:
        return None
    if normalized[0] in {"v", "e"}:
        digits = re.sub(r"\D", "", normalized[1:])
        return f"{normalized[0]}{digits}" if digits else None
    digits = re.sub(r"\D", "", normalized)
    return digits or None


def fingerprint_digits(value: Any) -> str | None:
    normalized = normalize_identifier(value)
    if not normalized:
        return None
    return keyed_fingerprint(normalized)


def fingerprint_url(value: Any) -> str | None:
    normalized = normalize_text(value)
    if not normalized:
        return None
    return keyed_fingerprint(normalized)


def keyed_fingerprint(value: str) -> str:
    settings = get_settings()
    secret = settings.fingerprint_secret
    if not secret:
        if settings.allow_insecure_fingerprints_for_local_dev:
            secret = "local-dev-insecure-fingerprint-secret"
        else:
            raise RuntimeError("VDCH_FINGERPRINT_SECRET is required for derived identifiers")
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def split_name(display_name: str | None) -> tuple[str | None, str | None]:
    normalized = normalize_text(display_name)
    if not normalized:
        return None, None
    parts = normalized.split()
    first_name = parts[0] if parts else None
    last_name = parts[-1] if len(parts) > 1 else None
    return first_name, last_name


def build_person_fields(record: dict[str, Any], mappings: dict[str, str]) -> dict[str, Any]:
    display_name = mapped_value(record, mappings, "display_name")
    cedula = mapped_value(record, mappings, "cedula")
    phone = mapped_value(record, mappings, "phone")
    photo_url = mapped_value(record, mappings, "photo_url")
    first_name, last_name = split_name(display_name)
    normalized_name = normalize_text(display_name)
    evidence = {
        "has_name": bool(normalized_name),
        "has_cedula": bool(cedula),
        "has_phone": bool(phone),
        "has_photo_url": bool(photo_url),
    }
    quality_score = sum(1 for value in evidence.values() if value) / len(evidence)
    age = mapped_value(record, mappings, "age")
    try:
        age = int(age) if age not in (None, "") else None
    except (TypeError, ValueError):
        age = None

    return {
        "display_name": str(display_name).strip() if display_name is not None else None,
        "normalized_name": normalized_name,
        "first_name": first_name,
        "last_name": last_name,
        "cedula_display": None,
        "cedula_fingerprint": fingerprint_digits(cedula),
        "phone_fingerprint": fingerprint_digits(phone),
        "photo_url": str(photo_url).strip() if photo_url is not None else None,
        "photo_fingerprint": fingerprint_url(photo_url),
        "status": mapped_value(record, mappings, "status"),
        "age": age,
        "location_general": mapped_value(record, mappings, "location_general"),
        "source_date": mapped_value(record, mappings, "source_date"),
        "quality_score": quality_score,
        "quality_evidence_json": evidence,
        "identity_token_version": IDENTITY_TOKEN_VERSION,
    }
