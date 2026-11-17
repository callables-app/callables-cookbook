"""LinkedIn: post as yourself or as a company page you admin. Posting previews first.

Two connections on the same LinkedIn app, because LinkedIn approves page access separately:
- `linkedin` posts as you. Its scopes are self-serve (products "Sign In with LinkedIn using OpenID Connect" and
  "Share on LinkedIn"), so it works as soon as the app exists.
- `linkedin_pages` posts as a company page. Its scopes need LinkedIn's approval of the app (the Community
  Management API product). Asking for scopes the app doesn't have fails the whole sign-in, which is why it's apart.
"""
from typing import Literal

from callables import Connection, Group, Secret

from providers.linkedin.linkedin_api import MAX_LENGTH, LinkedIn

APP = {"authorize_url": "https://www.linkedin.com/oauth/v2/authorization",
       "token_url": "https://www.linkedin.com/oauth/v2/accessToken",
       "userinfo_url": "https://api.linkedin.com/v2/userinfo", "account_field": "name",
       "client_id": Secret("LINKEDIN_CLIENT_ID"), "client_secret": Secret("LINKEDIN_CLIENT_SECRET")}

linkedin = Connection("linkedin", title="LinkedIn", scopes=["openid", "profile", "w_member_social"], **APP)
linkedin_pages = Connection("linkedin_pages", title="LinkedIn pages",
                            scopes=["openid", "profile", "w_organization_social", "r_organization_admin"], **APP)

li = Group("linkedin", title="LinkedIn",
           description="Post to LinkedIn as yourself or as a company page you admin. Posts preview first.")

Visibility = Literal["Public", "Connections only"]


def _preview(text: str, as_who: str) -> dict:
    return {"result": "Preview only: nothing posted. Untick Dry run to post.", "as": as_who,
            "characters": f"{len(text)} of {MAX_LENGTH}", "text": text}


@li.deploy(title="Post on LinkedIn", name="post", connections=[linkedin])
def post(text: str, visibility: Visibility = "Public", dry_run: bool = True) -> dict:
    """A text post as you. Links in the text become clickable, and #hashtags work."""
    api = LinkedIn(linkedin.token)
    me = api.me()
    if dry_run:
        return _preview(text, me["name"])
    made = api.post(me["urn"], text, "PUBLIC" if visibility == "Public" else "CONNECTIONS")
    return {"result": "Posted.", "as": me["name"], **made}


@li.deploy(title="My LinkedIn pages", name="pages", connections=[linkedin_pages])
def pages() -> list[dict]:
    """The company pages you can post as, with your role on each."""
    return [{"page": p.get("name"), "role": p["role"], "page_id": p["urn"].rsplit(":", 1)[-1], "urn": p["urn"]}
            for p in LinkedIn(linkedin_pages.token).pages()]


@li.deploy(title="Post on a LinkedIn page", name="post_as_page", connections=[linkedin_pages])
def post_as_page(text: str, page: str | None = None, dry_run: bool = True) -> dict:
    """A text post as a company page you admin. Page is its name or id; empty means your only page."""
    api = LinkedIn(linkedin_pages.token)
    target = api.page(page)
    if dry_run:
        return _preview(text, target.get("name") or target["urn"])
    return {"result": "Posted.", "as": target.get("name"), **api.post(target["urn"], text)}
