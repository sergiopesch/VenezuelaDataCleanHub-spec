# VenezuelaDataCleanHub Platform Spec

Architecture and product specification for a production-grade data deduplication,
cleanup, review, and API service platform.

This repository is intentionally separate from the initial deduplication prototype. The prototype
proved the deduplication workflow and surfaced operational constraints. This
spec defines the durable platform that should sit behind mobile apps, authorized
operators, data pipelines, and controlled external integrations.

## Documents

- [Platform Architecture](docs/platform-architecture.md)
- [Prototype Learnings](docs/prototype-learnings.md)
- [Security and Privacy Model](docs/security/security-and-privacy.md)
- [OpenClaw Operations Model](docs/operations/openclaw-operations.md)
- [Implementation Slice](docs/implementation-slice.md)
- [Roadmap](docs/roadmap.md)
- [References](docs/references.md)
- [ADR 0001: Architecture Direction](docs/adr/0001-platform-architecture-direction.md)

## Current Recommendation

Build a separate open-source platform around:

- FastAPI for the public and internal APIs.
- PostgreSQL as the operational source of truth.
- Object storage compatible with S3 for uploaded files, image artifacts, and exports.
- Temporal for durable workflow orchestration.
- Redpanda or Kafka-compatible streaming for high-volume ingestion events.
- OpenSearch for search and operator investigation.
- DuckDB/Polars workers for analytical batch matching.
- Qdrant or pgvector for optional embedding/vector similarity.
- Keycloak and Open Policy Agent for identity, authorization, and policy decisions.
- OpenTelemetry, Prometheus, Grafana, and Loki for observability.
- OpenClaw as the operational agent/control plane for authorized runbooks and incident workflows.

Prototype hosting remains useful for demos, review experiments, and model tests,
but it should not be the production API boundary for Android/iOS traffic.

## Repo Status

This repo now contains the first production-shaped foundation in addition to
the architecture specification. The initial implementation slice includes:

- FastAPI API service skeleton.
- PostgreSQL SQLAlchemy models and Alembic migration.
- Approved source manifest registry.
- Durable ingestion workflow boundary with Temporal worker support.
- Local background execution path for tests and early development.
- Immutable raw records, derived person records, deterministic duplicate
  candidates, review cases, decisions, and audit events.
- Aggregated duplicate evidence, duplicate clusters, and cluster/member review
  APIs.
- Idempotent ingestion job creation, attempt tracking, and append-only job event
  history for diagnostics.
- Scoped OpenClaw operations bridge endpoints.
- Docker Compose environment for Postgres, Temporal, MinIO, OPA, Keycloak, API,
  and worker.

No real sensitive data should be committed here.

## Local Development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
```

To run the local service stack:

```bash
docker compose -f infra/docker-compose.yml up --build
```

See [Local Foundation](docs/development/local-foundation.md) for the first
slice workflow and local service URLs.
