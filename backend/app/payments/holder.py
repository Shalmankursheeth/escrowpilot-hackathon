"""The funds-holding adapter.

The demo implements this with PayPal (sandbox, test money). A licensed escrow or bank partner can
implement the same interface later, and later still your own licensed holding, without changing the rest.
"""
from typing import Protocol


class HolderError(Exception):
    """The funds holder refused or failed a request."""


class FundsHolder(Protocol):
    name: str

    def create_funding(self, amount_cents: int, currency: str, reference: str, request_id: str) -> dict:
        """Returns {'id': str, 'approve_url': str}."""

    def approve_url(self, funding_id: str) -> str:
        """The page where the buyer approves an order that was already created (used when they come back to it)."""

    def capture_funding(self, funding_id: str, request_id: str) -> dict:
        """Returns {'status': 'COMPLETED' | ..., 'capture_id': str}."""

    def payout(self, receiver: str, amount_cents: int, currency: str, sender_batch_id: str, note: str) -> dict:
        """Returns {'batch_id': str, 'status': str}. Must refuse a repeated sender_batch_id."""

    def refund(self, capture_id: str, amount_cents: int, currency: str, request_id: str) -> dict:
        """Returns {'refund_id': str, 'status': str}."""

    def verify_webhook(self, headers: dict, body: bytes) -> bool: ...
