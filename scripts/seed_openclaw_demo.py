import os
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from vdch.config import Settings, get_settings
from vdch.db import Base
from vdch.models import DuplicateCluster, JobChunk, ReviewCase
from vdch.schemas import SourceManifestCreate
from vdch.security import Actor
from vdch.services import (
    approve_manifest,
    create_ingestion_job,
    create_source_manifest,
    run_manifest_ingestion,
)


def demo_manifest() -> SourceManifestCreate:
    return SourceManifestCreate(
        source_slug="openclaw-demo-registry",
        source_display_name="OpenClaw Demo Registry",
        owner="demo-data-team",
        permission_basis="Synthetic demo fixture",
        sensitive_fields_json={"safe_fields": ["status", "age", "location_general"]},
        manifest_json={
            "type": "sample_json",
            "sample_records": [
                {
                    "id": "demo-1",
                    "name": "Synthetic Alpha",
                    "cedula": "V-12345678",
                    "phone": "0412 555 0000",
                    "status": "active",
                    "age": 41,
                    "location": "Synthetic District",
                },
                {
                    "id": "demo-2",
                    "name": "Synthetic Alfa",
                    "cedula": "V-12345678",
                    "phone": "04125550000",
                    "status": "active",
                    "age": 41,
                    "location": "Synthetic District",
                },
                {
                    "id": "demo-3",
                    "name": "Synthetic Beta",
                    "phone": "0412 555 1111",
                    "status": "missing",
                    "age": 36,
                    "location": "Synthetic Parish",
                },
            ],
            "field_mappings": {
                "source_record_id": "id",
                "display_name": "name",
                "cedula": "cedula",
                "phone": "phone",
                "status": "status",
                "age": "age",
                "location_general": "location",
            },
        },
    )


def main() -> None:
    os.environ.setdefault("VDCH_FINGERPRINT_SECRET", "synthetic-openclaw-demo-secret")
    get_settings.cache_clear()
    default_database_url = "sqlite:///openclaw-demo.sqlite"
    database_url = os.environ.get("VDCH_DATABASE_URL", default_database_url)
    if database_url == default_database_url:
        Path("openclaw-demo.sqlite").unlink(missing_ok=True)
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    actor = Actor(
        actor_id="demo-steward",
        actor_type="user",
        scopes=frozenset({"operator", "data_steward", "reviewer"}),
    )
    session = Session()
    try:
        manifest = create_source_manifest(
            session,
            payload=demo_manifest(),
            actor=actor,
            policy_decision="allow:demo",
            settings=Settings(
                allow_sample_manifests=True,
                database_url=database_url,
            ),
            metadata={"request_id": "demo-seed"},
        )
        approve_manifest(
            session,
            manifest_id=manifest.id,
            actor=actor,
            policy_decision="allow:demo",
            reason="Synthetic OpenClaw demo approval",
            metadata={"request_id": "demo-seed"},
        )
        job = create_ingestion_job(
            session,
            manifest_id=manifest.id,
            actor=actor,
            policy_decision="allow:demo",
            idempotency_key="openclaw-demo-seed",
            metadata={"request_id": "demo-seed"},
        )
        run_manifest_ingestion(session, job_id=job.id)
        session.commit()

        chunks = session.scalars(select(JobChunk).where(JobChunk.job_id == job.id)).all()
        review_case_count = len(session.scalars(select(ReviewCase)).all())
        cluster_count = len(session.scalars(select(DuplicateCluster)).all())

        print("OpenClaw demo seed completed")
        print(f"source_manifest_version_id={manifest.id}")
        print(f"job_id={job.id}")
        print(f"job_status={job.status}")
        print(f"records_seen={job.summary_json.get('records_seen', 0)}")
        print(f"chunks={len(chunks)}")
        print(f"duplicate_clusters={cluster_count}")
        print(f"review_cases={review_case_count}")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
