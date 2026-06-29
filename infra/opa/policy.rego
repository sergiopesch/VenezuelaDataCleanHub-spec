package vdch

default allow := false

allow if {
  input.actor.type == "user"
  input.operation == "source_manifest.create"
  "operator" in input.actor.scopes
}

allow if {
  input.actor.type == "user"
  input.operation == "source_manifest.approve"
  "data_steward" in input.actor.scopes
}

allow if {
  input.actor.type == "user"
  input.operation == "job.create.approved_manifest_ingestion"
  "operator" in input.actor.scopes
}

allow if {
  input.actor.type == "user"
  input.operation == "review_case.decide"
  "reviewer" in input.actor.scopes
}

allow if {
  input.actor.type == "agent"
  input.operation in {
    "ops.runbook.start_approved_ingestion",
    "ops.runbook.retry_job",
  }
  "openclaw:runbook" in input.actor.scopes
}

allow if {
  input.actor.type == "agent"
  input.operation == "ops.job.diagnostics"
  "openclaw:diagnostics" in input.actor.scopes
}
