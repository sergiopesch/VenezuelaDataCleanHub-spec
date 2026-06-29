from sqlalchemy.orm import Session

from vdch.models import AuditEvent
from vdch.security import Actor


def write_audit_event(
    session: Session,
    *,
    actor: Actor,
    operation: str,
    resource_type: str,
    resource_id: str | None,
    policy_decision: str,
    metadata: dict | None = None,
    trace_id: str | None = None,
) -> AuditEvent:
    resolved_metadata = metadata or {}
    event = AuditEvent(
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        operation=operation,
        resource_type=resource_type,
        resource_id=resource_id,
        policy_decision=policy_decision,
        metadata_json=resolved_metadata,
        trace_id=trace_id or resolved_metadata.get("request_id"),
    )
    session.add(event)
    return event
