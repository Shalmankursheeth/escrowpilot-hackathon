"""Offline provider: fixed rules on the sample documents. Free, fast and needs no key."""
import re

from .base import AIError, ContractTerms, MilestoneTerm, normalize_doc, plain_dispute_summary, to_cents

_PARTIES_SELLER_FIRST = re.compile(r"between\s+(.+?)\s*\(\s*Seller\s*\)\s+and\s+(.+?)\s*\(\s*Buyer\s*\)", re.I | re.S)
_PARTIES_BUYER_FIRST = re.compile(r"between\s+(.+?)\s*\(\s*Buyer\s*\)\s+and\s+(.+?)\s*\(\s*Seller\s*\)", re.I | re.S)
_TOTAL = re.compile(r"total\s*(?:amount)?\s*:?\s*(?:USD|\$)?\s*\$?\s*([\d,]+(?:\.\d{1,2})?)", re.I)
_QTY = re.compile(r"([\d,]+)\s+units", re.I)
_GOODS = re.compile(r"goods\s*:\s*[\d,]*\s*(?:units\s+of\s+)?(.+?)(?:\s+at\s+\$|\.\s|\.$|\n|$)", re.I)
_MILESTONE = re.compile(r"(\d{1,3})\s*%\s*(?:on|upon|at|after)\s+([^,.;(\n]+)", re.I)
_INSPECTION = re.compile(r"inspection\s+window\s*:?\s*(?:of\s+)?(\d+)\s+days", re.I)

_DOC_TITLES = {
    "ORDER CONFIRMATION": "order_confirmation",
    "BILL OF LADING": "bill_of_lading",
    "COMMERCIAL INVOICE": "commercial_invoice",
    "PACKING LIST": "packing_list",
    "DELIVERY RECEIPT": "delivery_receipt",
    "RETURN RECEIPT": "return_receipt",
}
_FIELD_ALIASES = {
    "shipper": "shipper", "seller": "shipper", "exporter": "shipper",
    "consignee": "consignee", "buyer": "consignee", "receiver": "consignee", "importer": "consignee",
    "document number": "document_number", "doc number": "document_number", "number": "document_number",
    "goods": "goods", "description": "goods", "quantity": "quantity", "date": "date",
}


def _proof_for(name: str) -> str:
    n = name.lower()
    if "ship" in n or "lading" in n or "dispatch" in n:
        return "bill_of_lading"
    if "deliver" in n or "receiv" in n:
        return "delivery_receipt"
    return "order_confirmation"


class OfflineProvider:
    name = "offline"

    def parse_contract(self, text: str) -> ContractTerms:
        m = _PARTIES_SELLER_FIRST.search(text)
        if m:
            seller, buyer = m.group(1).strip(), m.group(2).strip()
        else:
            m = _PARTIES_BUYER_FIRST.search(text)
            if not m:
                raise AIError("Could not find the buyer and seller (expected '... between X (Seller) and Y (Buyer)').")
            buyer, seller = m.group(1).strip(), m.group(2).strip()
        total = _TOTAL.search(text)
        if not total:
            raise AIError("Could not find the total amount (expected 'Total $50,000').")
        milestones = [
            MilestoneTerm(name=n.strip().capitalize(), share_pct=int(p), required_proof=_proof_for(n))
            for p, n in _MILESTONE.findall(text)
        ]
        if not milestones:
            raise AIError("Could not find payment terms (expected '30% on order confirmation, ...').")
        qty = _QTY.search(text)
        goods = _GOODS.search(text)
        insp = _INSPECTION.search(text)
        return ContractTerms(
            seller_name=seller,
            buyer_name=buyer,
            goods=goods.group(1).strip() if goods else None,
            quantity=int(qty.group(1).replace(",", "")) if qty else None,
            total_cents=to_cents(total.group(1)),
            currency="USD",
            inspection_days=int(insp.group(1)) if insp else None,
            milestones=milestones,
        )

    def summarize_dispute(self, facts: dict) -> str:
        return plain_dispute_summary(facts)

    def extract_file(self, data: bytes, mime: str) -> dict:
        raise AIError("Reading scanned documents and photos needs the Gemini provider (set AI_PROVIDER=gemini and GEMINI_API_KEY)")

    def extract_document(self, text: str) -> dict:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        raw: dict = {"doc_type": "unknown"}
        if lines:
            raw["doc_type"] = _DOC_TITLES.get(lines[0].upper().rstrip(":"), "unknown")
        for ln in lines[1:]:
            if ":" not in ln:
                continue
            key, _, value = ln.partition(":")
            canon = _FIELD_ALIASES.get(key.strip().lower())
            if canon and canon not in raw:
                raw[canon] = value.strip()
        return normalize_doc(raw)
