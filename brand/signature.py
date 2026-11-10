"""The company's email signature: the look, the HTML and the plain-text version. Shared by the Outlook and Gmail
signature callables, so both make the same signature. No callables here, just the template."""
import html
import re

# The company's look: Callables' own. It rarely changes, so it lives here; swap in yours. The logo has to be a square PNG
# or JPG at a public, stable address: email apps don't show SVGs, and recipients can't load a file from your computer.
COMPANY = {
    "name": "Callables",
    "tagline": "Turn Python functions into tools your team can run",
    "website": "https://callables.app",
    "logo": "https://callables.app/brand/icon-192.png",
    "color": "#ff6b45",  # the divider: the brand's coral
    "text_color": "#d9481f",  # the name and links: the coral, darkened enough to read on white
}
FONT = "'Segoe UI', Arial, Helvetica, sans-serif"  # what Outlook shows on Windows, with fallbacks everywhere else
# What a person dict holds; any of them can be blank except the name
FIELDS = ("name", "title", "department", "phone", "email", "office")


def _tel(phone: str) -> str:
    """A phone number as a tel: link target: digits and a leading +."""
    return "tel:" + re.sub(r"[^\d+]", "", phone)


def _line(*parts: str) -> str:
    return " &nbsp;|&nbsp; ".join(p for p in parts if p)


def render(person: dict, style: str) -> str:
    """The signature as HTML that survives pasting into an email app: a table with inline styles, nothing else."""
    person = {k: person.get(k) or "" for k in FIELDS}
    e = {k: html.escape(v) for k, v in person.items()}
    c = {k: html.escape(v) for k, v in COMPANY.items()}
    phone = f'<a href="{html.escape(_tel(person["phone"]))}" style="color:#1f2328;text-decoration:none">{e["phone"]}</a>' if person["phone"] else ""
    email = f'<a href="mailto:{e["email"]}" style="color:#1f2328;text-decoration:none">{e["email"]}</a>' if person["email"] else ""
    site = f'<a href="{c["website"]}" style="color:{c["text_color"]};text-decoration:none">{c["website"].split("//")[-1]}</a>'
    role = _line(e["title"], e["department"])

    if style == "compact":
        return (f'<p style="margin:0;font-family:{FONT};font-size:13px;line-height:1.5;color:#1f2328">'
                f'<strong>{e["name"]}</strong>{" &nbsp;|&nbsp; " + role if role else ""}<br>'
                f'<strong style="color:{c["text_color"]}">{c["name"]}</strong> &nbsp;|&nbsp; {_line(phone, email, site)}</p>')

    logo = (f'<a href="{c["website"]}"><img src="{c["logo"]}" width="56" height="56" alt="{c["name"]}" '
            f'style="display:block;border:0;width:56px;height:56px"></a>')
    rows = [
        f'<p style="margin:0;font-size:15px;font-weight:600;color:#0a2540">{e["name"]}</p>',
        f'<p style="margin:0;color:#57606a">{role}</p>' if role else "",
        f'<p style="margin:8px 0 0 0"><strong style="color:{c["text_color"]}">{c["name"]}</strong>'
        f'<span style="color:#57606a"> &mdash; {c["tagline"]}</span></p>',
        f'<p style="margin:0">{_line(phone, email)}</p>' if phone or email else "",
        f'<p style="margin:0">{_line(site, e["office"])}</p>',
    ]
    return (f'<table cellpadding="0" cellspacing="0" border="0" style="font-family:{FONT};font-size:13px;line-height:1.5;color:#1f2328">'
            f'<tr><td style="padding:2px 14px 0 0;vertical-align:top">{logo}</td>'
            f'<td style="border-left:3px solid {c["color"]};padding-left:14px;vertical-align:top">{"".join(r for r in rows if r)}</td></tr></table>')


def plain(person: dict) -> str:
    """The same signature as plain text, for plain-text emails and replies."""
    p = {k: person.get(k) or "" for k in FIELDS}
    lines = [p["name"], _line(p["title"], p["department"]).replace("&nbsp;", " "),
             f'{COMPANY["name"]} | {COMPANY["website"].split("//")[-1]}', _line(p["phone"], p["email"]).replace("&nbsp;", " ")]
    return "\n".join(line for line in lines if line.strip())


def page(signature: str, title: str = "Email signature") -> bytes:
    """A signature as a standalone HTML file, to open in a browser and copy."""
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title></head>'
            f'<body style="margin:32px">{signature}</body></html>').encode()


def missing_note(person: dict) -> str:
    """A note naming the job title or phone number the profile didn't have, or "" if it had both."""
    missing = [label for key, label in (("title", "job title"), ("phone", "phone number")) if not person.get(key)]
    if not missing:
        return ""
    many = len(missing) > 1
    them = "them" if many else "it"
    return (f"\n\nYour profile has no {' or '.join(missing)}, so {'they are' if many else 'it is'} left out. "
            f"Fill {them} in above and run again to add {them}.")
