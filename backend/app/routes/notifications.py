from fastapi import APIRouter, Depends
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Notification, User
from ..security import current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Notification).where(Notification.user_id == user.id).order_by(Notification.id.desc()).limit(30)).all()
    return {"unread": sum(1 for n in rows if not n.read),
            "items": [{"id": n.id, "text": n.text, "deal_id": n.deal_id, "read": n.read, "at": n.created_at.isoformat()} for n in rows]}


@router.post("/read")
def mark_read(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(update(Notification).where(Notification.user_id == user.id).values(read=True))
    db.commit()
    return {"ok": True}
