"""The whole job, once each provider has fetched its emails: read the attachments, then write the CSV and the zip.
No callables: google/gmail/invoices.py and microsoft/outlook/invoices.py call find() with their own emails."""
import csv
import io
import tempfile
import zipfile
from datetime import date, datetime
from pathlib import Path

from callables import File

from invoices.attachments import Attachment, readable, safe_name
from invoices.reader import Invoice, read_all

COLUMNS = ["invoice_date", "vendor", "invoice_number", "total", "tax", "subtotal", "currency", "due_date", "kind",
           "bill_to", "description", "file", "email_from", "email_subject", "email_date"]


def collect(emails, limit: int) -> tuple[list[Attachment], int]:
    """The readable attachments from (raw MIME, received) pairs, each file once, up to `limit`. Also how many
    emails were opened."""
    found, seen, opened = [], set(), 0
    for raw, received in emails:
        opened += 1
        for attachment in readable(raw, received):
            if attachment.digest not in seen:
                seen.add(attachment.digest)
                found.append(attachment)
        if len(found) >= limit:
            break
    return found[:limit], opened


def _zip_name(attachment: Attachment, invoice: Invoice, taken: set[str]) -> str:
    """"2026-11-03 Acme Ltd INV-1042.pdf": sorts by date, says whose it is. "(2)" when two would clash."""
    ext = attachment.name.rpartition(".")[2] if "." in attachment.name else "pdf"
    parts = [invoice.invoice_date or attachment.email_date.date().isoformat(), invoice.vendor or "Unknown vendor",
             invoice.invoice_number or ""]
    name = safe_name(" ".join(p for p in parts if p) + f".{ext}")
    stem, n, candidate = name.rpartition(".")[0], 1, name
    while candidate.lower() in taken:
        n += 1
        candidate = f"{stem} ({n}).{ext}"
    taken.add(candidate.lower())
    return candidate


def find(emails, label: str, max_attachments: int, include_receipts: bool) -> list[File]:
    """Reads the attachments in `emails` ((raw MIME, received) pairs, newest first) and returns invoices.csv and
    invoices.zip (every invoice file, renamed by date and vendor, plus the CSV)."""
    attachments, opened = collect(emails, max_attachments)
    if not attachments:
        raise ValueError(f"No PDF or image attachments in {label} ({opened} emails with attachments looked at).")
    print(f"Reading {len(attachments)} attachments from {opened} emails...")

    kinds = {"invoice", "credit note"} | ({"receipt"} if include_receipts else set())
    rows, files, taken = [], [], set()
    for attachment, invoice in read_all(attachments):
        if not invoice or not invoice.is_invoice or invoice.kind not in kinds:
            continue
        file_name = _zip_name(attachment, invoice, taken)
        files.append((file_name, attachment))
        rows.append({**invoice.model_dump(exclude={"is_invoice"}), "file": file_name,
                     "email_from": attachment.email_from, "email_subject": attachment.email_subject,
                     "email_date": attachment.email_date.date().isoformat()})
    if not rows:
        raise ValueError(f"None of the {len(attachments)} attachments in {label} is an invoice"
                         f"{' or receipt' if include_receipts else ''}.")
    rows.sort(key=lambda r: r["invoice_date"] or r["email_date"], reverse=True)

    text = io.StringIO()
    writer = csv.DictWriter(text, fieldnames=COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

    out = Path(tempfile.mkdtemp())
    stamp = date.today().isoformat()
    csv_path = out / "invoices.csv"
    csv_path.write_text(text.getvalue(), encoding="utf-8-sig")  # the BOM makes Excel read accents correctly
    zip_path = out / "invoices.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("invoices.csv", text.getvalue().encode("utf-8-sig"))
        for file_name, attachment in files:
            when = attachment.email_date.timetuple()[:6] if isinstance(attachment.email_date, datetime) else None
            zf.writestr(zipfile.ZipInfo(file_name, when) if when else file_name, attachment.data, zipfile.ZIP_DEFLATED)

    totals: dict[str, float] = {}
    for r in rows:
        if r["total"] is not None:
            totals[r["currency"] or "?"] = totals.get(r["currency"] or "?", 0) + r["total"]
    print(f"Found {len(rows)} invoices in {len(attachments)} attachments. Totals: "
          + (", ".join(f"{v:,.2f} {k}" for k, v in sorted(totals.items())) or "none"))
    return [File(csv_path, name=f"invoices {stamp}.csv"), File(zip_path, name=f"invoices {stamp}.zip")]
