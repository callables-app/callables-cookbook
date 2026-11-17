"""Google Search Console's API: https://developers.google.com/webmaster-tools. No callables here.

Signs in as the person running it, through the `search_console` connection (scope webmasters.readonly), so each
person sees the properties their own Google account can see. The OAuth app needs the Google Search Console API
enabled in its Google Cloud project.

Site is "example.com", "sc-domain:example.com" (a domain property) or "https://example.com/" (a URL prefix).
Left empty, the account's only property is used.

Dates default to the last 28 days ending 2 days ago (the last two days are still filling in). Page and Query
filter by "contains"; start them with = for an exact match, ! to exclude, or ~ for a regex. Country is a 3-letter
code (USA, GBR).

Metrics: clicks, impressions, ctr = clicks / impressions %, position = average ranking (1 is the top result).
"""
import time
from datetime import date, timedelta
from urllib.parse import quote

import requests

BASE = "https://www.googleapis.com/webmasters/v3"
INSPECT = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
MAX_ROWS = 25_000
SEARCH_TYPES = {"Web": "web", "Image": "image", "Video": "video", "News": "news", "Google News": "googleNews",
                "Discover": "discover"}
OPERATORS = {"=": "equals", "!": "notContains", "~": "includingRegex"}
# Typical CTR by position for web results. Rough, but enough to flag titles and descriptions that undersell.
EXPECTED_CTR = {1: 28.0, 2: 15.0, 3: 10.0, 4: 7.0, 5: 5.0, 6: 4.0, 7: 3.0, 8: 2.5, 9: 2.0, 10: 1.8}


class SearchConsoleError(RuntimeError):
    pass


def window(start: date | None, end: date | None, days: int = 28) -> tuple[date, date]:
    end = end or date.today() - timedelta(days=2)
    start = start or end - timedelta(days=days - 1)
    if start > end:
        raise ValueError(f"Start ({start}) is after End ({end}).")
    return start, end


def previous(start: date, end: date) -> tuple[date, date]:
    """The period of the same length just before start..end."""
    length = (end - start).days + 1
    return start - timedelta(days=length), start - timedelta(days=1)


def change(now, before) -> float | None:
    return round(100 * (now - before) / before, 1) if now is not None and before else None


def _message(resp: requests.Response) -> str:
    try:
        return resp.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return resp.text[:500]


class SearchConsole:
    def __init__(self, token: str):
        if not token:
            raise SearchConsoleError("No Google sign-in: connect Google Search Console first.")
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"

    def request(self, method: str, url: str, **kwargs):
        for attempt in range(5):
            resp = self.session.request(method, url, timeout=60, **kwargs)
            if resp.status_code in (429, 500, 503) and attempt < 4:
                time.sleep(2 ** attempt)
                continue
            if resp.status_code == 403 and "has not been used" in resp.text:
                raise SearchConsoleError("Enable the Google Search Console API in the OAuth app's Google Cloud "
                                         f"project: {_message(resp)}")
            if resp.status_code != 200:
                raise SearchConsoleError(f"Search Console failed ({resp.status_code}): {_message(resp)}")
            return resp.json()

    def sites(self) -> list[dict]:
        return self.request("GET", f"{BASE}/sites").get("siteEntry", [])

    def site(self, site: str | None = None) -> str:
        """The property to report on: `site` (a property or a bare domain), else the account's only one."""
        if site and (site.startswith("sc-domain:") or site.startswith("http")):
            return site
        entries = [s for s in self.sites() if s.get("permissionLevel") != "siteUnverifiedUser"]
        if site:
            domain = site.lower().removeprefix("www.").strip("/")
            for candidate in (f"sc-domain:{domain}", f"https://{domain}/", f"https://www.{domain}/"):
                if any(s["siteUrl"] == candidate for s in entries):
                    return candidate
            raise SearchConsoleError(f"No Search Console property for {site!r}. Properties: "
                                     + ", ".join(s["siteUrl"] for s in entries))
        if len(entries) == 1:
            return entries[0]["siteUrl"]
        if not entries:
            raise SearchConsoleError("This Google account has no verified Search Console properties.")
        raise SearchConsoleError("Your Google account has several Search Console properties: pick one with Site "
                                 "url: " + ", ".join(s["siteUrl"] for s in entries))

    def query(self, site: str, body: dict, limit: int) -> list[dict]:
        """searchAnalytics.query, paged up to `limit` rows."""
        rows, start = [], 0
        while len(rows) < limit:
            page = min(MAX_ROWS, limit - len(rows))
            data = self.request("POST", f"{BASE}/sites/{quote(site, safe='')}/searchAnalytics/query",
                                json={**body, "rowLimit": page, "startRow": start})
            batch = data.get("rows") or []
            rows += batch
            if len(batch) < page:
                break
            start += page
        return rows

    def sitemaps(self, site: str) -> list[dict]:
        return self.request("GET", f"{BASE}/sites/{quote(site, safe='')}/sitemaps").get("sitemap", [])

    def inspect(self, site: str, url: str) -> dict:
        return self.request("POST", INSPECT, json={"inspectionUrl": url, "siteUrl": site}).get("inspectionResult", {})

    def full_url(self, site: str, url: str) -> str:
        """A path like /blog/post/ as a full URL on the property."""
        if not url.startswith("/"):
            return url
        base = f"https://{site.removeprefix('sc-domain:')}" if site.startswith("sc-domain:") else site.rstrip("/")
        return base + url


# ── reports ──────────────────────────────────────────────────────────────────

def filters(page=None, query=None, country=None, device=None) -> list[dict]:
    out = []
    for dimension, value in (("page", page), ("query", query)):
        if value:
            operator = OPERATORS.get(value[0])
            out.append({"dimension": dimension, "operator": operator or "contains",
                        "expression": value[1:] if operator else value})
    if country:
        out.append({"dimension": "country", "operator": "equals", "expression": country.lower()})
    if device and device != "All":
        out.append({"dimension": "device", "operator": "equals", "expression": device.upper()})
    return [{"groupType": "and", "filters": out}] if out else []


def rows(client: SearchConsole, site: str, dimensions: list[str], start: date, end: date, filter_groups: list[dict],
         search_type: str = "Web", limit: int = 1000) -> list[dict]:
    body = {"startDate": start.isoformat(), "endDate": end.isoformat(), "dimensions": dimensions,
            "type": SEARCH_TYPES.get(search_type, search_type), "dataState": "all"}
    if filter_groups:
        body["dimensionFilterGroups"] = filter_groups
    out = []
    for r in client.query(site, body, limit):
        row = dict(zip(dimensions, r.get("keys") or []))
        row.update(clicks=int(r["clicks"]), impressions=int(r["impressions"]), ctr=round(100 * r["ctr"], 2),
                   position=round(r["position"], 1))
        out.append(row)
    return out


def report(token, dimensions, start=None, end=None, page=None, query=None, country=None, device=None,
           search_type="Web", limit=1000, site=None) -> list[dict]:
    """Clicks, impressions, CTR and position grouped by any of query, page, country, device, date."""
    client = SearchConsole(token)
    start, end = window(start, end)
    return rows(client, client.site(site), dimensions, start, end, filters(page, query, country, device),
                search_type, limit)


def totals(token, start=None, end=None, page=None, query=None, site=None) -> list[dict]:
    client = SearchConsole(token)
    site = client.site(site)
    start, end = window(start, end)
    groups = filters(page, query)
    a = (rows(client, site, [], start, end, groups, limit=1) or [{}])[0]
    b = (rows(client, site, [], *previous(start, end), groups, limit=1) or [{}])[0]
    return [{"metric": m, "value": a.get(m), "previous_period": b.get(m), "change_pct": change(a.get(m), b.get(m))}
            for m in ("clicks", "impressions", "ctr", "position")]


def changes(token, dimension="page", start=None, end=None, page=None, query=None, min_impressions=20, limit=200,
            site=None) -> list[dict]:
    """Each page (or query) now against the period before, biggest change in clicks first."""
    client = SearchConsole(token)
    site = client.site(site)
    start, end = window(start, end)
    groups = filters(page, query)
    now = {r[dimension]: r for r in rows(client, site, [dimension], start, end, groups, limit=5000)}
    before = {r[dimension]: r for r in rows(client, site, [dimension], *previous(start, end), groups, limit=5000)}
    out = []
    for key in now.keys() | before.keys():
        a, b = now.get(key, {}), before.get(key, {})
        if max(a.get("impressions", 0), b.get("impressions", 0)) < min_impressions:
            continue
        out.append({
            dimension: key,
            "clicks": a.get("clicks", 0), "clicks_before": b.get("clicks", 0),
            "clicks_change": a.get("clicks", 0) - b.get("clicks", 0),
            "impressions": a.get("impressions", 0), "impressions_before": b.get("impressions", 0),
            "impressions_change_pct": change(a.get("impressions", 0), b.get("impressions")),
            "position": a.get("position"), "position_before": b.get("position"),
        })
    out.sort(key=lambda r: (-abs(r["clicks_change"]), -abs(r["impressions"] - r["impressions_before"])))
    return out[:limit]


def opportunities(token, start=None, end=None, min_impressions=50, page=None, limit=200, site=None) -> list[dict]:
    """Query + page pairs worth working on:
    - Striking distance: ranking 5 to 20 with real impressions. Better content or internal links can reach the top 3.
    - Low CTR: on page one but clicked far less than its position usually gets. Rewrite the title or description.
    """
    client = SearchConsole(token)
    start, end = window(start, end)
    out = []
    for r in rows(client, client.site(site), ["query", "page"], start, end, filters(page), limit=25_000):
        if r["impressions"] < min_impressions:
            continue
        expected = EXPECTED_CTR.get(round(r["position"]))
        if 5 <= r["position"] <= 20:
            r["opportunity"] = "Striking distance"
        elif expected and r["ctr"] < expected / 2:
            r["opportunity"] = "Low CTR"
        else:
            continue
        r["expected_ctr"] = expected
        # The clicks it would get at position 3 (striking distance) or at its position's usual CTR (low CTR)
        target = EXPECTED_CTR[3] if r["opportunity"] == "Striking distance" else expected
        r["potential_extra_clicks"] = max(0, round(r["impressions"] * target / 100) - r["clicks"])
        out.append(r)
    out.sort(key=lambda r: -r["potential_extra_clicks"])
    return out[:limit]


def inspect_url(token, url, site=None) -> dict:
    """Whether Google has indexed a URL, and why not if it hasn't."""
    client = SearchConsole(token)
    site = client.site(site)
    url = client.full_url(site, url)
    result = client.inspect(site, url)
    index = result.get("indexStatusResult") or {}
    rich = result.get("richResultsResult") or {}
    return {
        "url": url,
        "verdict": index.get("verdict"),
        "coverage": index.get("coverageState"),
        "indexing": index.get("indexingState"),
        "robots_txt": index.get("robotsTxtState"),
        "page_fetch": index.get("pageFetchState"),
        "last_crawl": index.get("lastCrawlTime"),
        "crawled_as": index.get("crawledAs"),
        "google_canonical": index.get("googleCanonical"),
        "your_canonical": index.get("userCanonical"),
        "sitemaps": ", ".join(index.get("sitemap") or []),
        "referring_urls": ", ".join((index.get("referringUrls") or [])[:5]),
        "rich_results": rich.get("verdict"),
        "rich_result_types": ", ".join(i.get("richResultType", "") for i in rich.get("detectedItems") or []),
        "rich_result_issues": "; ".join(
            f"{item.get('name')}: {issue.get('issueMessage')}"
            for d in rich.get("detectedItems") or [] for item in d.get("items") or []
            for issue in item.get("issues") or []),
        "report": result.get("inspectionResultLink"),
    }


def sitemaps(token, site=None) -> list[dict]:
    client = SearchConsole(token)
    out = []
    for s in client.sitemaps(client.site(site)):
        contents = s.get("contents") or []
        out.append({
            "sitemap": s.get("path"),
            "last_submitted": (s.get("lastSubmitted") or "")[:10],
            "last_read": (s.get("lastDownloaded") or "")[:10],
            "pending": s.get("isPending"),
            "errors": int(s.get("errors") or 0),
            "warnings": int(s.get("warnings") or 0),
            "urls_submitted": sum(int(c.get("submitted") or 0) for c in contents),
        })
    return out


def sites(token) -> list[dict]:
    return [{"site": s.get("siteUrl"), "permission": s.get("permissionLevel")} for s in SearchConsole(token).sites()]
