"""Gmail automations that run on the inbox of whoever runs them: each person connects their own Google account."""
from collections import Counter
from datetime import datetime, timedelta, timezone

from callables import Connection, Group, Next
from gmail_api import Gmail, check_address

google = Connection("google", provider="google", scopes=["gmail.modify"])

gmail = Group("gmail", title="Gmail", description="Work with your own Gmail inbox", connections=[google])

# Gmail's inbox tabs, as labels on each message
CATEGORIES = {"CATEGORY_PERSONAL": "Primary", "CATEGORY_UPDATES": "Updates", "CATEGORY_PROMOTIONS": "Promotions",
              "CATEGORY_SOCIAL": "Social", "CATEGORY_FORUMS": "Forums"}
SCAN_LIMIT = 1000  # messages read for the last-N-days breakdown


def _pct(part: int, whole: int) -> str:
    return f"{round(100 * part / whole)}%" if whole else "0%"


@gmail.deploy(title="Summarize my inbox", timeout=300)
def summarize_inbox(days: int = 7) -> str:
    """Statistics for your inbox: what's in it now, and what arrived in the last few days, by tab, day and sender."""
    if not 1 <= days <= 90:
        raise ValueError("days must be between 1 and 90")
    client = Gmail(google.token)
    inbox = client.label("INBOX")
    messages = client.messages(client.search(f"in:inbox newer_than:{days}d", SCAN_LIMIT))

    out = [
        "### Your inbox now",
        "",
        "| | Messages | Conversations |",
        "|---|---:|---:|",
        f"| In the inbox | {inbox.get('messagesTotal', 0):,} | {inbox.get('threadsTotal', 0):,} |",
        f"| Unread | {inbox.get('messagesUnread', 0):,} | {inbox.get('threadsUnread', 0):,} |",
        "",
        f"### Last {days} day{'s' if days != 1 else ''}",
        "",
    ]
    if not messages:
        out.append("Nothing arrived in your inbox.")
        return "\n".join(out)

    total = len(messages)
    unread = sum(m.unread for m in messages)
    starred = sum("STARRED" in m.labels for m in messages)
    important = sum("IMPORTANT" in m.labels for m in messages)
    senders = Counter(m.sender_email for m in messages)
    names = {m.sender_email: m.sender_name for m in messages}
    capped = " (the newest, Gmail search is capped here)" if total >= SCAN_LIMIT else ""
    out += [
        f"- **{total:,}** received{capped}, about **{total / days:.1f}** a day",
        f"- **{unread:,}** still unread ({_pct(unread, total)})",
        f"- **{important:,}** marked important, **{starred:,}** starred",
        f"- From **{len(senders):,}** different senders",
        "",
    ]

    tabs = Counter(next((CATEGORIES[label] for label in m.labels if label in CATEGORIES), "Primary") for m in messages)
    unread_tabs = Counter(next((CATEGORIES[label] for label in m.labels if label in CATEGORIES), "Primary")
                          for m in messages if m.unread)
    out += ["**By tab**", "", "| Tab | Received | Unread | Share |", "|---|---:|---:|---:|"]
    out += [f"| {tab} | {n:,} | {unread_tabs[tab]:,} | {_pct(n, total)} |" for tab, n in tabs.most_common()]
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


@gmail.deploy(title="Archive emails from a sender", timeout=180)
def archive_from_sender(sender: str, older_than_days: int = 0, dry_run: bool = True) -> str:
    """Archives every inbox email from one sender. They stay in All Mail. Leave dry run on to see what would move."""
    address = check_address(sender)
    if older_than_days < 0:
        raise ValueError("older_than_days can't be negative")
    query = f"in:inbox from:{address}" + (f" older_than:{older_than_days}d" if older_than_days else "")
    client = Gmail(google.token)
    ids = client.search(query, 5000)
    if not ids:
        return f"No inbox emails from {address}" + (f" older than {older_than_days} days." if older_than_days else ".")
    if dry_run:
        sample = client.messages(ids[:5])
        lines = "\n".join(f"- {m.received:%d %b} · {m.subject}" for m in sample)
        more = f"\n- …and {len(ids) - 5} more" if len(ids) > 5 else ""
        return (f"**Dry run:** {len(ids)} email(s) from {address} would be archived.\n\n{lines}{more}\n\n"
                "Run again with dry run off to archive them.")
    client.archive(ids)
    return f"Archived {len(ids)} email(s) from {address}. They're still in All Mail."


@gmail.deploy(title="Recent senders", timeout=180,
              next=[Next(archive_from_sender, label="Archive their emails", sender="email")])
def recent_senders(days: int = 7, limit: int = 25) -> list[dict]:
    """Who has emailed you most in the last few days, with how many are still unread."""
    if not 1 <= days <= 90:
        raise ValueError("days must be between 1 and 90")
    client = Gmail(google.token)
    messages = client.messages(client.search(f"in:inbox newer_than:{days}d", 500))
    senders: dict[str, dict] = {}
    for m in messages:
        row = senders.setdefault(m.sender_email, {"sender": m.sender_name, "email": m.sender_email, "emails": 0,
                                                  "unread": 0, "last_received": m.received})
        row["emails"] += 1
        row["unread"] += m.unread
        row["last_received"] = max(row["last_received"], m.received)
    rows = sorted(senders.values(), key=lambda r: (-r["emails"], -r["unread"]))[:limit]
    for row in rows:
        row["last_received"] = row["last_received"].strftime("%Y-%m-%d %H:%M UTC")
    return rows
