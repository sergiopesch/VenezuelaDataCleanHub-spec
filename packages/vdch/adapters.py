from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from vdch.manifest import get_by_path, validate_manifest


class AdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class RecordChunk:
    sequence: int
    records: list[Any]
    source_uri: str | None = None
    checkpoint_json: dict[str, Any] | None = None


class SourceAdapter(Protocol):
    name: str

    def fetch_chunks(self, manifest: dict[str, Any]) -> Iterable[RecordChunk]:
        pass


class SampleJsonAdapter:
    name = "sample_inline"

    def fetch_chunks(self, manifest: dict[str, Any]) -> Iterable[RecordChunk]:
        records = manifest.get("sample_records")
        if not isinstance(records, list):
            raise AdapterError("sample_json manifests require sample_records list")
        yield RecordChunk(
            sequence=1,
            records=list(records),
            source_uri="sample_json",
            checkpoint_json={"adapter": self.name, "records": len(records)},
        )


class HttpJsonAdapter:
    name = "http_json"

    def __init__(self, *, approved_hosts: set[str]) -> None:
        self.approved_hosts = approved_hosts

    def fetch_chunks(self, manifest: dict[str, Any]) -> Iterable[RecordChunk]:
        validate_manifest(manifest, allow_sample=False, approved_hosts=self.approved_hosts)
        response = httpx.get(
            manifest["base_url"],
            params=manifest.get("query_params") or {},
            headers=manifest.get("headers") or {},
            timeout=manifest.get("timeout_seconds", 30),
            follow_redirects=False,
        )
        response.raise_for_status()
        payload = response.json()
        records = get_by_path(payload, manifest.get("records_path"))
        if not isinstance(records, list):
            raise AdapterError("Manifest records_path did not resolve to a list")
        yield RecordChunk(
            sequence=1,
            records=list(records),
            source_uri=manifest.get("base_url"),
            checkpoint_json={"adapter": self.name, "records": len(records)},
        )


def adapter_name_for_manifest(manifest: dict[str, Any]) -> str:
    manifest_type = manifest.get("type")
    if manifest_type == "sample_json":
        return SampleJsonAdapter.name
    if manifest_type == "http_json":
        return HttpJsonAdapter.name
    raise AdapterError("unsupported manifest adapter type")


def get_adapter(name: str, *, approved_hosts: set[str]) -> SourceAdapter:
    if name == SampleJsonAdapter.name:
        return SampleJsonAdapter()
    if name == HttpJsonAdapter.name:
        return HttpJsonAdapter(approved_hosts=approved_hosts)
    raise AdapterError(f"unknown adapter: {name}")
