from temporalio import activity, workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from datetime import timedelta

    from vdch.db import SessionLocal
    from vdch.services import run_manifest_ingestion


@activity.defn
def run_manifest_ingestion_activity(job_id: str) -> str:
    session = SessionLocal()
    try:
        job = run_manifest_ingestion(session, job_id=job_id)
        session.commit()
        return job.id
    except Exception:
        session.commit()
        raise
    finally:
        session.close()


@workflow.defn
class ApprovedManifestIngestionWorkflow:
    @workflow.run
    async def run(self, job_id: str) -> str:
        return await workflow.execute_activity(
            run_manifest_ingestion_activity,
            job_id,
            start_to_close_timeout=timedelta(minutes=45),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
