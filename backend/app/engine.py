"""Business rules. This is the only place that can decide a verdict or start a payout.
The AI supplies extracted facts; plain code compares them and the rules engine decides."""
import re
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import clock
from .ai.base import ALLOWED_PROOFS, ContractTerms
from .audit import add_audit
from .config import get_settings
from .errors import BusinessError
from .models import Deal, Milestone, PaymentEvent
from .notify import notify_deal
from .payments import FundsHolder, HolderError

_SUFFIXES = {"ltd", "limited", "pvt", "private", "llc", "inc", "co", "corp", "gmbh", "llp", "plc"}
PROOF_LABELS = {
    "order_confirmation": "order confirmation",
    "bill_of_lading": "bill of lading",
    "commercial_invoice": "commercial invoice",
    "packing_list": "packing list",
    "delivery_receipt": "delivery receipt",
    "return_receipt": "return receipt",
    "unknown": "unknown document",
}
PAID_OR_CLOSED = ("released", "refunded", "cancelled")
PENALTY_PCT = 5  # the at-fault side loses 5% of the order: the victim gets 2 parts of it, the platform 3
VICTIM_PCT = 2
SETTLED_FOR_NEXT = ("accepted", "released", "refunded", "cancelled")  # stage is finished, money may still be held


_DATE_FORMATS = ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%d-%m-%Y", "%d/%m/%Y")


def _parse_date(s: str | None):
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime((s or "").strip(), fmt)
        except ValueError:
            continue
    return None


def norm_name(s: str | None) -> str:
    tokens = re.findall(r"[a-z0-9]+", (s or "").lower())
    return " ".join(t for t in tokens if t not in _SUFFIXES)


def split_fee(amount_cents: int, fee_bps: int) -> tuple[int, int]:
    fee = amount_cents * fee_bps // 10000
    return fee, amount_cents - fee


def deposit_cents(deal: Deal) -> int:
    return deal.total_cents * deal.seller_deposit_pct // 100


def deposit_ready(deal: Deal) -> bool:
    """Buyers fund only after the seller's security deposit is held (or the signed terms ask for none)."""
    return deal.seller_deposit_pct == 0 or deal.deposit_state == "held"


# ---------------------------------------------------------------- terms -----------------------
def validate_terms(terms: ContractTerms) -> list[int]:
    """Return milestone amounts in cents, or raise BusinessError. Shares must total 100%."""
    if terms.total_cents <= 0:
        raise BusinessError("The contract total must be more than zero", 422)
    if not terms.milestones:
        raise BusinessError("No payment milestones were found in the contract", 422)
    if sum(m.share_pct for m in terms.milestones) != 100:
        raise BusinessError(
            f"Milestone shares add up to {sum(m.share_pct for m in terms.milestones)}%, not 100%", 422
        )
    for m in terms.milestones:
        if m.share_pct <= 0:
            raise BusinessError("Each milestone share must be above zero", 422)
        if m.required_proof not in ALLOWED_PROOFS:
            raise BusinessError(f"Unknown proof type {m.required_proof!r}", 422)
    amounts = [terms.total_cents * m.share_pct // 100 for m in terms.milestones]
    amounts[-1] += terms.total_cents - sum(amounts)  # last milestone absorbs rounding
    return amounts


# ---------------------------------------------------------------- verdict ---------------------
def check_proof(deal: Deal, ms: Milestone, doc: dict, prior: list | None = None, duplicate: str | None = None) -> dict:
    """prior: [(label, extracted_fields)] of this deal's earlier stages. duplicate: why this exact file was seen before."""
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})

    found = doc.get("doc_type") or "unknown"
    add(
        "document type",
        found == ms.required_proof,
        f"Expected a {PROOF_LABELS[ms.required_proof]}, found {PROOF_LABELS.get(found, found)}",
    )
    number = doc.get("document_number")
    add("document number", bool(number), f"Document number {number}" if number else "No document number found")

    seller_in_doc, buyer_in_doc = doc.get("shipper"), doc.get("consignee")
    if seller_in_doc or ms.required_proof != "delivery_receipt":
        add(
            "seller name",
            norm_name(seller_in_doc) == norm_name(deal.seller_name) and bool(seller_in_doc),
            f"Seller/shipper on document is {seller_in_doc!r}, contract says {deal.seller_name!r}",
        )
    add(
        "buyer name",
        norm_name(buyer_in_doc) == norm_name(deal.buyer_name) and bool(buyer_in_doc),
        f"Buyer/consignee on document is {buyer_in_doc!r}, contract says {deal.buyer_name!r}",
    )

    qty_needed = ms.required_proof != "order_confirmation"
    doc_qty = doc.get("quantity")
    if deal.quantity and (qty_needed or doc_qty is not None):
        add(
            "quantity",
            doc_qty == deal.quantity,
            f"Quantity on document is {doc_qty}, contract says {deal.quantity}",
        )

    if deal.goods and doc.get("goods"):
        want = {w for w in re.findall(r"[a-z]{4,}", deal.goods.lower())}
        have = {w for w in re.findall(r"[a-z]{4,}", doc["goods"].lower())}
        ok = (not want) or len(want & have) / len(want) >= 0.5
        add("goods description", ok, f"Goods on document: {doc['goods']!r}; contract: {deal.goods!r}")

    # Cross-document checks: the new paper must agree with what the seller already submitted for earlier stages.
    prior = prior or []
    if deal.quantity is None and doc.get("quantity") is not None:
        for label, earlier in prior:
            if earlier.get("quantity") is not None:
                add("quantity matches earlier documents", earlier["quantity"] == doc["quantity"],
                    f"Quantity {doc['quantity']} here, {earlier['quantity']} on the {label}")
                break
    this_date = _parse_date(doc.get("date"))
    dated = [(label, _parse_date(e.get("date"))) for label, e in prior]
    if this_date and any(d for _, d in dated):
        later = [label for label, d in dated if d and d > this_date]
        add("date order", not later, f"This document is dated before the {later[0]}" if later else "Dated after the earlier stage documents")
    if duplicate:
        add("duplicate document", False, duplicate)

    failed = [c for c in checks if not c["ok"]]
    outcome = "approve" if not failed else "flag"
    reasons = [c["detail"] for c in failed] or ["All checks passed: " + ", ".join(c["check"] for c in checks)]
    return {"outcome": outcome, "reasons": reasons, "checks": checks}


# ---------------------------------------------------------------- money movement --------------
def _finalize(db: Session, holder: FundsHolder, deal: Deal, actor: str) -> None:
    if deal.state == "funded" and all(m.state in PAID_OR_CLOSED for m in deal.milestones):
        deal.state = "completed"
        add_audit(db, deal.id, actor, "deal_completed", {})
        settle_deposit(db, holder, deal, actor)


def settle_deposit(db: Session, holder: FundsHolder, deal: Deal, actor: str) -> None:
    """The deal ended without a fault ruling against the seller: the security deposit goes back in full."""
    if deal.deposit_state != "held" or deal.fault == "seller":
        return
    key = f"ep-d{deal.id}-deposit-return"
    amount = deposit_cents(deal)
    if db.scalar(select(PaymentEvent).where(PaymentEvent.idempotency_key == key)) is None:
        try:
            res = holder.refund(deal.deposit_capture_id, amount, deal.currency, key)
        except HolderError as exc:
            add_audit(db, deal.id, actor, "deposit_return_failed", {"error": str(exc)})
            return  # stays "held"; run_timers retries
        db.add(PaymentEvent(deal_id=deal.id, kind="deposit_return", amount_cents=amount, ref=res["refund_id"],
                            idempotency_key=key, status=res["status"]))
    deal.deposit_state = "returned"
    add_audit(db, deal.id, actor, "deposit_returned", {"amount_cents": amount})
    notify_deal(db, deal, f"The seller's security deposit ({amount / 100:,.2f} {deal.currency}) was returned in full.")


def forfeit_deposit(db: Session, holder: FundsHolder, deal: Deal, actor: str) -> None:
    """Seller at fault: the deposit is gone. The buyer gets the victim share, the platform keeps the rest."""
    if deal.deposit_state != "held":
        return
    amount = deposit_cents(deal)
    comp = amount * VICTIM_PCT // PENALTY_PCT
    key = f"ep-d{deal.id}-deposit-comp"
    if comp > 0 and db.scalar(select(PaymentEvent).where(PaymentEvent.idempotency_key == key)) is None:
        try:
            res = holder.payout(deal.buyer.paypal_email, comp, deal.currency, key, f"{deal.title}: dispute compensation")
        except HolderError as exc:
            add_audit(db, deal.id, actor, "payout_failed", {"error": str(exc)})
            db.commit()
            raise BusinessError(f"The payment provider could not pay the buyer's compensation: {exc}", 502)
        db.add(PaymentEvent(deal_id=deal.id, kind="payout", amount_cents=comp, ref=res["batch_id"],
                            idempotency_key=key, status=res["status"]))
    deal.deposit_state = "forfeited"
    add_audit(db, deal.id, actor, "deposit_forfeited",
              {"deposit_cents": amount, "to_buyer_cents": comp, "to_platform_cents": amount - comp})
    notify_deal(db, deal, f"The seller was found at fault. The security deposit was forfeited: {comp / 100:,.2f} {deal.currency} "
                          f"goes to the buyer, the rest to the platform.")


def refresh_deadline(deal: Deal) -> None:
    """The buyer has a signed number of days to fund the next stage. Start the clock when a stage becomes
    fundable; stop it once that stage is funded or nothing is left to fund."""
    if deal.state not in ("terms_confirmed", "funded"):
        deal.fund_due_at = None
        return
    nxt = next((m for m in deal.milestones if m.state not in SETTLED_FOR_NEXT), None)
    if nxt is None or nxt.funded:
        deal.fund_due_at = None
    elif deal.fund_due_at is None:
        deal.fund_due_at = clock.now() + timedelta(days=deal.funding_deadline_days)


def release_milestone(db: Session, holder: FundsHolder, deal: Deal, ms: Milestone, actor: str, reason: str) -> Milestone:
    """Pay the seller for one milestone. Safe to call twice: one idempotency key means one payout."""
    if ms.state == "released":
        return ms
    if ms.state == "refunded":
        raise BusinessError("This milestone was already refunded", 409)
    if deal.state not in ("funded",) or not ms.funded:
        raise BusinessError("This milestone has not been funded", 409)
    if not deal.seller.paypal_email:
        raise BusinessError("The seller has no payout account yet", 409)

    key = f"ep-d{deal.id}-m{ms.id}-release"
    fee, net = split_fee(ms.amount_cents, get_settings().fee_bps)
    existing = db.scalar(select(PaymentEvent).where(PaymentEvent.idempotency_key == key))
    if existing is None:
        try:
            res = holder.payout(deal.seller.paypal_email, net, deal.currency, key, f"{deal.title}: {ms.name}")
        except HolderError as exc:
            add_audit(db, deal.id, actor, "payout_failed", {"milestone": ms.id, "error": str(exc)})
            db.commit()
            raise BusinessError(f"The payment provider could not pay out: {exc}", 502)
        db.add(
            PaymentEvent(
                deal_id=deal.id, milestone_id=ms.id, kind="payout", amount_cents=net,
                ref=res["batch_id"], idempotency_key=key, status=res["status"],
            )
        )
        ref = res["batch_id"]
    else:
        ref = existing.ref
    ms.state, ms.payout_ref, ms.fee_cents, ms.paid_cents, ms.release_after = "released", ref, fee, net, None
    add_audit(db, deal.id, actor, "milestone_released",
              {"milestone": ms.id, "paid_cents": net, "fee_cents": fee, "reason": reason, "ref": ref})
    notify_deal(db, deal, f"Milestone '{ms.name}' was paid out ({net / 100:,.2f} {deal.currency} to the seller after the fee).")
    _finalize(db, holder, deal, actor)
    refresh_deadline(deal)
    return ms


def accept_or_release(db: Session, holder: FundsHolder, deal: Deal, ms: Milestone, actor: str, reason: str) -> Milestone:
    """A stage passed. Under the signed release rule the money is either paid now (per_stage)
    or stays locked in escrow until the whole order is accepted (on_completion)."""
    if deal.release_rule == "per_stage":
        return release_milestone(db, holder, deal, ms, actor, reason)
    ms.state, ms.release_after = "accepted", None
    refresh_deadline(deal)
    add_audit(db, deal.id, actor, "milestone_accepted_held", {"milestone": ms.id, "reason": reason})
    notify_deal(db, deal, f"Stage '{ms.name}' is accepted. The money stays locked in escrow until the whole order is accepted.")
    settle_held(db, holder, deal, actor)
    return ms


def settle_held(db: Session, holder: FundsHolder, deal: Deal, actor: str) -> int:
    """When every stage is finished (accepted or refunded) and nothing is open, pay out all held stages together."""
    if deal.state != "funded" or any(m.state not in SETTLED_FOR_NEXT for m in deal.milestones):
        return 0
    n = 0
    for m in deal.milestones:
        if m.state == "accepted":
            release_milestone(db, holder, deal, m, actor, "order fully accepted")
            n += 1
    return n


def check_return_proof(deal: Deal, doc: dict) -> dict:
    """The buyer proves the goods were shipped back: a return receipt from the buyer to the seller."""
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "ok": ok, "detail": detail})

    found = doc.get("doc_type") or "unknown"
    add("document type", found == "return_receipt", f"Expected a return receipt, found {PROOF_LABELS.get(found, found)}")
    add("document number", bool(doc.get("document_number")), f"Document number {doc.get('document_number')}")
    add("sent by buyer", bool(doc.get("shipper")) and norm_name(doc.get("shipper")) == norm_name(deal.buyer_name),
        f"Shipper on document is {doc.get('shipper')!r}, buyer is {deal.buyer_name!r}")
    add("sent to seller", bool(doc.get("consignee")) and norm_name(doc.get("consignee")) == norm_name(deal.seller_name),
        f"Consignee on document is {doc.get('consignee')!r}, seller is {deal.seller_name!r}")
    failed = [c for c in checks if not c["ok"]]
    return {"ok": not failed, "reasons": [c["detail"] for c in failed] or ["Return shipment document matches the signed terms"],
            "checks": checks}


def goods_back(deal: Deal, ms: Milestone) -> bool:
    """The returned goods count as back with the seller: the return shipment proof is accepted and, when the signed terms
    give the seller a check window, the seller confirmed the goods match (or the window ended without objection)."""
    return ms.return_proof_ok and (deal.return_check_days == 0 or ms.return_received == "confirmed")


def start_return_check(deal: Deal, ms: Milestone) -> None:
    """Return proof was accepted: the seller now checks the returned goods before any refund can move."""
    ms.return_received, ms.return_received_note = None, None
    ms.return_check_due_at = clock.now() + timedelta(days=deal.return_check_days) if deal.return_check_days > 0 else None


def record_return_check(db: Session, deal: Deal, ms: Milestone, actor: str, ok: bool, note: str) -> None:
    """The seller (or a reviewer) records whether the returned goods match what was shipped. A mismatch blocks the refund."""
    if ms.state != "flagged" or not ms.return_proof_ok:
        raise BusinessError("There is no accepted return shipment to check", 409)
    ms.return_received, ms.return_received_note, ms.return_check_due_at = "confirmed" if ok else "mismatch", note or None, None
    add_audit(db, deal.id, actor, "return_goods_confirmed" if ok else "return_goods_mismatch", {"milestone": ms.id, "note": note})
    if ok:
        notify_deal(db, deal, f"The seller confirmed the returned goods for '{ms.name}' arrived as shipped. The refund can proceed.", admins=True)
    else:
        notify_deal(db, deal, f"The seller reports the returned goods for '{ms.name}' do not match what was shipped: {note[:120]}. "
                              f"No refund moves until a reviewer decides.", admins=True)


def refund_milestone(db: Session, holder: FundsHolder, deal: Deal, ms: Milestone, actor: str, note: str,
                     pct: int | None = None, needs_proof: bool = True, kept_seller_pct: int | None = None,
                     order_pct: int | None = None) -> Milestone:
    """Refund exactly what the signed failure terms say. The buyer gets return_refund_pct back; the seller keeps the rest
    (minus the fee). If the terms require proof of return shipment, nothing moves until it is on file."""
    if ms.state == "refunded":
        return ms
    if ms.state == "released":
        raise BusinessError("This milestone was already paid out", 409)
    capture = ms.capture_id or deal.paypal_capture_id
    if not capture:
        raise BusinessError("There is no captured payment to refund", 409)
    pct = deal.return_refund_pct if pct is None else pct
    refund_cents = ms.amount_cents * pct // 100
    keep_cents = ms.amount_cents - refund_cents
    if needs_proof and deal.return_proof_required and refund_cents > 0 and not goods_back(deal, ms):
        raise BusinessError("The signed terms require proof of return shipment, and the seller's check of the returned goods, "
                            "before a refund", 409)
    if keep_cents > 0 and not deal.seller.paypal_email:
        raise BusinessError("The seller has no payout account yet", 409)
    net_kept = fee_kept = 0
    if kept_seller_pct is not None:  # fault ruling: of the kept share the seller gets a fixed part, the platform the rest
        net_kept = ms.amount_cents * kept_seller_pct // 100
        fee_kept = keep_cents - net_kept

    rkey = f"ep-d{deal.id}-m{ms.id}-refund"
    if refund_cents > 0 and db.scalar(select(PaymentEvent).where(PaymentEvent.idempotency_key == rkey)) is None:
        try:
            res = holder.refund(capture, refund_cents, deal.currency, rkey)
        except HolderError as exc:
            add_audit(db, deal.id, actor, "refund_failed", {"milestone": ms.id, "error": str(exc)})
            db.commit()
            raise BusinessError(f"The payment provider could not refund: {exc}", 502)
        db.add(PaymentEvent(deal_id=deal.id, milestone_id=ms.id, kind="refund", amount_cents=refund_cents,
                            ref=res["refund_id"], idempotency_key=rkey, status=res["status"]))
        add_audit(db, deal.id, actor, "refund_sent", {"milestone": ms.id, "refund_cents": refund_cents, "ref": res["refund_id"]})
        db.commit()  # the refund really happened; keep the record even if the next step fails

    fee = net = 0
    if keep_cents > 0:
        fee, net = split_fee(keep_cents, get_settings().fee_bps) if kept_seller_pct is None else (fee_kept, net_kept)
    if net > 0:
        pkey = f"ep-d{deal.id}-m{ms.id}-keep"
        if db.scalar(select(PaymentEvent).where(PaymentEvent.idempotency_key == pkey)) is None:
            try:
                res = holder.payout(deal.seller.paypal_email, net, deal.currency, pkey, f"{deal.title}: {ms.name} (kept share)")
            except HolderError as exc:
                add_audit(db, deal.id, actor, "payout_failed", {"milestone": ms.id, "error": str(exc)})
                db.commit()
                raise BusinessError(f"The payment provider could not pay out: {exc}", 502)
            db.add(PaymentEvent(deal_id=deal.id, milestone_id=ms.id, kind="payout", amount_cents=net,
                                ref=res["batch_id"], idempotency_key=pkey, status=res["status"]))
            ms.payout_ref = res["batch_id"]
    ms.state, ms.release_after, ms.fee_cents, ms.paid_cents = "refunded", None, fee, net
    add_audit(db, deal.id, actor, "milestone_refunded",
              {"milestone": ms.id, "note": note, "refund_cents": refund_cents, "seller_kept_cents": keep_cents,
               "terms": f"{pct}% refund per signed terms"})
    notify_deal(db, deal, f"Milestone '{ms.name}' was refunded under the signed terms ({pct}% to the buyer).")
    if needs_proof and deal.failure_scope == "whole_order":
        unwind_order(db, holder, deal, ms, actor, note, order_pct)
    if needs_proof:  # bulk unwinds (whole-order failure, buyer default) must never pay out the stages they are still refunding
        settle_held(db, holder, deal, actor)
    _finalize(db, holder, deal, actor)
    refresh_deadline(deal)
    return ms


def unwind_order(db: Session, holder: FundsHolder, deal: Deal, failed: Milestone, actor: str, note: str,
                 order_pct: int | None = None) -> None:
    """Signed scope 'whole_order': a failed delivery unwinds everything still locked. Held stages are refunded on the same
    signed percentage (the return proof already on file covers the whole order); stages never started are cancelled."""
    for m in deal.milestones:
        if m.id == failed.id:
            continue
        if m.state == "accepted":
            refund_milestone(db, holder, deal, m, actor, f"whole-order failure: {note}", pct=order_pct, needs_proof=False)
        elif m.state in ("waiting", "approved_hold", "flagged"):
            if m.funded:  # paid in but never delivered: the buyer gets all of it back
                refund_milestone(db, holder, deal, m, actor, f"whole-order failure: {note}", pct=100, needs_proof=False)
            else:
                m.state = "cancelled"
                add_audit(db, deal.id, actor, "milestone_cancelled", {"milestone": m.id, "reason": "order failed"})


def default_order(db: Session, holder: FundsHolder, deal: Deal, actor: str = "system") -> None:
    """The buyer missed the signed funding deadline. Locked money goes back to the buyer except the signed penalty share,
    which the seller keeps; stages not yet funded are cancelled."""
    add_audit(db, deal.id, actor, "buyer_default", {"deadline_days": deal.funding_deadline_days, "penalty_pct": deal.default_penalty_pct})
    for m in deal.milestones:
        if m.state == "accepted":
            refund_milestone(db, holder, deal, m, actor, "buyer missed the funding deadline",
                             pct=100 - deal.default_penalty_pct, needs_proof=False)
    for m in deal.milestones:
        if m.state in ("waiting", "approved_hold", "flagged") and not m.funded:
            m.state = "cancelled"
            add_audit(db, deal.id, actor, "milestone_cancelled", {"milestone": m.id, "reason": "buyer default"})
    deal.fund_due_at = None
    deal.state = "completed" if any(m.state in ("released", "refunded") for m in deal.milestones) else "cancelled"
    add_audit(db, deal.id, actor, "deal_closed_by_default", {"state": deal.state})
    settle_deposit(db, holder, deal, actor)
    notify_deal(db, deal, "The buyer did not fund the next stage before the signed deadline. The order is closed under the signed terms.")


def rule_dispute(db: Session, holder: FundsHolder, deal: Deal, ms: Milestone, fault: str, actor: str, note: str) -> None:
    """An admin names who was at fault. Code then applies the fixed percentages; nothing here is a judgement call.
    seller: the buyer is refunded in full (after the return proof the signed terms ask for) and the seller loses the deposit.
    buyer, goods back with the seller: refund minus 5%; the seller gets 2% of it, the platform 3%, the deposit returns.
    buyer, goods kept: the seller is paid as normal (minus the fee) and the deposit returns."""
    if fault == "seller":
        if deal.deposit_state == "held" and not deal.buyer.paypal_email:
            raise BusinessError("The buyer has no payout account for the compensation", 409)
        deal.fault = "seller"
        refund_milestone(db, holder, deal, ms, actor, note or "seller at fault", pct=100, order_pct=100)
        forfeit_deposit(db, holder, deal, actor)
    else:
        deal.fault = "buyer"
        whole = deal.failure_scope == "whole_order"
        if goods_back(deal, ms):
            refund_milestone(db, holder, deal, ms, actor, note or "buyer at fault", pct=100 - PENALTY_PCT,
                             needs_proof=False, kept_seller_pct=VICTIM_PCT)
            if whole:  # the goods came back, so the ruling covers everything held for them
                wind_down_after_buyer_fault(db, holder, deal, ms, actor, note, goods_returned=True)
            else:
                settle_held(db, holder, deal, actor)
        else:
            accept_or_release(db, holder, deal, ms, actor, f"buyer at fault, goods kept: {note}")
            if whole:
                wind_down_after_buyer_fault(db, holder, deal, ms, actor, note, goods_returned=False)
    if deal.failure_scope == "whole_order":
        announce_combined_refund(db, deal, actor)
    add_audit(db, deal.id, actor, "fault_ruled", {"milestone": ms.id, "fault": fault, "note": note})


def announce_combined_refund(db: Session, deal: Deal, actor: str) -> None:
    """PayPal refunds one payment at a time. When an order unwinds across several stages, say it once as a single total."""
    refunds = db.scalars(select(PaymentEvent).where(PaymentEvent.deal_id == deal.id, PaymentEvent.kind == "refund")).all()
    if len(refunds) < 2:
        return
    total = sum(r.amount_cents for r in refunds)
    add_audit(db, deal.id, actor, "combined_refund", {"stages": len(refunds), "refund_cents": total})
    notify_deal(db, deal, f"The buyer is refunded {total / 100:,.2f} {deal.currency} in total across {len(refunds)} stages.")


def wind_down_after_buyer_fault(db: Session, holder: FundsHolder, deal: Deal, ruled: Milestone, actor: str, note: str,
                                goods_returned: bool = True) -> None:
    """Signed scope 'whole_order' and the buyer was at fault: the order ends here.
    Goods returned: the ruling covers the full amount held. Every held stage (delivered or not) is refunded minus 5%, of which the
    seller gets 2% and the platform 3%, exactly like the disputed stage. Stages never funded are cancelled.
    Goods kept: delivered stages are paid (minus the fee) and funded, undelivered stages go back to the buyer in full."""
    for m in deal.milestones:
        if m.id == ruled.id:
            continue
        if goods_returned and (m.state == "accepted" or (m.state in ("waiting", "approved_hold", "flagged") and m.funded)):
            refund_milestone(db, holder, deal, m, actor, f"order ended, buyer at fault: {note}", pct=100 - PENALTY_PCT,
                             needs_proof=False, kept_seller_pct=VICTIM_PCT)
        elif m.state == "accepted":
            release_milestone(db, holder, deal, m, actor, f"order ended, buyer at fault: {note}")
        elif m.state in ("waiting", "approved_hold", "flagged"):
            if m.funded:
                refund_milestone(db, holder, deal, m, actor, f"order ended, buyer at fault: {note}", pct=100, needs_proof=False)
            else:
                m.state = "cancelled"
                add_audit(db, deal.id, actor, "milestone_cancelled", {"milestone": m.id, "reason": "order ended, buyer at fault"})
    _finalize(db, holder, deal, actor)


def precheck_ruling(deal: Deal, ms: Milestone, fault: str) -> None:
    """Refuse a ruling that could not be carried out, before anyone starts waiting on it."""
    if ms.state != "flagged":
        raise BusinessError("Only a flagged milestone can be ruled on", 409)
    if fault == "seller":
        if deal.deposit_state == "held" and not deal.buyer.paypal_email:
            raise BusinessError("The buyer has no payout account for the compensation", 409)
        if deal.return_proof_required and not goods_back(deal, ms):
            raise BusinessError("The signed terms require proof of return shipment, and the seller's check of the returned "
                                "goods, before a seller-fault refund", 409)
    elif ms.return_proof_ok and deal.return_check_days > 0 and ms.return_received is None:
        raise BusinessError("The seller is still checking the returned goods. Rule once they confirm or the window ends", 409)


def execute_ruling(db: Session, holder: FundsHolder, deal: Deal, ms: Milestone, actor: str) -> None:
    ms.ruling_due_at = None
    rule_dispute(db, holder, deal, ms, ms.ruling, actor, ms.ruling_note or "")


def propose_ruling(db: Session, holder: FundsHolder, deal: Deal, ms: Milestone, fault: str, admin: str, note: str) -> bool:
    """Record who the reviewer says is at fault. The money only moves after the cooling-off (unless appealed).
    Returns True when it was applied straight away (cooling-off set to 0)."""
    precheck_ruling(deal, ms, fault)
    hours = get_settings().cooling_off_hours
    ms.ruling, ms.ruling_by, ms.ruling_note, ms.appeal_by, ms.appeal_reason = fault, admin, note, None, None
    add_audit(db, deal.id, admin, "ruling_proposed", {"milestone": ms.id, "fault": fault, "note": note, "cooling_off_hours": hours})
    if hours <= 0:
        execute_ruling(db, holder, deal, ms, admin)
        return True
    ms.ruling_due_at = clock.now() + timedelta(hours=hours)
    notify_deal(db, deal, f"A reviewer ruled the {fault} at fault on '{ms.name}'. It takes effect in {hours} hours unless "
                          f"either side appeals once.", admins=True)
    return False


def appeal_ruling(db: Session, deal: Deal, ms: Milestone, who: str, reason: str) -> None:
    """Either side can appeal a pending ruling once; a different reviewer then decides, and that decision is final."""
    if not ms.ruling or ms.state != "flagged" or ms.ruling_due_at is None:
        raise BusinessError("There is no pending ruling to appeal", 409)
    if clock.now() > ms.ruling_due_at:
        raise BusinessError("The appeal window has closed", 409)
    ms.appeal_by, ms.appeal_reason, ms.ruling_due_at = who, reason, None
    add_audit(db, deal.id, who, "ruling_appealed", {"milestone": ms.id, "reason": reason})
    notify_deal(db, deal, f"The ruling on '{ms.name}' was appealed. A second reviewer will decide; that decision is final.", admins=True)


def dispute_facts(deal: Deal, ms: Milestone, docs: list[dict]) -> dict:
    """The plain facts a reviewer needs, in one place. Fed to the AI summary and shown beside it."""
    reasons = (ms.verdict or {}).get("reasons", [])
    failed = [c["detail"] for c in (ms.verdict or {}).get("checks", []) if not c.get("ok")]
    return {
        "stage": ms.name, "amount": f"{ms.amount_cents / 100:,.2f} {deal.currency}",
        "dispute_reason": next((r.removeprefix("Buyer dispute: ") for r in reasons if r.startswith("Buyer dispute")), None),
        "contract": " ".join(str(x) for x in (deal.quantity, deal.goods) if x) or None,
        "documents": docs, "failed_checks": failed,
        "return_proof": ("accepted and on file" + {
            "confirmed": "; seller confirmed the returned goods match what was shipped",
            "mismatch": f"; seller reports the returned goods do NOT match what was shipped ({ms.return_received_note})",
            None: "; seller has not yet checked the returned goods" if deal.return_check_days > 0 else "",
        }[ms.return_received]) if ms.return_proof_ok else "not on file",
        "deposit": f"{deposit_cents(deal) / 100:,.2f} {deal.currency} ({deal.deposit_state})",
        "ruling_pending": ms.ruling, "appealed": bool(ms.appeal_by),
    }


def apply_verdict(db: Session, holder: FundsHolder, deal: Deal, ms: Milestone, verdict: dict, actor: str) -> None:
    ms.verdict = verdict
    if verdict["outcome"] != "approve":
        ms.state = "flagged"
        add_audit(db, deal.id, actor, "milestone_flagged", {"milestone": ms.id, "reasons": verdict["reasons"]})
        notify_deal(db, deal, f"Milestone '{ms.name}' was flagged for review: {verdict['reasons'][0]}", admins=True)
        return
    add_audit(db, deal.id, actor, "milestone_verified", {"milestone": ms.id, "reasons": verdict["reasons"]})
    if ms.required_proof == "delivery_receipt" and deal.inspection_days > 0:
        ms.state = "approved_hold"
        ms.release_after = clock.now() + timedelta(days=deal.inspection_days)
        add_audit(db, deal.id, actor, "inspection_window_started",
                  {"milestone": ms.id, "release_after": ms.release_after.isoformat()})
        notify_deal(db, deal, f"Delivery proof for '{ms.name}' was verified. The buyer has {deal.inspection_days} days to inspect before payment is released.")
    else:
        accept_or_release(db, holder, deal, ms, actor, "verdict approved")


def run_timers(db: Session, holder: FundsHolder) -> int:
    """Release every milestone whose inspection window has ended without a dispute."""
    due = db.scalars(
        select(Milestone).where(Milestone.state == "approved_hold", Milestone.release_after <= clock.now())
    ).all()
    released = 0
    for ms in due:
        try:
            accept_or_release(db, holder, ms.deal, ms, "system", "inspection window ended without dispute")
            db.commit()
            released += 1
        except BusinessError:
            db.rollback()
    overdue = db.scalars(select(Deal).where(Deal.fund_due_at.is_not(None), Deal.fund_due_at <= clock.now(),
                                            Deal.state.in_(("terms_confirmed", "funded")))).all()
    for deal in overdue:
        try:
            default_order(db, holder, deal)
            db.commit()
            released += 1
        except BusinessError:
            db.rollback()
    pending = db.scalars(select(Milestone).where(
        Milestone.state == "flagged", Milestone.ruling.is_not(None), Milestone.ruling_due_at.is_not(None),
        Milestone.ruling_due_at <= clock.now())).all()
    for ms in pending:
        try:
            execute_ruling(db, holder, ms.deal, ms, "system: cooling-off ended")
            db.commit()
            released += 1
        except BusinessError:
            db.rollback()
    unchecked = db.scalars(select(Milestone).where(
        Milestone.state == "flagged", Milestone.return_proof_ok.is_(True), Milestone.return_received.is_(None),
        Milestone.return_check_due_at.is_not(None), Milestone.return_check_due_at <= clock.now())).all()
    for ms in unchecked:  # the seller did not object in time: the goods count as received as shipped
        record_return_check(db, ms.deal, ms, "system: check window ended", True, "no objection within the signed check window")
        db.commit()
        released += 1
    stuck = db.scalars(select(Deal).where(Deal.deposit_state == "held", Deal.state.in_(("completed", "cancelled")))).all()
    for deal in stuck:
        settle_deposit(db, holder, deal, "system")
        db.commit()
    return released
