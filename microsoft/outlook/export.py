"""Export the attachments from your latest Outlook emails: a zip per thread, named after the thread's subject."""
import hashlib
import mimetypes
import re
import tempfile
import zipfile
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path

from callables import File
from microsoft.outlook.graph_api import Graph, Message
from microsoft.outlook.inbox import INBOX, mail, outlook

MAX_EMAILS = 500
# A run can hand back 20 files and 100 MB in all; stop a little short of the size so the last zip always fits
MAX_ZIPS = 20
MAX_TOTAL_BYTES = 95 * 1024 * 1024
# Characters Windows, macOS or Linux won't take in a file name, and control characters
UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
# Names Windows keeps for devices, even with an extension (CON.txt)
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))}
# "RE: ", "Fwd: ", "AW: "... at the front of a reply's subject, so every email in a thread has the same one
REPLY_PREFIX = re.compile(r"^\s*((re|fw|fwd|aw|wg|sv|vs|tr|rv)\s*(\[\d+\])?\s*:\s*)+", re.IGNORECASE)


def clean_name(text: str, max_length: int, fallback: str) -> str:
    """`text` as a file name that works everywhere: unsafe characters stripped, spaces collapsed, no trailing dots or
    spaces, and cut to `max_length` characters."""
    # Tabs and line breaks become spaces first, so the words either side stay apart
    name = re.sub(r"\s+", " ", UNSAFE.sub("", re.sub(r"\s+", " ", text))).strip()
    name = name[:max_length].rstrip(". ") or fallback
    if name.split(".")[0].upper() in RESERVED:
        name = f"_{name}"
    return name


def clean_file_name(text: str, max_length: int, fallback: str) -> str:
    """Like clean_name, but keeps the extension when the name has to be cut."""
    stem, dot, ext = text.rpartition(".")
    if not dot or not stem or len(ext) > 10:
        return clean_name(text, max_length, fallback)
    ext = clean_name(ext, 10, "")
    return f"{clean_name(stem, max(1, max_length - len(ext) - 1), fallback)}.{ext}" if ext else clean_name(stem, max_length, fallback)


def unique(name: str, taken: set[str]) -> str:
    """`name`, or `name (2).ext`, `name (3).ext`... if it's already used. Case doesn't count, as on Windows and macOS."""
    stem, dot, ext = name.rpartition(".") if "." in name[1:] else (name, "", "")
    candidate, n = name, 1
    while candidate.lower() in taken:
        n += 1
        candidate = f"{stem} ({n}){dot}{ext}"
    taken.add(candidate.lower())
    return candidate


def thread_subject(subject: str) -> str:
    """The subject without reply and forward prefixes: "RE: Fwd: Invoice" is "Invoice"."""
    return REPLY_PREFIX.sub("", subject).strip() or "No subject"


def attachments(message: EmailMessage, max_length: int):
    """(file name, bytes) for each attachment. An attached email comes out as its own .eml file."""
    for number, part in enumerate(message.iter_attachments(), start=1):
        if part.get_content_type() == "message/rfc822":
            inner = part.get_content()
            data = inner.as_bytes(policy=policy.SMTP)
            name = part.get_filename() or f"{inner.get('subject') or 'Attached email'}.eml"
            if not name.lower().endswith(".eml"):
                name += ".eml"
        else:
            data = part.get_payload(decode=True) or b""
            name = part.get_filename() or f"attachment {number}{mimetypes.guess_extension(part.get_content_type()) or ''}"
        yield clean_file_name(name, max_length, f"attachment {number}"), data


def by_thread(messages: list[Message]) -> dict[str, list[Message]]:
    """The emails with attachments, grouped by thread, newest thread first and oldest email first within each."""
    threads: dict[str, list[Message]] = {}
    for m in messages:  # newest first, so threads come out in the order their latest email arrived
        if m.has_attachments:
            threads.setdefault(m.conversation_id or m.id, []).append(m)
    return {key: sorted(found, key=lambda m: m.received) for key, found in threads.items()}


@mail.deploy(title="Export attachments by thread", timeout=900)
def export_attachments(count: int = 50, max_name_length: int = 80) -> list[File]:
    """The attachments from your newest inbox emails, as a zip per thread named after the thread's subject."""
    if not 1 <= count <= MAX_EMAILS:
        raise ValueError(f"count must be between 1 and {MAX_EMAILS}")
    if not 10 <= max_name_length <= 150:
        raise ValueError("max_name_length must be between 10 and 150")
    client = Graph(outlook.token)
    # Graph wants the sort field in the filter too; this one matches every email
    messages = client.messages(INBOX, "receivedDateTime ge 1900-01-01T00:00:00Z", count)
    threads = by_thread(messages)
    if not threads:
        raise ValueError(f"None of your latest {len(messages)} inbox emails have attachments.")

    parser = BytesParser(policy=policy.default)
    out = Path(tempfile.mkdtemp())
    zip_names: set[str] = set()
    files: list[File] = []
    total, left_out = 0, 0
    for emails in threads.values():
        if len(files) == MAX_ZIPS or total >= MAX_TOTAL_BYTES:
            left_out += 1
            continue
        name = unique(clean_name(thread_subject(emails[0].subject), max_name_length, "No subject"), zip_names)
        path = out / f"{len(files)}.zip"
        names: set[str] = set()
        seen: set[bytes] = set()  # the same file attached again further down a thread goes in once
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for message, raw in zip(emails, client.mimes([m.id for m in emails])):
                stamp = message.received.timetuple()[:6]  # each file dated when its email arrived
                for file_name, data in attachments(parser.parsebytes(raw), max_name_length):
                    digest = hashlib.sha256(file_name.lower().encode() + b"\0" + data).digest()
                    if digest in seen:
                        continue
                    seen.add(digest)
                    zf.writestr(zipfile.ZipInfo(unique(file_name, names), stamp), data, zipfile.ZIP_DEFLATED)
        if not names:  # Outlook said it had attachments, but they were all inline (a signature logo, say)
            zip_names.discard(name.lower())
            continue
        size = path.stat().st_size
        if total + size > MAX_TOTAL_BYTES:
            left_out += 1
            zip_names.discard(name.lower())
            continue
        total += size
        files.append(File(path, name=f"{name}.zip"))

    if not files:
        raise ValueError(f"The attachments in your latest {len(messages)} inbox emails are all inline images, so there's "
                         "nothing to export.")
    print(f"Exported attachments from {len(files)} thread(s), {total / 1_048_576:.1f} MB in all.")
    if left_out:
        print(f"{left_out} older thread(s) were left out: a run can hand back {MAX_ZIPS} files and 100 MB. "
              "Export fewer emails to get them.")
    return files
