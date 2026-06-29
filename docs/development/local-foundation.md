# Local Foundation

This repository now contains the first production-shaped implementation slice.

## Run Locally

```bash
docker compose -f infra/docker-compose.yml up --build
```

The local Compose stack uses `VDCH_AUTH_MODE=dev_headers` with
`VDCH_DEV_AUTH_ENABLED=true`. This is deliberately unsafe outside localhost:
clients can self-assert `X-Actor-ID`, `X-Actor-Type`, and `X-Scopes`. Production
and shared environments should use `VDCH_AUTH_MODE=oidc` with issuer, audience,
and JWKS verification configured, must set `VDCH_ENVIRONMENT=production`, should
set `VDCH_TRUSTED_HOSTS`, and must keep dev-header auth disabled. In production,
OpenAPI docs are disabled by default unless `VDCH_API_DOCS_ENABLED=true` is set
intentionally behind an access-controlled route.

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
12. Job chunks and quarantine records preserve resumable ingestion state and
    unsafe-record review without exposing raw payloads.
13. Promotion requests capture explicit, audited data-steward approval before
    any future master-data mutation path is added.
14. OpenClaw uses scoped `/v1/ops/*` endpoints only, as an authenticated agent.
15. List endpoints use bounded pagination with `limit` and `offset`.

`sample_json` manifests are intended for local development and tests. Real API
sources should use bounded HTTPS adapters with explicit host allowlists:
`http_json`, `http_jsonl`, or `http_csv`.
Approved manifests also carry fixed `adapter_name` and `parser_name` values.
The current registry supports `sample_inline`, `http_json`, `http_jsonl`,
`http_csv`, and `person_json_v1`; manifests cannot select arbitrary executable
code.

Source approval requires a recorded `permission_basis`. Source metadata stores
trust tier, source type, allowed domains, default rate limits, review owner,
and latest job pointers.

Source registry endpoints:

- `GET /v1/sources`
- `GET /v1/sources/{source_ref}`
- `PATCH /v1/sources/{source_ref}/status`

## Review APIs

Reviewer-scoped endpoints intentionally expose derived evidence, not raw
payloads:

- `GET /v1/review-cases`
- `GET /v1/duplicate-candidates/{candidate_id}`
- `GET /v1/duplicate-clusters`
- `GET /v1/duplicate-clusters/{cluster_id}`
- `POST /v1/review-cases/{review_case_id}/assign`
- `POST /v1/review-cases/{review_case_id}/decision`

## Job Control APIs

Operator-scoped job endpoints provide status and lifecycle history:

- `GET /v1/jobs/{job_id}`
- `GET /v1/jobs/{job_id}/summary`
- `GET /v1/jobs/{job_id}/events`
- `GET /v1/jobs/{job_id}/chunks`
- `GET /v1/quarantine-records`
- `POST /v1/quarantine-records/{quarantine_record_id}/resolve`

`POST /v1/ingestion-jobs` accepts an optional `idempotency_key`. Reusing the
same key for the same actor and manifest returns the existing job instead of
creating duplicate work. Reusing the key for a different manifest is rejected.

Records that cannot be parsed are written to quarantine with a redacted payload
snapshot and reason code. Missing identity-token secrets still fail the job
instead of producing unsafe derived records.

Payload redaction is deny-by-default. Only manifest `safe_fields` plus a small
default set of non-identifying operational fields are retained; likely
identifiers, contacts, URLs, image references, notes, nested sensitive keys, and
values matching identifier patterns are redacted even when a manifest is
incomplete.

Job failure responses expose `error_code` plus a generic safe failure message.
Job event responses mask failed-event details and redact free-form runbook
reasons so exception text cannot leak raw identifiers, payloads, or source
secrets through diagnostics APIs.

OpenClaw retry runbooks create or reuse child retry jobs rather than resetting a
failed job in place. This preserves the failed job history and avoids collisions
with chunk sequence constraints created during partial failures.

## Promotion Boundary

Promotion endpoints create and decide an audited request ledger. They do not
merge identities, mutate canonical master records, export raw payloads, or expose
HMAC tokens.

- `POST /v1/promotions`
- `GET /v1/promotions`
- `POST /v1/promotions/{promotion_id}/decision`

Only completed ingestion jobs can be requested for promotion. Operators may
request promotion, and data stewards may approve or reject the pending request.

## OpenClaw Operations APIs

OpenClaw endpoints are agent-scoped and return safe counters or status only:

- `POST /v1/ops/runbooks/start-approved-ingestion`
- `POST /v1/ops/runbooks/retry-job`
- `GET /v1/ops/jobs/{job_id}/diagnostics`
- `POST /v1/ops/reports/daily-quality-summary`

Diagnostics intentionally omit raw payloads, manifest bodies, HMAC tokens,
source secrets, and free-form job error messages.

The retry runbook request body includes the failed `job_id` and a free-form
reason. The reason is not stored in audit metadata verbatim.

OpenClaw callers should provide audit context headers when available:

- `X-Request-ID`
- `X-OpenClaw-Agent-ID`
- `X-OpenClaw-Session-ID`
- `X-Invoking-User-ID`
- `X-Runbook-ID`
- `X-Approval-ID`

These values are copied into audit metadata and job event trace fields where
applicable. They are identifiers for operational audit correlation, not
authorization inputs; authorization still comes from the signed actor identity,
scopes, and OPA policy.
