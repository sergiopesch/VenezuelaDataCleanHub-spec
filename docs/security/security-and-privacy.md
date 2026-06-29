# Security and Privacy Model

## Data Sensitivity

The data may be public, but it is still sensitive. Records can contain names,
images, locations, status, dates, phone numbers, source identifiers, and cedula
values or masked cedula values. Public availability does not remove the need for
governance.

## Principles

- Least privilege by default.
- Immutable raw records.
- Derived normalized records.
- Explicit promotion from run output to master database.
- Human review for uncertain or conflicting matches.
- Policy approval for biometric processing.
- Audit every privileged operation.
- Separate public summaries from raw data access.

## Access Control

Use identity and policy layers:

- Keycloak for user identity and service accounts.
- Open Policy Agent for authorization decisions.
- PostgreSQL row-level security where useful.
- Short-lived signed URLs for upload/download.
- Separate credentials for mobile apps, operators, workers, and OpenClaw.

## Biometric Controls

Face recognition should require:

- Explicit source or job-level approval.
- Role permission.
- Audit event.
- Model version tracking.
- Retention policy.
- Ability to delete/recompute embeddings.
- No export of raw embeddings by default.

## Agent Controls

OpenClaw should never have raw database superuser access. It should use scoped
service accounts and restricted internal APIs.

Allowed agent actions:

- Create an ingestion job from an approved manifest.
- Check job status.
- Summarize logs.
- Draft reports.
- Open GitHub issues.
- Notify operators.

Restricted agent actions:

- Promote a run without human approval.
- Delete data.
- Export raw records.
- Enable face recognition.
- Change source policies.
- Modify role assignments.

## Audit Events

Record:

- Actor type: user, service, agent.
- Actor ID.
- Operation.
- Target resource.
- Input metadata.
- Policy decision.
- Result.
- Timestamp.
- Trace ID.

## Threats

- Unauthorized source execution.
- SSRF through arbitrary API manifests.
- Overbroad mobile data access.
- Leakage of raw payloads or images.
- Re-identification through exported reports.
- Agent prompt injection through source data.
- Silent auto-merge of wrong people.
- Biometric processing without approval.

## Mitigations

- Host allowlists and URL validation.
- Manifest review and versioning.
- No arbitrary headers/secrets in user-provided manifests.
- Queue-based jobs with idempotency.
- Role-scoped exports.
- Safe reports by default.
- Data retention policies.
- Explicit human approval for sensitive workflows.
- Prompt-injection safe agent design: source data is untrusted content.

