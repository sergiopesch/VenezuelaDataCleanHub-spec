from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VDCH_", env_file=".env", extra="ignore")

    database_url: str = Field(
        default="postgresql+psycopg://vdch:vdch@postgres:5432/vdch",
        description="SQLAlchemy database URL.",
    )
    temporal_address: str = "temporal:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "vdch-ingestion"
    temporal_enabled: bool = False
    environment: str = "local"
    api_docs_enabled: bool | None = None
    trusted_hosts: str = ""
    auth_mode: str = "dev_headers"
    dev_auth_enabled: bool = False
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_algorithms: str = "RS256"
    oidc_hs256_secret: str | None = None
    allow_insecure_oidc_hs256_for_local_dev: bool = False
    opa_url: str = "http://opa:8181/v1/data/vdch/allow"
    opa_enabled: bool = False
    allow_policy_bypass_for_local_dev: bool = False
    allow_sample_manifests: bool = True
    manifest_host_allowlist: str = ""
    object_storage_endpoint: str = "http://minio:9000"
    object_storage_bucket: str = "vdch-local"
    fingerprint_secret: str | None = None
    allow_insecure_fingerprints_for_local_dev: bool = False
    max_match_block_size: int = 1000
    ingestion_chunk_size: int = 1000
    max_ingestion_records: int = 100_000
    max_http_response_bytes: int = 20_000_000
    max_api_request_bytes: int = 1_000_000

    @property
    def approved_manifest_hosts(self) -> set[str]:
        return {
            host.strip().lower().rstrip(".")
            for host in self.manifest_host_allowlist.split(",")
            if host.strip()
        }

    @property
    def approved_oidc_algorithms(self) -> list[str]:
        return [
            algorithm.strip()
            for algorithm in self.oidc_algorithms.split(",")
            if algorithm.strip()
        ]

    @property
    def resolved_api_docs_enabled(self) -> bool:
        if self.api_docs_enabled is not None:
            return self.api_docs_enabled
        return self.environment != "production"

    @property
    def approved_trusted_hosts(self) -> list[str]:
        return [host.strip() for host in self.trusted_hosts.split(",") if host.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
