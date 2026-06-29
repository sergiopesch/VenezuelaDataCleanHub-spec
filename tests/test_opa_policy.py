import json
import shutil
import subprocess
from pathlib import Path

import pytest

OPA_POLICY = Path("infra/opa/policy.rego")


def opa_allows(input_payload: dict, tmp_path: Path) -> bool:
    if shutil.which("opa") is None:
        pytest.skip("opa CLI is not installed")
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(input_payload), encoding="utf-8")
    result = subprocess.run(
        [
            "opa",
            "eval",
            "--format",
            "json",
            "--data",
            str(OPA_POLICY),
            "--input",
            str(input_path),
            "data.vdch.allow",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    parsed = json.loads(result.stdout)
    return bool(parsed["result"][0]["expressions"][0]["value"])


def test_opa_policy_allows_only_users_to_approve_manifests(tmp_path):
    approved_source_resource = {
        "exists": True,
        "source_status": "active",
        "operation_risk": "high",
    }
    user_input = {
        "actor": {"type": "user", "scopes": ["data_steward"]},
        "operation": "source_manifest.approve",
        "resource": approved_source_resource,
    }
    agent_input = {
        "actor": {
            "type": "agent",
            "scopes": ["data_steward", "openclaw:runbook", "openclaw_operator_agent"],
        },
        "operation": "source_manifest.approve",
        "resource": approved_source_resource,
    }

    assert opa_allows(user_input, tmp_path) is True
    assert opa_allows(agent_input, tmp_path) is False


def test_opa_policy_requires_active_approved_source_for_openclaw_start(tmp_path):
    actor = {
        "type": "agent",
        "scopes": ["openclaw:runbook", "openclaw_operator_agent"],
    }
    active_input = {
        "actor": actor,
        "operation": "ops.runbook.start_approved_ingestion",
        "resource": {"approval_status": "approved", "source_status": "active"},
    }
    disabled_input = {
        "actor": actor,
        "operation": "ops.runbook.start_approved_ingestion",
        "resource": {"approval_status": "approved", "source_status": "disabled"},
    }

    assert opa_allows(active_input, tmp_path) is True
    assert opa_allows(disabled_input, tmp_path) is False


def test_opa_policy_denies_openclaw_without_operator_agent_scope(tmp_path):
    input_payload = {
        "actor": {"type": "agent", "scopes": ["openclaw:diagnostics"]},
        "operation": "ops.job.diagnostics",
        "resource": {"operation_risk": "low"},
    }

    assert opa_allows(input_payload, tmp_path) is False
