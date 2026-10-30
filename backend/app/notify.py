"""In-app notifications, plus optional email. Emails are sent after the database commit by a background sweep,
so a rolled-back action never sends an email. With no SMTP settings, only the in-app bell is used."""
import logging
import smtplib
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Deal, Notification, User

log = logging.getLogger("escrowpilot.notify")


def notify(db: Session, user_id: int, text: str, deal_id: int | None = None) -> None:
    db.add(Notification(user_id=user_id, deal_id=deal_id, text=text[:300]))


def notify_deal(db: Session, deal: Deal, text: str, to=("buyer", "seller"), admins: bool = False, skip_user_id: int | None = None) -> None:
    ids = set()
    if "buyer" in to:
        ids.add(deal.buyer_id)
    if "seller" in to:
        ids.add(deal.seller_id)
    if admins:
        ids.update(db.scalars(select(User.id).where(User.role == "admin")).all())
    ids.discard(skip_user_id)
    for uid in ids:
        notify(db, uid, text, deal.id)


def send_pending_emails(db: Session) -> int:
    s = get_settings()
    if not s.smtp_host:
        return 0
    rows = db.scalars(select(Notification).where(Notification.emailed.is_(False)).order_by(Notification.id).limit(50)).all()
    sent = 0
    for n in rows:
        user = db.get(User, n.user_id)
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = s.smtp_from, user.email, "EscrowPilot: " + n.text[:80]
        link = f"{s.public_app_url}/#deal-{n.deal_id}" if n.deal_id else s.public_app_url
        msg.set_content(f"{n.text}\n\nOpen EscrowPilot: {link}\n\n(Sandbox demo, test money only.)")
        try:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
                smtp.starttls()
                if s.smtp_user:
                    smtp.login(s.smtp_user, s.smtp_password)
                smtp.send_message(msg)
            n.emailed = True
            sent += 1
        except Exception:
            log.exception("email to user %s failed", n.user_id)
            n.emailed = True  # do not retry forever; the in-app notification still exists
    db.commit()
    return sent
