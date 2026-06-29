# Implementation Slice

This document defines the first production-shaped build. It is intentionally
smaller than the final architecture, but it exercises every critical boundary:
API, auth, source registry, workflow, database, matching, review, audit, and
OpenClaw operations.

## Services

```text
api-service
worker-ingestion
worker-normalize
worker-match
worker-export
worker-openclaw-ops
postgres
object-storage
temporal
redis-or-redpanda
keycloak
opa
```

## API Service

### Public/Mobile Endpoints

```http
POST /v1/submissions
GET  /v1/jobs/{job_id}
GET  /v1/jobs/{job_id}/summary
```

### Operator Endpoints

```http
POST /v1/source-manifests
GET  /v1/source-manifests
GET  /v1/source-manifests/{id}
POST /v1/ingestion-jobs
POST /v1/dedupe-jobs
GET  /v1/review-cases
POST /v1/review-cases/{id}/decision
POST /v1/promotions
POST /v1/export-jobs
```

### OpenClaw Operations Endpoints

```http
POST /v1/ops/runbooks/start-approved-ingestion
POST /v1/ops/runbooks/retry-job
GET  /v1/ops/jobs/{job_id}/diagnostics
POST /v1/ops/incidents
POST /v1/ops/reports/daily-quality-summary
```

OpenClaw endpoints should be scoped, audited, and policy-checked separately from
human operator endpoints.

## Initial PostgreSQL Tables

### `sources`

- `id`
- `slug`
- `display_name`
- `owner`
- `status`
- `created_at`
- `updated_at`

### `source_manifest_versions`

- `id`
- `source_id`
- `version`
- `manifest_json`
- `approval_status`
- `approved_by`
- `approved_at`
- `rate_limit_policy_json`
- `sensitive_fields_json`
- `created_at`

### `jobs`

- `id`
- `type`
- `status`
- `requested_by`
- `source_manifest_version_id`
- `input_object_uri`
- `progress_json`
- `error_code`
- `error_message`
- `created_at`
- `started_at`
- `completed_at`

### `raw_records`

- `id`
- `source_id`
- `source_record_id`
- `ingestion_job_id`
- `source_url`
- `payload_object_uri`
- `payload_hash`
- `payload_json_redacted`
- `created_at`

Unique key:

- `(source_id, source_record_id)`

### `person_records`

- `id`
- `raw_record_id`
- `source_id`
- `source_record_id`
- `display_name`
- `normalized_name`
- `first_name`
- `last_name`
- `cedula_display`
- `cedula_fingerprint`
- `phone_fingerprint`
- `photo_url`
- `photo_fingerprint`
- `status`
- `age`
- `location_general`
- `source_date`
- `quality_score`
- `quality_evidence_json`
- `created_at`
- `updated_at`

### `image_features`

- `id`
- `person_record_id`
- `photo_url`
- `image_sha256`
- `image_phash`
- `image_width`
- `image_height`
- `face_count`
- `face_embedding_ref`
- `face_model`
- `image_error`
- `created_at`

### `duplicate_candidates`

- `id`
- `left_person_record_id`
- `right_person_record_id`
- `confidence`
- `evidence_json`
- `review_bucket`
- `conflict_flags_json`
- `model_version`
- `created_at`

### `duplicate_clusters`

- `id`
- `cluster_key`
- `canonical_person_record_id`
- `confidence`
- `status`
- `created_at`
- `updated_at`

### `duplicate_cluster_members`

- `cluster_id`
- `person_record_id`
- `membership_confidence`

### `review_cases`

- `id`
- `duplicate_candidate_id`
- `cluster_id`
- `queue`
- `status`
- `assigned_to`
- `priority`
- `created_at`
- `closed_at`

### `review_decisions`

- `id`
- `review_case_id`
- `decision`
- `reason`
- `decided_by`
- `evidence_snapshot_json`
- `created_at`

### `audit_events`

- `id`
- `actor_type`
- `actor_id`
- `operation`
- `resource_type`
- `resource_id`
- `policy_decision`
- `metadata_json`
- `trace_id`
- `created_at`

## Workflow: Approved API Manifest Ingestion

1. Operator or OpenClaw creates job from approved manifest version.
2. API validates authorization and OPA policy.
3. Temporal workflow starts.
4. Ingestion worker chunks source by configured pagination.
5. Worker fetches with source-specific throttling and retries.
6. Raw records are stored immutably.
7. Normalization worker creates/updates person records.
8. Match worker creates duplicate candidates.
9. Cluster worker builds duplicate groups.
10. Review queue records are created.
11. Audit event and job summary are written.

## First Performance Targets

- 100k records per full run.
- No all-pairs matching.
- Chunked API fetches.
- Retry/backoff per source.
- Resume from checkpoints.
- Job status updates every phase.
- Matching result under 30 minutes on a modest CPU worker for 100k records.

## MVP Compatibility

The first implementation should import the Hugging Face MVP manifests and
matching rules so we can compare production output against known MVP output.

