from ..config import get_settings
from .base import AIError, AIProvider, ContractTerms
from .gemini import GeminiProvider
from .offline import OfflineProvider


class FallbackProvider:
    """Tries the live model first; on any AI error falls back to the offline rules so a demo never breaks."""

    def __init__(self, primary: AIProvider, fallback: AIProvider):
        self.primary, self.fallback = primary, fallback
        self.name = f"{primary.name}+{fallback.name}"

    def parse_contract(self, text: str) -> ContractTerms:
        try:
            return self.primary.parse_contract(text)
        except AIError:
            return self.fallback.parse_contract(text)

    def extract_document(self, text: str) -> dict:
        try:
            return self.primary.extract_document(text)
        except AIError:
            return self.fallback.extract_document(text)

    def summarize_dispute(self, facts: dict) -> str:
        try:
            return self.primary.summarize_dispute(facts)
        except AIError:
            return self.fallback.summarize_dispute(facts)

    def extract_file(self, data: bytes, mime: str) -> dict:
        try:
            return self.primary.extract_file(data, mime)
        except AIError as exc:
            raise AIError(f"{exc}. The offline reader cannot read scanned files.")


_provider: AIProvider | None = None


def get_ai() -> AIProvider:
    global _provider
    if _provider is None:
        s = get_settings()
        offline = OfflineProvider()
        if s.ai_provider == "gemini" and s.gemini_api_key:
            live = GeminiProvider(s.gemini_api_key, s.gemini_model)
            _provider = FallbackProvider(live, offline) if s.ai_fallback_offline else live
        else:
            _provider = offline
    return _provider


__all__ = ["AIError", "AIProvider", "ContractTerms", "get_ai"]
