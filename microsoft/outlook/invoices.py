"""Find the invoices in your Outlook mailbox: Claude reads every PDF and image attached to your recent emails, and you
get a CSV of the invoices and a zip of their files. The reading and the files are shared with Gmail, in invoices/."""
from callables import File

from invoices.report import find
from microsoft.outlook.graph_api import SKIP_FOLDERS, Graph, since
from microsoft.outlook.inbox import mail, outlook

MAX_EMAILS = 2000


@mail.deploy(title="Find invoices", timeout=900, secrets=["ANTHROPIC_API_KEY"])
def find_invoices(days: int = 30, max_attachments: int = 100, include_receipts: bool = True) -> list[File]:
    """Finds the invoices attached to your emails from the last few days and returns invoices.csv (vendor, number,
    date, total, tax...) and invoices.zip with every invoice file, renamed by date and vendor.

    Claude reads each PDF or image attachment, up to Max attachments (about a cent each). Every folder is searched
    except Sent Items, Drafts, Deleted Items and Junk.
    """
    if not 1 <= days <= 365:
        raise ValueError("Days must be between 1 and 365.")
    if not 1 <= max_attachments <= 500:
        raise ValueError("Max attachments must be between 1 and 500.")
    client = Graph(outlook.token)
    skip = client.folder_ids(SKIP_FOLDERS)
    # Graph wants the sort field (receivedDateTime) first in the filter
    messages = [m for m in client.messages("/me/messages", f"receivedDateTime ge {since(days)} and hasAttachments eq true",
                                           MAX_EMAILS) if m.folder_id not in skip]
    emails = zip(client.mimes([m.id for m in messages]), (m.received for m in messages))
    return find(emails, f"your Outlook from the last {days} days", max_attachments, include_receipts)
