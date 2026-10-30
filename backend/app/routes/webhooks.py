import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Deal
from ..payments import FundsHolder, get_holder
from ..models import Milestone
from .deals import mark_funded, mark_milestone_funded

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/paypal")
async def paypal_webhook(request: Request, db: Session = Depends(get_db), holder: FundsHolder = Depends(get_holder)):
    body = await request.body()
    if len(body) > 100_000:
        raise HTTPException(status_code=413, detail="Too large")
    if not holder.verify_webhook(dict(request.headers), body):
        raise HTTPException(status_code=400, detail="Webhook signature could not be verified")
    try:
        event = json.loads(body)
        kind = event.get("event_type")
        resource = event.get("resource", {})
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Bad event")
    if kind == "PAYMENT.CAPTURE.COMPLETED":
        m = re.fullmatch(r"deal-(\d+)(?:-m-(\d+))?", str(resource.get("custom_id", "")))
        if m:
            deal = db.get(Deal, int(m.group(1)))
            cap = str(resource.get("id", ""))
            if deal is not None and m.group(2):
                ms = db.get(Milestone, int(m.group(2)))
                if ms is not None and ms.deal_id == deal.id:
                    mark_milestone_funded(db, deal, ms, cap, "paypal-webhook")
                    db.commit()
            elif deal is not None and deal.state == "terms_confirmed":
                mark_funded(db, deal, cap, "paypal-webhook")
                db.commit()
    return {"received": True}
