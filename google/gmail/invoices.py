"""Find the invoices in your Gmail: Claude reads every PDF and image attached to your recent emails, and you get a CSV
of the invoices and a zip of their files. The reading and the files are shared with Outlook, in invoices/."""
from callables import File

from google.gmail.gmail_api import Gmail
from google.gmail.inbox import gmail, google
from invoices.report import find

MAX_EMAILS = 2000


@gmail.deploy(title="Find invoices", timeout=900, secrets=["ANTHROPIC_API_KEY"])
def find_invoices(days: int = 30, max_attachments: int = 100, include_receipts: bool = True) -> list[File]:
    """Finds the invoices attached to your emails from the last few days and returns invoices.csv (vendor, number,
    date, total, tax...) and invoices.zip with every invoice file, renamed by date and vendor.

    Claude reads each PDF or image attachment, up to Max attachments (about a cent each). Sent mail, drafts, spam
    and trash are skipped.
    """
    if not 1 <= days <= 365:
        raise ValueError("Days must be between 1 and 365.")
    if not 1 <= max_attachments <= 500:
        raise ValueError("Max attachments must be between 1 and 500.")
    client = Gmail(google.token)
    query = (f"has:attachment newer_than:{days}d -in:sent -in:drafts "
             "{filename:pdf filename:png filename:jpg filename:jpeg filename:gif filename:webp}")
    ids = client.search(query, MAX_EMAILS)
    return find(client.raws(ids), f"your Gmail from the last {days} days", max_attachments, include_receipts)
