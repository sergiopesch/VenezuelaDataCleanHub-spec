import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from vdch.config import get_settings
from vdch.db import Base


@pytest.fixture(autouse=True)
def local_dev_security_settings(monkeypatch):
    monkeypatch.setenv("VDCH_DEV_AUTH_ENABLED", "true")
    monkeypatch.setenv("VDCH_ALLOW_POLICY_BYPASS_FOR_LOCAL_DEV", "true")
    monkeypatch.setenv("VDCH_OPA_ENABLED", "false")
    monkeypatch.setenv("VDCH_FINGERPRINT_SECRET", "test-fingerprint-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
