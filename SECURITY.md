# Security Policy

This project handles workflows that may involve sensitive humanitarian-style
data. Public data can still be sensitive.

## Reporting Security Issues

Please do not open public issues for vulnerabilities involving:

- Authentication or authorization bypass.
- Raw payload, identifier, HMAC token, signed URL, or source-secret exposure.
- OpenClaw privilege escalation.
- Unsafe source adapter behavior.
- Biometric or export-control bypass.

Use GitHub private vulnerability reporting if enabled for the repository, or
contact the repository owner privately.

## Security Model

Core invariants:

- Raw records are immutable.
- Identifier fingerprints are HMAC-backed and secret-dependent.
- Payload snapshots are deny-by-default redacted.
- Source manifests require approval before execution.
- Promotions require explicit audited user action.
- OpenClaw may call approved operations endpoints only.
- OpenClaw cannot approve sources, mutate source policy, merge identities,
  promote records, export raw payloads, or control biometrics.
- AI can assist review and operations, but cannot be the final identity
  authority.

## Supported Baseline

The current supported baseline is the `main` branch. Security-sensitive changes
should include tests and, where schema changes are involved, Alembic migrations.

## Local Security Checks

```bash
ruff check .
pytest -W error
python scripts/security_checks.py
docker compose -f infra/docker-compose.yml config
git diff --check
```

OPA policy checks are run in CI through the pinned OPA Docker image. If the OPA
CLI is installed locally, `tests/test_opa_policy.py` will also execute policy
regression tests directly.
