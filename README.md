# AcopioVE Data Hub Platform Spec

Architecture and product specification for a production-grade data deduplication,
cleanup, review, and API service platform.

This repository is intentionally separate from the Hugging Face MVP. The MVP
proved the deduplication workflow and surfaced operational constraints. This
spec defines the durable platform that should sit behind mobile apps, authorized
operators, data pipelines, and controlled external integrations.

## Documents

- [Platform Architecture](docs/platform-architecture.md)
- [MVP Learnings](docs/mvp-learnings.md)
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

Hugging Face remains useful for public demo, review UI, and model experiments,
but it should not be the production API boundary for Android/iOS traffic.

## Repo Status

This is a planning/specification repo. No production code or sensitive data
should be committed here.
