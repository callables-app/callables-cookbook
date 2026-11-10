"""A small Gmail REST client: just what the inbox callables need. Every call uses the access token for the person
running the callable, so it only ever sees their own mailbox."""
import base64
import random
import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parseaddr
from urllib.parse import parse_qs, quote, unquote, urlsplit

import requests

API = "https://gmail.googleapis.com/gmail/v1/users/me"
# batchModify takes up to 1000 ids per call
BATCH = 1000
# Gmail charges each call in quota units and caps each user at 15,000 a minute. Stay under it with room to spare,
# since other runs or apps may be using the same mailbox.
UNITS_PER_MINUTE = 10_000
RETRIES = 6
# A plain address, so a sender can't smuggle extra search operators into the Gmail query
ADDRESS = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


@dataclass
class Message:
    id: str
    sender_name: str
    sender_email: str
    subject: str
    snippet: str
    received: datetime
    unread: bool
    labels: list[str]
    headers: dict[str, str] = field(default_factory=dict)  # lower-cased names; only the ones asked for


def _cost(method: str, path: str) -> int:
    """Gmail's quota units for a call (developers.google.com/workspace/gmail/api/reference/quota)."""
    if path == "/messages/send":
        return 100
    if path == "/messages/batchModify":
        return 50
    if path.startswith("/settings/sendAs/") and method in ("PATCH", "PUT"):
        return 100
    if path.startswith("/labels/") or path.startswith("/settings/"):
        return 1
    return 5  # messages.list, messages.get, messages.trash


def _error(resp: requests.Response) -> tuple[str, str]:
    """(reason, message) from a Google API error body."""
    try:
        error = resp.json().get("error", {})
    except ValueError:
        return "", resp.text[:200]
    reasons = [e.get("reason", "") for e in error.get("errors", [])] + [
        d.get("reason", "") for d in error.get("details", []) if isinstance(d, dict)]
    return " ".join(r for r in reasons if r), error.get("message", "")


class Gmail:
    def __init__(self, token: str):
        self.http = requests.Session()
        self.http.headers["Authorization"] = f"Bearer {token}"
        self._spent: deque[tuple[float, int]] = deque()  # (when, units) for the last minute
        self._lock = threading.Lock()

    def _pace(self, units: int) -> None:
        """Wait until spending `units` keeps the last minute under budget. Shared by the worker threads."""
        while True:
            with self._lock:
                now = time.monotonic()
                while self._spent and now - self._spent[0][0] > 60:
                    self._spent.popleft()
                if sum(u for _, u in self._spent) + units <= UNITS_PER_MINUTE:
                    self._spent.append((now, units))
                    return
                wait = 60 - (now - self._spent[0][0]) + 0.05
            time.sleep(wait)

    def _call(self, method: str, path: str, **kwargs) -> dict:
        for attempt in range(RETRIES):
            self._pace(_cost(method, path))
            resp = self.http.request(method, f"{API}{path}", timeout=30, **kwargs)
            if resp.status_code == 401:
                raise RuntimeError("Google didn't accept your access. Reconnect Google and run this again.")
            if resp.status_code in (403, 429):
                reason, message = _error(resp)
                limited = resp.status_code == 429 or "ratelimit" in reason.lower() or "quota" in (reason + message).lower()
                if limited and attempt < RETRIES - 1:
                    # Gmail asks to slow down: back off, longer each time, as Google recommends
                    retry_after = resp.headers.get("Retry-After", "")
                    time.sleep(float(retry_after) if retry_after.isdigit() else min(60, 2 ** attempt + random.random()))
                    continue
                if limited:
                    raise RuntimeError("Gmail's rate limit for your account was hit and didn't clear after waiting. "
                                       "Wait a minute and run it again, or use a shorter time range.")
                if "insufficient" in (reason + message).lower():
                    raise RuntimeError("Your Google connection is missing a Gmail permission this needs. Disconnect "
                                       "Google under Connections, connect again, and tick every box on Google's screen.")
                raise RuntimeError(f"Google refused this request: {message.rstrip('.') or 'permission denied'}.")
            if resp.status_code >= 500 and attempt < RETRIES - 1:
                time.sleep(min(30, 2 ** attempt + random.random()))
                continue
            resp.raise_for_status()
            return resp.json() if resp.content else {}
        raise RuntimeError("Gmail kept failing. Try again in a minute.")

    def search(self, query: str, limit: int) -> list[str]:
        """Message ids matching a Gmail search (the same syntax as the search box), newest first."""
        ids: list[str] = []
        page = None
        while len(ids) < limit:
            params = {"q": query, "maxResults": min(500, limit - len(ids))}
            if page:
                params["pageToken"] = page
            data = self._call("GET", "/messages", params=params)
            ids += [m["id"] for m in data.get("messages", [])]
            page = data.get("nextPageToken")
            if not page:
                break
        return ids[:limit]

    def _message(self, message_id: str, extra_headers: tuple[str, ...] = ()) -> Message:
        data = self._call("GET", f"/messages/{message_id}", params={
            "format": "metadata", "metadataHeaders": ["From", "Subject", *extra_headers]})
        headers = {h["name"].lower(): h["value"] for h in data.get("payload", {}).get("headers", [])}
        name, address = parseaddr(headers.get("from", ""))
        return Message(
            id=message_id,
            sender_name=name or address,
            sender_email=address.lower(),
            subject=headers.get("subject", "(no subject)"),
            snippet=data.get("snippet", ""),
            received=datetime.fromtimestamp(int(data.get("internalDate", 0)) / 1000, tz=timezone.utc),
            unread="UNREAD" in data.get("labelIds", []),
            labels=data.get("labelIds", []),
            headers=headers,
        )

    def label(self, label_id: str) -> dict:
        """A label's counts: messagesTotal, messagesUnread, threadsTotal, threadsUnread."""
        return self._call("GET", f"/labels/{label_id}")

    def messages(self, ids: list[str], extra_headers: tuple[str, ...] = ()) -> list[Message]:
        """Sender, subject and snippet for each id (plus any extra headers), fetched a few at a time, in order."""
        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(lambda i: self._message(i, extra_headers), ids))

    def archive(self, ids: list[str]) -> None:
        """Archiving in Gmail means taking the INBOX label off; the messages stay in All Mail."""
        for start in range(0, len(ids), BATCH):
            self._call("POST", "/messages/batchModify",
                       json={"ids": ids[start:start + BATCH], "removeLabelIds": ["INBOX"]})


    def trash(self, ids: list[str]) -> None:
        """Moves messages to Trash, where Gmail keeps them for 30 days before deleting them."""
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: self._call("POST", f"/messages/{i}/trash"), ids))

    def send_as(self) -> dict:
        """Your main address's "send as" settings: sendAsEmail, displayName, signature (HTML)..."""
        addresses = self._call("GET", "/settings/sendAs").get("sendAs", [])
        return next((a for a in addresses if a.get("isPrimary")), addresses[0] if addresses else {})

    def set_signature(self, address: str, signature: str) -> dict:
        """Replaces the signature Gmail adds for `address`, one of your "send as" addresses. Needs gmail.settings.basic."""
        return self._call("PATCH", f"/settings/sendAs/{quote(address)}", json={"signature": signature})

    def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["To"], msg["Subject"] = to, subject
        msg.set_content(body)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        self._call("POST", "/messages/send", json={"raw": raw})


@dataclass
class Unsubscribe:
    """The ways a List-Unsubscribe header offers (RFC 2369), and whether the web one is one-click (RFC 8058)."""
    one_click: str | None = None  # https URL that takes a POST, no page to click through
    mailto: str | None = None
    link: str | None = None       # https URL that may need a click or a form

    @property
    def how(self) -> str:
        return "one-click" if self.one_click else "email" if self.mailto else "link only" if self.link else "none"


def unsubscribe_options(header: str, post_header: str = "") -> Unsubscribe:
    urls = re.findall(r"<([^>]+)>", header or "")
    https = next((u for u in urls if u.lower().startswith("https://")), None)
    mailto = next((u for u in urls if u.lower().startswith("mailto:")), None)
    one_click = "list-unsubscribe=one-click" in (post_header or "").lower().replace(" ", "")
    return Unsubscribe(one_click=https if https and one_click else None, mailto=mailto, link=https)


def parse_mailto(url: str) -> tuple[str, str, str]:
    """mailto:list@x.com?subject=unsubscribe&body=... -> (address, subject, body)."""
    parts = urlsplit(url)
    query = {k.lower(): v[0] for k, v in parse_qs(parts.query).items()}
    return unquote(parts.path), query.get("subject", "Unsubscribe"), query.get("body", "Please unsubscribe me.")


def check_address(value: str) -> str:
    value = value.strip().lower()
    if not ADDRESS.match(value):
        raise ValueError(f"'{value}' isn't an email address. Use the sender's address, such as news@example.com")
    return value
