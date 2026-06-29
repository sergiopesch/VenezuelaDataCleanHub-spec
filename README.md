# VenezuelaDataCleanHub

VenezuelaDataCleanHub is an open-source, production-shaped platform for high-volume
data deduplication, cleanup, review, and controlled data pipeline operations.

The platform is separate from the earlier Hugging Face prototype. This repository
now contains both the architecture specification and the first hardened
implementation foundation: FastAPI APIs, PostgreSQL models and migrations,
approved source manifests, chunked ingestion, deterministic matching, reviewer
queues, quarantine handling, OpenClaw operations guardrails, and CI checks.

No real sensitive data should be committed to this repository. Tests and fixtures
must use synthetic records only.

## Architecture At A Glance

```mermaid
flowchart LR
    mobile[Android / iOS apps]
    operators[Authorized operators]
    systems[External systems]
    openclaw[OpenClaw agent]

    api[FastAPI backend]
    oidc[Keycloak / OIDC]
    opa[Open Policy Agent]
    postgres[(PostgreSQL)]
    temporal[Temporal workflows]
    objects[(S3-compatible object storage)]
    workers[Ingestion and matching workers]
    events[Redpanda / Kafka-compatible eventing]
    observability[OpenTelemetry / Prometheus / Grafana / logs]

    mobile --> api
    operators --> api
    systems --> api
    openclaw -->|scoped ops endpoints only| api

    api --> oidc
    api --> opa
    api --> postgres
    api --> temporal
    api --> objects
    api --> observability

    temporal --> workers
    workers --> postgres
    workers --> objects
    workers --> events
    workers --> observability
```

## Hardened Ingestion Flow

```mermaid
sequenceDiagram
    participant Operator
    participant API as FastAPI API
    participant Policy as OPA policy
    participant DB as PostgreSQL
    participant WF as Temporal/local runner
    participant Worker

    Operator->>API: Create source manifest
    API->>Policy: Check source_manifest.create
    API->>DB: Store draft manifest and source governance metadata

    Operator->>API: Approve manifest
    API->>Policy: Check source_manifest.approve
    API->>DB: Record approval, parser, adapter, permission basis

    Operator->>API: Create ingestion job
    API->>Policy: Check approved ingestion execution
    API->>DB: Create queued job and job event
    API->>WF: Start durable workflow or local background task

    WF->>Worker: Execute approved adapter and parser
    Worker->>DB: Store immutable raw records
    Worker->>DB: Store HMAC identity tokens and derived person records
    Worker->>DB: Store quarantine records for unsafe input
    Worker->>DB: Create duplicate candidates, stable clusters, review cases
    Worker->>DB: Mark job complete with safe counters
```

## Safety Boundaries

```mermaid
flowchart TB
    raw[Immutable raw records]
    derived[Derived person records with HMAC identity tokens]
    quarantine[Quarantine records with redacted payload snapshots]
    review[Reviewer queue and decisions]
    promotion[Audited promotion requests]
    master[Future master database mutation boundary]
    ops[OpenClaw operations bridge]

    raw --> derived
    raw --> quarantine
    derived --> review
    review --> promotion
    promotion -.explicit future workflow.-> master

    ops -->|start approved ingestion| derived
    ops -->|retry failed jobs| derived
    ops -->|safe diagnostics only| review
    ops -.blocked.-> master
    ops -.blocked.-> raw
```

## Implemented Foundation

- FastAPI service with explicit Pydantic request and response contracts.
- PostgreSQL SQLAlchemy models and Alembic migrations.
- Source registry with governance metadata, status controls, and audit events.
- Approved manifest versions with static parser and adapter selection.
- HMAC-SHA256 identity tokens for cédula and phone matching signals.
- Chunked ingestion jobs with progress, counters, events, and idempotent job creation.
- Immutable raw record storage with redacted payload snapshots.
- Quarantine records and quarantine events for unsafe or unparseable inputs.
- Deterministic duplicate candidates and stable duplicate clusters.
- Reviewer workflow primitives for assignment and decision recording.
- Audited promotion request and decision boundary.
- OpenClaw operations endpoints limited to approved runbooks and safe diagnostics.
- Safe API error handling that avoids returning raw exception text.
- Local Docker Compose stack for Postgres, Temporal, MinIO, OPA, Keycloak, API, and worker.
- CI workflow for lint, tests, migration application, and whitespace checks.

## Core Documents

- [Platform Hardening Spec](docs/platform-hardening-spec.md)
- [Platform Architecture](docs/platform-architecture.md)
- [Implementation Slice](docs/implementation-slice.md)
- [Security and Privacy Model](docs/security/security-and-privacy.md)
- [OpenClaw Operations Model](docs/operations/openclaw-operations.md)
- [Roadmap](docs/roadmap.md)
- [ADR 0001: Architecture Direction](docs/adr/0001-platform-architecture-direction.md)
- [Local Foundation Guide](docs/development/local-foundation.md)
- [References](docs/references.md)

## Local Development

Create a virtual environment and install the package with development
dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/pytest
```

Run the local service stack:

```bash
docker compose -f infra/docker-compose.yml up --build
```

Useful local services:

- API docs: <http://localhost:8000/docs>
- Temporal UI: <http://localhost:8088>
- Keycloak: <http://localhost:8081>
- MinIO console: <http://localhost:9001>
- OPA: <http://localhost:8181>

## Verification

The current foundation is expected to pass:

```bash
.venv/bin/ruff check .
.venv/bin/pytest -W error
docker compose -f infra/docker-compose.yml config
git diff --check
VDCH_DATABASE_URL='postgresql+psycopg://vdch:vdch@127.0.0.1:5432/vdch' .venv/bin/alembic upgrade head
```

The Alembic command requires a reachable PostgreSQL database.

## Current Deferrals

The following remain staged production work:

- Full OIDC/JWT verification at the API boundary.
- Signed file uploads and object-storage snapshot lifecycle.
- CSV, JSONL, and file adapters.
- Redpanda/Kafka event streaming integration.
- Export workflows and role-scoped export approval.
- Biometric processing approval, retention, and audit controls.
- Full OpenTelemetry metrics and tracing integration.

## Security Principles

- Public data can still be sensitive.
- Raw records are immutable.
- Promotions and merges must be explicit, policy-checked, and audited.
- OpenClaw cannot mutate identity, merge records, export raw payloads, or bypass policy.
- Raw identifiers, HMAC tokens, raw payloads, and source secrets must not be logged or returned by default.
- AI may assist review and operations, but it is not the final identity authority.
