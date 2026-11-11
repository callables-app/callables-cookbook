# Invoices

Find the invoices in your inbox without opening every email. **Find invoices**, in both [Gmail](../google/gmail/) and [Outlook](../microsoft/outlook/), looks at every PDF and image attached to your emails from the last N days. Claude decides which ones are invoices or receipts and reads their details. You get two downloads:

- **`invoices.csv`**: one row per invoice, newest first, with invoice date, vendor, invoice number, total, tax, subtotal, currency, due date, who it's billed to, what it's for, the file's name in the zip, and the email it came in. It opens cleanly in Excel and Google Sheets.
- **`invoices.zip`**: every invoice file, renamed so they sort by date and say whose they are (`2026-11-03 Acme Ltd INV-1042.pdf`), plus the CSV.

Hand both to your accountant at the end of the month, or ask an assistant connected through the [Callables MCP server](https://callables.app/docs/mcp) "what did we spend on software in October?"

## How it's built

    invoices/attachments.py    pulls the PDFs and images out of an email's raw MIME; skips logos, zips and oversize files
    invoices/reader.py         asks Claude whether an attachment is an invoice, and for its fields
    invoices/report.py         the whole job: read the attachments, write the CSV and the zip
    google/gmail/invoices.py   Gmail's Find invoices: searches for emails with attachments, hands over their MIME
    microsoft/outlook/invoices.py   the same for Outlook

None of `invoices/` knows about Gmail or Outlook. Each provider fetches its own emails as raw MIME and calls `invoices.report.find()`, so adding another mail provider is a few lines.

Claude reads each attachment as a PDF or image, so scanned invoices and photos of receipts work as well as generated PDFs. The answer comes back in a fixed format (a Pydantic model in `reader.py`), validated before it reaches the CSV. Add a field there, such as a PO number or VAT number, and it shows up as a column. The model is Claude Haiku: about a cent per one-page attachment. Change `MODEL` in `reader.py` for a more capable one.

The same file sent twice, in a reply or a reminder, is read once.

## Set it up

1. Set up the [Gmail](../google/gmail/README.md) or [Outlook](../microsoft/outlook/README.md) connection, if you haven't.
2. Get an API key at [console.anthropic.com](https://console.anthropic.com/) and set it as the project secret `ANTHROPIC_API_KEY`.
3. Run **Find invoices**.

Locally, put `ANTHROPIC_API_KEY=...` in `.env`, then:

    call gmail find_invoices --days 30
    call outlook find_invoices --days 90 --max-attachments 200

## Notes

- **Your attachments go to Anthropic's API** to be read. Under Anthropic's commercial terms, API inputs aren't used for training. Keep that in mind for mailboxes that hold sensitive documents.
- **Max attachments** (default 100) caps how many Claude reads in one run, and so the cost. The newest emails come first.
- Only PDFs and images are read. Invoices sent as Word or Excel files, or as links to a billing portal, aren't found.
- Text in an attachment can't change what the run does: Claude is told to treat it as data, and its answer is limited to the invoice fields.
