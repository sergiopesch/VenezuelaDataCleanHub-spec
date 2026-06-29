# Platform Hardening Spec

This document defines the production-hardening direction for
VenezuelaDataCleanHub. It is the implementation source of truth for turning the
current foundation into a governed data cleanup, deduplication, review, and
operations platform.

The platform must remain separate from prototype/demo environments. Scrapers,
mobile apps, public API pulls, and operational agents integrate through explicit
backend contracts rather than bypassing this service.

## Executive Summary

The foundation already has the right shape:

- FastAPI service boundary.
- PostgreSQL operational source of truth.
- Approved source manifest registry.
- Durable job boundary with Temporal support.
- Immutable raw records and derived person records.
- Duplicate candidates, clusters, review cases, decisions, and audit events.
- Scoped OpenClaw operations endpoints.

Hardening should now focus on governed source execution, safe identity tokens,
reviewable ingestion failures, chunked jobs, stable derived data, review
workflow primitives, strict operations guardrails, and repeatable verification.

## Non-Negotiable Principles

- Raw records are immutable.
- Derived records are reproducible from raw records, source manifests, adapter
  versions, parser versions, and normalizer versions.
- Promotions and merges are explicit, policy-checked, and audited.
- Sensitive identifiers use keyed HMAC tokens, not plain hashes.
- Unknown or unsafe records go to quarantine, not silent discard.
- Every privileged action writes an audit event.
- Every long-running action is represented as a job with events and status.
- OpenClaw can operate only through explicit, policy-checked runbooks.
- OpenClaw cannot mutate identity, merge records, export raw payloads, or change
  source policy.
- Tests use synthetic data only.

## Priority 1: Identity Token Hardening

Plain SHA-256 over cédula or phone digits is insufficient because those values
have small search spaces. Store deterministic HMAC-SHA256 tokens with a secret
key instead.

```text
identity_token = HMAC-SHA256(identity_secret, normalized_identifier)
```

Identifier normalization must:

- Trim whitespace.
- Lowercase alphabetic prefixes.
- Remove punctuation and spaces.
- Preserve meaningful identity prefixes such as `v` and `e`.
- Reject empty normalized identifiers.

Examples:

```text
V-12.345.678 -> v12345678
E-12.345.678 -> e12345678
0412 555 0000 -> 04125550000
```

Acceptance criteria:

- Equivalent prefixed cédula formats produce the same token.
- `V` and `E` identifiers do not collapse.
- No plain SHA-256 identity fingerprint code remains for cédula or phone.
- Tests assert secret requirement, token shape, and token version.
- Raw cédula display is not stored by default.

## Priority 2: Governed Source Registry

Sources must carry governance metadata before execution:

- `status`
- `trust_tier`
- `source_type`
- `permission_basis`
- `allowed_domains_json`
- `default_rate_limit_json`
- `reviewed_by`
- `reviewed_at`
- latest successful and failed job pointers

Manifest versions must record:

- `parser_name`
- `parser_version`
- `adapter_name`
- `adapter_config_json`
- `field_mappings_json`
- `approval_status`
- `approved_by`
- `approved_at`
- `required_keywords_json`
- `sample_payload_redacted_json`
- `sensitive_fields_json`
- `review_notes`

Approval rules:

- Creating a manifest never executes it.
- Approval requires `data_steward`.
- Execution requires an approved manifest version.
- Source must be active.
- Source permission basis must be recorded.
- URL hosts must match both manifest host controls and source allowed domains.
- Parser and adapter names must be registered.

## Priority 3: Adapter and Parser Boundary

Manifest execution must use approved adapters and parsers. Manifests must not
select arbitrary executable code, dynamic imports, shell commands, or unreviewed
network clients.

Initial approved boundary:

```text
SourceManifestVersion
  -> Adapter.fetch_chunks()
  -> Parser.parse()
  -> RawRecord batch
  -> PersonRecord batch
  -> Matcher
  -> Cluster updater
  -> Review queue
```

Current approved adapters:

- `sample_inline`
- `http_json`

Current approved parser:

- `person_json_v1`

## Priority 4: Quarantine

Records that cannot be safely processed must be written to quarantine with:

- job and chunk reference
- source reference when available
- source record id when available
- reason code and message
- payload hash
- redacted payload snapshot only
- status and events

Quarantine APIs must not expose raw payloads, identity tokens, or sensitive
fields. Operators may list and resolve quarantine records with audit events.

## Priority 5: Chunked Ingestion

Jobs must track chunk-level progress and failures:

- chunk sequence
- status
- source URI or checkpoint
- records seen
- raw records created
- person records created
- quarantine records created
- error code/message

Chunk tracking is the foundation for durable resume, retry, and high-volume
pipeline operations.

## Priority 6: Stable Duplicate Clusters

Duplicate clusters are derived state, but cluster rows should be stable. Rebuilds
must not destructively delete and recreate all clusters when a stable
`cluster_key` can preserve identity. Stale derived clusters should be marked
instead of silently disappearing.

## Priority 7: Reviewer Workflow

Review queues need explicit workflow primitives:

- list open and closed cases
- assign a case
- decide a case
- snapshot evidence at decision time
- audit assignment and decision actions

Reviewer APIs expose derived evidence only, not raw payloads.

## Priority 8: OpenClaw Operations Guardrails

OpenClaw should call only scoped operations endpoints. It may:

- start ingestion from approved manifests
- retry failed jobs
- read safe diagnostics
- read safe summaries

OpenClaw must not:

- approve manifests
- change source policy
- merge records
- resolve identity
- export raw records
- read raw payloads
- enable biometric processing

## Priority 9: API Contracts And Error Boundaries

APIs should use explicit Pydantic contracts, stable response models, bounded
query parameters, and safe error messages. Raw payloads, HMAC tokens, source
secrets, and sensitive fields must not be returned by default.

## Priority 10: CI, Security, And Data Safety

The repository should provide repeatable checks for:

- lint
- tests
- migration application
- whitespace/diff safety
- synthetic-data-only fixtures

## Priority 11: Observability

Jobs, chunks, quarantine records, and operations runbooks should expose safe
status, counters, and diagnostic events. Metrics and logs must never include raw
identifiers, HMAC tokens, raw payloads, or source secrets.

## Deferred Production Layers

The following remain staged production work unless explicitly implemented:

- deployment-specific Keycloak realm hardening and OIDC/JWKS configuration
- signed file uploads and object-storage snapshots
- CSV/JSONL/file adapters
- Redpanda/Kafka event streaming
- promotion/export workflows
- biometric processing approval and retention controls
- full OpenTelemetry metrics/tracing integration
