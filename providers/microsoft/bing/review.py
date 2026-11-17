"""Bing Webmaster Tools, live: every run calls Bing and stores nothing. Submitting URLs previews first."""
from datetime import date

from callables import Group, Next

from providers.microsoft.bing import bing_api as api

bing = Group(
    "bing",
    title="Bing Webmaster",
    description="Bing Webmaster Tools, live: queries, pages, daily traffic, crawl issues and URL submission for "
                "Bing search (and DuckDuckGo, Yahoo and ChatGPT search, which use it).",
    secrets=api.SECRETS,
)


@bing.deploy(title="Submit URLs to Bing", name="submit_urls")
def submit_urls(urls: str | None = None, only_uncrawled: bool = True, dry_run: bool = True,
                site_url: str | None = None) -> list[dict]:
    """Ask Bing to crawl pages now, up to the site's daily submission quota.

    Leave URLs empty to use the sitemap; Only uncrawled skips pages Bing has already crawled. Untick Dry run to
    submit.
    """
    return api.submit_urls(urls, only_uncrawled, dry_run, site_url)


@bing.deploy(title="Bing queries", name="queries")
def queries(start: date | None = None, end: date | None = None, contains: str | None = None, limit: int = 500,
            site_url: str | None = None) -> list[dict]:
    """Bing searches that showed the site: clicks, impressions, CTR and position, summed over the weeks in the dates
    (last 28 days by default; Bing updates these weekly).
    """
    return api.queries(start, end, contains, limit, site_url)


@bing.deploy(title="Bing pages", name="pages")
def pages(start: date | None = None, end: date | None = None, contains: str | None = None, limit: int = 500,
          site_url: str | None = None) -> list[dict]:
    """Each page's Bing clicks, impressions, CTR and position (last 28 days by default; updated weekly)."""
    return api.pages(start, end, contains, limit, site_url)


@bing.deploy(title="Bing traffic", name="traffic")
def traffic(start: date | None = None, end: date | None = None, site_url: str | None = None) -> list[dict]:
    """Bing clicks and impressions per day (last 90 days by default)."""
    return api.traffic(start, end, site_url)


@bing.deploy(title="Bing crawl", name="crawl")
def crawl(site_url: str | None = None) -> list[dict]:
    """Bing's crawl per day over 6 months: pages crawled, in index, errors by HTTP code, blocked by robots.txt."""
    return api.crawl(site_url)


@bing.deploy(title="Bing crawl issues", name="crawl_issues",
             next=[Next(submit_urls, label="Resubmit", urls="url")])
def crawl_issues(site_url: str | None = None) -> list[dict]:
    """URLs Bing had trouble with, with the HTTP code and inbound links."""
    return api.crawl_issues(site_url)


@bing.deploy(title="Bing URL status", name="url_status",
             next=[Next(submit_urls, label="Submit to Bing", urls="url")])
def url_status(urls: str | None = None, site_url: str | None = None, start_at: int = 0) -> list[dict]:
    """Whether Bing has crawled each URL, when, and the HTTP status it got. Never-crawled pages first.

    Leave URLs empty to check every page in the sitemap; otherwise one URL or path per line or comma. A run stops
    after about 4 minutes; the rest come back with the Start at to continue from.
    """
    return api.url_status(urls, site_url, start_at)


@bing.deploy(title="Bing submission quota", name="quota")
def quota(site_url: str | None = None) -> dict:
    """How many URLs the site can still submit to Bing today and this month."""
    return api.quota(site_url)
