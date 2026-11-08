"""Mailing lists in your Gmail: find them by their List-Unsubscribe header, see which send the most, and unsubscribe."""
from collections import defaultdict
from typing import Literal

import requests

from callables import Next
from gmail_api import Gmail, Message, check_address, parse_mailto, unsubscribe_options
from inbox import archive_from_sender, gmail, google

LIST_HEADERS = ("List-Unsubscribe", "List-Unsubscribe-Post", "List-Id")
SCAN_LIMIT = 2000
# Mailing lists nearly always say "unsubscribe" in the body, so Gmail's search narrows the scan; the header decides
QUERY = "newer_than:{days}d unsubscribe -in:sent -in:drafts -in:chats"


def _list_messages(client: Gmail, query: str, limit: int) -> list[Message]:
    found = client.messages(client.search(query, limit), extra_headers=LIST_HEADERS)
    return [m for m in found if m.headers.get("list-unsubscribe")]


def unsubscribe_now(client: Gmail, sender: str) -> str:
    """Uses the newest list email from the sender to pick the best way out."""
    messages = _list_messages(client, f"from:{sender} unsubscribe", 5)
    if not messages:
        raise ValueError(f"No email from {sender} offers an unsubscribe option.")
    newest = max(messages, key=lambda m: m.received)
    options = unsubscribe_options(newest.headers.get("list-unsubscribe", ""),
                                  newest.headers.get("list-unsubscribe-post", ""))
    if options.one_click:
        # RFC 8058: a POST with this exact body; no cookies, no page to click through
        resp = requests.post(options.one_click, data={"List-Unsubscribe": "One-Click"}, timeout=30,
                             headers={"User-Agent": "Callables unsubscribe"})
        if resp.ok:
            return f"Unsubscribed from {sender} with their one-click link."
        if not options.mailto:
            raise RuntimeError(f"{sender}'s one-click unsubscribe answered HTTP {resp.status_code}. "
                               f"Try their page instead: {options.link}")
    if options.mailto:
        to, subject, body = parse_mailto(options.mailto)
        client.send(to, subject, body)
        return f"Sent an unsubscribe email to {to} for {sender}. Lists can take a few days to stop."
    return (f"{sender} only offers an unsubscribe page, which may need you to click through it, so it wasn't done "
            f"automatically. Open it: [unsubscribe]({options.link})")


@gmail.deploy(title="Unsubscribe", timeout=300)
def unsubscribe(sender: str, then: Literal["keep", "archive", "trash"] = "keep") -> str:
    """Unsubscribes from a mailing list, then optionally archives or trashes everything it sent you."""
    address = check_address(sender)
    client = Gmail(google.token)
    lines = [unsubscribe_now(client, address)]
    if then != "keep":
        where = "in:inbox " if then == "archive" else "-in:trash "
        ids = client.search(f"{where}from:{address}", 5000)
        if ids:
            if then == "archive":
                client.archive(ids)
                lines.append(f"Archived {len(ids)} email(s) from {address}. They're still in All Mail.")
            else:
                client.trash(ids)
                lines.append(f"Moved {len(ids)} email(s) from {address} to Trash. Gmail deletes them after 30 days.")
        else:
            lines.append(f"No email from {address} to {then}.")
    return "\n\n".join(lines)


@gmail.deploy(title="Subscriptions", timeout=300,
              next=[Next(unsubscribe, label="Unsubscribe", sender="email"),
                    Next(archive_from_sender, label="Archive their emails", sender="email")])
def subscriptions(days: int = 30, limit: int = 50) -> list[dict]:
    """The mailing lists that emailed you lately, the busiest first, with how much of it you actually read."""
    if not 1 <= days <= 365:
        raise ValueError("days must be between 1 and 365")
    client = Gmail(google.token)
    messages = _list_messages(client, QUERY.format(days=days), SCAN_LIMIT)
    by_sender: dict[str, list[Message]] = defaultdict(list)
    for m in messages:
        by_sender[m.sender_email].append(m)
    print(f"{len(messages)} mailing-list email(s) from {len(by_sender)} sender(s) in the last {days} days"
          + (" (capped: only the newest were read)" if len(messages) >= SCAN_LIMIT else ""))

    rows = []
    for address, items in by_sender.items():
        newest = max(items, key=lambda m: m.received)
        unread = sum(m.unread for m in items)
        options = unsubscribe_options(newest.headers.get("list-unsubscribe", ""),
                                      newest.headers.get("list-unsubscribe-post", ""))
        rows.append({
            "sender": newest.sender_name,
            "email": address,
            "emails": len(items),
            "per_week": round(len(items) / days * 7, 1),
            "unread": unread,
            "read": f"{round(100 * (len(items) - unread) / len(items))}%",
            "in_inbox": sum("INBOX" in m.labels for m in items),
            "last_received": newest.received.strftime("%Y-%m-%d"),
            "unsubscribe": options.how,
        })
    rows.sort(key=lambda r: (-r["emails"], r["email"]))
    return rows[:limit]
