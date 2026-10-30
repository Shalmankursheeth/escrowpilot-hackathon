from ..config import get_settings
from .holder import FundsHolder, HolderError
from .mock import MockHolder
from .paypal import PayPalHolder

_holder: FundsHolder | None = None


def get_holder() -> FundsHolder:
    global _holder
    if _holder is None:
        s = get_settings()
        if s.paypal_mode == "sandbox":
            _holder = PayPalHolder(
                s.paypal_base_url, s.paypal_client_id, s.paypal_client_secret, s.paypal_webhook_id, s.public_app_url
            )
        else:
            _holder = MockHolder()
    return _holder


def reset_holder() -> None:
    """For tests: drop the cached holder so a fresh mock is created."""
    global _holder
    _holder = None


__all__ = ["FundsHolder", "HolderError", "get_holder", "reset_holder"]
