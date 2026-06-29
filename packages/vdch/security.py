from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import httpx
import jwt
from fastapi import Header, HTTPException, Request, status
from jwt import PyJWKClient

from vdch.config import Settings, get_settings


@dataclass(frozen=True)
class Actor:
    actor_id: str
    actor_type: str
    scopes: frozenset[str]
    auth_method: str = "unknown"
    claims: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RequestContext:
    request_id: str | None = None
    openclaw_agent_id: str | None = None
    openclaw_session_id: str | None = None
    invoking_user_id: str | None = None
    runbook_id: str | None = None
    approval_id: str | None = None

    def audit_metadata(self) -> dict[str, str]:
        return {
            key: value
            for key, value in {
                "request_id": self.request_id,
                "openclaw_agent_id": self.openclaw_agent_id,
                "openclaw_session_id": self.openclaw_session_id,
                "invoking_user_id": self.invoking_user_id,
                "runbook_id": self.runbook_id,
                "approval_id": self.approval_id,
            }.items()
            if value
        }


async def get_actor(
    request: Request,
    authorization: str | None = Header(default=None),
    x_actor_id: str | None = Header(default=None),
    x_actor_type: str | None = Header(default=None),
    x_scopes: str | None = Header(default=None),
) -> Actor:
    settings = get_settings()
    if settings.auth_mode == "dev_headers":
        actor = _dev_header_actor(settings, x_actor_id, x_actor_type, x_scopes)
        request.state.actor = actor
        return actor
    if settings.auth_mode == "oidc":
        actor = _oidc_actor(settings, authorization)
        request.state.actor = actor
        return actor
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Unsupported authentication mode.",
    )


def _dev_header_actor(
    settings: Settings,
    x_actor_id: str | None,
    x_actor_type: str | None,
    x_scopes: str | None,
) -> Actor:
    if not settings.dev_auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is not configured for this environment.",
        )
    actor_type = x_actor_type or "user"
    if actor_type not in {"user", "agent", "service"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid actor type.")
    return Actor(
        actor_id=x_actor_id or "local-operator",
        actor_type=actor_type,
        scopes=_split_scopes(x_scopes or "operator,reviewer"),
        auth_method="dev_headers",
    )


def _oidc_actor(settings: Settings, authorization: str | None) -> Actor:
    token = _bearer_token(authorization)
    claims = _decode_oidc_token(settings, token)
    scopes = _claims_scopes(claims)
    actor_type = _actor_type_from_claims(claims, scopes)
    actor_id = str(
        claims.get("preferred_username")
        or claims.get("client_id")
        or claims.get("azp")
        or claims.get("sub")
        or ""
    )
    if not actor_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject.",
        )
    return Actor(
        actor_id=actor_id,
        actor_type=actor_type,
        scopes=frozenset(scopes),
        auth_method="oidc",
        claims=dict(claims),
    )


def _bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token.",
        )
    return token


def _decode_oidc_token(settings: Settings, token: str) -> dict[str, Any]:
    if not settings.oidc_issuer or not settings.oidc_audience:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC authentication is not configured.",
        )
    try:
        algorithms = settings.approved_oidc_algorithms
        if settings.oidc_hs256_secret:
            if (
                "HS256" not in algorithms
                or not settings.allow_insecure_oidc_hs256_for_local_dev
            ):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Insecure local OIDC verification is disabled.",
                )
            return jwt.decode(
                token,
                settings.oidc_hs256_secret,
                algorithms=["HS256"],
                audience=settings.oidc_audience,
                issuer=settings.oidc_issuer,
            )
        if not settings.oidc_jwks_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="OIDC JWKS URL is not configured.",
            )
        signing_key = PyJWKClient(settings.oidc_jwks_url).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=algorithms,
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
        )
    except HTTPException:
        raise
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token.",
        ) from exc


def _split_scopes(scopes: str) -> frozenset[str]:
    return frozenset(scope.strip() for scope in scopes.replace(",", " ").split() if scope.strip())


def _claims_scopes(claims: dict[str, Any]) -> set[str]:
    scopes = set(_split_scopes(str(claims.get("scope") or "")))
    realm_roles = claims.get("realm_access", {}).get("roles", [])
    if isinstance(realm_roles, list):
        scopes.update(str(role) for role in realm_roles)
    resource_access = claims.get("resource_access", {})
    if isinstance(resource_access, dict):
        for resource in resource_access.values():
            roles = resource.get("roles", []) if isinstance(resource, dict) else []
            if isinstance(roles, list):
                scopes.update(str(role) for role in roles)
    return {scope for scope in scopes if scope}


def _actor_type_from_claims(claims: dict[str, Any], scopes: set[str]) -> str:
    claimed_type = claims.get("vdch_actor_type")
    if claimed_type in {"user", "agent", "service"}:
        return str(claimed_type)
    client_id = str(claims.get("client_id") or claims.get("azp") or "")
    if "openclaw_operator_agent" in scopes or client_id.startswith("openclaw"):
        return "agent"
    return "user"


async def require_scope(actor: Actor, scope: str) -> None:
    if scope not in actor.scopes and "admin" not in actor.scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required scope: {scope}",
        )


async def require_actor_type(actor: Actor, actor_type: str) -> None:
    if actor.actor_type != actor_type:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Actor type must be {actor_type}.",
        )


def get_request_context(request: Request) -> RequestContext:
    request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID")
    if not request_id:
        request_id = str(uuid4())
        request.state.request_id = request_id
    return RequestContext(
        request_id=request_id,
        openclaw_agent_id=request.headers.get("X-OpenClaw-Agent-ID"),
        openclaw_session_id=request.headers.get("X-OpenClaw-Session-ID"),
        invoking_user_id=request.headers.get("X-Invoking-User-ID"),
        runbook_id=request.headers.get("X-Runbook-ID"),
        approval_id=request.headers.get("X-Approval-ID"),
    )


async def check_policy(
    actor: Actor,
    operation: str,
    resource: dict,
    settings: Settings | None = None,
    context: RequestContext | None = None,
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
                "auth_method": actor.auth_method,
            },
            "operation": operation,
            "resource": resource,
            "context": (context or RequestContext()).audit_metadata(),
        }
    }
    async with httpx.AsyncClient(timeout=2.0) as client:
        response = await client.post(resolved_settings.opa_url, json=payload)
    response.raise_for_status()
    allowed = response.json().get("result", False)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="OPA denied operation")
    return "allow:opa"
