"""Pulling the attachments worth reading out of emails. No callables, and nothing Gmail- or Outlook-specific: both
hand over each email as raw MIME (what a .eml file holds), and this takes it from there."""
import hashlib
import mimetypes
import re
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr

# What Claude can read: PDFs and images. Office files and zips are skipped.
READABLE = {
    "application/pdf": "pdf",
    "image/png": "image", "image/jpeg": "image", "image/gif": "image", "image/webp": "image",
}
MIN_IMAGE_BYTES = 15_000      # smaller images are logos and signature icons, not scanned invoices
MAX_BYTES = 20 * 1024 * 1024  # leaves room under Claude's 32 MB request limit once base64-encoded
UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')


@dataclass
class Attachment:
    name: str
    content_type: str
    data: bytes
    email_subject: str
    email_from: str
    email_date: datetime
    digest: str  # the file's SHA-256, so the same invoice sent twice is read once


def safe_name(text: str, max_length: int = 120) -> str:
    """A file name that works on Windows, macOS and Linux, keeping the extension."""
    text = re.sub(r"\s+", " ", UNSAFE.sub("", text)).strip().rstrip(". ")
    stem, dot, ext = text.rpartition(".")
    if dot and stem and len(ext) <= 5:
        return f"{stem[:max_length - len(ext) - 1].rstrip('. ')}.{ext}"
    return text[:max_length] or "file"


def _content_type(part) -> str:
    """The attachment's real type: mail clients often send PDFs as application/octet-stream."""
    declared = part.get_content_type()
    if declared in READABLE:
        return declared
    guessed = mimetypes.guess_type(part.get_filename() or "")[0]
    return guessed if guessed in READABLE else declared


def readable(raw: bytes, received: datetime) -> list[Attachment]:
    """The PDFs and images attached to one email, skipping logos, oversize files and everything else."""
    message = BytesParser(policy=policy.default).parsebytes(raw)
    name, address = parseaddr(str(message.get("from", "")))
    out = []
    for number, part in enumerate(message.iter_attachments(), start=1):
        content_type = _content_type(part)
        if content_type not in READABLE:
            continue
        data = part.get_payload(decode=True) or b""
        if not data or len(data) > MAX_BYTES or (READABLE[content_type] == "image" and len(data) < MIN_IMAGE_BYTES):
            continue
        filename = part.get_filename() or f"attachment {number}{mimetypes.guess_extension(content_type) or ''}"
        out.append(Attachment(
            name=safe_name(filename),
            content_type=content_type,
            data=data,
            email_subject=str(message.get("subject", "")) or "(no subject)",
            email_from=f"{name} <{address}>" if name else address,
            email_date=received,
            digest=hashlib.sha256(data).hexdigest(),
        ))
    return out
