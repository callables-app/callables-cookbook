"""Mailing lists in your Outlook mailbox: find them by their List-Unsubscribe header, see which send the most, and
unsubscribe."""
from collections import defaultdict
from typing import Literal

import requests

from callables import Next
from graph_api import SKIP_FOLDERS, Graph, Message, check_address, from_sender, parse_mailto, since, unsubscribe_options
from inbox import archive_from_sender, mail, outlook

SCAN_LIMIT = 2000
ALL_MAIL = "/me/messages"  # every folder; sent, drafts, deleted and junk are left out below


def _list_messages(client: Graph, query: str, limit: int) -> list[Message]:
    skip = client.folder_ids(SKIP_FOLDERS)
    found = client.messages(ALL_MAIL, query, limit, headers=True)
    return [m for m in found if m.headers.get("list-unsubscribe") and m.folder_id not in skip]


def unsubscribe_now(client: Graph, sender: str) -> str:
    """Uses the newest list email from the sender to pick the best way out."""
    messages = _list_messages(client, from_sender(sender), 10)
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


@mail.deploy(title="Unsubscribe", timeout=300)
def unsubscribe(sender: str, then: Literal["keep", "archive", "trash"] = "keep") -> str:
    """Unsubscribes from a mailing list, then optionally archives or deletes everything it sent you."""
    address = check_address(sender)
    client = Graph(outlook.token)
    lines = [unsubscribe_now(client, address)]
    if then != "keep":
        where = "/me/mailFolders/inbox/messages" if then == "archive" else ALL_MAIL
        found = client.messages(where, from_sender(address), 5000)
        if then == "trash":
            skip = client.folder_ids(("deleteditems", "sentitems", "drafts"))
            found = [m for m in found if m.folder_id not in skip]
        ids = [m.id for m in found]
        if ids and then == "archive":
            client.archive(ids)
            lines.append(f"Archived {len(ids)} email(s) from {address}. They're in your Archive folder.")
        elif ids:
            client.trash(ids)
            lines.append(f"Moved {len(ids)} email(s) from {address} to Deleted Items.")
        else:
            lines.append(f"No email from {address} to {then}.")
    return "\n\n".join(lines)


@mail.deploy(title="Subscriptions", timeout=300,
             next=[Next(unsubscribe, label="Unsubscribe", sender="email"),
                   Next(archive_from_sender, label="Archive their emails", sender="email")])
def subscriptions(days: int = 30, limit: int = 50) -> list[dict]:
    """The mailing lists that emailed you lately, the busiest first, with how much of it you actually read."""
    if not 1 <= days <= 365:
        raise ValueError("days must be between 1 and 365")
    client = Graph(outlook.token)
    messages = _list_messages(client, f"receivedDateTime ge {since(days)}", SCAN_LIMIT)
    by_sender: dict[str, list[Message]] = defaultdict(list)
    for m in messages:
        by_sender[m.sender_email].append(m)
    print(f"{len(messages)} mailing-list email(s) from {len(by_sender)} sender(s) in the last {days} days")

    inbox_id = client.folder("inbox")["id"]
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
            "in_inbox": sum(m.folder_id == inbox_id for m in items),
            "last_received": newest.received.strftime("%Y-%m-%d"),
            "unsubscribe": options.how,
        })
    rows.sort(key=lambda r: (-r["emails"], r["email"]))
    return rows[:limit]
