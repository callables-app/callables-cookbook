"""A small LinkedIn API client: who's signed in, the pages they admin, and text posts through the Posts API. No
callables in here, so any folder (or recipe) can import it: `from providers.linkedin.linkedin_api import LinkedIn`.

Posts go to https://api.linkedin.com/rest/posts with a monthly LinkedIn-Version header. The text uses LinkedIn's
"little text" format, where reserved characters must be escaped: `escape()` does that, and keeps #hashtags working.
"""
import re
import time

import requests

API = "https://api.linkedin.com"
VERSION = "202611"  # LinkedIn supports each monthly version for at least a year
MAX_LENGTH = 3000  # LinkedIn's limit for a post's text

RESERVED = re.compile(r"([\\|{}@\[\]()<>#*_~])")
HASHTAG = re.compile(r"(?<![\w\\])\\#((?:\w|\\_)+)")  # after escaping, so underscores arrive as \_


class LinkedInError(RuntimeError):
    pass


def escape(text: str) -> str:
    """Post text as LinkedIn's little text: every reserved character backslash-escaped, except that #word stays a
    clickable hashtag."""
    return HASHTAG.sub(r"{hashtag|\\#|\1}", RESERVED.sub(r"\\\1", text))


def post_url(urn: str) -> str:
    return f"https://www.linkedin.com/feed/update/{urn}/"


def _error(resp: requests.Response) -> str:
    try:
        body = resp.json()
        return body.get("message") or body.get("error_description") or str(body)[:300]
    except ValueError:
        return resp.text[:300]


class LinkedIn:
    def __init__(self, token: str):
        if not token:
            raise LinkedInError("No LinkedIn sign-in: connect LinkedIn first.")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "LinkedIn-Version": VERSION,
                                     "X-Restli-Protocol-Version": "2.0.0"})

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        for attempt in range(3):
            resp = self.session.request(method, f"{API}{path}", timeout=30, **kwargs)
            if resp.status_code == 429 and attempt < 2:
                time.sleep(2 ** attempt * 5)
                continue
            if resp.status_code == 401:
                raise LinkedInError("LinkedIn says the sign-in has expired (they last 60 days): reconnect LinkedIn.")
            if resp.status_code == 403:
                raise LinkedInError(f"LinkedIn refused this ({_error(resp)}). Posting as a page needs the page "
                                    "scopes, which LinkedIn has to approve for your app, and an admin role on the page.")
            if not resp.ok:
                raise LinkedInError(f"LinkedIn {method} {path.split('?')[0]} failed ({resp.status_code}): "
                                    f"{_error(resp)}")
            return resp

    def me(self) -> dict:
        """The signed-in member: {"urn", "name"}. Needs the openid and profile scopes."""
        body = self.request("GET", "/v2/userinfo").json()
        return {"urn": f"urn:li:person:{body['sub']}", "name": body.get("name")}

    def pages(self) -> list[dict]:
        """The company pages the member can post as: [{"urn", "name", "role"}]. Needs r_organization_admin."""
        out, start = [], 0
        while True:
            body = self.request("GET", "/rest/organizationAcls", params={
                "q": "roleAssignee", "state": "APPROVED", "start": start, "count": 100}).json()
            for acl in body.get("elements", []):
                role = acl.get("role")
                if role not in ("ADMINISTRATOR", "CONTENT_ADMIN", "DIRECT_SPONSORED_CONTENT_POSTER"):
                    continue
                urn = acl.get("organization") or acl.get("organizationTarget")
                out.append({"urn": urn, "role": role})
            if len(body.get("elements", [])) < 100:
                break
            start += 100
        for page in out:
            org_id = page["urn"].rsplit(":", 1)[-1]
            try:
                page["name"] = self.request("GET", f"/rest/organizations/{org_id}").json().get("localizedName")
            except LinkedInError:
                page["name"] = None
        return out

    def page(self, wanted: str | None) -> dict:
        """One page to post as: by name, id or URN, else the only page the member admins."""
        pages = self.pages()
        if wanted:
            w = wanted.strip().lower()
            for p in pages:
                if w in (p["urn"].lower(), p["urn"].rsplit(":", 1)[-1], (p.get("name") or "").lower()):
                    return p
            raise LinkedInError(f"You can't post as {wanted!r}. Your pages: "
                                + (", ".join(f"{p.get('name')} ({p['urn'].rsplit(':', 1)[-1]})" for p in pages)
                                   or "none"))
        if len(pages) == 1:
            return pages[0]
        if not pages:
            raise LinkedInError("You don't admin any LinkedIn page that this sign-in can post as.")
        raise LinkedInError("You admin several pages: pick one with Page. "
                            + ", ".join(f"{p.get('name')} ({p['urn'].rsplit(':', 1)[-1]})" for p in pages))

    def post(self, author: str, text: str, visibility: str = "PUBLIC") -> dict:
        """A text post as `author` (a person or organization URN): {"urn", "url"}. Links in the text show as links."""
        if len(text) > MAX_LENGTH:
            raise LinkedInError(f"The post is {len(text)} characters; LinkedIn allows {MAX_LENGTH}.")
        resp = self.request("POST", "/rest/posts", json={
            "author": author,
            "commentary": escape(text),
            "visibility": visibility,
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                             "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        })
        urn = resp.headers.get("x-restli-id") or resp.headers.get("x-linkedin-id") or ""
        return {"urn": urn, "url": post_url(urn) if urn else None}
