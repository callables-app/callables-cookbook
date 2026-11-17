"""A small X (Twitter) API v2 client: who's signed in and creating posts. No callables in here, so any folder (or
recipe) can import it: `from providers.x.x_api import X`.

X bills per request (pay-per-use credits in the X Developer Console). At the time of writing a post costs $0.015,
and a post containing a URL $0.20, so links are worth using on purpose.
"""
import re
import time

import requests

API = "https://api.x.com/2"
MAX_LENGTH = 280  # without X Premium
URL = re.compile(r"https?://\S+")
URL_LENGTH = 23  # X counts every link as 23 characters (t.co)


class XError(RuntimeError):
    pass


def length(text: str) -> int:
    """How long X counts the text: every link is 23 characters."""
    return len(URL.sub("x" * URL_LENGTH, text))


def has_link(text: str) -> bool:
    return bool(URL.search(text))


def _error(resp: requests.Response) -> str:
    try:
        body = resp.json()
        errors = body.get("errors") or []
        return body.get("detail") or "; ".join(e.get("message", "") for e in errors) or str(body)[:300]
    except ValueError:
        return resp.text[:300]


class X:
    def __init__(self, token: str):
        if not token:
            raise XError("No X sign-in: connect X first.")
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"

    def request(self, method: str, path: str, **kwargs) -> dict:
        for attempt in range(3):
            resp = self.session.request(method, f"{API}{path}", timeout=30, **kwargs)
            if resp.status_code == 429 and attempt < 2:
                reset = float(resp.headers.get("x-rate-limit-reset") or 0)
                time.sleep(min(max(reset - time.time(), 2), 30))
                continue
            if resp.status_code == 402:
                raise XError("X needs credits for this: add them in the X Developer Console (the API is pay-per-use).")
            if resp.status_code == 401:
                raise XError("X says the sign-in isn't valid anymore: reconnect X.")
            if not resp.ok:
                raise XError(f"X {method} {path} failed ({resp.status_code}): {_error(resp)}")
            return resp.json()

    def me(self) -> dict:
        """The signed-in account: {"id", "username", "name"}."""
        return self.request("GET", "/users/me", params={"user.fields": "username,name"})["data"]

    def post(self, text: str, reply_to: str | None = None, username: str | None = None) -> dict:
        """A post (a reply when reply_to is a post id): {"id", "url"}."""
        if length(text) > MAX_LENGTH:
            raise XError(f"The post is {length(text)} characters as X counts them (links are 23); the limit is "
                         f"{MAX_LENGTH}.")
        body = {"text": text}
        if reply_to:
            body["reply"] = {"in_reply_to_tweet_id": str(reply_to)}
        made = self.request("POST", "/tweets", json=body)["data"]
        handle = username or self.me()["username"]
        return {"id": made["id"], "url": f"https://x.com/{handle}/status/{made['id']}"}
