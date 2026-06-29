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
3. Create an ingestion job from the approved manifest.
4. Temporal or the local background runner ingests records.
5. Raw records remain immutable.
6. Person records are derived.
7. Deterministic duplicate candidates are created by blocking signals.
8. Review cases are exposed through the API.
9. OpenClaw uses scoped `/v1/ops/*` endpoints only.

`sample_json` manifests are intended for local development and tests. Real API
sources should use `http_json` with `https` URLs and explicit host allowlists.
