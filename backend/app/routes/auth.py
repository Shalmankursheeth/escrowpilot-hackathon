import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import add_audit
from ..config import get_settings
from ..db import get_db
from ..models import User
from ..schemas import LoginIn, RegisterIn
from ..security import create_token, current_user, hash_password, verify_password

router = APIRouter(tags=["auth"])
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no look-alike characters


def new_public_id(db: Session) -> str:
    for _ in range(20):
        pid = "EP-" + "".join(secrets.choice(_ALPHABET) for _ in range(6))
        if db.scalar(select(User).where(User.public_id == pid)) is None:
            return pid
    raise HTTPException(status_code=500, detail="Could not create an id, try again")


def user_dict(u: User) -> dict:
    return {
        "id": u.id, "public_id": u.public_id, "email": u.email, "role": u.role, "company_name": u.company_name,
        "verified": u.verified, "has_payout_account": bool(u.paypal_email),
    }


@router.post("/auth/register", status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == body.email)):
        raise HTTPException(status_code=409, detail="That email is already registered")
    is_admin = body.email in get_settings().admin_emails
    user = User(
        email=body.email,
        public_id=new_public_id(db),
        password_hash=hash_password(body.password),
        role="admin" if is_admin else body.role,
        company_name=body.company_name,
        paypal_email=body.paypal_email,
        verified=is_admin,
    )
    db.add(user)
    db.flush()
    add_audit(db, None, user.email, "user_registered", {"role": user.role})
    db.commit()
    return {"token": create_token(user), "user": user_dict(user)}


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Wrong email or password")
    return {"token": create_token(user), "user": user_dict(user)}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_dict(user)
