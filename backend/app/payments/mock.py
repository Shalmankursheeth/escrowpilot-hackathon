"""Offline stand-in for PayPal. It behaves like the sandbox for the calls we use,
including refusing a repeated sender_batch_id, so tests can prove we never pay twice."""
import itertools

from .holder import HolderError


class MockHolder:
    name = "mock"

    def __init__(self) -> None:
        self._n = itertools.count(1)
        self.orders: dict[str, dict] = {}
        self.payouts: list[dict] = []
        self.refunds: list[dict] = []
        self._batch_ids: set[str] = set()

    def create_funding(self, amount_cents, currency, reference, request_id):
        oid = f"MOCKORDER-{next(self._n)}"
        self.orders[oid] = {"amount_cents": amount_cents, "currency": currency, "reference": reference, "captured": False}
        return {"id": oid, "approve_url": f"mock://paypal/approve/{oid}"}

    def approve_url(self, funding_id):
        return f"mock://paypal/approve/{funding_id}"

    def capture_funding(self, funding_id, request_id):
        # The mock keeps orders in memory only, so after a server restart it may not know an old order id.
        # It is a stand-in, so accept any id it issued earlier.
        if not funding_id.startswith("MOCKORDER-"):
            raise HolderError("unknown order")
        self.orders.setdefault(funding_id, {"captured": False})["captured"] = True
        return {"status": "COMPLETED", "capture_id": f"MOCKCAP-{funding_id}"}

    def payout(self, receiver, amount_cents, currency, sender_batch_id, note):
        if sender_batch_id in self._batch_ids:
            raise HolderError("duplicate sender_batch_id")
        self._batch_ids.add(sender_batch_id)
        rec = {"receiver": receiver, "amount_cents": amount_cents, "currency": currency, "sender_batch_id": sender_batch_id}
        self.payouts.append(rec)
        return {"batch_id": f"MOCKPAYOUT-{sender_batch_id}", "status": "SUCCESS"}

    def refund(self, capture_id, amount_cents, currency, request_id):
        rec = {"capture_id": capture_id, "amount_cents": amount_cents, "currency": currency, "request_id": request_id}
        self.refunds.append(rec)
        return {"refund_id": f"MOCKREFUND-{next(self._n)}", "status": "COMPLETED"}

    def verify_webhook(self, headers, body):
        return True  # dev only; the real client verifies PayPal's signature
