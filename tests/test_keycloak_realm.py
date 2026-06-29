import json
from pathlib import Path

REALM_PATH = Path("infra/keycloak/vdch-local-realm.json")


def test_keycloak_realm_defines_openclaw_service_account_without_static_secret():
    realm = json.loads(REALM_PATH.read_text(encoding="utf-8"))
    clients = {client["clientId"]: client for client in realm["clients"]}
    openclaw_client = clients["vdch-openclaw-agent"]

    assert openclaw_client["publicClient"] is False
    assert openclaw_client["serviceAccountsEnabled"] is True
    assert openclaw_client["standardFlowEnabled"] is False
    assert openclaw_client["directAccessGrantsEnabled"] is False
    assert "secret" not in openclaw_client


def test_keycloak_realm_maps_openclaw_service_account_to_agent_role():
    realm = json.loads(REALM_PATH.read_text(encoding="utf-8"))
    service_accounts = {
        user["serviceAccountClientId"]: user
        for user in realm.get("users", [])
        if "serviceAccountClientId" in user
    }

    assert "openclaw_operator_agent" in {
        role["name"] for role in realm["roles"]["realm"]
    }
    assert service_accounts["vdch-openclaw-agent"]["realmRoles"] == [
        "openclaw_operator_agent"
    ]
