"""Umami website analytics (API v3): https://umami.is/docs/api. No callables here, so any folder can import it.

Self-hosted: UMAMI_URL is your instance (https://umami.example.com), and you sign in with an API key
(UMAMI_API_KEY) or a user (UMAMI_USERNAME + UMAMI_PASSWORD; a view-only user is enough).
Umami Cloud: UMAMI_URL=https://api.umami.is and UMAMI_API_KEY.

UMAMI_WEBSITE_ID picks the website; without it, the only website the account can see is used.

Dates are whole UTC days and default to the last 30 days ending yesterday. Filters narrow any report, as
"name=value; name2=value": path, referrer, title, query, hostname, country (US), region, city, device (mobile,
desktop, tablet), browser, os, language, event, utmSource, utmMedium, utmCampaign. A value matches exactly
unless it starts with c. (contains), neq. (not equal) or re. (regex): "path=c./blog".

Metrics: visitors (unique), visits (sessions), pageviews, bounce_rate = single-page visits / visits %,
avg_visit_seconds = time on site per visit, views_per_visit.
"""
import os
import time
from datetime import date, datetime, time as clock, timedelta, timezone

import requests

SECRETS = ["UMAMI_URL", "UMAMI_API_KEY", "UMAMI_USERNAME", "UMAMI_PASSWORD", "UMAMI_WEBSITE_ID"]

DIMENSIONS = {
    "Page": "path", "Entry page": "entry", "Exit page": "exit", "Page title": "title", "Query string": "query",
    "Referrer": "referrer", "Channel": "channel", "Country": "country", "Region": "region", "City": "city",
    "Device": "device", "Browser": "browser", "OS": "os", "Language": "language", "Screen": "screen",
    "Event": "event", "UTM source": "utmSource", "UTM medium": "utmMedium", "UTM campaign": "utmCampaign",
    "UTM content": "utmContent", "UTM term": "utmTerm", "Hostname": "hostname",
}


class UmamiError(RuntimeError):
    pass


# ── numbers ──────────────────────────────────────────────────────────────────

def num(value) -> float | int | None:
    """A number from an API value that may arrive as a string (Umami sends big counts as "123")."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return value
    f = float(value)
    return int(f) if f.is_integer() else f


def pct(part, whole, digits: int = 1) -> float | None:
    part, whole = num(part), num(whole)
    return round(100 * part / whole, digits) if whole and part is not None else None


def change(now, before) -> float | None:
    """The % change from before to now, or None when before is 0."""
    return round(100 * (now - before) / before, 1) if now is not None and before else None


def parse_filters(text: str | None) -> dict[str, str]:
    """"path=/blog; country=US" -> {"path": "/blog", "country": "US"}."""
    out = {}
    for item in (text or "").split(";"):
        if not item.strip():
            continue
        name, sep, value = item.partition("=")
        if not sep or not name.strip():
            raise ValueError(f"Filters look like name=value; name2=value, got {item.strip()!r}.")
        out[name.strip()] = value.strip()
    return out


def window(start: date | None, end: date | None, days: int = 30) -> tuple[date, date, dict]:
    """The dates to report on, and the same range as Umami's startAt/endAt milliseconds."""
    end = end or date.today() - timedelta(days=1)
    start = start or end - timedelta(days=days - 1)
    if start > end:
        raise ValueError(f"Start ({start}) is after End ({end}).")
    start_at = datetime.combine(start, clock.min, timezone.utc)
    end_at = datetime.combine(end, clock.max, timezone.utc)
    return start, end, {"startAt": int(start_at.timestamp() * 1000), "endAt": int(end_at.timestamp() * 1000),
                        "timezone": "UTC"}


def _message(resp: requests.Response) -> str:
    try:
        body = resp.json()
        error = body.get("error", body) if isinstance(body, dict) else body
        if isinstance(error, dict):
            return error.get("message") or str(error)[:500]
        return str(error)[:500]
    except ValueError:
        return resp.text[:500]


# ── client ───────────────────────────────────────────────────────────────────

class Umami:
    def __init__(self):
        url = os.environ.get("UMAMI_URL", "").rstrip("/")
        if not url:
            raise UmamiError("Set UMAMI_URL to your Umami instance (or https://api.umami.is for Umami Cloud).")
        self.cloud = "api.umami.is" in url
        if self.cloud:
            self.base = url if url.endswith("/v1") else f"{url}/v1"
        else:
            self.base = url if url.endswith("/api") else f"{url}/api"
        self.session = requests.Session()
        key = os.environ.get("UMAMI_API_KEY")
        if key:
            if self.cloud:
                self.session.headers["x-umami-api-key"] = key
            else:
                self.session.headers["Authorization"] = f"Bearer {key}"
        else:
            self._sign_in()
        self._website_id = os.environ.get("UMAMI_WEBSITE_ID") or None

    def _sign_in(self):
        username, password = os.environ.get("UMAMI_USERNAME"), os.environ.get("UMAMI_PASSWORD")
        if not (username and password):
            raise UmamiError("Set UMAMI_API_KEY, or UMAMI_USERNAME and UMAMI_PASSWORD.")
        resp = requests.post(f"{self.base}/auth/login", json={"username": username, "password": password},
                             timeout=30)
        if resp.status_code != 200:
            raise UmamiError(f"Umami sign-in failed ({resp.status_code}): {_message(resp)}")
        body = resp.json()
        if body.get("requiresTwoFactor"):
            raise UmamiError("This Umami user has two-factor sign-in. Use an API key or a separate view-only user.")
        self.session.headers["Authorization"] = f"Bearer {body['token']}"

    def get(self, endpoint: str, /, **params):
        params = {k: v for k, v in params.items() if v not in (None, "")}
        for attempt in range(4):
            resp = self.session.get(f"{self.base}{endpoint}", params=params, timeout=60)
            if resp.status_code in (429, 502, 503, 504) and attempt < 3:
                time.sleep(float(resp.headers.get("Retry-After") or 2 ** attempt))
                continue
            if resp.status_code != 200:
                raise UmamiError(f"Umami {endpoint} failed ({resp.status_code}): {_message(resp)}")
            return resp.json()

    def websites(self) -> list[dict]:
        out, page = [], 1
        while True:
            body = self.get("/websites", page=page, pageSize=100)
            rows = body.get("data", body) if isinstance(body, dict) else body
            out += rows
            if not isinstance(body, dict) or len(out) >= int(body.get("count") or 0) or not rows:
                return out
            page += 1

    def website_id(self, website: str | None = None) -> str:
        """The website to report on: `website` (an id or domain), else UMAMI_WEBSITE_ID, else the only one."""
        wanted = website or self._website_id
        if wanted and len(wanted) == 36 and wanted.count("-") == 4:
            return wanted
        sites = self.websites()
        if wanted:
            domain = wanted.lower().removeprefix("https://").removeprefix("http://").removeprefix("www.").strip("/")
            for site in sites:
                if (site.get("domain") or "").lower().removeprefix("www.") == domain or site.get("name") == wanted:
                    return site["id"]
            raise UmamiError(f"No Umami website {wanted!r}. Websites: "
                             + ", ".join(f"{s.get('domain')} ({s['id']})" for s in sites))
        if len(sites) == 1:
            return sites[0]["id"]
        raise UmamiError("Several Umami websites: set UMAMI_WEBSITE_ID or pick one with Website. Websites: "
                         + ", ".join(f"{s.get('domain')} ({s['id']})" for s in sites))

    def stats(self, wid: str, /, **params) -> dict:
        return self.get(f"/websites/{wid}/stats", **params)

    def pageviews(self, wid: str, /, **params) -> dict:
        return self.get(f"/websites/{wid}/pageviews", **params)

    def metrics(self, wid: str, type: str, /, **params) -> list[dict]:
        """[{x, y}]: a dimension's values ranked by count."""
        return self.get(f"/websites/{wid}/metrics", type=type, **params)

    def expanded(self, wid: str, type: str, /, **params) -> list[dict]:
        """[{name, pageviews, visitors, visits, bounces, totaltime}] per value of a dimension."""
        return self.get(f"/websites/{wid}/metrics/expanded", type=type, **params)

    def active(self, wid: str) -> int:
        body = self.get(f"/websites/{wid}/active")
        return int(body.get("visitors", body.get("x", 0)) if isinstance(body, dict) else body or 0)

    def event_properties(self, wid: str, /, **params) -> list[dict]:
        return self.get(f"/websites/{wid}/event-data/events", **params)

    def event_values(self, wid: str, /, **params) -> list[dict]:
        return self.get(f"/websites/{wid}/event-data/values", **params)


# ── reports ──────────────────────────────────────────────────────────────────

def _rates(row: dict) -> dict:
    visits, pageviews = num(row.get("visits")) or 0, num(row.get("pageviews")) or 0
    totaltime = num(row.get("totaltime"))
    return {
        "visitors": num(row.get("visitors")) or 0,
        "visits": visits,
        "pageviews": pageviews,
        "bounce_rate": pct(row.get("bounces"), visits),
        "avg_visit_seconds": round(totaltime / visits) if visits and totaltime is not None else None,
        "views_per_visit": round(pageviews / visits, 2) if visits else None,
    }


def overview(start=None, end=None, filters=None, website=None) -> list[dict]:
    client = Umami()
    wid = client.website_id(website)
    _, _, params = window(start, end)
    body = client.stats(wid, **params, **parse_filters(filters))
    now, before = _rates(body), _rates(body.get("comparison") or {})
    rows = [{"metric": k, "value": v, "previous_period": before[k], "change_pct": change(v, before[k])}
            for k, v in now.items()]
    if not filters:
        rows.append({"metric": "active_now", "value": client.active(wid), "previous_period": None,
                     "change_pct": None})
    return rows


def trend(start=None, end=None, unit="day", filters=None, website=None) -> list[dict]:
    client = Umami()
    wid = client.website_id(website)
    _, _, params = window(start, end)
    body = client.pageviews(wid, unit=unit, **params, **parse_filters(filters))
    rows: dict[str, dict] = {}
    for key, name in (("pageviews", "pageviews"), ("sessions", "visitors")):
        for point in body.get(key) or []:
            bucket = str(point["x"])[: 10 if unit in ("day", "week", "month", "year") else 16].replace("T", " ")
            rows.setdefault(bucket, {"period": bucket, "pageviews": 0, "visitors": 0})[name] = point["y"]
    return sorted(rows.values(), key=lambda r: r["period"])


def breakdown(dimension="Page", start=None, end=None, filters=None, limit=100, website=None) -> list[dict]:
    type_ = DIMENSIONS.get(dimension, dimension)
    client = Umami()
    wid = client.website_id(website)
    _, _, params = window(start, end)
    rows = client.expanded(wid, type_, limit=limit, **params, **parse_filters(filters))
    column = {"entry": "path", "exit": "path"}.get(type_, type_)
    out = [{column: r.get("name") if r.get("name") not in (None, "") else "(none)", **_rates(r)} for r in rows]
    if type_ in ("path", "title", "query", "hostname") or type_.startswith("utm"):
        # A visit bounces, not a page, so page-level rows have no bounce rate: drop the empty column.
        for r in out:
            if not r["bounce_rate"]:
                r.pop("bounce_rate")
    return out


def pages(start=None, end=None, filters=None, limit=100, website=None) -> list[dict]:
    """Each page with visitors, pageviews, visits that started (entries) and ended (exits) there, and exit rate."""
    client = Umami()
    wid = client.website_id(website)
    _, _, params = window(start, end)
    extra = parse_filters(filters)
    rows = client.expanded(wid, "path", limit=limit, **params, **extra)
    entries = {r["x"]: num(r["y"]) for r in client.metrics(wid, "entry", limit=1000, **params, **extra)}
    exits = {r["x"]: num(r["y"]) for r in client.metrics(wid, "exit", limit=1000, **params, **extra)}
    out = []
    for r in rows:
        path = r.get("name") or "(none)"
        visits, totaltime, pageviews = num(r.get("visits")), num(r.get("totaltime")), num(r.get("pageviews")) or 0
        out.append({
            "path": path,
            "visitors": num(r.get("visitors")) or 0,
            "pageviews": pageviews,
            "entries": entries.get(path, 0),
            "exits": exits.get(path, 0),
            "exit_rate": pct(exits.get(path, 0), pageviews),
            "avg_visit_seconds": round(totaltime / visits) if visits and totaltime else None,
        })
    return out


def events(start=None, end=None, filters=None, limit=100, website=None) -> list[dict]:
    """Custom events: count, visitors, and each property's split by value."""
    client = Umami()
    wid = client.website_id(website)
    _, _, params = window(start, end)
    extra = parse_filters(filters)
    span = {"startAt": params["startAt"], "endAt": params["endAt"]}
    rows = client.expanded(wid, "event", limit=limit, **params, **extra)
    properties: dict[str, set] = {}
    try:
        for p in client.event_properties(wid, **span, **extra):
            properties.setdefault(p.get("eventName"), set()).add(p.get("propertyName"))
    except (UmamiError, requests.RequestException):  # event data is optional; the counts still stand
        pass
    out = []
    for r in rows:
        name = r.get("name")
        props = sorted(p for p in properties.get(name, ()) if p)
        parts = []
        for prop in props:  # e.g. "location: hero 31, nav 4"
            try:
                # The values endpoint ignores eventName, so filter by event as well.
                values = client.event_values(wid, **span, event=name, eventName=name, propertyName=prop, **extra)
            except (UmamiError, requests.RequestException):
                continue
            values = sorted(values, key=lambda v: -(num(v.get("total")) or 0))
            parts.append(f"{prop}: " + ", ".join(f"{v.get('value')} {num(v.get('total')) or 0}" for v in values))
        out.append({"event": name, "count": num(r.get("pageviews")) or 0,
                    "visitors": num(r.get("visitors")) or 0, "visits": num(r.get("visits")) or 0,
                    "properties": ", ".join(props), "breakdown": "; ".join(parts)})
    return out


def event_values(event, property, start=None, end=None, filters=None, website=None) -> list[dict]:
    client = Umami()
    wid = client.website_id(website)
    _, _, params = window(start, end)
    rows = client.event_values(wid, startAt=params["startAt"], endAt=params["endAt"], event=event, eventName=event,
                               propertyName=property, **parse_filters(filters))
    total = sum(num(r.get("total")) or 0 for r in rows)
    return [{"event": event, "property": property, "value": r.get("value"), "count": num(r.get("total")) or 0,
             "share_pct": pct(r.get("total"), total)}
            for r in sorted(rows, key=lambda r: -(num(r.get("total")) or 0))]


def websites() -> list[dict]:
    return [{"name": s.get("name"), "domain": s.get("domain"), "website_id": s["id"],
             "created": (s.get("createdAt") or "")[:10]} for s in Umami().websites()]
