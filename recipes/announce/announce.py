"""Announce: post to LinkedIn and X, then email your audience through Resend with links to the posts, in one run.

The email is a Resend broadcast built from one of your Resend templates. Besides any variables you pass, the run
fills these in the template:
- LINKEDIN_URL: the new LinkedIn post (empty if you skip LinkedIn)
- X_URL: the new X post (empty if you skip X)
- POST_TEXT: the post's text

If a post fails, the email isn't sent, and the result carries what you need to send it with Send email to a segment.
"""
from callables import Group, Next

from providers.linkedin.linkedin_api import MAX_LENGTH as LINKEDIN_MAX
from providers.linkedin.linkedin_api import LinkedIn
from providers.linkedin.review import linkedin, linkedin_pages
from providers.resend.resend_api import SECRETS as RESEND_SECRETS
from providers.resend.resend_api import Resend, parse_variables
from providers.resend.review import prepare_broadcast, send_broadcast
from providers.x.review import preview as x_preview
from providers.x.review import x
from providers.x.x_api import MAX_LENGTH as X_MAX
from providers.x.x_api import X, length

announce = Group("announce", title="Announce",
                 description="Post to LinkedIn and X, then email your audience with links to the posts, in one run. "
                             "Previews first.",
                 secrets=RESEND_SECRETS)

PREVIEW = "Preview only: nothing posted or sent. Untick Dry run to do it."
LINK_PLACEHOLDER = "(link to the new {} post)"


def _run(li_token: str, page: str | None, as_page: bool, text: str, x_text: str | None, post_linkedin: bool,
         post_x: bool, email: bool, template: str | None, segment: str | None, subject: str | None,
         variables: str | None, from_address: str | None, dry_run: bool) -> dict:
    x_text = (x_text or text).strip()
    if not (post_linkedin or post_x or email):
        raise ValueError("Tick at least one of Post linkedin, Post x and Email.")
    if email and not template:
        raise ValueError("Pick the Resend Template for the email (Templates in the Resend group lists them).")
    if post_x and length(x_text) > X_MAX:
        raise ValueError(f"The X text is {length(x_text)} characters as X counts them (links are 23); the limit is "
                         f"{X_MAX}. Write a shorter X text.")
    if post_linkedin and len(text) > LINKEDIN_MAX:
        raise ValueError(f"The post is {len(text)} characters; LinkedIn allows {LINKEDIN_MAX}.")

    out: dict = {}
    li_api = LinkedIn(li_token) if post_linkedin else None
    author = None
    if li_api:
        author = li_api.page(page) if as_page else li_api.me()
        out["linkedin_as"] = author.get("name") or author["urn"]
    x_api, me = (X(x.token), None) if post_x else (None, None)
    if x_api:
        me = x_api.me()
        out["x_as"] = f"@{me['username']}"
        out["x_cost"] = x_preview(x_text, me["username"])["x_cost"]

    values = parse_variables(variables)
    values.setdefault("POST_TEXT", text)

    if dry_run:
        values.setdefault("LINKEDIN_URL", LINK_PLACEHOLDER.format("LinkedIn") if post_linkedin else "")
        values.setdefault("X_URL", LINK_PLACEHOLDER.format("X") if post_x else "")
        out = {"result": PREVIEW, **out}
        if post_linkedin:
            out["linkedin_text"] = f"{len(text)} of {LINKEDIN_MAX} characters"
        if post_x:
            out["x_text"] = f"{length(x_text)} of {X_MAX} characters: {x_text}"
        if email:
            _, summary, missing = prepare_broadcast(segment, template, subject, values, from_address)
            out.update({f"email_{k}": v for k, v in summary.items()})
            if missing:
                out["email_problem"] = f"The template needs {', '.join(missing)}: add them to Variables."
        return out

    errors = []
    if li_api:
        try:
            made = li_api.post(author["urn"], text)
            out["linkedin_url"] = made["url"]
        except Exception as e:  # noqa: BLE001 - keep going so the other post still happens
            errors.append(f"LinkedIn: {e}")
    if x_api:
        try:
            out["x_url"] = x_api.post(x_text, username=me["username"])["url"]
        except Exception as e:  # noqa: BLE001
            errors.append(f"X: {e}")
    values.setdefault("LINKEDIN_URL", out.get("linkedin_url") or "")
    values.setdefault("X_URL", out.get("x_url") or "")
    email_inputs = {"template": template, "segment": segment, "subject": subject,
                    "variables": "; ".join(f"{k}={v}" for k, v in values.items() if k != "POST_TEXT")}

    if errors:
        return {"result": "Not everything posted, so the email wasn't sent. Fix it, then use Send the email.",
                "errors": " | ".join(errors), **out, **email_inputs}
    if not email:
        return {"result": "Posted.", **out}
    body, summary, missing = prepare_broadcast(segment, template, subject, values, from_address)
    if missing:
        return {"result": f"Posted, but the email wasn't sent: the template needs {', '.join(missing)}.",
                **out, **email_inputs}
    body["send"] = True
    broadcast_id = Resend().create_broadcast(body)
    return {"result": "Posted and emailed.", **out, "email_segment": summary["segment"],
            "email_subject": summary["subject"], "broadcast_id": broadcast_id}


NEXT = [Next(send_broadcast, label="Send the email")]


@announce.deploy(title="Post everywhere", name="post_everywhere", connections=[linkedin, x], next=NEXT)
def post_everywhere(text: str, x_text: str | None = None, post_linkedin: bool = True, post_x: bool = True,
                    email: bool = True, template: str | None = None, segment: str | None = None,
                    subject: str | None = None, variables: str | None = None, from_address: str | None = None,
                    dry_run: bool = True) -> dict:
    """Post to LinkedIn and X as yourself, then email a Resend segment with links to both posts.

    X text replaces Text on X (280 characters, links count as 23). The email uses your Resend Template, with
    LINKEDIN_URL, X_URL and POST_TEXT filled in, plus any Variables ("KEY=value; KEY2=value"). Untick Dry run to
    post and send.
    """
    return _run(linkedin.token if post_linkedin else "", None, False, text, x_text, post_linkedin, post_x, email,
                template, segment, subject, variables, from_address, dry_run)


@announce.deploy(title="Post everywhere as a page", name="post_everywhere_as_page",
                 connections=[linkedin_pages, x], next=NEXT)
def post_everywhere_as_page(text: str, page: str | None = None, x_text: str | None = None,
                            post_linkedin: bool = True, post_x: bool = True, email: bool = True,
                            template: str | None = None, segment: str | None = None, subject: str | None = None,
                            variables: str | None = None, from_address: str | None = None,
                            dry_run: bool = True) -> dict:
    """The same as Post everywhere, but on LinkedIn as a company page you admin. Page is its name or id; empty means
    your only page. Needs LinkedIn's approval of your app for page posting."""
    return _run(linkedin_pages.token if post_linkedin else "", page, True, text, x_text, post_linkedin, post_x,
                email, template, segment, subject, variables, from_address, dry_run)
