# Platform Architecture

## Executive Summary

The production AcopioVE Data Hub should be a high-volume, auditable data
pipeline and deduplication service. It should accept authorized file uploads,
JSON source manifests, public API pulls, and mobile-app submissions; normalize
the data; compare records against a governed master database; produce
duplicate/quality decisions; and route uncertain cases to human review.

The Hugging Face MVP proved that the matching approach is useful. It should not
be the final production hub because long-running jobs, mobile-facing APIs,
multi-user access control, observability, governance, and high-volume ingestion
need a more durable backend.

## Goals

- Provide a central deduplication and data-cleaning service.
- Support authorized operators loading files and approved JSON API manifests.
- Support Android/iOS apps calling stable backend APIs.
- Cross-check incoming records against a persistent master database.
- Preserve source provenance and audit trails.
- Run deterministic dedupe first, then AI-assisted review second.
- Support high-volume ingestion without blocking UI requests.
- Keep biometric and image analysis explicit, staged, auditable, and revocable.
- Use open-source frameworks by default.

## Non-Goals

- Do not let agents directly mutate master records without policy and audit.
- Do not use Hugging Face Spaces as the primary production API gateway.
- Do not make LLMs the primary identity-matching authority.
- Do not auto-merge sensitive person records without review policy.
- Do not store raw secrets, API keys, or unrestricted personal data in git.

## MVP Learnings That Shape This Architecture

The Hugging Face MVP taught several important constraints:

- Full public API volume is already above 100k records.
- One full run promoted 106k+ records and produced 26k+ duplicate groups.
- Public APIs can rate-limit aggressively; the SOS API required throttling.
- A single Gradio request is not the right production boundary for long jobs.
- Persistent storage is mandatory; ephemeral compute loses master state.
- DuckDB is excellent for local analytics and batch reports, but production
  access control and multi-user writes need PostgreSQL or equivalent.
- Image URLs are common, but downloading and hashing every image is expensive.
- Perceptual hashing and face embeddings should run as staged jobs, not as a
  default part of every ingestion run.
- Human review queues are essential because high-confidence duplicates and
  uncertain matches need different operational handling.

## Recommended High-Level Architecture

```text
Android/iOS Apps, Web Operators, OpenClaw Agents, API Clients
        |
        v
API Gateway / BFF
AuthN + AuthZ + Rate Limits + Request Auditing
        |
        v
Job Orchestrator
Temporal workflows + queue-backed workers
        |
        +--> Ingestion Workers
        |    files, JSON manifests, public APIs, mobile submissions
        |
        +--> Normalization Workers
        |    schema mapping, canonical person model, validation
        |
        +--> Match Workers
        |    deterministic blocking, fuzzy text, image hash, phash, optional face
        |
        +--> Review Workers
        |    queues, reviewer assignments, decisions, merge suggestions
        |
        v
Operational Datastores
PostgreSQL + Object Storage + OpenSearch + Analytics Store
        |
        v
Downstream APIs, Export Jobs, Audit Reports, Mobile Responses
```

## Layer 1: API Gateway and Backend-for-Frontend

### Responsibilities

- Provide stable REST/OpenAPI endpoints for mobile apps and operators.
- Authenticate users, devices, service accounts, and OpenClaw-controlled agents.
- Enforce rate limits, request size limits, and upload policies.
- Issue job IDs for long-running ingestion/dedupe workflows.
- Return job status, review queues, result summaries, and export links.
- Keep mobile clients away from raw worker internals.

### Recommended Stack

- FastAPI for Python API services.
- Pydantic for request/response schemas.
- Uvicorn/Gunicorn for serving.
- NGINX, Traefik, or Envoy as edge reverse proxy.
- OpenAPI as the contract for Android/iOS clients.

### Critical Design Rule

Mobile apps should never call a Hugging Face Space directly for production
dedupe. They should call this API layer, which queues work and returns a job ID.

## Layer 2: Identity, Authorization, and Policy

### Responsibilities

- User login and service-account auth.
- Role-based and attribute-based authorization.
- Source-level permissions.
- Approval workflows for sensitive operations.
- Policy enforcement before data export, deletion, merge, or face analysis.

### Recommended Stack

- Keycloak for open-source identity and OAuth/OIDC.
- Open Policy Agent for policy-as-code decisions.
- PostgreSQL row-level security where it materially reduces blast radius.

### Roles

- `mobile_submitter`: submits app records and checks job status.
- `operator`: creates ingestion jobs and views summaries.
- `reviewer`: resolves human-review duplicate cases.
- `data_steward`: promotes runs, approves exports, manages source policies.
- `admin`: manages users, keys, and infrastructure.
- `openclaw_operator_agent`: executes approved operational runbooks only.

## Layer 3: Source Registry and Manifest System

### Responsibilities

- Store approved source manifests.
- Version every source configuration.
- Track owner, permission basis, API limits, and data fields.
- Prevent arbitrary SSRF or local-network access.
- Define pagination, retry, throttling, and field mapping.

### MVP Carryover

Keep the JSON manifest concept from the MVP, but move manifests into a governed
registry instead of treating every JSON input as trusted. Each manifest should
be reviewed and versioned before it is executable.

### Manifest Fields

- Source name and owner.
- Base URL and allowlisted host.
- HTTP method, headers, and query parameters.
- Pagination type: page, offset, cursor, none.
- Throttling policy.
- Records path.
- Field mappings to canonical model.
- Permission confirmation and review metadata.
- Sensitive-field classification.

## Layer 4: Ingestion and Durable Workflow Orchestration

### Responsibilities

- Fetch APIs under source-specific rate limits.
- Parse uploaded CSV/JSON/JSONL files.
- Split high-volume sources into chunks.
- Retry transient failures.
- Checkpoint progress.
- Produce immutable raw ingestion batches.

### Recommended Stack

- Temporal for durable workflows, retries, and long-running jobs.
- Redpanda or Kafka-compatible topics for ingestion events.
- Python workers for ingestion and normalization.
- Object storage for raw files and source response snapshots.

### Why Temporal

The MVP showed that full runs can take 20+ minutes and may fail due to remote
rate limits or output handling. A workflow engine is a better fit than a web
request because it can retry, resume, record state, and expose progress.

## Layer 5: Canonical Data Model

### Core Entities

- `source`
- `source_manifest_version`
- `ingestion_job`
- `raw_record`
- `person_record`
- `image_feature`
- `duplicate_candidate`
- `duplicate_cluster`
- `review_case`
- `review_decision`
- `export_job`
- `audit_event`

### Person Fields

- Internal record ID.
- Source ID and source record ID.
- Display name.
- Normalized name.
- First name and surname tokens.
- Cedula display value if allowed.
- Cedula fingerprint for matching.
- Phone fingerprint.
- Photo URL.
- Photo URL fingerprint.
- Image hashes when available.
- Optional face embedding reference.
- Status, age, location, source date.
- Quality score and quality evidence.
- Provenance metadata.

### Data Principle

Raw records should remain immutable. Normalized records, duplicate candidates,
clusters, and review decisions are derived layers.

## Layer 6: Master Database

### Recommended Stack

- PostgreSQL as operational source of truth.
- Native partitioning for large raw and event tables.
- GIN/trigram indexes for fuzzy name investigation.
- pgvector only if vector similarity is needed in PostgreSQL.
- Logical backups and point-in-time recovery.

### Why Not Only DuckDB

DuckDB is excellent for local batch analytics and export generation. It is not
the right primary multi-user operational database for access control, API
concurrency, and long-lived production state.

### Where DuckDB Still Fits

- Worker-local analytical matching.
- Reproducible run snapshots.
- Report generation.
- Offline investigations.
- Portable exports for auditors.

## Layer 7: Matching Engine

### First-Pass Deterministic Signals

- Same cedula fingerprint.
- Same phone fingerprint.
- Same photo URL fingerprint.
- Same downloaded image SHA-256.
- Same source-specific stable identifier.

### Fuzzy and Probabilistic Signals

- Name normalization and token similarity.
- Spanish phonetic keys.
- Surname/first-initial blocking.
- Location similarity.
- Age compatibility.
- Status compatibility.
- Date proximity.
- Perceptual image hash distance.

### Optional Biometric Signals

- Face detection count.
- Face embedding similarity.
- Face model version.

Face recognition should be a separate opt-in workflow with explicit policy
approval, audit events, and deletion controls.

### Matching Strategy

Use blocking to avoid all-pairs comparison:

- Block by cedula, phone, exact photo URL, image hash.
- Block by name key, phonetic key, surname/initial.
- Block by phash prefix when available.
- Score candidate pairs inside blocks.
- Build clusters using union-find.
- Route results by confidence and conflict flags.

## Layer 8: Image and Face Processing

### Image Pipeline

1. Pull records with photo URLs.
2. Download images with size/type limits.
3. Store original image only if policy permits.
4. Compute SHA-256 for exact duplicate images.
5. Compute perceptual hash for near-duplicate images.
6. Store dimensions, content type, error status, and hash metadata.
7. Optionally run face detection/embedding.

### Recommended Stack

- Pillow and imagehash for image validation and phash.
- OpenCV where needed for preprocessing.
- InsightFace/AuraFace or another reviewed open model for local embeddings.
- GPU workers for large face workloads.
- Object storage for image cache if image retention is permitted.

### Practical Policy

Start with URL fingerprint, SHA-256, and phash. Add face embeddings only after
the pipeline has review policy, user roles, audit logs, retention limits, and
delete/recompute procedures.

## Layer 9: Human Review

### Review Queues

- `alta_confianza`: likely duplicate, eligible for fast approval policy.
- `revision_humana`: uncertain, requires reviewer decision.
- `conflicto`: contradictory status, age, image, or source evidence.
- `biometria_pendiente`: optional queue for face-analysis decisions.

### Review Actions

- Confirm duplicate.
- Reject duplicate.
- Split cluster.
- Merge clusters.
- Mark insufficient data.
- Escalate to data steward.
- Request source correction.

### Audit Rule

Every human decision must store who, when, why, before/after state, and evidence
shown at decision time.

## Layer 10: AI Assistance and OpenAI Credits

### Good Uses

- Suggest field mappings for new source manifests.
- Explain why a record has low quality.
- Summarize duplicate evidence for human reviewers.
- Generate SQL/report drafts for operators.
- Detect suspicious ingestion anomalies.
- Classify source documentation and data dictionaries.
- Help OpenClaw operators create safe runbooks.

### Bad Uses

- Letting an LLM be the final identity-matching authority.
- Auto-merging people based only on LLM reasoning.
- Sending raw sensitive records to third-party APIs without policy.
- Letting agents freely execute arbitrary scripts against production data.

### Recommended Model Pattern

Use LLMs as decision support, not decision owners. Store prompts, model version,
input redaction policy, output, and reviewer decision when AI is involved.

## Layer 11: OpenClaw Operations Plane

OpenClaw should be used as an operational assistant/control plane, not as the
database or authoritative workflow engine.

### Good OpenClaw Responsibilities

- Trigger approved ingestion runbooks.
- Check pipeline health and summarize failures.
- Tail logs and explain incidents.
- Generate manifests from source documentation for human approval.
- Create GitHub issues for failed sources or data-quality regressions.
- Notify operators through approved channels.
- Run read-only diagnostics.
- Draft data steward reports.

### Boundaries

- OpenClaw must call signed internal APIs, not directly mutate PostgreSQL.
- OpenClaw tools need scoped service accounts.
- Dangerous actions require human approval.
- All agent actions must be logged as audit events.
- OpenClaw should not bypass RBAC, OPA policies, or workflow approvals.

## Layer 12: External and Mobile APIs

### Mobile API Patterns

- `POST /v1/submissions`: submit record or file reference.
- `POST /v1/jobs/dedupe`: create dedupe job.
- `GET /v1/jobs/{job_id}`: status and progress.
- `GET /v1/persons/{id}/dedupe-summary`: permitted summary.
- `GET /v1/review-cases`: reviewer queue.
- `POST /v1/review-cases/{id}/decision`: human decision.

### Mobile Constraints

- Do not send raw master data to mobile.
- Return minimal summaries, not entire duplicate graphs.
- Support idempotency keys.
- Rate-limit by user, device, source, and organization.
- Use short-lived upload URLs for files and images.

## Layer 13: Observability

### Required Signals

- Ingestion throughput.
- API error rate.
- Source rate-limit events.
- Retry counts.
- Job phase timing.
- Match candidate counts.
- Human review backlog.
- Image download success/error rate.
- Face processing throughput and failure rate.
- Postgres query latency.
- Queue depth.

### Recommended Stack

- OpenTelemetry instrumentation.
- Prometheus metrics.
- Grafana dashboards.
- Loki or OpenSearch for logs.
- Alertmanager for alerts.

## Layer 14: Deployment

### Recommended Initial Deployment

- Docker Compose for local development.
- Kubernetes for production once workflows and worker counts grow.
- Separate worker pools:
  - ingestion
  - normalization
  - text matching
  - image hashing
  - face embedding
  - exports
  - OpenClaw operations bridge

### Environments

- `local`: synthetic data, minimal services.
- `staging`: production-like services, no sensitive production data unless approved.
- `production`: locked-down access, backups, monitoring, incident response.

## Recommended Technology Choices

| Layer | Recommended | Why |
|---|---|---|
| API | FastAPI | Python-native, OpenAPI-first, async support |
| Workflow | Temporal | Durable long-running workflows and retries |
| Events | Redpanda or Kafka | High-volume ingestion/event stream |
| DB | PostgreSQL | Operational source of truth and governance |
| Object Storage | MinIO/S3-compatible | Files, images, reports, snapshots |
| Search | OpenSearch | Reviewer search and investigations |
| Batch Analytics | DuckDB + Polars | Fast local analytical jobs |
| Vector Store | Qdrant or pgvector | Optional embeddings |
| Identity | Keycloak | Open-source OIDC/IAM |
| Policy | Open Policy Agent | Policy-as-code |
| Observability | OpenTelemetry + Prometheus + Grafana + Loki | Standard open observability stack |
| Operations Agent | OpenClaw | Controlled operational automation |

## First Build Slice

Build the smallest production-shaped slice:

1. FastAPI service with auth stub and OpenAPI.
2. PostgreSQL schema for sources, manifests, jobs, raw records, normalized records.
3. Temporal workflow for one approved API manifest.
4. Worker that fetches source chunks with throttling and checkpoints.
5. Normalization worker.
6. Deterministic/text matching worker.
7. Review queue API.
8. Operator dashboard.
9. OpenClaw runbook that starts a job and summarizes result.

## Main Risks

- Public source APIs may change shape or rate-limit without notice.
- Sensitive person data can be mishandled if raw payload access is broad.
- Face recognition introduces biometric privacy risk.
- All-pairs duplicate matching can explode without blocking.
- Mobile clients can create abuse traffic if rate limits are weak.
- Agent operations can become dangerous if not constrained by policy.

## Recommended Decision

Proceed with a separate production platform repo. Keep Hugging Face as a demo,
model-testing, and public transparency surface. Build the production API,
workflow, and database backbone independently using open-source components.

