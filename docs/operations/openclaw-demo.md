# OpenClaw Demo Guide

This guide shows the safe local path to demonstrate VenezuelaDataCleanHub as an
OpenClaw operations use case.

## What The Demo Shows

- A synthetic source manifest is created and approved.
- A bounded ingestion job runs locally.
- Raw records are stored immutably with redacted payload snapshots.
- Deterministic duplicate candidates and review cases are created.
- OpenClaw-safe diagnostics expose counters and status, not raw payloads.

The demo does not use real personal data, AI image processing, exports, or
biometrics.

## Start The Local Stack

```bash
docker compose -f infra/docker-compose.yml up --build
```

Local service URLs:

- API docs: <http://localhost:8000/docs>
- Temporal UI: <http://localhost:8088>
- Keycloak: <http://localhost:8081>
- OPA: <http://localhost:8181>

## Seed Synthetic Data

In another terminal:

```bash
.venv/bin/python scripts/seed_openclaw_demo.py
```

By default, the script creates `openclaw-demo.sqlite` in the repository root so
it can run without a live PostgreSQL container. Set `VDCH_DATABASE_URL` to seed a
different database. The script prints synthetic resource IDs and safe counters
only.

## Safe Operations Endpoints

OpenClaw should use an agent identity and scoped operations endpoints:

- `POST /v1/ops/runbooks/start-approved-ingestion`
- `POST /v1/ops/runbooks/retry-job`
- `GET /v1/ops/jobs/{job_id}/diagnostics`
- `POST /v1/ops/reports/daily-quality-summary`

Recommended audit headers:

- `X-Request-ID`
- `X-OpenClaw-Agent-ID`
- `X-OpenClaw-Session-ID`
- `X-Invoking-User-ID`
- `X-Runbook-ID`
- `X-Approval-ID`

These headers support audit correlation. They do not grant authorization.

## Collaboration Ask

Useful OpenClaw contribution areas:

- Review the operations bridge boundaries.
- Suggest runbook metadata and approval patterns.
- Improve diagnostics and failure summaries.
- Add issue creation and notification workflows.
- Help design safe multimodal-review runbooks that keep AI assistive and
  policy-controlled.
