from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..audit import add_audit
from ..notify import notify
from ..db import get_db
from ..models import Connection, User
from ..schemas import ConnectIn
from ..trust import trust_profile
from ..security import current_user, require_roles, require_verified

router = APIRouter(tags=["connections"])


def find_user(db: Session, public_id: str) -> User | None:
    return db.scalar(select(User).where(User.public_id == public_id.upper()))


def are_connected(db: Session, a: int, b: int) -> bool:
    return db.scalar(
        select(Connection).where(
            Connection.status == "accepted",
            or_((Connection.requester_id == a) & (Connection.addressee_id == b),
                (Connection.requester_id == b) & (Connection.addressee_id == a)),
        )
    ) is not None


def conn_dict(c: Connection, me: User) -> dict:
    other = c.addressee if c.requester_id == me.id else c.requester
    return {"id": c.id, "status": c.status, "direction": "sent" if c.requester_id == me.id else "received",
            "partner": {"public_id": other.public_id, "company_name": other.company_name, "role": other.role}}


@router.get("/users/lookup/{public_id}")
def lookup(public_id: str, me: User = Depends(current_user), db: Session = Depends(get_db)):
    """Find a trading partner by their id. Shows only what is needed to recognise them."""
    u = find_user(db, public_id)
    if u is None or u.role == "admin" or u.id == me.id:
        raise HTTPException(status_code=404, detail="No trader found with that id")
    return {"public_id": u.public_id, "company_name": u.company_name, "role": u.role, "verified": u.verified,
            "trust": trust_profile(db, u)}


@router.post("/connections", status_code=201)
def request_connection(body: ConnectIn, me: User = Depends(require_roles("buyer", "seller")),
                       _v: User = Depends(require_verified), db: Session = Depends(get_db)):
    other = find_user(db, body.public_id)
    if other is None or other.role == "admin" or other.id == me.id:
        raise HTTPException(status_code=404, detail="No trader found with that id")
    if other.role == me.role:
        raise HTTPException(status_code=422, detail=f"You can only connect a buyer with a seller; {other.public_id} is also a {other.role}")
    existing = db.scalar(select(Connection).where(
        or_((Connection.requester_id == me.id) & (Connection.addressee_id == other.id),
            (Connection.requester_id == other.id) & (Connection.addressee_id == me.id))))
    if existing:
        raise HTTPException(status_code=409, detail=f"A connection already exists ({existing.status})")
    c = Connection(requester_id=me.id, addressee_id=other.id)
    db.add(c)
    db.flush()
    add_audit(db, None, me.email, "connection_requested", {"to": other.public_id})
    notify(db, other.id, f"{me.company_name} ({me.public_id}) wants to connect with you.")
    db.commit()
    return conn_dict(c, me)


@router.post("/connections/{conn_id}/accept")
def accept_connection(conn_id: int, me: User = Depends(require_roles("buyer", "seller")), db: Session = Depends(get_db)):
    c = db.get(Connection, conn_id)
    if c is None or c.addressee_id != me.id:
        raise HTTPException(status_code=404, detail="Connection request not found")
    c.status = "accepted"
    add_audit(db, None, me.email, "connection_accepted", {"with": c.requester.public_id})
    notify(db, c.requester_id, f"{me.company_name} accepted your connection. You can create an order now.")
    db.commit()
    return conn_dict(c, me)


@router.get("/connections")
def my_connections(me: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Connection).where(
        or_(Connection.requester_id == me.id, Connection.addressee_id == me.id)).order_by(Connection.id.desc())).all()
    return [conn_dict(c, me) for c in rows]
