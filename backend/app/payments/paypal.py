"""PayPal REST client for the SANDBOX (test money only).

Not yet run against the live sandbox in the build environment: create PayPal sandbox accounts,
put the keys in .env and test one funding and one payout first (see README).
"""
import base64
import json
import time
from decimal import Decimal

import httpx

from .holder import HolderError


def _money(cents: int) -> str:
    return f"{(Decimal(cents) / 100):.2f}"


class PayPalHolder:
    name = "paypal-sandbox"

    def __init__(self, base_url: str, client_id: str, client_secret: str, webhook_id: str, return_url: str):
        if not (client_id and client_secret):
            raise HolderError("PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET are required for sandbox mode")
        self.base = base_url.rstrip("/")
        self.client_id, self.client_secret, self.webhook_id = client_id, client_secret, webhook_id
        self.return_url = return_url
        self._token: str | None = None
        self._token_exp = 0.0

    # --- plumbing -------------------------------------------------------------------------
    def _auth(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        r = httpx.post(
            f"{self.base}/v1/oauth2/token",
            headers={"Authorization": f"Basic {basic}"},
            data={"grant_type": "client_credentials"},
            timeout=20,
        )
        if r.status_code != 200:
            raise HolderError(f"PayPal sign-in failed ({r.status_code})")
        data = r.json()
        self._token = data["access_token"]
        self._token_exp = time.time() + int(data.get("expires_in", 300))
        return self._token

    def _post(self, path: str, body: dict, request_id: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self._auth()}", "Content-Type": "application/json"}
        if request_id:
            headers["PayPal-Request-Id"] = request_id
        try:
            r = httpx.post(f"{self.base}{path}", headers=headers, json=body, timeout=30)
        except httpx.HTTPError as exc:
            raise HolderError(f"PayPal unreachable: {type(exc).__name__}")
        if r.status_code >= 400:
            raise HolderError(f"PayPal refused {path} ({r.status_code}): {r.text[:300]}")
        return r.json() if r.content else {}

    # --- interface ------------------------------------------------------------------------
    def create_funding(self, amount_cents, currency, reference, request_id):
        data = self._post(
            "/v2/checkout/orders",
            {
                "intent": "CAPTURE",
                "purchase_units": [
                    {
                        "reference_id": reference,
                        "custom_id": reference,
                        "amount": {"currency_code": currency, "value": _money(amount_cents)},
                    }
                ],
                "payment_source": {
                    "paypal": {
                        "experience_context": {
                            "return_url": f"{self.return_url}/paypal/return",
                            "cancel_url": f"{self.return_url}/paypal/cancel",
                            "user_action": "PAY_NOW",
                        }
                    }
                },
            },
            request_id=request_id,
        )
        link = next((l["href"] for l in data.get("links", []) if l.get("rel") in ("payer-action", "approve")), None)
        if not link:
            raise HolderError("PayPal did not return an approval link")
        return {"id": data["id"], "approve_url": link}

    def approve_url(self, funding_id):
        host = "www.sandbox.paypal.com" if "sandbox" in self.base else "www.paypal.com"
        return f"https://{host}/checkoutnow?token={funding_id}"

    def capture_funding(self, funding_id, request_id):
        data = self._post(f"/v2/checkout/orders/{funding_id}/capture", {}, request_id=request_id)
        try:
            cap = data["purchase_units"][0]["payments"]["captures"][0]
        except (KeyError, IndexError):
            return {"status": data.get("status", "UNKNOWN"), "capture_id": ""}
        return {"status": cap.get("status", data.get("status", "UNKNOWN")), "capture_id": cap["id"]}

    def payout(self, receiver, amount_cents, currency, sender_batch_id, note):
        data = self._post(
            "/v1/payments/payouts",
            {
                "sender_batch_header": {
                    "sender_batch_id": sender_batch_id,
                    "email_subject": "EscrowPilot milestone payment (sandbox)",
                },
                "items": [
                    {
                        "recipient_type": "EMAIL",
                        "receiver": receiver,
                        "amount": {"value": _money(amount_cents), "currency": currency},
                        "note": note[:200],
                        "sender_item_id": sender_batch_id,
                    }
                ],
            },
        )
        head = data.get("batch_header", {})
        return {
            "batch_id": head.get("payout_batch_id", ""),
            "status": head.get("batch_status", "PENDING"),
        }

    def refund(self, capture_id, amount_cents, currency, request_id):
        data = self._post(
            f"/v2/payments/captures/{capture_id}/refund",
            {"amount": {"value": _money(amount_cents), "currency_code": currency}},
            request_id=request_id,
        )
        return {"refund_id": data.get("id", ""), "status": data.get("status", "PENDING")}

    def verify_webhook(self, headers, body):
        if not self.webhook_id:
            return False
        h = {k.lower(): v for k, v in headers.items()}
        try:
            event = json.loads(body)
            data = self._post(
                "/v1/notifications/verify-webhook-signature",
                {
                    "auth_algo": h["paypal-auth-algo"],
                    "cert_url": h["paypal-cert-url"],
                    "transmission_id": h["paypal-transmission-id"],
                    "transmission_sig": h["paypal-transmission-sig"],
                    "transmission_time": h["paypal-transmission-time"],
                    "webhook_id": self.webhook_id,
                    "webhook_event": event,
                },
            )
        except (KeyError, ValueError, HolderError):
            return False
        return data.get("verification_status") == "SUCCESS"
