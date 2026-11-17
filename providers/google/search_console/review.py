"""Google Search Console, live: each person signs in with their own Google account, and nothing is stored.

Page and Query filter by "contains": start with = for exact, ! to exclude, ~ for a regex.
Dates default to the last 28 days ending 2 days ago.
"""
from datetime import date
from typing import Literal

from callables import Connection, Group, Next, Secret

from providers.google.search_console import search_console_api as api

# Its own sign-in with only the read-only Search Console scope, on the same Google OAuth app as Gmail.
search_console = Connection(
    "search_console",
    provider="google",
    title="Google Search Console",
    scopes=["webmasters.readonly"],
    client_id=Secret("GOOGLE_CLIENT_ID"),
    client_secret=Secret("GOOGLE_CLIENT_SECRET"),
)

gsc = Group(
    "search_console",
    title="Google Search Console",
    description="Google Search Console, live: the queries and pages your site ranks for, clicks, CTR and position, "
                "what changed, quick wins, and whether a page is indexed.",
    connections=[search_console],
)

Device = Literal["All", "Desktop", "Mobile", "Tablet"]
SearchType = Literal["Web", "Image", "Video", "News", "Google News", "Discover"]


@gsc.deploy(title="Inspect URL")
def inspect_url(url: str, site_url: str | None = None) -> dict:
    """Whether Google has indexed a page and why not: coverage, robots.txt, Google's canonical vs yours, last crawl,
    rich results.

    URL can be a full URL or a path like /blog/post/.
    """
    return api.inspect_url(search_console.token, url, site_url)


@gsc.deploy(title="Query pages")
def query_pages(query: str | None = None, page: str | None = None, start: date | None = None,
                end: date | None = None, device: Device = "All", limit: int = 1000,
                site_url: str | None = None) -> list[dict]:
    """Which page ranks for which query. Several pages on one query split its clicks."""
    return api.report(search_console.token, ["query", "page"], start, end, page, query, None, device, "Web", limit,
                      site_url)


@gsc.deploy(title="Queries", next=[Next(query_pages, label="Pages for this query", query="query")])
def queries(page: str | None = None, query: str | None = None, start: date | None = None, end: date | None = None,
            country: str | None = None, device: Device = "All", search_type: SearchType = "Web",
            limit: int = 1000, site_url: str | None = None) -> list[dict]:
    """What people searched on Google before seeing the site: clicks, impressions, CTR and average position.

    Country is a 3-letter code (USA, GBR).
    """
    return api.report(search_console.token, ["query"], start, end, page, query, country, device, search_type, limit,
                      site_url)


@gsc.deploy(title="Pages", next=[Next(queries, label="Queries for this page", page="page"),
                                 Next(inspect_url, label="Inspect", url="page")])
def pages(page: str | None = None, query: str | None = None, start: date | None = None, end: date | None = None,
          country: str | None = None, device: Device = "All", search_type: SearchType = "Web",
          limit: int = 1000, site_url: str | None = None) -> list[dict]:
    """Each page's Google clicks, impressions, CTR and average position."""
    return api.report(search_console.token, ["page"], start, end, page, query, country, device, search_type, limit,
                      site_url)


@gsc.deploy(title="Search trend", name="trend")
def trend(page: str | None = None, query: str | None = None, start: date | None = None, end: date | None = None,
          device: Device = "All", site_url: str | None = None) -> list[dict]:
    """Clicks, impressions, CTR and position per day, for the site or a page or query."""
    return api.report(search_console.token, ["date"], start, end, page, query, None, device, "Web", 1000, site_url)


@gsc.deploy(title="Search totals", name="totals")
def totals(page: str | None = None, query: str | None = None, start: date | None = None, end: date | None = None,
           site_url: str | None = None) -> list[dict]:
    """Clicks, impressions, CTR and position against the period just before."""
    return api.totals(search_console.token, start, end, page, query, site_url)


@gsc.deploy(title="What changed", name="changes", next=[Next(queries, label="Queries for this page", page="page")])
def changes(dimension: Literal["page", "query"] = "page", page: str | None = None, query: str | None = None,
            start: date | None = None, end: date | None = None, min_impressions: int = 20, limit: int = 200,
            site_url: str | None = None) -> list[dict]:
    """Pages or queries now against the period just before, biggest change in clicks first."""
    return api.changes(search_console.token, dimension, start, end, page, query, min_impressions, limit, site_url)


@gsc.deploy(title="Opportunities", next=[Next(query_pages, label="Pages for this query", query="query"),
                                         Next(inspect_url, label="Inspect", url="page")])
def opportunities(min_impressions: int = 50, page: str | None = None, start: date | None = None,
                  end: date | None = None, limit: int = 200, site_url: str | None = None) -> list[dict]:
    """Query + page pairs worth improving, most extra clicks first.

    Striking distance: ranking 5 to 20, so better content or internal links could reach the top 3. Low CTR: on
    page one but clicked under half as often as usual, so rewrite the title and meta description.
    """
    return api.opportunities(search_console.token, start, end, min_impressions, page, limit, site_url)


@gsc.deploy(title="Sitemaps")
def sitemaps(site_url: str | None = None) -> list[dict]:
    """Submitted sitemaps: when Google last read them, errors, warnings and URLs submitted."""
    return api.sitemaps(search_console.token, site_url)


@gsc.deploy(title="Properties")
def properties() -> list[dict]:
    """The Search Console properties your Google account can see. Pass one as Site url to the other actions."""
    return api.sites(search_console.token)
