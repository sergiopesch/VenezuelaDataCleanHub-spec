package vdch

import future.keywords.if
import future.keywords.in

default allow := false

allow if {
  input.actor.type == "user"
  input.operation == "source_manifest.create"
  "operator" in input.actor.scopes
  input.resource.operation_risk == "medium"
}

allow if {
  input.actor.type == "user"
  input.operation == "source_manifest.approve"
  "data_steward" in input.actor.scopes
  input.resource.source_status == "active"
  input.resource.exists == true
}

allow if {
  input.actor.type == "user"
  input.operation == "source.update_status"
  "data_steward" in input.actor.scopes
  input.resource.exists == true
}

allow if {
  input.actor.type == "user"
  input.operation == "job.create.approved_manifest_ingestion"
  "operator" in input.actor.scopes
  input.resource.approval_status == "approved"
  input.resource.source_status == "active"
}

allow if {
  input.actor.type == "user"
  input.operation == "quarantine.resolve"
  "operator" in input.actor.scopes
  input.resource.operation_risk == "medium"
}

allow if {
  input.actor.type == "user"
  input.operation == "review_case.decide"
  "reviewer" in input.actor.scopes
  input.resource.operation_risk == "high"
}

allow if {
  input.actor.type == "user"
  input.operation == "review_case.assign"
  "reviewer" in input.actor.scopes
  input.resource.operation_risk == "medium"
}

allow if {
  input.actor.type == "user"
  input.operation == "promotion.request"
  "operator" in input.actor.scopes
  input.resource.operation_risk == "high"
}

allow if {
  input.actor.type == "user"
  input.operation == "promotion.decide"
  "data_steward" in input.actor.scopes
  input.resource.operation_risk == "high"
}

allow if {
  input.actor.type == "agent"
  input.operation in {
    "ops.runbook.start_approved_ingestion",
  }
  "openclaw:runbook" in input.actor.scopes
  "openclaw_operator_agent" in input.actor.scopes
  input.resource.approval_status == "approved"
  input.resource.source_status == "active"
}

allow if {
  input.actor.type == "agent"
  input.operation == "ops.runbook.retry_job"
  "openclaw:runbook" in input.actor.scopes
  "openclaw_operator_agent" in input.actor.scopes
  input.resource.operation_risk == "medium"
}

allow if {
  input.actor.type == "agent"
  input.operation == "ops.job.diagnostics"
  "openclaw:diagnostics" in input.actor.scopes
  "openclaw_operator_agent" in input.actor.scopes
}

allow if {
  input.actor.type == "agent"
  input.operation == "ops.report.daily_quality_summary"
  "openclaw:diagnostics" in input.actor.scopes
  "openclaw_operator_agent" in input.actor.scopes
}
