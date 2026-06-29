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
    opa_url: str = "http://opa:8181/v1/data/vdch/allow"
    opa_enabled: bool = False
    allow_sample_manifests: bool = True
    object_storage_endpoint: str = "http://minio:9000"
    object_storage_bucket: str = "vdch-local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
