from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import engine
from ..audit import add_audit
from ..db import get_db
from ..errors import BusinessError
from ..ai import AIProvider, get_ai
from ..models import AuditEvent, Deal, Evidence, Milestone, PaymentEvent, User
from ..payments import FundsHolder, get_holder
from ..schemas import ReturnCheckIn, ReviewIn
from ..security import require_roles
from .auth import user_dict
from .deals import deal_dict, milestone_dict, proof_evidence

router = APIRouter(prefix="/admin", tags=["admin"])
admin_only = require_roles("admin")


@router.get("/users")
def list_users(_a: User = Depends(admin_only), db: Session = Depends(get_db)):
    return [user_dict(u) for u in db.scalars(select(User).order_by(User.id)).all()]


@router.post("/users/{user_id}/verify")
def verify_user(user_id: int, admin: User = Depends(admin_only), db: Session = Depends(get_db)):
    """Simulated KYC: in production this is a verification provider, not a button."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    user.verified = True
    add_audit(db, None, admin.email, "user_verified", {"user": user.email})
    db.commit()
    return user_dict(user)


@router.get("/queue")
def review_queue(_a: User = Depends(admin_only), db: Session = Depends(get_db)):
    rows = db.scalars(select(Milestone).where(Milestone.state == "flagged").order_by(Milestone.id)).all()
    return [{"deal_id": m.deal_id, "deal_title": m.deal.title, "milestone": milestone_dict(m)} for m in rows]


@router.get("/ledger")
def ledger(_a: User = Depends(admin_only), db: Session = Depends(get_db)):
    """What came in, what went out, and what the platform earned. Read-only; built from the payment log."""
    events = db.scalars(select(PaymentEvent).order_by(PaymentEvent.id.desc())).all()
    total = lambda *kinds: sum(e.amount_cents for e in events if e.kind in kinds)
    stage_fees = sum(m.fee_cents or 0 for m in db.scalars(select(Milestone)).all())
    forfeits = db.scalars(select(AuditEvent).where(AuditEvent.action == "deposit_forfeited")).all()
    deposit_kept = sum(int((f.detail or {}).get("to_platform_cents", 0)) for f in forfeits)
    collected = total("capture", "deposit_capture")
    paid_out = total("payout", "deposit_return")
    refunded = total("refund")
    platform = stage_fees + deposit_kept
    deals = {d.id: d.title for d in db.scalars(select(Deal)).all()}
    ms_names = {m.id: m.name for m in db.scalars(select(Milestone)).all()}
    labels = {"deposit_order": "Seller deposit requested", "deposit_capture": "Seller deposit received",
              "order": "Stage payment requested", "capture": "Stage payment received", "payout": "Paid out",
              "refund": "Refunded to buyer", "deposit_return": "Deposit returned to seller"}
    rows = [{"id": e.id, "deal": deals.get(e.deal_id, "-"), "stage": ms_names.get(e.milestone_id),
             "label": labels.get(e.kind, e.kind), "kind": e.kind, "amount_cents": e.amount_cents,
             "status": e.status, "at": e.created_at.isoformat()} for e in events]
    fee_rows = [{"deal": deals.get(m.deal_id, "-"), "stage": m.name, "fee_cents": m.fee_cents, "state": m.state}
                for m in db.scalars(select(Milestone).where(Milestone.fee_cents > 0)).all()]
    return {
        "collected_cents": collected, "paid_out_cents": paid_out, "refunded_cents": refunded,
        "platform_cents": platform, "stage_fees_cents": stage_fees, "deposit_kept_cents": deposit_kept,
        "held_cents": collected - paid_out - refunded - platform,
        "fees": fee_rows, "events": rows,
    }


@router.post("/deals/{deal_id}/milestones/{ms_id}/review")
def review(
    deal_id: int, ms_id: int, body: ReviewIn, admin: User = Depends(admin_only),
    db: Session = Depends(get_db), holder: FundsHolder = Depends(get_holder),
):
    # Lock the deal row first: a double tap (or a retry) waits here, then sees the finished state and is refused.
    deal = db.get(Deal, deal_id, with_for_update=True)
    ms = db.get(Milestone, ms_id)
    if deal is None or ms is None or ms.deal_id != deal.id:
        raise HTTPException(status_code=404, detail="Milestone not found")
    if ms.state != "flagged":
        raise HTTPException(status_code=409, detail="Only a flagged milestone can be reviewed")
    appealed = bool(ms.appeal_by)
    if ms.ruling and ms.ruling_due_at is not None:
        raise HTTPException(status_code=409, detail="A ruling is already waiting out its cooling-off. It can be appealed once.")
    if appealed and admin.email == ms.ruling_by:
        raise HTTPException(status_code=409, detail="A different reviewer must decide the appeal")
    add_audit(db, deal.id, admin.email, "admin_review", {"milestone": ms.id, "decision": body.decision, "note": body.note})
    try:
        if body.decision in ("seller_fault", "buyer_fault") and not appealed:
            engine.propose_ruling(db, holder, deal, ms, body.decision.split("_")[0], admin.email, body.note)
        elif body.decision == "approve":
            engine.accept_or_release(db, holder, deal, ms, admin.email, f"admin approved: {body.note}")
        elif body.decision == "refund":
            engine.refund_milestone(db, holder, deal, ms, admin.email, body.note)
        else:
            engine.rule_dispute(db, holder, deal, ms, body.decision.split("_")[0], admin.email, body.note)
    except BusinessError:
        db.rollback()
        raise
    db.commit()
    return deal_dict(deal, admin)


@router.post("/deals/{deal_id}/milestones/{ms_id}/return-check")
def override_return_check(
    deal_id: int, ms_id: int, body: ReturnCheckIn, admin: User = Depends(admin_only), db: Session = Depends(get_db),
):
    """A reviewer settles a disputed return check after looking at the evidence: the goods matched, or they did not."""
    deal = db.get(Deal, deal_id)
    ms = db.get(Milestone, ms_id)
    if deal is None or ms is None or ms.deal_id != deal.id:
        raise HTTPException(status_code=404, detail="Milestone not found")
    engine.record_return_check(db, deal, ms, admin.email, body.ok, body.note.strip())
    db.commit()
    return milestone_dict(ms)


@router.get("/deals/{deal_id}/milestones/{ms_id}/brief")
def dispute_brief(
    deal_id: int, ms_id: int, _a: User = Depends(admin_only), db: Session = Depends(get_db), ai: AIProvider = Depends(get_ai),
):
    """Facts for the reviewer plus a neutral AI summary of them. The AI never recommends a ruling."""
    deal = db.get(Deal, deal_id)
    ms = db.get(Milestone, ms_id)
    if deal is None or ms is None or ms.deal_id != deal.id:
        raise HTTPException(status_code=404, detail="Milestone not found")
    docs = []
    for m in deal.milestones:
        ev = proof_evidence(db, m)
        if ev is not None and ev.extracted:
            docs.append({"stage": m.name, "type": engine.PROOF_LABELS.get(ev.extracted.get("doc_type"), "document"),
                         "number": ev.extracted.get("document_number"), "quantity": ev.extracted.get("quantity")})
    facts = engine.dispute_facts(deal, ms, docs)
    try:
        summary, provider = ai.summarize_dispute(facts), ai.name
    except Exception:  # a failed summary must never block a reviewer
        from ..ai.base import plain_dispute_summary
        summary, provider = plain_dispute_summary(facts), "offline"
    return {"summary": summary, "provider": provider, "facts": facts}


@router.post("/run-timers")
def run_timers(_a: User = Depends(admin_only), db: Session = Depends(get_db), holder: FundsHolder = Depends(get_holder)):
    return {"released": engine.run_timers(db, holder)}
