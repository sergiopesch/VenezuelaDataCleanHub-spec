# Local Foundation

This repository now contains the first production-shaped implementation slice.

## Run Locally

```bash
docker compose -f infra/docker-compose.yml up --build
```

Useful services:

- API: <http://localhost:8000/docs>
- Temporal UI: <http://localhost:8088>
- Keycloak: <http://localhost:8081>
- MinIO console: <http://localhost:9001>
- OPA: <http://localhost:8181>

## First Slice

The executable path is:

1. Create a source manifest.
2. Approve the manifest.
3. Create an ingestion job from the approved manifest. Clients may provide an
   idempotency key to safely retry job creation.
4. Temporal or the local background runner ingests records.
5. Raw records remain immutable.
6. Person records are derived.
7. Deterministic duplicate candidates are created by blocking signals.
8. Candidate evidence aggregates all matching signals found for a pair.
9. High-confidence non-conflicting candidates are grouped into duplicate clusters.
10. Review cases, candidate detail, and cluster detail are exposed through the API.
11. Job attempts and append-only job events are available for diagnostics.
12. OpenClaw uses scoped `/v1/ops/*` endpoints only.

`sample_json` manifests are intended for local development and tests. Real API
sources should use `http_json` with `https` URLs and explicit host allowlists.

## Review APIs

Reviewer-scoped endpoints intentionally expose derived evidence, not raw
payloads:

- `GET /v1/review-cases`
- `GET /v1/duplicate-candidates/{candidate_id}`
- `GET /v1/duplicate-clusters`
- `GET /v1/duplicate-clusters/{cluster_id}`
- `POST /v1/review-cases/{review_case_id}/decision`

## Job Control APIs

Operator-scoped job endpoints provide status and lifecycle history:

- `GET /v1/jobs/{job_id}`
- `GET /v1/jobs/{job_id}/summary`
- `GET /v1/jobs/{job_id}/events`

`POST /v1/ingestion-jobs` accepts an optional `idempotency_key`. Reusing the
same key for the same actor and manifest returns the existing job instead of
creating duplicate work. Reusing the key for a different manifest is rejected.
