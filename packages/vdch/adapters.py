import csv
import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from io import StringIO
from typing import Any, Protocol

import httpx

from vdch.config import get_settings
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
        yield from _chunks(self.name, records, source_uri="sample_json")


class HttpJsonAdapter:
    name = "http_json"

    def __init__(self, *, approved_hosts: set[str]) -> None:
        self.approved_hosts = approved_hosts

    def fetch_chunks(self, manifest: dict[str, Any]) -> Iterable[RecordChunk]:
        settings = get_settings()
        validate_manifest(manifest, allow_sample=False, approved_hosts=self.approved_hosts)
        response = _fetch_http_response(manifest, settings.max_http_response_bytes)
        payload = response.json()
        records = get_by_path(payload, manifest.get("records_path"))
        if not isinstance(records, list):
            raise AdapterError("Manifest records_path did not resolve to a list")
        yield from _chunks(self.name, records, source_uri=manifest.get("base_url"))


class HttpJsonlAdapter:
    name = "http_jsonl"

    def __init__(self, *, approved_hosts: set[str]) -> None:
        self.approved_hosts = approved_hosts

    def fetch_chunks(self, manifest: dict[str, Any]) -> Iterable[RecordChunk]:
        settings = get_settings()
        validate_manifest(manifest, allow_sample=False, approved_hosts=self.approved_hosts)
        response = _fetch_http_response(manifest, settings.max_http_response_bytes)
        yield from _iter_chunks(
            self.name,
            _jsonl_records(response.text),
            source_uri=manifest.get("base_url"),
        )


class HttpCsvAdapter:
    name = "http_csv"

    def __init__(self, *, approved_hosts: set[str]) -> None:
        self.approved_hosts = approved_hosts

    def fetch_chunks(self, manifest: dict[str, Any]) -> Iterable[RecordChunk]:
        settings = get_settings()
        validate_manifest(manifest, allow_sample=False, approved_hosts=self.approved_hosts)
        response = _fetch_http_response(manifest, settings.max_http_response_bytes)
        delimiter = manifest.get("delimiter", ",")
        yield from _iter_chunks(
            self.name,
            csv.DictReader(StringIO(response.text), delimiter=delimiter),
            source_uri=manifest.get("base_url"),
        )


def _chunks(
    adapter_name: str,
    records: list[Any],
    *,
    source_uri: str | None,
) -> Iterable[RecordChunk]:
    yield from _iter_chunks(adapter_name, iter(records), source_uri=source_uri)


def _iter_chunks(
    adapter_name: str,
    records: Iterable[Any],
    *,
    source_uri: str | None,
) -> Iterator[RecordChunk]:
    settings = get_settings()
    chunk_size = max(1, settings.ingestion_chunk_size)
    sequence = 1
    offset = 0
    chunk_records: list[Any] = []
    for record in records:
        if offset >= settings.max_ingestion_records:
            raise AdapterError("Source record count exceeded configured maximum")
        chunk_records.append(record)
        offset += 1
        if len(chunk_records) == chunk_size:
            yield RecordChunk(
                sequence=sequence,
                records=chunk_records,
                source_uri=source_uri,
                checkpoint_json={
                    "adapter": adapter_name,
                    "records": len(chunk_records),
                    "offset": offset - len(chunk_records),
                },
            )
            sequence += 1
            chunk_records = []
    if chunk_records:
        yield RecordChunk(
            sequence=sequence,
            records=chunk_records,
            source_uri=source_uri,
            checkpoint_json={
                "adapter": adapter_name,
                "records": len(chunk_records),
                "offset": offset - len(chunk_records),
            },
        )


def _fetch_http_response(manifest: dict[str, Any], max_bytes: int) -> httpx.Response:
    _validate_content_length(manifest["base_url"], max_bytes)
    response = httpx.get(
        manifest["base_url"],
        params=manifest.get("query_params") or {},
        headers=manifest.get("headers") or {},
        timeout=manifest.get("timeout_seconds", 30),
        follow_redirects=False,
    )
    response.raise_for_status()
    if len(response.content) > max_bytes:
        raise AdapterError("HTTP response exceeded configured maximum size")
    return response


def _jsonl_records(payload: str) -> Iterator[Any]:
    for line_number, line in enumerate(payload.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError as exc:
            raise AdapterError(f"JSONL record {line_number} is not valid JSON") from exc


def _validate_content_length(url: str, max_bytes: int) -> None:
    try:
        response = httpx.head(url, timeout=10, follow_redirects=False)
    except httpx.HTTPError:
        return
    if not response.is_success:
        return
    content_length = response.headers.get("content-length")
    try:
        if content_length and int(content_length) > max_bytes:
            raise AdapterError("HTTP response content length exceeded configured maximum size")
    except ValueError:
        return


def adapter_name_for_manifest(manifest: dict[str, Any]) -> str:
    manifest_type = manifest.get("type")
    if manifest_type == "sample_json":
        return SampleJsonAdapter.name
    if manifest_type == "http_json":
        return HttpJsonAdapter.name
    if manifest_type == "http_jsonl":
        return HttpJsonlAdapter.name
    if manifest_type == "http_csv":
        return HttpCsvAdapter.name
    raise AdapterError("unsupported manifest adapter type")


def get_adapter(name: str, *, approved_hosts: set[str]) -> SourceAdapter:
    if name == SampleJsonAdapter.name:
        return SampleJsonAdapter()
    if name == HttpJsonAdapter.name:
        return HttpJsonAdapter(approved_hosts=approved_hosts)
    if name == HttpJsonlAdapter.name:
        return HttpJsonlAdapter(approved_hosts=approved_hosts)
    if name == HttpCsvAdapter.name:
        return HttpCsvAdapter(approved_hosts=approved_hosts)
    raise AdapterError(f"unknown adapter: {name}")
