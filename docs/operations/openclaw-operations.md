# OpenClaw Operations Model

## Recommended Role

OpenClaw should be the operational assistant for the Data Hub, not the source of
truth and not the final decision-maker.

Use it to coordinate runbooks, summarize failures, produce operator briefings,
and help authorized humans move faster.

## Why OpenClaw Fits

OpenClaw already has useful operating characteristics for this role:

- Local-first gateway and tools.
- Agent sessions and workspace model.
- Multi-channel notifications.
- Logs and diagnostics.
- Credentials and auth-profile concepts.
- Pairing and allowlist concepts for channels.
- Ability to run controlled commands and workflows.

## Recommended Integration Pattern

```text
OpenClaw Agent
    |
    v
Operations Bridge API
    |
    +--> Job API
    +--> Source Registry API
    +--> Observability API
    +--> GitHub Issues API
    +--> Notification API
```

OpenClaw should call the Operations Bridge. The bridge enforces identity,
policy, scopes, and audit logging.

## Runbooks

Initial runbooks:

- Start approved source ingestion.
- Retry failed job.
- Summarize job failure.
- Compare latest run to previous run.
- Report source schema drift.
- Generate daily data-quality summary.
- Create GitHub issue for failed source.
- Notify reviewers when backlog crosses threshold.
- Request human approval for promotion.

## Approval Levels

- Read-only diagnostics: agent can run directly.
- Low-risk job creation: agent can run if manifest is approved.
- Promotion/export: human approval required.
- Deletion, source policy changes, face recognition: data steward approval required.

## Logging and Audit

Every OpenClaw action should include:

- OpenClaw agent ID.
- Session ID.
- User who requested action.
- Tool/runbook invoked.
- API endpoint called.
- Result.
- Trace ID.

## OpenAI Credits

Use OpenAI credits through OpenClaw for operational reasoning:

- Interpret failure logs.
- Draft incident summaries.
- Generate manifest candidates.
- Explain match evidence to reviewers.
- Draft runbooks and documentation changes.

Do not use OpenAI calls for unredacted raw sensitive data unless the governance
policy explicitly allows it.

