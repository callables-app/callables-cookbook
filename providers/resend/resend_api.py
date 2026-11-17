"""A small Resend API client: segments, templates and broadcasts. No callables in here, so any folder (or recipe)
can import it: `from providers.resend.resend_api import Resend`.

Broadcasts can't reference a template in Resend's API (only single emails can), so `render()` fills a template's
{{{VARIABLES}}} here and the result is sent as the broadcast's HTML. Per-contact placeholders such as
{{{contact.first_name|there}}} and the unsubscribe link are left for Resend to fill for each person.
"""
import html as html_lib
import os
import re
import time

import requests

API = "https://api.resend.com"
SECRETS = ["RESEND_API_KEY", "RESEND_FROM"]
UNSUBSCRIBE = "{{{RESEND_UNSUBSCRIBE_URL}}}"
VARIABLE = re.compile(r"\{\{\{\s*([A-Za-z0-9_.]+)\s*(?:\|([^}]*))?\}\}\}")
# Optional sections: <!--if:BLOG_URL-->...<!--endif:BLOG_URL--> is dropped when BLOG_URL is empty.
# <!--if:LINKEDIN_URL,X_URL--> keeps the section when any of them is set. Resend's templates have no conditionals.
SECTION = re.compile(r"<!--\s*if:\s*([A-Za-z0-9_,\s]+?)\s*-->(.*?)<!--\s*endif:\s*\1\s*-->", re.S)
# Template placeholders Resend fills for single emails, spelled the way broadcasts expect them
CONTACT = {"FIRST_NAME": "contact.first_name", "LAST_NAME": "contact.last_name", "EMAIL": "contact.email"}


class ResendError(RuntimeError):
    pass


def parse_variables(text: str | None) -> dict[str, str]:
    """"KEY=value; KEY2=value" -> {"KEY": "value", "KEY2": "value"}."""
    out = {}
    for item in (text or "").split(";"):
        if item.strip():
            key, sep, value = item.partition("=")
            if not sep or not key.strip():
                raise ValueError(f"Variables look like KEY=value; KEY2=value, got {item.strip()!r}.")
            out[key.strip()] = value.strip()
    return out


def render(text: str, declared: list[dict], values: dict[str, str], as_html: bool = False) -> tuple[str, list[str]]:
    """The template's {{{KEY}}} variables filled from `values`, else their fallback. Returns the text and the keys
    that have neither (left in place, so the caller can refuse to send). as_html escapes the values and turns line
    breaks into <br>, so a post's text can't break the email's HTML. Optional sections (see SECTION) whose variables
    are all empty are removed first, so their variables don't count as missing."""
    defaults = {v["key"]: v.get("fallback_value") for v in declared or []}
    missing: list[str] = []

    def section(m: re.Match) -> str:
        keys = [k.strip() for k in m.group(1).split(",") if k.strip()]
        keep = any(values.get(k) or defaults.get(k) for k in keys)
        return m.group(2) if keep else ""

    text = text or ""
    while True:  # nested sections: the outer one goes first, then what's left inside it
        new = SECTION.sub(section, text)
        if new == text:
            break
        text = new
    if not as_html:
        text = re.sub(r"\n{3,}", "\n\n", text)  # removed sections leave blank lines in plain text

    def fill(m: re.Match) -> str:
        key, fallback = m.group(1), m.group(2)
        if key == "RESEND_UNSUBSCRIBE_URL" or key.startswith("contact."):
            return m.group(0)  # Resend fills these per contact
        if key == "UNSUBSCRIBE_URL":
            return UNSUBSCRIBE
        if key in CONTACT:
            return "{{{" + CONTACT[key] + (f"|{fallback}" if fallback is not None else "") + "}}}"
        value = values.get(key)
        if value is None:
            value = defaults.get(key) if defaults.get(key) is not None else fallback
        if value is None:
            missing.append(key)
            return m.group(0)
        return html_lib.escape(str(value)).replace("\n", "<br>") if as_html else str(value)

    return VARIABLE.sub(fill, text), sorted(set(missing))


def with_unsubscribe(html: str) -> str:
    """Broadcast HTML with an unsubscribe link: the template's own, else a small footer."""
    if "RESEND_UNSUBSCRIBE_URL" in html:
        return html
    footer = (f'<p style="font-size:12px;color:#888;text-align:center">'
              f'<a href="{UNSUBSCRIBE}" style="color:#888">Unsubscribe</a></p>')
    return re.sub(r"</body>", footer + "</body>", html, count=1, flags=re.I) if re.search(r"</body>", html, re.I) \
        else html + footer


class Resend:
    def __init__(self):
        key = os.environ.get("RESEND_API_KEY")
        if not key:
            raise ResendError("Set RESEND_API_KEY (Resend > API Keys) in the project's secrets.")
        self.session = requests.Session()
        # Resend refuses requests without a User-Agent
        self.session.headers.update({"Authorization": f"Bearer {key}", "User-Agent": "callables-cookbook/1.0"})

    def request(self, method: str, path: str, **kwargs) -> dict:
        for attempt in range(4):
            resp = self.session.request(method, f"{API}{path}", timeout=30, **kwargs)
            if resp.status_code == 429 and attempt < 3:
                time.sleep(float(resp.headers.get("retry-after") or 1))
                continue
            if not resp.ok:
                try:
                    message = resp.json().get("message") or resp.text[:300]
                except ValueError:
                    message = resp.text[:300]
                raise ResendError(f"Resend {method} {path} failed ({resp.status_code}): {message}")
            return resp.json() if resp.content else {}

    def _all(self, path: str) -> list[dict]:
        out, after = [], None
        while True:
            body = self.request("GET", path, params={"limit": 100, **({"after": after} if after else {})})
            out += body.get("data", [])
            if not body.get("has_more") or not body.get("data"):
                return out
            after = body["data"][-1]["id"]

    def segments(self) -> list[dict]:
        return self._all("/segments")

    def segment(self, wanted: str | None) -> dict:
        """A segment by id or name, else the only one."""
        segments = self.segments()
        if wanted:
            w = wanted.strip().lower()
            for s in segments:
                if w in (s["id"].lower(), (s.get("name") or "").lower()):
                    return s
            raise ResendError(f"No Resend segment {wanted!r}. Segments: "
                              + (", ".join(s.get("name") or s["id"] for s in segments) or "none"))
        if len(segments) == 1:
            return segments[0]
        raise ResendError("Pick a Segment: " + (", ".join(s.get("name") or s["id"] for s in segments) or "none"))

    def templates(self) -> list[dict]:
        return self._all("/templates")

    def template(self, id_or_alias: str) -> dict:
        """One template with its html, text, subject, from and declared variables. Also finds one by name."""
        try:
            return self.request("GET", f"/templates/{id_or_alias}")
        except ResendError:
            match = next((t for t in self.templates() if (t.get("name") or "").lower() == id_or_alias.lower()), None)
            if not match:
                raise ResendError(f"No Resend template {id_or_alias!r}: use its id, alias or exact name.")
            return self.request("GET", f"/templates/{match['id']}")

    def broadcasts(self) -> list[dict]:
        return self._all("/broadcasts")

    def create_broadcast(self, body: dict) -> str:
        return self.request("POST", "/broadcasts", json=body)["id"]
