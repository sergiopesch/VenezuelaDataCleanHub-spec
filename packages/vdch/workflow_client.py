from temporalio.client import Client

from vdch.config import Settings, get_settings
from workers.workflows import ApprovedManifestIngestionWorkflow


async def start_ingestion_workflow(job_id: str, settings: Settings | None = None) -> None:
    resolved_settings = settings or get_settings()
    client = await Client.connect(
        resolved_settings.temporal_address,
        namespace=resolved_settings.temporal_namespace,
    )
    await client.start_workflow(
        ApprovedManifestIngestionWorkflow.run,
        job_id,
        id=f"approved-manifest-ingestion-{job_id}",
        task_queue=resolved_settings.temporal_task_queue,
    )
