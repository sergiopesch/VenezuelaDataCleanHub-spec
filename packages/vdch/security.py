from dataclasses import dataclass

import httpx
from fastapi import Header, HTTPException, Request, status

from vdch.config import Settings, get_settings


@dataclass(frozen=True)
class Actor:
    actor_id: str
    actor_type: str
    scopes: frozenset[str]


async def get_actor(
    request: Request,
    x_actor_id: str | None = Header(default=None),
    x_actor_type: str | None = Header(default=None),
    x_scopes: str | None = Header(default=None),
) -> Actor:
    settings = get_settings()
    if not settings.dev_auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is not configured for this environment.",
        )
    # Development auth boundary. Production deployments should put Keycloak/OIDC
    # verification in front of this dependency and keep the same Actor contract.
    actor = Actor(
        actor_id=x_actor_id or "local-operator",
        actor_type=x_actor_type or "user",
        scopes=frozenset(scope.strip() for scope in (x_scopes or "operator,reviewer").split(",")),
    )
    request.state.actor = actor
    return actor


async def require_scope(actor: Actor, scope: str) -> None:
    if scope not in actor.scopes and "admin" not in actor.scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required scope: {scope}",
        )


async def check_policy(
    actor: Actor,
    operation: str,
    resource: dict,
    settings: Settings | None = None,
) -> str:
    resolved_settings = settings or get_settings()
    if not resolved_settings.opa_enabled:
        if resolved_settings.allow_policy_bypass_for_local_dev:
            return "allow:local-policy-disabled"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Policy enforcement is not configured for this environment.",
        )

    payload = {
        "input": {
            "actor": {
                "id": actor.actor_id,
                "type": actor.actor_type,
                "scopes": sorted(actor.scopes),
            },
            "operation": operation,
            "resource": resource,
        }
    }
    async with httpx.AsyncClient(timeout=2.0) as client:
        response = await client.post(resolved_settings.opa_url, json=payload)
    response.raise_for_status()
    allowed = response.json().get("result", False)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="OPA denied operation")
    return "allow:opa"
