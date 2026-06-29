# ADR 0001: Platform Architecture Direction

## Status

Proposed

## Context

The initial deduplication prototype demonstrated that the deduplication approach works on real
public API data. It also showed that a production service needs durable
workflows, stronger access control, persistent operational storage, mobile-safe
APIs, and better observability.

## Decision

Build a separate open-source platform rather than extending the initial deduplication prototype
into the production backend.

Use:

- FastAPI for APIs.
- PostgreSQL for operational truth.
- Temporal for durable workflows.
- S3-compatible object storage for files, images, reports, and snapshots.
- Kafka-compatible eventing for ingestion and processing events.
- DuckDB/Polars for analytical worker jobs.
- Keycloak and OPA for identity and policy.
- OpenClaw for operational runbooks and agent-assisted workflows.

## Consequences

Positive:

- Production-ready architecture for mobile and external API clients.
- Clear separation between demo/operator UI and system of record.
- Better handling of long-running jobs and API rate limits.
- Stronger governance for sensitive and biometric data.

Negative:

- More infrastructure than the prototype.
- Requires explicit operations discipline.
- Requires schema design, migrations, and deployment automation.
- OpenClaw integration must be carefully scoped to avoid unsafe automation.

## Open Questions

- Should the GitHub repo be public immediately or private until security review?
- Which deployment target should be first: single VM Docker Compose, managed
  Kubernetes, or self-hosted Kubernetes?
- Should PostgreSQL use pgvector or should vectors live in Qdrant?
- Which identity provider is preferred if Keycloak is too heavy initially?
