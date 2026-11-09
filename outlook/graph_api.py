"""A small Microsoft Graph mail client: just what the Outlook callables need. Every call uses the access token for the
person running the callable, so it only ever sees their own mailbox."""
import random
import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urlsplit

import requests

GRAPH = "https://graph.microsoft.com/v1.0"
# Outlook allows 4 requests at once per mailbox, and about 10,000 per 10 minutes per app. Stay under both, since
# other apps may be using the same mailbox.
CONCURRENCY = 4
REQUESTS_PER_WINDOW = 8_000
WINDOW = 600
BATCH = 20  # Graph's JSON batching takes up to 20 requests per call
RETRIES = 6
PAGE = 100
# A plain address, so a sender can't change the shape of an OData filter
ADDRESS = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
FIELDS = "id,from,subject,receivedDateTime,isRead,parentFolderId,importance,flag,inferenceClassification,hasAttachments"
# Mail that isn't really "received": what you sent, drafts, and what's already deleted or junk
SKIP_FOLDERS = ("sentitems", "drafts", "deleteditems", "junkemail")


@dataclass
class Message:
    id: str
    sender_name: str
    sender_email: str
    subject: str
    received: datetime
    unread: bool
    folder_id: str
    focused: bool  # Outlook's Focused inbox; False means Other
    important: bool
    flagged: bool
    has_attachments: bool
    headers: dict[str, str] = field(default_factory=dict)  # lower-cased names; only when asked for


def _message(data: dict) -> Message:
    sender = (data.get("from") or {}).get("emailAddress") or {}
    address = (sender.get("address") or "").lower()
    headers = {h["name"].lower(): h["value"] for h in data.get("internetMessageHeaders") or []}
    return Message(
        id=data["id"],
        sender_name=sender.get("name") or address,
        sender_email=address,
        subject=data.get("subject") or "(no subject)",
        received=datetime.fromisoformat(data["receivedDateTime"].replace("Z", "+00:00")),
        unread=not data.get("isRead", True),
        folder_id=data.get("parentFolderId", ""),
        focused=data.get("inferenceClassification", "focused") == "focused",
        important=data.get("importance") == "high",
        flagged=(data.get("flag") or {}).get("flagStatus") == "flagged",
        has_attachments=bool(data.get("hasAttachments")),
        headers=headers,
    )


def since(days: int) -> str:
    """An OData timestamp for `days` ago."""
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _quote(value: str) -> str:
    """A string literal for an OData filter."""
    return "'" + value.replace("'", "''") + "'"


def _error(resp: requests.Response) -> tuple[str, str]:
    """(code, message) from a Graph error body."""
    try:
        error = resp.json().get("error", {})
    except ValueError:
        return "", resp.text[:200]
    return error.get("code", ""), error.get("message", "")


class Graph:
    def __init__(self, token: str):
        self.http = requests.Session()
        self.http.headers["Authorization"] = f"Bearer {token}"
        self._sent: deque[float] = deque()  # when each request in the last window went out
        self._lock = threading.Lock()
        self._slots = threading.Semaphore(CONCURRENCY)

    def _pace(self, count: int = 1) -> None:
        """Wait until `count` more requests keep the last window under budget. Shared by the worker threads."""
        while True:
            with self._lock:
                now = time.monotonic()
                while self._sent and now - self._sent[0] > WINDOW:
                    self._sent.popleft()
                if len(self._sent) + count <= REQUESTS_PER_WINDOW:
                    self._sent.extend([now] * count)
                    return
                wait = WINDOW - (now - self._sent[0]) + 0.05
            time.sleep(wait)

    def _call(self, method: str, url: str, cost: int = 1, **kwargs) -> dict:
        if not url.startswith("https://"):
            url = f"{GRAPH}{url}"
        for attempt in range(RETRIES):
            self._pace(cost)
            with self._slots:
                resp = self.http.request(method, url, timeout=60, **kwargs)
            if resp.status_code == 401:
                raise RuntimeError("Microsoft didn't accept your access. Reconnect Outlook and run this again.")
            if resp.status_code in (429, 503, 504) and attempt < RETRIES - 1:
                # Graph asks to slow down and says for how long
                retry_after = resp.headers.get("Retry-After", "")
                time.sleep(float(retry_after) if retry_after.isdigit() else min(60, 2 ** attempt + random.random()))
                continue
            if resp.status_code == 429:
                raise RuntimeError("Outlook's rate limit for your mailbox was hit and didn't clear after waiting. "
                                   "Wait a few minutes and run it again, or use a shorter time range.")
            if resp.status_code >= 500 and attempt < RETRIES - 1:
                time.sleep(min(30, 2 ** attempt + random.random()))
                continue
            if resp.status_code >= 400:
                code, message = _error(resp)
                if code == "MailboxNotEnabledForRESTAPI":
                    raise RuntimeError("This account has no Exchange Online mailbox (usually a missing Microsoft 365 "
                                       "license), so Outlook can't be reached.")
                if resp.status_code == 403:
                    raise RuntimeError("Your Outlook connection doesn't allow this. Ask the project's builder to check "
                                       "the app's API permissions and admin consent, then reconnect Outlook.")
                raise RuntimeError(f"Outlook refused this request: {message.rstrip('.') or code or resp.status_code}.")
            return resp.json() if resp.content else {}
        raise RuntimeError("Outlook kept failing. Try again in a minute.")

    # ---------- reading ----------

    def folder(self, name: str) -> dict:
        """A folder's counts: totalItemCount, unreadItemCount. `name` can be a well-known name such as inbox."""
        return self._call("GET", f"/me/mailFolders/{name}")

    def folder_ids(self, names: tuple[str, ...]) -> set[str]:
        return {self.folder(n)["id"] for n in names}

    def messages(self, where: str, query: str, limit: int, headers: bool = False) -> list[Message]:
        """Messages matching an OData filter, newest first. `where` is /me/messages (every folder) or a folder's
        /me/mailFolders/<name>/messages. With headers, each message also has its internet headers."""
        select = FIELDS + (",internetMessageHeaders" if headers else "")
        params = {"$filter": query, "$orderby": "receivedDateTime desc", "$select": select,
                  "$top": min(PAGE, limit)}
        found: list[dict] = []
        url, page_params = where, params
        while url and len(found) < limit:
            data = self._call("GET", url, params=page_params)
            found += data.get("value", [])
            url, page_params = data.get("@odata.nextLink"), None  # the next link carries the query
        found = found[:limit]
        if headers and found and all("internetMessageHeaders" not in m for m in found):
            found = self._with_headers([m["id"] for m in found])
        return [_message(m) for m in found]

    def _with_headers(self, ids: list[str]) -> list[dict]:
        """Fetches each message with its headers, when the list didn't include them."""
        select = FIELDS + ",internetMessageHeaders"
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            return list(pool.map(lambda i: self._call("GET", f"/me/messages/{i}", params={"$select": select}), ids))

    # ---------- changing ----------

    def _batch(self, requests_: list[dict]) -> None:
        """Runs requests through Graph's JSON batching, 20 at a time, retrying any that were throttled."""
        pending = [{**r, "id": str(n)} for n, r in enumerate(requests_)]
        for attempt in range(RETRIES):
            if not pending:
                return
            failed, throttled, wait = [], [], 0.0
            for start in range(0, len(pending), BATCH):
                chunk = pending[start:start + BATCH]
                data = self._call("POST", "/$batch", cost=len(chunk), json={"requests": chunk})
                by_id = {r["id"]: r for r in chunk}
                for answer in data.get("responses", []):
                    status = answer.get("status", 500)
                    if status in (429, 503, 504):
                        throttled.append(by_id[answer["id"]])
                        wait = max(wait, float((answer.get("headers") or {}).get("Retry-After", 0) or 0))
                    elif status >= 400:
                        failed.append(answer)
            if failed:
                code = ((failed[0].get("body") or {}).get("error") or {}).get("message", failed[0].get("status"))
                raise RuntimeError(f"Outlook refused {len(failed)} change(s): {code}")
            pending = throttled
            if pending:
                time.sleep(wait or min(60, 2 ** attempt + random.random()))
        if pending:
            raise RuntimeError(f"Outlook's rate limit stopped {len(pending)} change(s). Run it again in a few minutes.")

    def move(self, ids: list[str], destination: str) -> None:
        """Moves messages to a folder; `destination` can be a well-known name such as archive or deleteditems."""
        self._batch([{"method": "POST", "url": f"/me/messages/{i}/move", "body": {"destinationId": destination},
                      "headers": {"Content-Type": "application/json"}} for i in ids])

    def archive(self, ids: list[str]) -> None:
        """Moves messages to the Archive folder, where they stay searchable."""
        self.move(ids, "archive")

    def trash(self, ids: list[str]) -> None:
        """Moves messages to Deleted Items, which your organization empties on its own schedule."""
        self.move(ids, "deleteditems")

    def send(self, to: str, subject: str, body: str) -> None:
        self._call("POST", "/me/sendMail", json={
            "message": {"subject": subject, "body": {"contentType": "Text", "content": body},
                        "toRecipients": [{"emailAddress": {"address": to}}]},
            "saveToSentItems": True})


def from_sender(address: str, older_than_days: int = 0) -> str:
    """An OData filter for mail from one address, optionally older than some days."""
    query = f"from/emailAddress/address eq {_quote(check_address(address))}"
    if older_than_days:
        query += f" and receivedDateTime lt {since(older_than_days)}"
    return query


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
