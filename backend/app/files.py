"""Turn an uploaded file into extracted document fields. Files are untrusted: sniff the real type, cap the size,
never trust the filename or declared content type."""
import base64
import binascii
import hashlib
import io

from fastapi import HTTPException

from .ai import AIError, AIProvider
from .ai.base import normalize_doc  # noqa: F401  (re-export for tests)
from .config import get_settings

MAX_FILE_BYTES = 5 * 1024 * 1024


def _sniff(data: bytes) -> str:
    if data.startswith(b"%PDF"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    try:
        data[:2000].decode("utf-8")
        return "text/plain"
    except UnicodeDecodeError:
        return "unknown"


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise AIError("The PDF is password protected")
        return "\n".join((p.extract_text() or "") for p in reader.pages[:10]).strip()
    except AIError:
        raise
    except Exception:
        raise AIError("The PDF could not be read")


def read_document(body, ai: AIProvider) -> tuple[dict, str, str | None]:
    """Return (extracted_fields, text_kept_as_evidence, sha256_of_file_or_None)."""
    max_text = get_settings().max_text_bytes
    if body.data_b64:
        try:
            data = base64.b64decode(body.data_b64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=422, detail="The uploaded file is not valid")
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail="File is larger than 5 MB")
        kind = _sniff(data)
        digest = hashlib.sha256(data).hexdigest()
        try:
            if kind == "application/pdf":
                text = _pdf_text(data)
                if len(text) >= 20:
                    return ai.extract_document(text[:max_text]), text[:max_text], digest
                return ai.extract_file(data, kind), "[scanned PDF, read by AI vision]", digest  # no text layer
            if kind in ("image/png", "image/jpeg"):
                return ai.extract_file(data, kind), f"[image {kind}, read by AI vision]", digest
            if kind == "text/plain":
                text = data.decode("utf-8", "replace")
                return ai.extract_document(text[:max_text]), text[:max_text], digest
        except AIError as exc:
            raise HTTPException(status_code=422, detail=f"Could not read the document: {exc}")
        raise HTTPException(status_code=422, detail="Upload a PDF, PNG, JPEG or text file")
    text = body.text or ""
    if len(text.encode()) > max_text:
        raise HTTPException(status_code=413, detail="Document text is too large")
    try:
        return ai.extract_document(text), text, hashlib.sha256(text.strip().encode()).hexdigest()
    except AIError as exc:
        raise HTTPException(status_code=422, detail=f"Could not read the document: {exc}")
