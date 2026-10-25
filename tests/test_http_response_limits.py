from contextlib import contextmanager

import httpx
import pytest
from vdch.adapters import AdapterError, _fetch_http_response


class CountedBody(httpx.SyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.reads = 0
        self.closed = False

    def __iter__(self):
        for chunk in self.chunks:
            self.reads += 1
            yield chunk

    def close(self):
        self.closed = True


def serve(monkeypatch, body, headers=None, status=200):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, headers=headers, stream=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    @contextmanager
    def stream(method, url, **kwargs):
        with client.stream(method, url, **kwargs) as response:
            yield response

    monkeypatch.setattr("vdch.adapters.httpx.stream", stream)
    # Also serve the old eager implementation for the regression negative control.
    monkeypatch.setattr("vdch.adapters.httpx.get", client.get)

    def unavailable_head(*_args, **_kwargs):
        raise httpx.ConnectError("HEAD unavailable")

    monkeypatch.setattr("vdch.adapters.httpx.head", unavailable_head)
    return requests


@pytest.mark.parametrize("headers", [{}, {"content-length": "1"}, {"content-length": "invalid"}])
def test_oversized_get_stops_early_without_trusting_head_or_length(monkeypatch, headers):
    body = CountedBody([b"12345678"] * 1000)
    serve(monkeypatch, body, headers)
    with pytest.raises(AdapterError, match="exceeded configured maximum size"):
        _fetch_http_response({"base_url": "https://api.example.org/records"}, 10)
    assert body.reads <= 2
    assert body.closed


def test_declared_oversize_is_rejected_before_reading(monkeypatch):
    body = CountedBody([b"never read"])
    serve(monkeypatch, body, {"content-length": "11"})
    with pytest.raises(AdapterError, match="content length exceeded"):
        _fetch_http_response({"base_url": "https://api.example.org/records"}, 10)
    assert body.reads == 0
    assert body.closed


@pytest.mark.parametrize("encoding", ["gzip", "deflate", "br", "gzip, identity"])
def test_unsolicited_compression_is_rejected_without_decoding(monkeypatch, encoding):
    body = CountedBody([b"never decompress"])
    serve(monkeypatch, body, {"content-encoding": encoding})
    with pytest.raises(AdapterError, match="identity content encoding"):
        _fetch_http_response({"base_url": "https://api.example.org/records"}, 10)
    assert body.reads == 0
    assert body.closed


@pytest.mark.parametrize("payload", [b"", b'{"id":1}', b"1234567890"])
def test_identity_body_within_limit_preserves_request_and_response(monkeypatch, payload):
    body = CountedBody([payload])
    requests = serve(monkeypatch, body, {"content-type": "application/json; charset=utf-8"})
    response = _fetch_http_response(
        {
            "base_url": "https://api.example.org/records",
            "query_params": {"page": "2"},
            "headers": {"Accept": "application/json"},
            "timeout_seconds": 4,
        },
        10,
    )
    assert response.content == payload
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert requests[0].url.params["page"] == "2"
    assert requests[0].headers["accept"] == "application/json"
    assert requests[0].headers["accept-encoding"] == "identity"
    assert body.closed


def test_redirect_is_not_followed_or_read(monkeypatch):
    body = CountedBody([b"never read"])
    requests = serve(monkeypatch, body, {"location": "https://other.example/"}, 302)
    with pytest.raises(httpx.HTTPStatusError):
        _fetch_http_response({"base_url": "https://api.example.org/records"}, 10)
    assert len(requests) == 1
    assert body.reads == 0
    assert body.closed
