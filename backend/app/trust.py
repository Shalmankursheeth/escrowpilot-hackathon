"""Trust profile from real deal history. Plain counts, no AI: easy to explain and hard to game without doing real deals."""
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import AuditEvent, Deal, Milestone, User


def trust_profile(db: Session, user: User) -> dict:
    deals = db.scalars(select(Deal).where(or_(Deal.buyer_id == user.id, Deal.seller_id == user.id))).all()
    ms = [m for d in deals for m in d.milestones]
    done = [m for m in ms if m.state in ("released", "refunded")]
    clean = [m for m in done if m.state == "released" and (m.verdict or {}).get("outcome") == "approve"
             and not any("Buyer dispute" in r for r in (m.verdict or {}).get("reasons", []))]
    flagged = sum(1 for m in ms if (m.verdict or {}).get("outcome") == "flag")
    disputed = sum(1 for m in ms if any("Buyer dispute" in r for r in (m.verdict or {}).get("reasons", [])))
    completed = sum(1 for d in deals if d.state == "completed")
    volume = sum(d.total_cents for d in deals if d.state == "completed")
    strikes = sum(1 for d in deals if (d.fault == "buyer" and d.buyer_id == user.id) or (d.fault == "seller" and d.seller_id == user.id))
    rate = round(100 * len(clean) / len(done)) if done else None
    # Not a score until there is enough history: show "new" instead of a fake number.
    level = "new" if len(done) < 3 else ("trusted" if rate >= 90 else "mixed" if rate >= 70 else "caution")
    if strikes >= 2:
        level = "caution"
    return {"public_id": user.public_id, "completed_deals": completed, "completed_volume_cents": volume,
            "milestones_settled": len(done), "clean_rate_pct": rate, "flagged": flagged, "disputed": disputed,
            "strikes": strikes, "level": level}
