"""Outlook automations that run on the mailbox of whoever runs them: each person connects their own Microsoft 365
account. The same callables as the gmail/ folder, on Microsoft Graph."""
from collections import Counter
from datetime import datetime, timedelta, timezone

from callables import Connection, Group, Next, Secret
from graph_api import Graph, from_sender, since

# The app's details come from project secrets (and .env locally), never from code. MS_TENANT_ID is your
# Directory (tenant) ID, or "common" for a multi-tenant app.
outlook = Connection(
    "outlook",
    provider="microsoft",
    scopes=["Mail.ReadWrite", "Mail.Send"],
    client_id=Secret("MS_CLIENT_ID"),
    client_secret=Secret("MS_CLIENT_SECRET"),
    values={"tenant": Secret("MS_TENANT_ID")},
)

mail = Group("outlook", title="Outlook", description="Work with your own Outlook mailbox", connections=[outlook])

INBOX = "/me/mailFolders/inbox/messages"
SCAN_LIMIT = 1000  # messages read for the last-N-days breakdown


def _pct(part: int, whole: int) -> str:
    return f"{round(100 * part / whole)}%" if whole else "0%"


@mail.deploy(title="Summarize my inbox", timeout=300)
def summarize_inbox(days: int = 7) -> str:
    """Statistics for your inbox: what's in it now, and what arrived in the last few days, by Focused and Other, day
    and sender."""
    if not 1 <= days <= 90:
        raise ValueError("days must be between 1 and 90")
    client = Graph(outlook.token)
    inbox = client.folder("inbox")
    messages = client.messages(INBOX, f"receivedDateTime ge {since(days)}", SCAN_LIMIT)

    out = [
        "### Your inbox now",
        "",
        "| | Messages |",
        "|---|---:|",
        f"| In the inbox | {inbox.get('totalItemCount', 0):,} |",
        f"| Unread | {inbox.get('unreadItemCount', 0):,} |",
        "",
        f"### Last {days} day{'s' if days != 1 else ''}",
        "",
    ]
    if not messages:
        out.append("Nothing arrived in your inbox.")
        return "\n".join(out)

    total = len(messages)
    unread = sum(m.unread for m in messages)
    flagged = sum(m.flagged for m in messages)
    important = sum(m.important for m in messages)
    attachments = sum(m.has_attachments for m in messages)
    senders = Counter(m.sender_email for m in messages)
    names = {m.sender_email: m.sender_name for m in messages}
    capped = " (the newest, the scan is capped here)" if total >= SCAN_LIMIT else ""
    out += [
        f"- **{total:,}** received{capped}, about **{total / days:.1f}** a day",
        f"- **{unread:,}** still unread ({_pct(unread, total)})",
        f"- **{important:,}** marked high importance, **{flagged:,}** flagged, **{attachments:,}** with attachments",
        f"- From **{len(senders):,}** different senders",
        "",
    ]

    split = Counter("Focused" if m.focused else "Other" for m in messages)
    unread_split = Counter("Focused" if m.focused else "Other" for m in messages if m.unread)
    out += ["**Focused and Other**", "", "| | Received | Unread | Share |", "|---|---:|---:|---:|"]
    out += [f"| {name} | {n:,} | {unread_split[name]:,} | {_pct(n, total)} |" for name, n in split.most_common()]
    out.append("")

    today = datetime.now(timezone.utc).date()
    per_day = Counter(m.received.date() for m in messages)
    out += ["**By day** (UTC)", "", "| Day | Received |", "|---|---:|"]
    for offset in range(min(days, 14)):
        day = today - timedelta(days=offset)
        out.append(f"| {day:%a %d %b} | {per_day[day]:,} |")
    if days > 14:
        out.append(f"| _earlier_ | {sum(n for d, n in per_day.items() if d <= today - timedelta(days=14)):,} |")
    out.append("")

    out += ["**Top senders**", "", "| Sender | Received | Unread |", "|---|---:|---:|"]
    unread_by = Counter(m.sender_email for m in messages if m.unread)
    for address, n in senders.most_common(10):
        out.append(f"| {names[address]} ({address}) | {n:,} | {unread_by[address]:,} |")
    return "\n".join(out)


@mail.deploy(title="Archive emails from a sender", timeout=300)
def archive_from_sender(sender: str, older_than_days: int = 0, dry_run: bool = True) -> str:
    """Moves every inbox email from one sender to Archive. Leave dry run on to see what would move."""
    if older_than_days < 0:
        raise ValueError("older_than_days can't be negative")
    query = from_sender(sender, older_than_days)
    address = sender.strip().lower()
    client = Graph(outlook.token)
    messages = client.messages(INBOX, query, 5000)
    if not messages:
        return f"No inbox emails from {address}" + (f" older than {older_than_days} days." if older_than_days else ".")
    if dry_run:
        lines = "\n".join(f"- {m.received:%d %b} · {m.subject}" for m in messages[:5])
        more = f"\n- …and {len(messages) - 5} more" if len(messages) > 5 else ""
        return (f"**Dry run:** {len(messages)} email(s) from {address} would be archived.\n\n{lines}{more}\n\n"
                "Run again with dry run off to archive them.")
    client.archive([m.id for m in messages])
    return f"Archived {len(messages)} email(s) from {address}. They're in your Archive folder."


@mail.deploy(title="Recent senders", timeout=180,
             next=[Next(archive_from_sender, label="Archive their emails", sender="email")])
def recent_senders(days: int = 7, limit: int = 25) -> list[dict]:
    """Who has emailed you most in the last few days, with how many are still unread."""
    if not 1 <= days <= 90:
        raise ValueError("days must be between 1 and 90")
    client = Graph(outlook.token)
    messages = client.messages(INBOX, f"receivedDateTime ge {since(days)}", 500)
    senders: dict[str, dict] = {}
    for m in messages:
        if not m.sender_email:
            continue
        row = senders.setdefault(m.sender_email, {"sender": m.sender_name, "email": m.sender_email, "emails": 0,
                                                  "unread": 0, "last_received": m.received})
        row["emails"] += 1
        row["unread"] += m.unread
        row["last_received"] = max(row["last_received"], m.received)
    rows = sorted(senders.values(), key=lambda r: (-r["emails"], -r["unread"]))[:limit]
    for row in rows:
        row["last_received"] = row["last_received"].strftime("%Y-%m-%d %H:%M UTC")
    return rows
