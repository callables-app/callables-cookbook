"""SEO toolkit: Google Search Console, Bing Webmaster Tools and Umami together, so one run answers questions that
otherwise take three dashboards: how search is doing overall, which pages to fix next, what's wrong with one page,
and which pages each search engine hasn't indexed.

Everything is live and nothing is stored. Each platform is optional: a run uses the ones that are set up and says
which ones it skipped and why.

Site is your domain, like example.com. Each platform matches it to its own property; empty uses each one's default
(BING_SITE_URL, UMAMI_WEBSITE_ID, or the only property the account has).
"""
import time
from datetime import date
from urllib.parse import urlparse

from callables import Group, Next

from providers.google.search_console import search_console_api as gsc_api
from providers.google.search_console.review import inspect_url, query_pages, search_console
from providers.microsoft.bing import bing_api
from providers.microsoft.bing.review import submit_urls
from providers.umami import umami_api

seo = Group(
    "seo",
    title="SEO toolkit",
    description="Google Search Console, Bing Webmaster and Umami together: the search scorecard, which pages to fix "
                "next, a full report on one page, and which pages aren't indexed.",
    secrets=sorted(set(bing_api.SECRETS + umami_api.SECRETS)),
    connections=[search_console],
)

TIME_BUDGET_SECONDS = 240  # runs stop at 300 s by default; return what's done before then


def _path(url: str) -> str:
    """The path of a URL, without a trailing slash, so Google's, Bing's and Umami's page keys line up."""
    path = urlparse(url).path if url.startswith("http") else url
    return path.rstrip("/") or "/"


def _try(skipped: list[dict], source: str, fn, *args, default=None):
    """Run one platform's part; if it isn't set up or fails, note why and carry on with the others."""
    try:
        return fn(*args)
    except Exception as e:  # noqa: BLE001 - any platform failure becomes a "skipped" note
        skipped.append({"source": source, "skipped": str(e)[:300]})
        return default


# ── scorecard ────────────────────────────────────────────────────────────────

def _google_totals(site, start, end) -> list[dict]:
    return [{"source": "Google", **r} for r in gsc_api.totals(search_console.token, start, end, None, None, site)]


def _bing_totals(site, start, end) -> list[dict]:
    start, end = bing_api.window(start, end)
    before_start, before_end = gsc_api.previous(start, end)
    days = bing_api.traffic(before_start, end, site)
    rows = []
    for metric in ("clicks", "impressions"):
        now = sum(d[metric] for d in days if start.isoformat() <= d["date"])
        before = sum(d[metric] for d in days if d["date"] <= before_end.isoformat())
        rows.append({"source": "Bing", "metric": metric, "value": now, "previous_period": before,
                     "change_pct": gsc_api.change(now, before)})
    return rows


def _umami_search_visitors(site, start, end) -> list[dict]:
    """Visitors arriving from organic search, by Umami's Channel."""
    start, end, _ = umami_api.window(start, end)
    before_start, before_end = gsc_api.previous(start, end)

    def organic(a, b) -> int:
        rows = umami_api.breakdown("Channel", a, b, None, 50, site)
        return sum(r["visitors"] for r in rows
                   if "search" in str(r.get("channel", "")).lower() and "paid" not in str(r.get("channel", "")).lower())

    now, before = organic(start, end), organic(before_start, before_end)
    return [{"source": "Umami", "metric": "visitors from organic search", "value": now, "previous_period": before,
             "change_pct": gsc_api.change(now, before)}]


@seo.deploy(title="SEO scorecard", name="scorecard")
def scorecard(site: str | None = None, start: date | None = None, end: date | None = None) -> list[dict]:
    """Search at a glance against the period just before: Google clicks, impressions, CTR and position, Bing clicks
    and impressions, and the visitors Umami saw arrive from search.

    Dates default to the last 28 days. Schedule it weekly to keep an eye on things.
    """
    skipped: list[dict] = []
    rows = _try(skipped, "Google", _google_totals, site, start, end, default=[])
    rows += _try(skipped, "Bing", _bing_totals, site, start, end, default=[])
    rows += _try(skipped, "Umami", _umami_search_visitors, site, start, end, default=[])
    return rows + [{"source": s["source"], "metric": "skipped", "value": s["skipped"]} for s in skipped]


# ── pages to fix next ────────────────────────────────────────────────────────

def _suggestion(row: dict) -> str:
    exit_rate = row.get("exit_rate")
    if row["opportunity"] == "Low CTR":
        tip = "Rewrite the title and meta description to match the query; it ranks but doesn't get the click."
    elif row["position"] <= 10:
        tip = "On page one but below the top 3: cover the query more fully and link to the page from related pages."
    else:
        tip = "On page two: add a section for this query, put it in a heading, and add internal links."
    if exit_rate is not None and exit_rate >= 70:
        tip += f" Visitors also leave fast ({exit_rate}% exit), so check the page answers the search."
    return tip


@seo.deploy(title="Pages to fix next", name="opportunities",
            next=[Next(inspect_url, label="Inspect in Google", url="page"),
                  Next(query_pages, label="Other pages for this query", query="query")])
def opportunities(site: str | None = None, min_impressions: int = 50, limit: int = 50, start: date | None = None,
                  end: date | None = None) -> list[dict]:
    """Query + page pairs worth working on, most extra clicks first, with what to do about each.

    From Google: pages ranking 5 to 20 (striking distance) or on page one with a low CTR. Each row adds the query's
    Bing position, and the page's visitors and exit rate from Umami, so you can tell a ranking problem from a page
    that doesn't hold people.
    """
    rows = gsc_api.opportunities(search_console.token, start, end, min_impressions, None, limit, site)
    skipped: list[dict] = []
    bing = {r["query"].lower(): r for r in _try(skipped, "Bing", bing_api.queries, start, end, None, 5000, site,
                                                default=[])}
    umami = {_path(r["path"]): r for r in _try(skipped, "Umami", umami_api.pages, start, end, None, 1000, site,
                                               default=[])}
    for r in rows:
        b, u = bing.get(r["query"].lower(), {}), umami.get(_path(r["page"]), {})
        r["bing_position"] = b.get("position")
        r["bing_clicks"] = b.get("clicks")
        r["visitors"] = u.get("visitors")
        r["exit_rate"] = u.get("exit_rate")
        r["avg_visit_seconds"] = u.get("avg_visit_seconds")
        r["suggestion"] = _suggestion(r)
    if skipped:
        note = "; ".join(f"{s['source']} skipped: {s['skipped']}" for s in skipped)
        for r in rows:
            r["note"] = note
    return rows


# ── one page ─────────────────────────────────────────────────────────────────

@seo.deploy(title="Page report", name="page_report")
def page_report(page: str, site: str | None = None, start: date | None = None, end: date | None = None) -> str:
    """Everything about one page: Google clicks, position, top queries and index status; Bing clicks and crawl
    status; and Umami visitors, entries and exit rate.

    Page is a full URL or a path like /blog/post/.
    """
    token = search_console.token
    skipped: list[dict] = []
    path = _path(page)
    lines = [f"# {page}", ""]

    def google():
        client = gsc_api.SearchConsole(token)
        prop = client.site(site)
        url = client.full_url(prop, page)
        exact = "=" + url
        totals = gsc_api.totals(token, start, end, exact, None, prop)
        queries = gsc_api.report(token, ["query"], start, end, exact, None, limit=10, site=prop)
        index = gsc_api.inspect_url(token, url, prop)
        out = ["## Google", "", "| Metric | Now | Before | Change % |", "|---|---|---|---|"]
        out += [f"| {r['metric']} | {r['value']} | {r['previous_period']} | {r['change_pct']} |" for r in totals]
        out += ["", f"**Index:** {index['verdict']}, {index['coverage']}. Last crawl {index['last_crawl']}."]
        if index["google_canonical"] and index["your_canonical"] and index["google_canonical"] != index["your_canonical"]:
            out.append(f"Google chose a different canonical: {index['google_canonical']}")
        if queries:
            out += ["", "| Top query | Clicks | Impressions | CTR % | Position |", "|---|---|---|---|---|"]
            out += [f"| {q['query']} | {q['clicks']} | {q['impressions']} | {q['ctr']} | {q['position']} |"
                    for q in queries]
        return out

    def bing():
        prop = bing_api.site_url(site)
        url = page if page.startswith("http") else prop.rstrip("/") + path
        stats = [r for r in bing_api.pages(start, end, None, 5000, prop) if _path(r["page"]) == path]
        info = bing_api.url_info(prop, url)
        s = stats[0] if stats else {}
        crawled = f"crawled {info['last_crawled']}" if info["crawled"] else "not crawled yet"
        return ["## Bing", "", f"{s.get('clicks', 0)} clicks, {s.get('impressions', 0)} impressions, position "
                f"{s.get('position') or '-'}. {crawled.capitalize()}, HTTP {info['http_status'] or '-'}, "
                f"{info['inbound_links'] or 0} inbound links. {info['note']}".strip()]

    def umami():
        rows = [r for r in umami_api.pages(start, end, f"path=c.{path}", 50, site) if _path(r["path"]) == path]
        if not rows:
            return ["## Umami", "", "No visits in these dates."]
        r = rows[0]
        return ["## Umami", "", f"{r['visitors']} visitors, {r['pageviews']} pageviews, {r['entries']} entries, "
                f"exit rate {r['exit_rate']}%, {r['avg_visit_seconds'] or '-'} s per visit."]

    for source, part in (("Google", google), ("Bing", bing), ("Umami", umami)):
        lines += _try(skipped, source, part, default=[]) + [""]
    lines += [f"*{s['source']} skipped: {s['skipped']}*" for s in skipped]
    return "\n".join(lines)


# ── indexing ─────────────────────────────────────────────────────────────────

@seo.deploy(title="Index check", name="index_check", timeout=300,
            next=[Next(submit_urls, label="Submit to Bing", urls="url"),
                  Next(inspect_url, label="Inspect in Google", url="url")])
def index_check(site: str | None = None, urls: str | None = None, limit: int = 50, start_at: int = 0) -> list[dict]:
    """Whether Google has indexed each page and whether Bing has crawled it. Pages missing from either come first.

    Leave URLs empty to check the sitemap (Limit pages from Start at); otherwise one URL or path per line or comma.
    Google allows 2,000 inspections a day per site. A run stops after about 4 minutes and says where to continue.
    """
    token = search_console.token
    client = gsc_api.SearchConsole(token)
    prop = client.site(site)
    skipped: list[dict] = []
    bing_site = _try(skipped, "Bing", bing_api.site_url, site)
    root = bing_site or client.full_url(prop, "/")
    every = bing_api.url_list(urls, root)
    todo = every[start_at:start_at + limit]
    started, rows, finished = time.monotonic(), [], True
    for i, url in enumerate(todo, start=start_at):
        if time.monotonic() - started > TIME_BUDGET_SECONDS:
            finished = False
            rows += [{"url": u, "note": f"not checked: time limit, run again with Start at {i}"} for u in todo[i - start_at:]]
            break
        row = {"url": url}
        try:
            g = gsc_api.inspect_url(token, url, prop)
            row.update(google=g["verdict"], google_coverage=g["coverage"], google_last_crawl=g["last_crawl"])
        except gsc_api.SearchConsoleError as e:
            row.update(google=None, google_coverage=str(e)[:200])
        if bing_site:
            time.sleep(0.5)  # Bing throttles rapid URL checks
            b = bing_api.url_info(bing_site, url)
            row.update(bing_crawled=b["crawled"], bing_last_crawled=b["last_crawled"], bing_http=b["http_status"])
        rows.append(row)
    rows.sort(key=lambda r: (r.get("google") == "PASS" and r.get("bing_crawled") is not False, r["url"]))
    if finished and len(every) > start_at + limit:
        rows.append({"url": "", "note": f"{len(every) - start_at - limit} more pages: run again with Start at "
                                        f"{start_at + limit}"})
    if skipped:
        rows.append({"url": "", "note": "; ".join(f"{s['source']} skipped: {s['skipped']}" for s in skipped)})
    return rows
