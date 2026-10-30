"""Settings come only from environment variables. Never commit real keys."""
import os
import secrets
from functools import lru_cache


class Settings:
    def __init__(self) -> None:
        self.env = os.getenv("APP_ENV", "dev")
        url = os.getenv("DATABASE_URL", "sqlite:///./escrowpilot.db")
        # Hosts such as Neon hand out postgres:// or postgresql:// urls; SQLAlchemy needs the driver name.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                url = "postgresql+psycopg://" + url[len(prefix):]
        self.database_url = url
        # In production SECRET_KEY must be set; a random key per start is fine for local dev only.
        self.secret_key = os.getenv("SECRET_KEY") or secrets.token_urlsafe(32)
        # ADMIN_EMAIL may list several addresses (comma separated). An appeal needs a second, different admin.
        self.admin_emails = [e.strip().lower() for e in os.getenv("ADMIN_EMAIL", "").split(",") if e.strip()]
        self.admin_email = self.admin_emails[0] if self.admin_emails else ""
        self.cors_origins = [
            o.strip()
            for o in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
            if o.strip()
        ]
        # Payments: "mock" runs fully offline, "sandbox" talks to PayPal's sandbox (test money only).
        self.paypal_mode = os.getenv("PAYPAL_MODE", "mock")
        self.paypal_base_url = os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com")
        self.paypal_client_id = os.getenv("PAYPAL_CLIENT_ID", "")
        self.paypal_client_secret = os.getenv("PAYPAL_CLIENT_SECRET", "")
        self.paypal_webhook_id = os.getenv("PAYPAL_WEBHOOK_ID", "")
        self.public_app_url = os.getenv("PUBLIC_APP_URL", "http://localhost:5173")
        # AI: "offline" uses fixed rules on sample documents, "gemini" uses the free tier.
        self.ai_provider = os.getenv("AI_PROVIDER", "offline")
        self.ai_fallback_offline = os.getenv("AI_FALLBACK_OFFLINE", "true").lower() == "true"
        # Email is optional. Without SMTP_HOST only the in-app notifications are used.
        self.smtp_host = os.getenv("SMTP_HOST", "")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.smtp_from = os.getenv("SMTP_FROM", "EscrowPilot <no-reply@example.com>")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY", "").strip().strip("\"'")
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
        # Business rules
        self.fee_bps = int(os.getenv("FEE_BPS", "200"))  # 2% fee on the seller's payout
        self.default_inspection_days = int(os.getenv("DEFAULT_INSPECTION_DAYS", "3"))
        # A fault ruling waits this many hours so either side can appeal once; 0 applies it straight away.
        self.cooling_off_hours = int(os.getenv("COOLING_OFF_HOURS", "48"))
        self.duplicate_doc_check = os.getenv("DUPLICATE_DOC_CHECK", "true").lower() == "true"
        self.max_text_bytes = int(os.getenv("MAX_TEXT_BYTES", "200000"))
        self.timer_interval_seconds = int(os.getenv("TIMER_INTERVAL_SECONDS", "60"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
