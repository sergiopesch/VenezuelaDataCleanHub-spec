---
name: OpenClaw integration
about: Propose or refine an OpenClaw runbook, diagnostic, or operations bridge change
title: "[OpenClaw] "
labels: ["openclaw", "operations"]
assignees: ""
---

## Goal

What operational problem should OpenClaw help with?

## Proposed Runbook Or Endpoint

Which approved runbook or `/v1/ops/*` endpoint is involved?

## Safety Boundary

Confirm what OpenClaw must not do:

- [ ] no raw payload reads
- [ ] no source approval or policy mutation
- [ ] no identity merge or promotion
- [ ] no export execution
- [ ] no biometric control mutation

## Required Audit Context

List required headers or metadata:

- `X-Request-ID`
- `X-OpenClaw-Agent-ID`
- `X-OpenClaw-Session-ID`
- `X-Invoking-User-ID`
- `X-Runbook-ID`
- `X-Approval-ID`

## Tests

What allow and deny cases should be covered?
