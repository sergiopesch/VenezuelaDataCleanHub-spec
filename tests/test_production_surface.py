import importlib

from fastapi.testclient import TestClient
from vdch.config import get_settings


def reload_api_module():
    import apps.api.main as api_main

    get_settings.cache_clear()
    return importlib.reload(api_main)


def restore_local_api(monkeypatch):
    monkeypatch.setenv("VDCH_ENVIRONMENT", "local")
    monkeypatch.setenv("VDCH_API_DOCS_ENABLED", "true")
    monkeypatch.setenv("VDCH_TRUSTED_HOSTS", "")
    reload_api_module()


def test_production_disables_docs_by_default(monkeypatch):
    monkeypatch.setenv("VDCH_ENVIRONMENT", "production")
    monkeypatch.delenv("VDCH_API_DOCS_ENABLED", raising=False)
    monkeypatch.setenv("VDCH_TRUSTED_HOSTS", "api.example.test")
    try:
        api_main = reload_api_module()
        client = TestClient(api_main.app, base_url="http://api.example.test")

        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
    finally:
        restore_local_api(monkeypatch)


def test_trusted_hosts_reject_unapproved_host(monkeypatch):
    monkeypatch.setenv("VDCH_ENVIRONMENT", "production")
    monkeypatch.setenv("VDCH_TRUSTED_HOSTS", "api.example.test")
    try:
        api_main = reload_api_module()
        approved = TestClient(api_main.app, base_url="http://api.example.test")
        rejected = TestClient(api_main.app, base_url="http://evil.example.test")

        assert approved.get("/healthz").status_code == 200
        assert rejected.get("/healthz").status_code == 400
    finally:
        restore_local_api(monkeypatch)
