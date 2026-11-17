"""Resend: email a segment of your contacts, from one of your Resend templates. Sending previews first."""
import os

from callables import Group

from providers.resend.resend_api import SECRETS, Resend, parse_variables, render, with_unsubscribe

resend = Group("resend", title="Resend",
               description="Email your audience with Resend: segments, templates, and broadcasts sent from a "
                           "template. Sending previews first.",
               secrets=SECRETS)


def prepare_broadcast(segment: str | None, template: str, subject: str | None = None,
                      values: dict[str, str] | None = None, from_address: str | None = None,
                      name: str | None = None) -> tuple[dict, dict, list[str]]:
    """Everything a broadcast needs, from a template: (the request body, a summary to show, the template variables
    nothing filled). Plain function, for recipes."""
    api = Resend()
    seg = api.segment(segment)
    tpl = api.template(template)
    values = values or {}
    html, missing_html = render(tpl.get("html") or "", tpl.get("variables") or [], values, as_html=True)
    text, missing_text = render(tpl.get("text") or "", tpl.get("variables") or [], values)
    subj, missing_subject = render(subject or tpl.get("subject") or "", tpl.get("variables") or [], values)
    sender = from_address or tpl.get("from") or os.environ.get("RESEND_FROM")
    if not sender:
        raise ValueError("Who is it from? Set From, a sender on the template, or the RESEND_FROM secret "
                         "(like Dan <dan@example.com>, on a domain verified in Resend).")
    if not subj:
        raise ValueError("Set a Subject, or one on the template.")
    body = {"segment_id": seg["id"], "from": sender, "subject": subj, "html": with_unsubscribe(html),
            "name": name or subj}
    if text:
        body["text"] = text
    summary = {"segment": seg.get("name") or seg["id"], "template": tpl.get("name"),
               "template_status": tpl.get("status"), "from": sender, "subject": subj,
               "variables": "; ".join(f"{k}={v}" for k, v in values.items()) or "none"}
    if tpl.get("status") != "published" or tpl.get("has_unpublished_versions"):
        summary["template_note"] = "The template has unpublished changes; the broadcast uses what's saved now."
    return body, summary, sorted(set(missing_html + missing_text + missing_subject))


@resend.deploy(title="Segments")
def segments() -> list[dict]:
    """Your Resend segments: the groups of contacts a broadcast goes to."""
    return [{"segment": s.get("name"), "segment_id": s["id"], "created": (s.get("created_at") or "")[:10]}
            for s in Resend().segments()]


@resend.deploy(title="Templates")
def templates() -> list[dict]:
    """Your Resend templates, with the variables each one takes and their fallbacks."""
    api = Resend()
    rows = []
    for t in api.templates():
        full = api.template(t["id"])
        rows.append({
            "template": t.get("name"), "alias": t.get("alias"), "status": t.get("status"),
            "subject": full.get("subject"),
            "variables": ", ".join(f"{v['key']}" + (f" (default {v['fallback_value']})" if v.get("fallback_value")
                                                     is not None else "") for v in full.get("variables") or []),
            "template_id": t["id"],
        })
    return rows


@resend.deploy(title="Send email to a segment", name="send_broadcast")
def send_broadcast(template: str, segment: str | None = None, subject: str | None = None,
                   variables: str | None = None, from_address: str | None = None, send_at: str | None = None,
                   dry_run: bool = True) -> dict:
    """A broadcast to a segment, built from one of your Resend templates.

    Template is its id, alias or name. Variables fill its {{{KEYS}}}, like "LINK=https://...; TITLE=Launch".
    Send at schedules it ("in 1 hour", or an ISO time); empty sends now. Untick Dry run to send.
    """
    body, summary, missing = prepare_broadcast(segment, template, subject, parse_variables(variables), from_address)
    if missing:
        raise ValueError(f"The template needs {', '.join(missing)}: add them to Variables, or give them a fallback "
                         "in Resend.")
    if dry_run:
        return {"result": "Preview only: nothing sent. Untick Dry run to send.", **summary,
                "when": send_at or "now"}
    body["send"] = True
    if send_at:
        body["scheduled_at"] = send_at
    broadcast_id = Resend().create_broadcast(body)
    return {"result": f"Scheduled for {send_at}." if send_at else "Sending.", **summary,
            "broadcast_id": broadcast_id}


@resend.deploy(title="Broadcasts")
def broadcasts() -> list[dict]:
    """Your recent broadcasts: status, when they were sent or are scheduled, and their segment."""
    return [{"broadcast": b.get("name"), "status": b.get("status"), "segment_id": b.get("segment_id")
             or b.get("audience_id"), "scheduled_at": b.get("scheduled_at"), "sent_at": b.get("sent_at"),
             "created": (b.get("created_at") or "")[:10], "broadcast_id": b["id"]} for b in Resend().broadcasts()]
