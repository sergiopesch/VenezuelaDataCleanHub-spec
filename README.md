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

![VenezuelaDataCleanHub system architecture](docs/assets/system-architecture.svg)

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

![Hardened ingestion and review flow](docs/assets/hardened-ingestion-flow.svg)

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

![Safety boundaries](docs/assets/safety-boundaries.svg)

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
- Production-shaped OIDC/JWT auth boundary with local dev-header auth isolated
  to explicit local development mode.
- Production surface controls for disabling OpenAPI docs by default and enabling
  trusted-host validation.
- HMAC-SHA256 identity tokens for cédula and phone matching signals.
- Chunked ingestion jobs with progress, counters, events, child retry jobs, and
  idempotent job creation.
- Bounded HTTPS `http_json`, `http_jsonl`, and `http_csv` source adapters.
- Immutable raw record storage with deny-by-default redacted payload snapshots.
- Quarantine records and quarantine events for unsafe or unparseable inputs.
- Deterministic duplicate candidates and stable duplicate clusters.
- Reviewer workflow primitives for assignment and decision recording.
- Audited promotion request and decision boundary.
- OpenClaw operations endpoints limited to service-account agents, approved
  runbooks, safe retries, and counter-only diagnostics.
- Paginated list endpoints with bounded `limit`/`offset` contracts.
- Safe API error handling that avoids returning raw exception text.
- Local Docker Compose stack for Postgres, Temporal, MinIO, OPA, Keycloak, API, and worker.
- CI workflow for lint, tests, migration application, and whitespace checks.

## Core Documents

- [Contributing](CONTRIBUTING.md)
- [Security Policy](SECURITY.md)
- [Platform Hardening Spec](docs/platform-hardening-spec.md)
- [Platform Architecture](docs/platform-architecture.md)
- [Implementation Slice](docs/implementation-slice.md)
- [Security and Privacy Model](docs/security/security-and-privacy.md)
- [Multimodal Review Policy](docs/security/multimodal-review-policy.md)
- [OpenClaw Operations Model](docs/operations/openclaw-operations.md)
- [OpenClaw Demo Guide](docs/operations/openclaw-demo.md)
- [Outreach Brief](docs/operations/outreach-brief.md)
- [Production Hardening Runbook](docs/operations/production-hardening.md)
- [Diagram Assets](docs/assets)
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

The Compose stack intentionally sets `VDCH_AUTH_MODE=dev_headers` and
`VDCH_DEV_AUTH_ENABLED=true` for localhost testing. That mode lets clients
self-assert actor headers and is unsafe outside a developer machine. Production
deployments should set `VDCH_AUTH_MODE=oidc`, configure issuer, audience, and
JWKS URL, set `VDCH_ENVIRONMENT=production`, configure `VDCH_TRUSTED_HOSTS`,
and keep dev auth disabled.

Useful local services:

- API docs: <http://localhost:8000/docs>
- Temporal UI: <http://localhost:8088>
- Keycloak: <http://localhost:8081>
- MinIO console: <http://localhost:9001>
- OPA: <http://localhost:8181>

Seed a synthetic OpenClaw demo dataset:

```bash
.venv/bin/python scripts/seed_openclaw_demo.py
```

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

- Production Keycloak realm hardening, client provisioning, and deployment-specific
  OIDC/JWKS validation against the live IdP.
- Signed file uploads and object-storage snapshot lifecycle.
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
