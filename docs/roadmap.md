# Roadmap

## Phase 0: Specification

- Complete architecture spec.
- Agree on repository visibility.
- Confirm governance model.
- Confirm first production deployment target.

## Phase 1: Production-Shaped Skeleton

- FastAPI service.
- PostgreSQL schema.
- Keycloak/OIDC integration.
- Temporal workflow skeleton.
- Source registry CRUD.
- One API-manifest ingestion workflow.
- Job status API.
- Audit event table.

## Phase 2: Dedupe Core

- Canonical person normalization.
- Deterministic and fuzzy matching.
- Duplicate candidate storage.
- Cluster building.
- Review queue API.
- Basic operator dashboard.

## Phase 3: Files and Mobile

- Signed upload flow.
- CSV/JSON/JSONL ingestion.
- Android/iOS API contracts.
- Idempotency keys.
- Rate limits.

## Phase 4: Image Layer

- Photo URL fingerprinting.
- Image download worker.
- SHA-256 exact image hash.
- Perceptual hash.
- Image error dashboards.

## Phase 5: Biometric Layer

- Explicit policy controls.
- GPU worker pool.
- Face detection and embeddings.
- Model versioning.
- Retention/deletion controls.

## Phase 6: OpenClaw Operations

- Operations Bridge API.
- Approved runbooks.
- Job summaries.
- Failure triage.
- GitHub issue integration.
- Notifications.

## Phase 7: Scale and Governance

- Partitioning and archival.
- Load testing.
- Backups and restore drills.
- Data retention automation.
- Security review.
- Incident response runbooks.

