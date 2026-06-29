import asyncio

from temporalio.client import Client
from temporalio.worker import Worker
from vdch.config import get_settings

from workers.workflows import ApprovedManifestIngestionWorkflow, run_manifest_ingestion_activity


async def main() -> None:
    settings = get_settings()
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[ApprovedManifestIngestionWorkflow],
        activities=[run_manifest_ingestion_activity],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
