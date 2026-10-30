import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import models  # noqa: F401  (registers tables)
from .config import get_settings
from .db import Base, SessionLocal, engine as db_engine
from .errors import BusinessError
from .payments import get_holder
from .migrate import ensure_columns
from .notify import send_pending_emails
from .routes import admin, auth, connections, deals, notifications, webhooks
from . import engine as rules

log = logging.getLogger("escrowpilot")


async def _timer_loop(interval: int) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            with SessionLocal() as db:
                send_pending_emails(db)
                n = rules.run_timers(db, get_holder())
                if n:
                    log.info("released %s milestone(s) after inspection windows", n)
        except Exception:  # keep the loop alive
            log.exception("timer run failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(db_engine)  # demo convenience; production uses migrations
    ensure_columns(db_engine)
    interval = get_settings().timer_interval_seconds
    task = asyncio.create_task(_timer_loop(interval)) if interval > 0 else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="EscrowPilot (sandbox demo)", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.exception_handler(BusinessError)
async def business_error_handler(_request: Request, exc: BusinessError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.get("/health")
def health():
    s = get_settings()
    return {"ok": True, "payments": get_holder().name, "ai": s.ai_provider, "note": "sandbox demo, test money only"}


for r in (auth.router, connections.router, deals.router, notifications.router, admin.router, webhooks.router):
    app.include_router(r)
