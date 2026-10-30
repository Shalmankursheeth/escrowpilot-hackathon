from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import clock
from .db import Base


def _now() -> datetime:
    return clock.now()


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))  # buyer | seller | admin
    company_name: Mapped[str] = mapped_column(String(255))
    paypal_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)  # simulated KYC in the demo
    public_id: Mapped[str] = mapped_column(String(16), unique=True, index=True)  # shared with partners, e.g. EP-7K2M9Q
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Connection(Base):
    """A buyer and a seller who found each other by public id. Orders can only be made between accepted connections."""
    __tablename__ = "connections"
    __table_args__ = (UniqueConstraint("requester_id", "addressee_id", name="uq_connection_pair"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    addressee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending | accepted
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    requester: Mapped[User] = relationship(foreign_keys=[requester_id])
    addressee: Mapped[User] = relationship(foreign_keys=[addressee_id])


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id"), nullable=True)
    text: Mapped[str] = mapped_column(String(300))
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    emailed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Deal(Base):
    __tablename__ = "deals"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    buyer_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    seller_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    total_cents: Mapped[int] = mapped_column(Integer)
    goods: Mapped[str | None] = mapped_column(String(300), nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    buyer_name: Mapped[str] = mapped_column(String(255))
    seller_name: Mapped[str] = mapped_column(String(255))
    contract_text: Mapped[str] = mapped_column(Text, default="")
    # Terms are proposed by either side and signed by both. Editing bumps the version and voids signatures.
    terms_version: Mapped[int] = mapped_column(Integer, default=1)
    # Failure / return terms, fixed and signed up front so nobody pays or refunds by assumption.
    return_refund_pct: Mapped[int] = mapped_column(Integer, default=100)  # share of the milestone refunded on a failed delivery
    return_shipping_by: Mapped[str] = mapped_column(String(10), default="seller")  # seller | buyer
    return_proof_required: Mapped[bool] = mapped_column(Boolean, default=True)  # buyer must prove the goods were shipped back
    return_check_days: Mapped[int] = mapped_column(Integer, default=5)  # seller's window to check returned goods before any refund; 0 = no check
    # per_milestone: the buyer funds each stage just before it starts. upfront: the whole amount is funded first.
    funding_mode: Mapped[str] = mapped_column(String(14), default="per_milestone")
    release_rule: Mapped[str] = mapped_column(String(14), default="on_completion")  # on_completion | per_stage
    inspection_days: Mapped[int] = mapped_column(Integer, default=0)
    failure_scope: Mapped[str] = mapped_column(String(12), default="whole_order")  # whole_order | stage
    funding_deadline_days: Mapped[int] = mapped_column(Integer, default=7)
    default_penalty_pct: Mapped[int] = mapped_column(Integer, default=10)  # seller's share of held money if the buyer defaults
    fund_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Seller security deposit (percent of the order total), held until the deal ends, then returned or forfeited.
    seller_deposit_pct: Mapped[int] = mapped_column(Integer, default=5)
    deposit_state: Mapped[str] = mapped_column(String(10), default="none")  # none | held | returned | forfeited
    deposit_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    deposit_capture_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fault: Mapped[str | None] = mapped_column(String(10), nullable=True)  # seller | buyer, set by an admin ruling
    # draft -> terms_confirmed -> funded -> completed | cancelled
    state: Mapped[str] = mapped_column(String(20), default="draft")
    buyer_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    seller_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    paypal_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    paypal_capture_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    funded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    buyer: Mapped[User] = relationship(foreign_keys=[buyer_id])
    seller: Mapped[User] = relationship(foreign_keys=[seller_id])
    milestones: Mapped[list["Milestone"]] = relationship(
        back_populates="deal", order_by="Milestone.seq", cascade="all, delete-orphan"
    )


class Milestone(Base):
    __tablename__ = "milestones"
    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    share_pct: Mapped[int] = mapped_column(Integer)
    amount_cents: Mapped[int] = mapped_column(Integer)
    required_proof: Mapped[str] = mapped_column(String(40))
    # waiting -> flagged | approved_hold | accepted (held) -> released | refunded
    state: Mapped[str] = mapped_column(String(20), default="waiting")
    release_after: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    verdict: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    payout_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fee_cents: Mapped[int] = mapped_column(Integer, default=0)
    paid_cents: Mapped[int] = mapped_column(Integer, default=0)
    return_proof_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    # The seller checks the returned goods against what was shipped: confirmed | mismatch (None while pending).
    return_received: Mapped[str | None] = mapped_column(String(10), nullable=True)
    return_received_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    return_check_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    funded: Mapped[bool] = mapped_column(Boolean, default=False)  # money for this stage is locked in escrow
    order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    capture_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # A fault ruling is proposed, waits out the cooling-off, and can be appealed once to a second reviewer.
    ruling: Mapped[str | None] = mapped_column(String(10), nullable=True)  # seller | buyer
    ruling_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ruling_note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    ruling_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    appeal_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    appeal_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    deal: Mapped[Deal] = relationship(back_populates="milestones")


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    milestone_id: Mapped[int] = mapped_column(ForeignKey("milestones.id"), index=True)
    uploader_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    extracted: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # same file reused = suspicious
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class PaymentEvent(Base):
    __tablename__ = "payment_events"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_payment_idempotency"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), index=True)
    milestone_id: Mapped[int | None] = mapped_column(ForeignKey("milestones.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))  # order | capture | payout | refund
    amount_cents: Mapped[int] = mapped_column(Integer)
    ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    deal_id: Mapped[int | None] = mapped_column(ForeignKey("deals.id"), nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
