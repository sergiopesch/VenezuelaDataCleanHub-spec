import argparse

from vdch.db import SessionLocal
from vdch.services import run_manifest_ingestion


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a single ingestion job without Temporal.")
    parser.add_argument("job_id")
    args = parser.parse_args()
    session = SessionLocal()
    try:
        job = run_manifest_ingestion(session, job_id=args.job_id)
        session.commit()
        print(f"{job.id} {job.status}")
    except Exception:
        session.commit()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
