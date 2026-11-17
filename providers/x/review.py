"""X (Twitter): post as yourself. Posting previews first.

Each person signs in with their own X account through your X app (OAuth 2.0 with PKCE). offline.access keeps the
sign-in alive: X's access tokens last two hours and Callables refreshes them.
"""
from callables import Connection, Group, Secret

from providers.x.x_api import MAX_LENGTH, X, has_link, length

x = Connection(
    "x",
    title="X",
    authorize_url="https://x.com/i/oauth2/authorize",
    token_url="https://api.x.com/2/oauth2/token",
    scopes=["tweet.read", "tweet.write", "users.read", "offline.access"],
    pkce=True,
    token_endpoint_auth_method="client_secret_basic",
    userinfo_url="https://api.x.com/2/users/me",
    account_field="data.username",
    client_id=Secret("X_CLIENT_ID"),
    client_secret=Secret("X_CLIENT_SECRET"),
)

x_group = Group("x", title="X", description="Post to X as yourself. Posts preview first.", connections=[x])


def preview(text: str, username: str) -> dict:
    return {"result": "Preview only: nothing posted. Untick Dry run to post.", "as": f"@{username}",
            "characters": f"{length(text)} of {MAX_LENGTH} (links count as 23)",
            "x_cost": "about $0.20: X charges more for a post with a link" if has_link(text) else "about $0.015",
            "text": text}


@x_group.deploy(title="Post on X", name="post")
def post(text: str, reply_to: str | None = None, dry_run: bool = True) -> dict:
    """A post on X as you, up to 280 characters (links count as 23). Reply to is a post id, for a thread."""
    api = X(x.token)
    me = api.me()
    if dry_run:
        return preview(text, me["username"])
    return {"result": "Posted.", "as": f"@{me['username']}", **api.post(text, reply_to, me["username"])}
