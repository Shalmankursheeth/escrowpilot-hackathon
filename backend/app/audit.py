"""Append-only audit log. Each entry's hash covers the previous entry, so edits are detectable."""
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import clock
from .models import AuditEvent

GENESIS = "0" * 64


def _digest(prev: str, deal_id, actor: str, action: str, detail: dict, ts: str) -> str:
    body = json.dumps(
        {"prev": prev, "deal": deal_id, "actor": actor, "action": action, "detail": detail, "ts": ts},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(body.encode()).hexdigest()


def add_audit(db: Session, deal_id: int | None, actor: str, action: str, detail: dict | None = None) -> AuditEvent:
    detail = detail or {}
    last = db.scalar(
        select(AuditEvent).where(AuditEvent.deal_id == deal_id).order_by(AuditEvent.id.desc()).limit(1)
    )
    prev = last.hash if last else GENESIS
    created = clock.now()
    ev = AuditEvent(
        deal_id=deal_id,
        actor=actor,
        action=action,
        detail=detail,
        prev_hash=prev,
        hash=_digest(prev, deal_id, actor, action, detail, created.isoformat()),
        created_at=created,
    )
    db.add(ev)
    db.flush()
    return ev


def verify_chain(db: Session, deal_id: int | None) -> bool:
    events = db.scalars(select(AuditEvent).where(AuditEvent.deal_id == deal_id).order_by(AuditEvent.id)).all()
    prev = GENESIS
    for ev in events:
        if ev.prev_hash != prev:
            return False
        if ev.hash != _digest(prev, ev.deal_id, ev.actor, ev.action, ev.detail, ev.created_at.isoformat()):
            return False
        prev = ev.hash
    return True
