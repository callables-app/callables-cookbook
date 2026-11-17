"""Bing Webmaster Tools' API: https://learn.microsoft.com/bingwebmaster/. No callables here.

How the site shows up in Bing, and the search engines Bing feeds (DuckDuckGo, Yahoo, Ecosia, ChatGPT search).
Needs BING_WEBMASTER_API_KEY (Bing Webmaster Tools > Settings > API access). BING_SITE_URL picks the site
(https://www.example.com/); without it, the only verified site is used.

Bing reports query and page stats per week and traffic per day, for roughly the last 6 months.
"""
import os
import re
import time
from datetime import date, datetime, timedelta, timezone

import requests

BASE = "https://ssl.bing.com/webmaster/api.svc/json"
SECRETS = ["BING_WEBMASTER_API_KEY", "BING_SITE_URL"]
MS_DATE = re.compile(r"/Date\((-?\d+)([+-]\d{4})?\)/")
TIME_BUDGET_SECONDS = 240  # runs stop at 300 s by default; leave room to return what's done


class BingError(RuntimeError):
    pass


def window(start: date | None, end: date | None, days: int = 28) -> tuple[date, date]:
    end = end or date.today() - timedelta(days=1)
    start = start or end - timedelta(days=days - 1)
    if start > end:
        raise ValueError(f"Start ({start}) is after End ({end}).")
    return start, end


def pct(part, whole, digits: int = 2) -> float | None:
    return round(100 * part / whole, digits) if whole and part is not None else None


def day(value) -> date | None:
    """A date from Microsoft's "/Date(1316156400000-0700)/", or None for missing and Bing's 0001-01-01 "never"."""
    match = MS_DATE.match(str(value or ""))
    if not match:
        return None
    try:
        d = datetime.fromtimestamp(int(match.group(1)) / 1000, timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None
    return d if d.year >= 2000 else None


def _key() -> str:
    key = os.environ.get("BING_WEBMASTER_API_KEY")
    if not key:
        raise BingError("Set BING_WEBMASTER_API_KEY (Bing Webmaster Tools > Settings > API access).")
    return key


def _message(resp: requests.Response) -> str:
    try:
        return resp.json().get("Message") or resp.text[:300]
    except ValueError:
        return resp.text[:300]


def get(method: str, **params):
    for attempt in range(4):
        resp = requests.get(f"{BASE}/{method}", params={**params, "apikey": _key()}, timeout=30)
        if resp.status_code in (429, 500, 503) and attempt < 3:
            time.sleep(2 ** attempt)
            continue
        if resp.status_code != 200:
            raise BingError(f"Bing {method} failed ({resp.status_code}): {_message(resp)}")
        return resp.json().get("d") or []


def post(method: str, body: dict):
    resp = requests.post(f"{BASE}/{method}", params={"apikey": _key()}, json=body, timeout=60,
                         headers={"Content-Type": "application/json; charset=utf-8"})
    if resp.status_code != 200:
        raise BingError(f"Bing {method} failed ({resp.status_code}): {_message(resp)}")
    return resp.json().get("d")


def site_url(site: str | None = None) -> str:
    """The site to report on: `site` (a URL or bare domain), else BING_SITE_URL, else the only verified site."""
    wanted = site or os.environ.get("BING_SITE_URL")
    if wanted and wanted.startswith("http"):
        return wanted
    sites = [s for s in get("GetUserSites") if s.get("IsVerified")]
    if wanted:
        domain = wanted.lower().removeprefix("www.").strip("/")
        for s in sites:
            if s["Url"].lower().split("//")[-1].removeprefix("www.").strip("/") == domain:
                return s["Url"]
        raise BingError(f"No verified Bing site {wanted!r}. Sites: " + ", ".join(s["Url"] for s in sites))
    if len(sites) == 1:
        return sites[0]["Url"]
    raise BingError("Set BING_SITE_URL or pick a Site url. Verified sites: " + ", ".join(s["Url"] for s in sites))


# ── reports ──────────────────────────────────────────────────────────────────

def _stats(method, column, start, end, contains, limit, site) -> list[dict]:
    """Query or page stats summed over the weeks in start..end."""
    start, end = window(start, end)
    totals: dict[str, dict] = {}
    for r in get(method, siteUrl=site_url(site)):
        d = day(r.get("Date"))
        key = r.get("Query") or ""
        if not d or not start <= d <= end or (contains and contains.lower() not in key.lower()):
            continue
        t = totals.setdefault(key, {column: key, "clicks": 0, "impressions": 0, "_pos": 0.0})
        t["clicks"] += r.get("Clicks") or 0
        t["impressions"] += r.get("Impressions") or 0
        t["_pos"] += (r.get("AvgImpressionPosition") or 0) * (r.get("Impressions") or 0)
    out = []
    for t in totals.values():
        weighted = t.pop("_pos")
        t["ctr"] = pct(t["clicks"], t["impressions"])
        t["position"] = round(weighted / t["impressions"], 1) if t["impressions"] else None
        out.append(t)
    out.sort(key=lambda r: (-r["clicks"], -r["impressions"]))
    return out[:limit]


def queries(start=None, end=None, contains=None, limit=500, site=None) -> list[dict]:
    return _stats("GetQueryStats", "query", start, end, contains, limit, site)


def pages(start=None, end=None, contains=None, limit=500, site=None) -> list[dict]:
    return _stats("GetPageStats", "page", start, end, contains, limit, site)


def traffic(start=None, end=None, site=None) -> list[dict]:
    start, end = window(start, end, days=90)
    out = []
    for r in get("GetRankAndTrafficStats", siteUrl=site_url(site)):
        d = day(r.get("Date"))
        if d and start <= d <= end:
            out.append({"date": d.isoformat(), "clicks": r.get("Clicks") or 0,
                        "impressions": r.get("Impressions") or 0, "ctr": pct(r.get("Clicks"), r.get("Impressions"))})
    return sorted(out, key=lambda r: r["date"])


def crawl(site=None) -> list[dict]:
    out = []
    for r in get("GetCrawlStats", siteUrl=site_url(site)):
        d = day(r.get("Date"))
        out.append({"date": d.isoformat() if d else None, "crawled": r.get("CrawledPages"),
                    "in_index": r.get("InIndex"), "crawl_errors": r.get("CrawlErrors"),
                    "ok_2xx": r.get("Code2xx"), "redirect_301": r.get("Code301"), "redirect_302": r.get("Code302"),
                    "client_4xx": r.get("Code4xx"), "server_5xx": r.get("Code5xx"),
                    "blocked_by_robots": r.get("BlockedByRobotsTxt"), "inbound_links": r.get("InLinks")})
    return sorted(out, key=lambda r: r["date"] or "", reverse=True)


def crawl_issues(site=None) -> list[dict]:
    return [{"url": r.get("Url"), "http_code": r.get("HttpCode"), "issues": r.get("Issues"),
             "inbound_links": r.get("InLinks")} for r in get("GetCrawlIssues", siteUrl=site_url(site))]


# ── URL status and submission ────────────────────────────────────────────────

def sitemap_urls(site: str) -> list[str]:
    """Every <loc> in the site's /sitemap.xml, following a sitemap index one level down."""
    def locs(url: str) -> list[str]:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "callables-cookbook/1.0"})
        resp.raise_for_status()
        return [u.strip() for u in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", resp.text)]

    urls: list[str] = []
    for u in locs(site.rstrip("/") + "/sitemap.xml"):
        urls.extend(locs(u) if u.endswith(".xml") else [u])
    return list(dict.fromkeys(urls))


def url_list(urls: str | None, site: str) -> list[str]:
    """URLs or paths, one per line or comma, as full URLs on the site. Empty means the whole sitemap."""
    if not urls:
        return sitemap_urls(site)
    root = site.rstrip("/")
    out = [u if u.startswith("http") else root + "/" + u.lstrip("/") for u in re.split(r"[\s,]+", urls.strip()) if u]
    return list(dict.fromkeys(out))


def url_info(site: str, url: str) -> dict:
    """What Bing knows about one URL. Bing throttles GetUrlInfo, so this retries and cools down."""
    info = None
    for attempt in range(3):
        try:
            info = get("GetUrlInfo", siteUrl=site, url=url) or {}
            break
        except BingError as e:
            if "Throttle" in str(e) and attempt < 2:
                time.sleep(4 * (attempt + 1))
                continue
            if "Throttle" in str(e):
                time.sleep(10)  # still throttled: cool down before the next URL
                info = {"_error": "Bing throttled this check; try again later"}
            else:
                info = {"_error": str(e)}
            break
        except (requests.RequestException, ValueError) as e:  # ValueError: Bing sent a non-JSON page
            if attempt < 2:
                time.sleep(2)
                continue
            info = {"_error": f"request failed: {e}"}
    crawled, discovered = day(info.get("LastCrawledDate")), day(info.get("DiscoveryDate"))
    return {
        "url": url,
        "crawled": None if "_error" in info else bool(crawled),
        "last_crawled": crawled.isoformat() if crawled else None,
        "discovered": discovered.isoformat() if discovered else None,
        "http_status": info.get("HttpStatus") or None,
        "size_bytes": info.get("DocumentSize") or None,
        "inbound_links": info.get("AnchorCount"),
        "note": info.get("_error", ""),
    }


def url_status(urls=None, site=None, start_at: int = 0) -> list[dict]:
    """Whether Bing has crawled each URL. A long list stops near the run's time limit and says where to resume."""
    site = site_url(site)
    todo = url_list(urls, site)
    started, out = time.monotonic(), []
    for i, url in enumerate(todo[start_at:], start=start_at):
        if time.monotonic() - started > TIME_BUDGET_SECONDS:
            out += [{"url": u, "crawled": None, "last_crawled": None, "discovered": None, "http_status": None,
                     "size_bytes": None, "inbound_links": None,
                     "note": f"not checked: time limit, run again with Start at {i}"} for u in todo[i:]]
            break
        if i > start_at:
            time.sleep(0.5)  # Bing answers "ThrottleHost" to rapid GetUrlInfo calls
        out.append(url_info(site, url))
    out.sort(key=lambda r: ({False: 0, None: 1, True: 2}[r["crawled"]], r["url"]))
    return out


def quota(site=None) -> dict:
    site = site_url(site)
    q = get("GetUrlSubmissionQuota", siteUrl=site) or {}
    return {"site": site, "daily_left": q.get("DailyQuota"), "monthly_left": q.get("MonthlyQuota")}


def submit_urls(urls=None, only_uncrawled=True, dry_run=True, site=None) -> list[dict]:
    """Ask Bing to crawl URLs now, up to the site's daily quota."""
    site = site_url(site)
    todo = url_list(urls, site)
    if only_uncrawled:
        todo = [r["url"] for r in url_status("\n".join(todo), site) if not r["crawled"]]
    left = quota(site)["daily_left"]
    send = todo if left is None else todo[: max(int(left), 0)]
    out = [{"url": u, "status": "would submit" if dry_run else "submitted"} for u in send]
    out += [{"url": u, "status": "over today's quota"} for u in todo[len(send):]]
    if send and not dry_run:
        for i in range(0, len(send), 500):
            post("SubmitUrlBatch", {"siteUrl": site, "urlList": send[i:i + 500]})
    return out
