# Contributing

VenezuelaDataCleanHub is a security-sensitive data cleanup and deduplication
platform. Contributions should preserve the core safety model: raw records are
immutable, promotions are explicit and audited, and OpenClaw is an operational
assistant rather than an identity authority.

## Development Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/pytest -W error
```

Run the local stack:

```bash
docker compose -f infra/docker-compose.yml up --build
```

Local development uses `VDCH_AUTH_MODE=dev_headers`. Do not use that mode in
shared or production environments.

## Contribution Priorities

Good first contribution areas:

- Improve synthetic fixtures and demo scripts.
- Add tests for policy, redaction, and API contracts.
- Improve OpenClaw runbook docs and diagnostics.
- Add bounded source adapters that do not execute arbitrary code.
- Improve observability using safe counters and trace IDs only.

Security-sensitive contribution areas:

- Authentication and authorization.
- Redaction and payload handling.
- Review, promotion, export, and biometric controls.
- OpenClaw operations endpoints.

Open an issue before changing security-sensitive behavior.

## Required Checks

Before submitting changes:

```bash
ruff check .
pytest -W error
python scripts/security_checks.py
docker compose -f infra/docker-compose.yml config
git diff --check
```

For schema changes, add an Alembic migration and verify it against fresh
PostgreSQL:

```bash
VDCH_DATABASE_URL='<fresh-postgres-url>' alembic upgrade head
```

## Data Rules

- Use synthetic fixtures only.
- Do not commit real Venezuelan personal data.
- Do not commit raw identifiers, HMAC tokens, source secrets, signed URLs, or
  raw payload samples.
- Do not weaken redaction, OPA policy, or OpenClaw guardrails to make tests
  easier.

## Pull Request Expectations

Each pull request should explain:

- What changed.
- Why it changed.
- Which safety boundary it affects.
- Which tests or checks were run.
- Any remaining risk or intentional deferral.
