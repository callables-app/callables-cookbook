"""A small Gmail REST client: just what the inbox callables need. Every call uses the access token for the person
running the callable, so it only ever sees their own mailbox."""
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parseaddr

import requests

API = "https://gmail.googleapis.com/gmail/v1/users/me"
# batchModify takes up to 1000 ids per call
BATCH = 1000
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


class Gmail:
    def __init__(self, token: str):
        self.http = requests.Session()
        self.http.headers["Authorization"] = f"Bearer {token}"

    def _call(self, method: str, path: str, **kwargs) -> dict:
        resp = self.http.request(method, f"{API}{path}", timeout=30, **kwargs)
        if resp.status_code == 401:
            raise RuntimeError("Google didn't accept your access. Reconnect Google and run this again.")
        if resp.status_code == 403:
            reason = resp.json().get("error", {}).get("message", "") if resp.content else ""
            raise RuntimeError(f"Google refused this request: {reason or 'permission denied'}. If the project just "
                               "added a permission, reconnect Google.")
        resp.raise_for_status()
        return resp.json() if resp.content else {}

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

    def _message(self, message_id: str) -> Message:
        data = self._call("GET", f"/messages/{message_id}", params={
            "format": "metadata", "metadataHeaders": ["From", "Subject"]})
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
        )

    def messages(self, ids: list[str]) -> list[Message]:
        """Sender, subject and snippet for each id, fetched a few at a time. Keeps the given order."""
        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(self._message, ids))

    def archive(self, ids: list[str]) -> None:
        """Archiving in Gmail means taking the INBOX label off; the messages stay in All Mail."""
        for start in range(0, len(ids), BATCH):
            self._call("POST", "/messages/batchModify",
                       json={"ids": ids[start:start + BATCH], "removeLabelIds": ["INBOX"]})


def check_address(value: str) -> str:
    value = value.strip().lower()
    if not ADDRESS.match(value):
        raise ValueError(f"'{value}' isn't an email address. Use the sender's address, such as news@example.com")
    return value
