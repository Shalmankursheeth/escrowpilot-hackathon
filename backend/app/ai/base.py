"""AI provider interface. The AI only READS and EXTRACTS. It never decides or moves money."""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Protocol

ALLOWED_PROOFS = {
    "order_confirmation",
    "bill_of_lading",
    "commercial_invoice",
    "packing_list",
    "delivery_receipt",
    "return_receipt",
}


class AIError(Exception):
    """The AI could not produce a usable, valid answer."""


@dataclass
class MilestoneTerm:
    name: str
    share_pct: int
    required_proof: str


@dataclass
class ContractTerms:
    seller_name: str
    buyer_name: str
    goods: str | None
    quantity: int | None
    total_cents: int
    currency: str
    inspection_days: int | None
    milestones: list[MilestoneTerm] = field(default_factory=list)


class AIProvider(Protocol):
    name: str

    def parse_contract(self, text: str) -> ContractTerms: ...

    def extract_document(self, text: str) -> dict: ...

    def extract_file(self, data: bytes, mime: str) -> dict: ...

    def summarize_dispute(self, facts: dict) -> str: ...


def plain_dispute_summary(facts: dict) -> str:
    """A neutral, fact-only brief for the human reviewer. Used offline and as the fallback for the live model."""
    parts = [f"Stage '{facts.get('stage')}' ({facts.get('amount')}) is in dispute."]
    if facts.get("dispute_reason"):
        parts.append(f"The buyer says: \"{facts['dispute_reason']}\".")
    if facts.get("contract"):
        parts.append(f"The contract is for {facts['contract']}.")
    docs = facts.get("documents") or []
    if docs:
        parts.append("Documents on file: " + "; ".join(
            f"{d['type']} {d.get('number') or '(no number)'}" + (f" quantity {d['quantity']}" if d.get("quantity") is not None else "")
            for d in docs) + ".")
    failed = facts.get("failed_checks") or []
    parts.append("Automated checks found problems: " + "; ".join(failed) + "." if failed else "Automated document checks all passed.")
    parts.append(f"Proof that the goods were sent back: {facts.get('return_proof')}.")
    parts.append(f"Seller deposit: {facts.get('deposit')}.")
    parts.append("This is a summary of facts only. It does not say who is at fault; the reviewer decides.")
    return " ".join(parts)


def to_cents(value) -> int:
    try:
        return int((Decimal(str(value).replace(",", "").replace("$", "").strip()) * 100).to_integral_value())
    except (InvalidOperation, ValueError):
        raise AIError(f"Could not read an amount from {value!r}")


def _int_or_none(v):
    if v in (None, "", "null"):
        return None
    try:
        return int(str(v).replace(",", "").split()[0])
    except (ValueError, IndexError):
        return None


def terms_from_dict(d: dict) -> ContractTerms:
    """Validate and normalise a dict that came from an AI model."""
    try:
        milestones = [
            MilestoneTerm(
                name=str(m["name"]).strip()[:200],
                share_pct=int(m["share_pct"]),
                required_proof=str(m["required_proof"]).strip(),
            )
            for m in d["milestones"]
        ]
        terms = ContractTerms(
            seller_name=str(d["seller_name"]).strip(),
            buyer_name=str(d["buyer_name"]).strip(),
            goods=(str(d["goods"]).strip()[:300] if d.get("goods") else None),
            quantity=_int_or_none(d.get("quantity")),
            total_cents=to_cents(d["total_amount"]),
            currency=str(d.get("currency") or "USD").upper()[:3],
            inspection_days=_int_or_none(d.get("inspection_days")),
            milestones=milestones,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AIError(f"AI answer is missing or has bad fields: {exc}")
    return terms


def normalize_doc(d: dict) -> dict:
    """Validate and normalise extracted document fields."""
    doc_type = str(d.get("doc_type") or "unknown").strip().lower().replace(" ", "_")
    if doc_type not in ALLOWED_PROOFS:
        doc_type = "unknown"
    return {
        "doc_type": doc_type,
        "document_number": (str(d["document_number"]).strip() if d.get("document_number") else None),
        "shipper": (str(d["shipper"]).strip() if d.get("shipper") else None),
        "consignee": (str(d["consignee"]).strip() if d.get("consignee") else None),
        "goods": (str(d["goods"]).strip() if d.get("goods") else None),
        "quantity": _int_or_none(d.get("quantity")),
        "date": (str(d["date"]).strip() if d.get("date") else None),
    }
