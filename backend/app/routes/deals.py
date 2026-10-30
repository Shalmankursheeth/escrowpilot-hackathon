from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import clock, engine
from ..ai import AIError, AIProvider, ContractTerms, get_ai
from ..ai.base import MilestoneTerm, to_cents
from ..audit import add_audit, verify_chain
from ..config import get_settings
from ..db import get_db
from ..errors import BusinessError
from ..files import read_document
from ..notify import notify, notify_deal
from ..models import AuditEvent, Deal, Evidence, Milestone, PaymentEvent, User
from ..payments import FundsHolder, HolderError, get_holder
from ..trust import trust_profile
from ..schemas import AppealIn, ConfirmIn, DealCreateIn, DisputeIn, ProofIn, ReturnCheckIn, TermsIn
from .connections import are_connected, find_user
from ..security import current_user, require_roles, require_verified

router = APIRouter(prefix="/deals", tags=["deals"])


def milestone_dict(ms: Milestone) -> dict:
    return {
        "id": ms.id, "seq": ms.seq, "name": ms.name, "share_pct": ms.share_pct,
        "amount_cents": ms.amount_cents, "required_proof": ms.required_proof, "state": ms.state,
        "release_after": ms.release_after.isoformat() if ms.release_after else None,
        "funded": ms.funded, "verdict": ms.verdict, "return_proof_ok": ms.return_proof_ok,
        "return_received": ms.return_received, "return_received_note": ms.return_received_note,
        "return_check_due_at": ms.return_check_due_at.isoformat() if ms.return_check_due_at else None, "fee_cents": ms.fee_cents, "paid_cents": ms.paid_cents,
        "ruling": ms.ruling, "ruling_note": ms.ruling_note, "appealed": bool(ms.appeal_by), "appeal_reason": ms.appeal_reason,
        "ruling_due_at": ms.ruling_due_at.isoformat() if ms.ruling_due_at else None,
    }


def _strikes(user: User) -> int:
    """How many of this trader's past deals ended with a fault ruling against them (counts only, no score)."""
    from sqlalchemy.orm import object_session
    db = object_session(user)
    return trust_profile(db, user)["strikes"] if db is not None else 0


def deal_dict(deal: Deal, user: User) -> dict:
    d = {
        "id": deal.id, "title": deal.title, "state": deal.state, "currency": deal.currency,
        "total_cents": deal.total_cents, "goods": deal.goods, "quantity": deal.quantity,
        "seller": deal.seller_name, "buyer": deal.buyer_name, "inspection_days": deal.inspection_days,
        "terms_version": deal.terms_version, "funding_mode": deal.funding_mode, "release_rule": deal.release_rule, "failure_scope": deal.failure_scope,
        "funding_deadline_days": deal.funding_deadline_days, "default_penalty_pct": deal.default_penalty_pct,
        "fund_due_at": deal.fund_due_at.isoformat() if deal.fund_due_at else None,
        "returns": {"refund_pct": deal.return_refund_pct, "shipping_by": deal.return_shipping_by,
                    "proof_required": deal.return_proof_required, "check_days": deal.return_check_days},
        "deposit": {"pct": deal.seller_deposit_pct, "cents": engine.deposit_cents(deal), "state": deal.deposit_state},
        "fault": deal.fault, "fee_bps": get_settings().fee_bps,
        "buyer_strikes": _strikes(deal.buyer), "seller_strikes": _strikes(deal.seller),
        "buyer_id": deal.buyer.public_id, "seller_id": deal.seller.public_id,
        "buyer_confirmed": deal.buyer_confirmed, "seller_confirmed": deal.seller_confirmed,
        "funded_at": deal.funded_at.isoformat() if deal.funded_at else None,
        "my_role": "admin" if user.role == "admin" else ("buyer" if user.id == deal.buyer_id else "seller"),
        "milestones": [milestone_dict(m) for m in deal.milestones],
    }
    if user.role in ("buyer", "admin"):  # the seller never sees the buyer's payment reference
        d["paypal_order_id"] = deal.paypal_order_id
    return d


def get_deal(db: Session, deal_id: int, user: User) -> Deal:
    deal = db.get(Deal, deal_id)
    if deal is None or (user.role != "admin" and user.id not in (deal.buyer_id, deal.seller_id)):
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal


def get_milestone(deal: Deal, ms_id: int) -> Milestone:
    ms = next((m for m in deal.milestones if m.id == ms_id), None)
    if ms is None:
        raise HTTPException(status_code=404, detail="Milestone not found")
    return ms


def _fill(deal: Deal, terms: ContractTerms, amounts: list[int]) -> None:
    deal.currency, deal.total_cents, deal.goods, deal.quantity = terms.currency, terms.total_cents, terms.goods, terms.quantity
    deal.seller_name, deal.buyer_name = terms.seller_name, terms.buyer_name
    deal.milestones.clear()
    for i, (m, amt) in enumerate(zip(terms.milestones, amounts), start=1):
        deal.milestones.append(Milestone(seq=i, name=m.name, share_pct=m.share_pct, amount_cents=amt,
                                         required_proof=m.required_proof))


def apply_terms(deal: Deal, t: TermsIn) -> None:
    """Write a full set of proposed terms onto a draft deal. Every change voids earlier signatures."""
    terms = ContractTerms(
        seller_name=deal.seller_name, buyer_name=deal.buyer_name, goods=t.goods, quantity=t.quantity,
        total_cents=to_cents(t.total_amount), currency=t.currency.upper(), inspection_days=t.inspection_days,
        milestones=[MilestoneTerm(name=m.name, share_pct=m.share_pct, required_proof=m.required_proof) for m in t.milestones],
    )
    _fill(deal, terms, engine.validate_terms(terms))
    deal.inspection_days = t.inspection_days
    deal.return_refund_pct, deal.return_shipping_by = t.return_refund_pct, t.return_shipping_by
    deal.return_proof_required = t.return_proof_required
    deal.return_check_days = t.return_check_days
    deal.funding_mode = t.funding_mode
    deal.release_rule = t.release_rule
    deal.failure_scope, deal.funding_deadline_days, deal.default_penalty_pct = t.failure_scope, t.funding_deadline_days, t.default_penalty_pct
    deal.seller_deposit_pct = t.seller_deposit_pct
    if deal.id is not None:
        deal.terms_version += 1
    deal.buyer_confirmed = deal.seller_confirmed = False


@router.post("", status_code=201)
def create_deal(
    body: DealCreateIn,
    user: User = Depends(require_roles("buyer", "seller")),
    _v: User = Depends(require_verified),
    db: Session = Depends(get_db),
    ai: AIProvider = Depends(get_ai),
):
    s = get_settings()
    other = find_user(db, body.counterparty_id)
    want = "buyer" if user.role == "seller" else "seller"
    if other is None or other.role != want or other.id == user.id:
        raise HTTPException(status_code=404, detail=f"No {want} found with that id")
    if not are_connected(db, user.id, other.id):
        raise HTTPException(status_code=403, detail="Connect with this trader first (they must accept your request)")
    buyer, seller = (user, other) if user.role == "buyer" else (other, user)
    deal = Deal(title=body.title, buyer_id=buyer.id, seller_id=seller.id, currency="USD", total_cents=0,
                buyer_name=buyer.company_name, seller_name=seller.company_name, contract_text="")
    deal.buyer, deal.seller = buyer, seller
    ai_name = "manual"
    if body.terms is not None:
        apply_terms(deal, body.terms)
    elif body.contract_text:
        if len(body.contract_text.encode()) > s.max_text_bytes:
            raise HTTPException(status_code=413, detail="Contract text is too large")
        try:
            terms = ai.parse_contract(body.contract_text)
        except AIError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        amounts = engine.validate_terms(terms)
        _fill(deal, terms, amounts)
        deal.contract_text = body.contract_text
        deal.inspection_days = (body.inspection_days if body.inspection_days is not None
                                else terms.inspection_days if terms.inspection_days is not None
                                else s.default_inspection_days)
        ai_name = ai.name
    else:
        raise HTTPException(status_code=422, detail="Send the payment terms, or a contract text for the AI to draft them")
    db.add(deal)
    db.flush()
    notify(db, other.id, f"{user.company_name} proposed a new order: {deal.title}. Review and sign the terms.", deal.id)
    add_audit(db, deal.id, user.email, "deal_created",
              {"by": ai_name, "total_cents": deal.total_cents, "milestones": len(deal.milestones)})
    db.commit()
    return deal_dict(deal, user)


@router.get("")
def list_deals(user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(Deal).order_by(Deal.id.desc())
    if user.role != "admin":
        q = q.where(or_(Deal.buyer_id == user.id, Deal.seller_id == user.id))
    return [deal_dict(d, user) for d in db.scalars(q).all()]


@router.get("/{deal_id}")
def read_deal(deal_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return deal_dict(get_deal(db, deal_id, user), user)


@router.get("/{deal_id}/audit")
def read_audit(deal_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    deal = get_deal(db, deal_id, user)
    events = db.scalars(select(AuditEvent).where(AuditEvent.deal_id == deal.id).order_by(AuditEvent.id)).all()
    return {
        "chain_ok": verify_chain(db, deal.id),
        "events": [
            {"at": e.created_at.isoformat(), "actor": e.actor, "action": e.action, "detail": e.detail, "hash": e.hash}
            for e in events
        ],
    }


@router.put("/{deal_id}/terms")
def propose_terms(
    deal_id: int, body: TermsIn, user: User = Depends(require_roles("buyer", "seller")),
    _v: User = Depends(require_verified), db: Session = Depends(get_db),
):
    """Either side can counter-propose while the deal is a draft. This voids both signatures."""
    deal = get_deal(db, deal_id, user)
    if deal.state != "draft":
        raise HTTPException(status_code=409, detail="The terms are already locked")
    apply_terms(deal, body)
    notify_deal(db, deal, f"{user.company_name} sent new terms (v{deal.terms_version}). Earlier signatures were voided; please review.", skip_user_id=user.id)
    add_audit(db, deal.id, user.email, "terms_proposed",
              {"version": deal.terms_version, "total_cents": deal.total_cents, "refund_pct": deal.return_refund_pct})
    db.commit()
    return deal_dict(deal, user)


@router.post("/{deal_id}/confirm")
def confirm_terms(
    deal_id: int, body: ConfirmIn, user: User = Depends(require_roles("buyer", "seller")),
    _v: User = Depends(require_verified), db: Session = Depends(get_db),
):
    deal = get_deal(db, deal_id, user)
    if deal.state != "draft":
        raise HTTPException(status_code=409, detail="The terms are already locked")
    if body.version != deal.terms_version:
        raise HTTPException(status_code=409, detail="The terms changed since you read them; review the new version first")
    if user.id == deal.buyer_id:
        deal.buyer_confirmed = True
    else:
        deal.seller_confirmed = True
    add_audit(db, deal.id, user.email, "terms_signed_by", {"role": user.role, "version": deal.terms_version})
    if deal.buyer_confirmed and deal.seller_confirmed:
        deal.state = "terms_confirmed"
        add_audit(db, deal.id, "system", "terms_locked", {})
        engine.refresh_deadline(deal)
        notify_deal(db, deal, "Both sides signed. The buyer can now fund the escrow.")
    else:
        notify_deal(db, deal, f"{user.company_name} signed the terms. Your signature is needed.", skip_user_id=user.id)
    db.commit()
    return deal_dict(deal, user)


@router.post("/{deal_id}/fund")
def start_funding(
    deal_id: int, user: User = Depends(require_roles("buyer")), _v: User = Depends(require_verified),
    db: Session = Depends(get_db), holder: FundsHolder = Depends(get_holder),
):
    deal = get_deal(db, deal_id, user)
    if user.id != deal.buyer_id:
        raise HTTPException(status_code=403, detail="Only the buyer can fund this deal")
    if deal.state != "terms_confirmed":
        raise HTTPException(status_code=409, detail="Both parties must confirm the terms first")
    if deal.funding_mode != "upfront":
        raise HTTPException(status_code=409, detail="This order is paid milestone by milestone; fund the next milestone instead")
    if not engine.deposit_ready(deal):
        raise HTTPException(status_code=409, detail="The seller must pay the security deposit before the buyer funds")
    if deal.paypal_order_id:  # the buyer came back to an order that was already started: reuse it, never open a second one
        return {"order_id": deal.paypal_order_id, "approve_url": holder.approve_url(deal.paypal_order_id)}
    try:
        res = holder.create_funding(deal.total_cents, deal.currency, f"deal-{deal.id}", f"ep-d{deal.id}-order")
    except HolderError as exc:
        raise HTTPException(status_code=502, detail=f"Payment provider error: {exc}")
    deal.paypal_order_id = res["id"]
    db.add(PaymentEvent(deal_id=deal.id, kind="order", amount_cents=deal.total_cents, ref=res["id"],
                        idempotency_key=f"ep-d{deal.id}-order", status="CREATED"))
    add_audit(db, deal.id, user.email, "funding_started", {"order": res["id"]})
    db.commit()
    return {"order_id": res["id"], "approve_url": res["approve_url"]}


def mark_funded(db: Session, deal: Deal, capture_id: str, actor: str) -> None:
    if deal.state == "funded":
        return
    deal.state, deal.paypal_capture_id, deal.funded_at = "funded", capture_id, clock.now()
    for m in deal.milestones:
        m.funded, m.capture_id = True, capture_id
    engine.refresh_deadline(deal)
    db.add(PaymentEvent(deal_id=deal.id, kind="capture", amount_cents=deal.total_cents, ref=capture_id,
                        idempotency_key=f"ep-d{deal.id}-capture", status="COMPLETED"))
    add_audit(db, deal.id, actor, "deal_funded", {"capture": capture_id, "amount_cents": deal.total_cents})
    notify_deal(db, deal, f"The escrow is funded ({deal.total_cents / 100:,.2f} {deal.currency}). The seller can start submitting proof.")


@router.post("/{deal_id}/fund/capture")
def capture_funding(
    deal_id: int, user: User = Depends(require_roles("buyer")), db: Session = Depends(get_db),
    holder: FundsHolder = Depends(get_holder),
):
    deal = get_deal(db, deal_id, user)
    if user.id != deal.buyer_id:
        raise HTTPException(status_code=403, detail="Only the buyer can fund this deal")
    if deal.state == "funded":
        return deal_dict(deal, user)
    if deal.state != "terms_confirmed" or not deal.paypal_order_id:
        raise HTTPException(status_code=409, detail="Start funding first")
    try:
        res = holder.capture_funding(deal.paypal_order_id, f"ep-d{deal.id}-capture")
    except HolderError as exc:
        raise HTTPException(status_code=502, detail=f"Payment provider error: {exc}")
    if res["status"] != "COMPLETED":
        raise HTTPException(status_code=409, detail=f"Payment not completed yet ({res['status']})")
    mark_funded(db, deal, res["capture_id"], user.email)
    db.commit()
    return deal_dict(deal, user)


def _fundable_milestone(deal: Deal, ms: Milestone, user: User) -> None:
    if user.id != deal.buyer_id:
        raise HTTPException(status_code=403, detail="Only the buyer can fund this deal")
    if deal.funding_mode != "per_milestone":
        raise HTTPException(status_code=409, detail="This order is funded in full up front")
    if deal.state not in ("terms_confirmed", "funded"):
        raise HTTPException(status_code=409, detail="Both parties must confirm the terms first")
    if not engine.deposit_ready(deal):
        raise HTTPException(status_code=409, detail="The seller must pay the security deposit before the buyer funds")
    if any(m.seq < ms.seq and m.state not in engine.SETTLED_FOR_NEXT for m in deal.milestones):
        raise HTTPException(status_code=409, detail="Earlier milestones must be settled before funding this one")


@router.post("/{deal_id}/milestones/{ms_id}/fund")
def fund_milestone(
    deal_id: int, ms_id: int, user: User = Depends(require_roles("buyer")), _v: User = Depends(require_verified),
    db: Session = Depends(get_db), holder: FundsHolder = Depends(get_holder),
):
    """Pay one stage into escrow, just before it starts. Calling it again returns the same payment, never a second one."""
    deal = get_deal(db, deal_id, user)
    ms = get_milestone(deal, ms_id)
    if ms.funded:
        raise HTTPException(status_code=409, detail="This milestone is already funded")
    _fundable_milestone(deal, ms, user)
    if ms.order_id:
        return {"order_id": ms.order_id, "approve_url": holder.approve_url(ms.order_id), "amount_cents": ms.amount_cents}
    try:
        res = holder.create_funding(ms.amount_cents, deal.currency, f"deal-{deal.id}-m-{ms.id}", f"ep-d{deal.id}-m{ms.id}-order")
    except HolderError as exc:
        raise HTTPException(status_code=502, detail=f"Payment provider error: {exc}")
    ms.order_id = res["id"]
    db.add(PaymentEvent(deal_id=deal.id, milestone_id=ms.id, kind="order", amount_cents=ms.amount_cents, ref=res["id"],
                        idempotency_key=f"ep-d{deal.id}-m{ms.id}-order", status="CREATED"))
    add_audit(db, deal.id, user.email, "milestone_funding_started", {"milestone": ms.id, "order": res["id"], "amount_cents": ms.amount_cents})
    db.commit()
    return {"order_id": res["id"], "approve_url": res["approve_url"], "amount_cents": ms.amount_cents}


def mark_milestone_funded(db: Session, deal: Deal, ms: Milestone, capture_id: str, actor: str) -> None:
    if ms.funded:
        return
    ms.funded, ms.capture_id = True, capture_id
    if deal.state == "terms_confirmed":
        deal.state, deal.funded_at = "funded", clock.now()
    engine.refresh_deadline(deal)
    db.add(PaymentEvent(deal_id=deal.id, milestone_id=ms.id, kind="capture", amount_cents=ms.amount_cents, ref=capture_id,
                        idempotency_key=f"ep-d{deal.id}-m{ms.id}-capture", status="COMPLETED"))
    add_audit(db, deal.id, actor, "milestone_funded", {"milestone": ms.id, "capture": capture_id, "amount_cents": ms.amount_cents})
    notify_deal(db, deal, f"Milestone '{ms.name}' is funded ({ms.amount_cents / 100:,.2f} {deal.currency} locked in escrow). The seller can go ahead and submit proof.")


@router.post("/{deal_id}/milestones/{ms_id}/fund/capture")
def capture_milestone(
    deal_id: int, ms_id: int, user: User = Depends(require_roles("buyer")), db: Session = Depends(get_db),
    holder: FundsHolder = Depends(get_holder),
):
    deal = get_deal(db, deal_id, user)
    ms = get_milestone(deal, ms_id)
    if ms.funded:
        return deal_dict(deal, user)
    _fundable_milestone(deal, ms, user)
    if not ms.order_id:
        raise HTTPException(status_code=409, detail="Start funding this milestone first")
    try:
        res = holder.capture_funding(ms.order_id, f"ep-d{deal.id}-m{ms.id}-capture")
    except HolderError as exc:
        raise HTTPException(status_code=502, detail=f"Payment provider error: {exc}")
    if res["status"] != "COMPLETED":
        raise HTTPException(status_code=409, detail=f"Payment not completed yet ({res['status']})")
    mark_milestone_funded(db, deal, ms, res["capture_id"], user.email)
    db.commit()
    return deal_dict(deal, user)


@router.post("/{deal_id}/deposit")
def start_deposit(
    deal_id: int, user: User = Depends(require_roles("seller")), _v: User = Depends(require_verified),
    db: Session = Depends(get_db), holder: FundsHolder = Depends(get_holder),
):
    """The seller pays the security deposit into escrow. It comes back in full unless the seller is ruled at fault."""
    deal = get_deal(db, deal_id, user)
    if user.id != deal.seller_id:
        raise HTTPException(status_code=403, detail="Only the seller pays the security deposit")
    if deal.state not in ("terms_confirmed", "funded") or deal.seller_deposit_pct == 0:
        raise HTTPException(status_code=409, detail="No security deposit is due on this order right now")
    if deal.deposit_state != "none":
        raise HTTPException(status_code=409, detail="The security deposit is already paid")
    amount = engine.deposit_cents(deal)
    if deal.deposit_order_id:
        return {"order_id": deal.deposit_order_id, "approve_url": holder.approve_url(deal.deposit_order_id), "amount_cents": amount}
    try:
        res = holder.create_funding(amount, deal.currency, f"deal-{deal.id}-deposit", f"ep-d{deal.id}-deposit-order")
    except HolderError as exc:
        raise HTTPException(status_code=502, detail=f"Payment provider error: {exc}")
    deal.deposit_order_id = res["id"]
    db.add(PaymentEvent(deal_id=deal.id, kind="deposit_order", amount_cents=amount, ref=res["id"],
                        idempotency_key=f"ep-d{deal.id}-deposit-order", status="CREATED"))
    add_audit(db, deal.id, user.email, "deposit_started", {"order": res["id"], "amount_cents": amount})
    db.commit()
    return {"order_id": res["id"], "approve_url": res["approve_url"], "amount_cents": amount}


@router.post("/{deal_id}/deposit/capture")
def capture_deposit(
    deal_id: int, user: User = Depends(require_roles("seller")), db: Session = Depends(get_db),
    holder: FundsHolder = Depends(get_holder),
):
    deal = get_deal(db, deal_id, user)
    if user.id != deal.seller_id:
        raise HTTPException(status_code=403, detail="Only the seller pays the security deposit")
    if deal.deposit_state == "held":
        return deal_dict(deal, user)
    if deal.state not in ("terms_confirmed", "funded") or not deal.deposit_order_id:
        raise HTTPException(status_code=409, detail="Start the deposit payment first")
    try:
        res = holder.capture_funding(deal.deposit_order_id, f"ep-d{deal.id}-deposit-capture")
    except HolderError as exc:
        raise HTTPException(status_code=502, detail=f"Payment provider error: {exc}")
    if res["status"] != "COMPLETED":
        raise HTTPException(status_code=409, detail=f"Payment not completed yet ({res['status']})")
    amount = engine.deposit_cents(deal)
    deal.deposit_state, deal.deposit_capture_id = "held", res["capture_id"]
    db.add(PaymentEvent(deal_id=deal.id, kind="deposit_capture", amount_cents=amount, ref=res["capture_id"],
                        idempotency_key=f"ep-d{deal.id}-deposit-capture", status="COMPLETED"))
    add_audit(db, deal.id, user.email, "deposit_held", {"capture": res["capture_id"], "amount_cents": amount})
    notify_deal(db, deal, f"The seller's security deposit ({amount / 100:,.2f} {deal.currency}) is held in escrow. The buyer can now fund.")
    db.commit()
    return deal_dict(deal, user)


def proof_evidence(db: Session, m: Milestone) -> Evidence | None:
    """The stage's own proof document. A buyer's return receipt is stored under the same stage, so skip it."""
    rows = db.scalars(select(Evidence).where(Evidence.milestone_id == m.id, Evidence.extracted.is_not(None))
                      .order_by(Evidence.id.desc())).all()
    return next((e for e in rows if e.extracted.get("doc_type") == m.required_proof), rows[0] if rows else None)


def _prior_docs(db: Session, deal: Deal, ms: Milestone) -> list:
    """What the seller already submitted for earlier stages of this deal, so a new document can be cross-checked."""
    out = []
    for m in deal.milestones:
        if m.seq >= ms.seq:
            continue
        ev = proof_evidence(db, m)
        if ev is not None and ev.extracted:
            out.append((engine.PROOF_LABELS.get(m.required_proof, m.required_proof), ev.extracted))
    return out


def _find_duplicate(db: Session, digest: str | None, ms: Milestone) -> str | None:
    """The same file used again for another stage or another open order is a classic paper-fraud sign."""
    if not digest or not get_settings().duplicate_doc_check:
        return None
    hit = db.scalar(select(Evidence).join(Milestone, Milestone.id == Evidence.milestone_id).join(Deal, Deal.id == Milestone.deal_id)
                    .where(Evidence.sha256 == digest, Evidence.milestone_id != ms.id,
                           Deal.state.not_in(("completed", "cancelled"))))
    if hit is None:
        return None
    other = db.get(Milestone, hit.milestone_id)
    return f"This exact document was already uploaded for another stage or order (order #{other.deal_id}, stage {other.seq})"


@router.post("/{deal_id}/milestones/{ms_id}/proof")
def submit_proof(
    deal_id: int, ms_id: int, body: ProofIn, user: User = Depends(require_roles("seller")),
    _v: User = Depends(require_verified), db: Session = Depends(get_db),
    ai: AIProvider = Depends(get_ai), holder: FundsHolder = Depends(get_holder),
):
    deal = get_deal(db, deal_id, user)
    if user.id != deal.seller_id:
        raise HTTPException(status_code=403, detail="Only the seller can submit proof")
    ms = get_milestone(deal, ms_id)
    if deal.state != "funded":
        raise HTTPException(status_code=409, detail="The deal is not funded yet")
    if not ms.funded:
        raise HTTPException(status_code=409, detail="The buyer has not funded this milestone yet")
    if ms.state != "waiting":
        raise HTTPException(status_code=409, detail=f"This milestone is {ms.state}; proof cannot be submitted now")
    if any(m.seq < ms.seq and m.state not in engine.SETTLED_FOR_NEXT for m in deal.milestones):
        raise HTTPException(status_code=409, detail="Earlier milestones must be completed first")
    doc, kept_text, digest = read_document(body, ai)
    verdict = engine.check_proof(deal, ms, doc, _prior_docs(db, deal, ms), _find_duplicate(db, digest, ms))
    verdict["provider"] = ai.name
    db.add(Evidence(milestone_id=ms.id, uploader_id=user.id, filename=body.filename[:200], text=kept_text, extracted=doc,
                    sha256=digest))
    add_audit(db, deal.id, user.email, "proof_submitted",
              {"milestone": ms.id, "file": body.filename[:200], "sha256": digest, "extracted": doc})
    try:
        engine.apply_verdict(db, holder, deal, ms, verdict, user.email)
    except BusinessError:
        db.rollback()
        raise
    db.commit()
    return milestone_dict(ms)


@router.post("/{deal_id}/milestones/{ms_id}/dispute")
def dispute(
    deal_id: int, ms_id: int, body: DisputeIn, user: User = Depends(require_roles("buyer")),
    db: Session = Depends(get_db),
):
    deal = get_deal(db, deal_id, user)
    if user.id != deal.buyer_id:
        raise HTTPException(status_code=403, detail="Only the buyer can dispute")
    ms = get_milestone(deal, ms_id)
    if ms.state not in ("approved_hold", "accepted"):
        raise HTTPException(status_code=409, detail="Only a milestone in its inspection window or held in escrow can be disputed")
    ms.state, ms.release_after = "flagged", None
    verdict = dict(ms.verdict or {})
    verdict["reasons"] = list(verdict.get("reasons", [])) + [f"Buyer dispute: {body.reason}"]
    ms.verdict = verdict
    add_audit(db, deal.id, user.email, "milestone_disputed", {"milestone": ms.id, "reason": body.reason})
    notify_deal(db, deal, f"The buyer disputed '{ms.name}': {body.reason[:120]}", admins=True, skip_user_id=user.id)
    db.commit()
    return milestone_dict(ms)


@router.post("/{deal_id}/milestones/{ms_id}/appeal")
def appeal(
    deal_id: int, ms_id: int, body: AppealIn, user: User = Depends(require_roles("buyer", "seller")),
    db: Session = Depends(get_db),
):
    """Either side can appeal a pending fault ruling once, before the cooling-off ends. A second reviewer decides."""
    deal = get_deal(db, deal_id, user)
    ms = get_milestone(deal, ms_id)
    engine.appeal_ruling(db, deal, ms, user.email, body.reason)
    db.commit()
    return milestone_dict(ms)


@router.post("/{deal_id}/milestones/{ms_id}/return-proof")
def submit_return_proof(
    deal_id: int, ms_id: int, body: ProofIn, user: User = Depends(require_roles("buyer")),
    db: Session = Depends(get_db), ai: AIProvider = Depends(get_ai),
):
    """The buyer proves the goods went back. Unlocks the refund the signed terms promise."""
    deal = get_deal(db, deal_id, user)
    if user.id != deal.buyer_id:
        raise HTTPException(status_code=403, detail="Only the buyer can submit return proof")
    ms = get_milestone(deal, ms_id)
    if ms.state != "flagged":
        raise HTTPException(status_code=409, detail="Return proof is only accepted for a disputed or flagged milestone")
    doc, kept_text, digest = read_document(body, ai)
    res = engine.check_return_proof(deal, doc)
    db.add(Evidence(milestone_id=ms.id, uploader_id=user.id, filename=body.filename[:200], text=kept_text, extracted=doc,
                    sha256=digest))
    ms.return_proof_ok = res["ok"]
    if res["ok"]:
        engine.start_return_check(deal, ms)
    notify_deal(db, deal, f"Return shipment proof for '{ms.name}' was {'accepted' if res['ok'] else 'rejected'}."
                + (f" Check the returned goods within {deal.return_check_days} days and confirm they match what you shipped."
                   if res["ok"] and deal.return_check_days > 0 else ""), to=("seller",), admins=True)
    add_audit(db, deal.id, user.email, "return_proof_submitted", {"milestone": ms.id, "ok": res["ok"], "sha256": digest, "reasons": res["reasons"]})
    db.commit()
    return {"ok": res["ok"], "reasons": res["reasons"], "milestone": milestone_dict(ms)}


@router.post("/{deal_id}/milestones/{ms_id}/return-received")
def return_received(
    deal_id: int, ms_id: int, body: ReturnCheckIn, user: User = Depends(require_roles("seller")),
    db: Session = Depends(get_db),
):
    """The seller checks the returned goods against what was shipped. Only a confirmed return lets the refund move."""
    deal = get_deal(db, deal_id, user)
    if user.id != deal.seller_id:
        raise HTTPException(status_code=403, detail="Only the seller can check the returned goods")
    ms = get_milestone(deal, ms_id)
    if ms.return_received is not None:
        raise HTTPException(status_code=409, detail="The returned goods were already checked")
    engine.record_return_check(db, deal, ms, user.email, body.ok, body.note.strip())
    db.commit()
    return milestone_dict(ms)
