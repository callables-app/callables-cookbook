"""Umami website analytics, live: every run calls Umami and stores nothing.

Filters: "name=value; name2=value" with path, referrer, title, query, country (US), device, browser, os, event,
utmSource, utmMedium, utmCampaign... A value matches exactly unless it starts with c. (contains), neq. (not equal)
or re. (regex). Dates default to the last 30 days ending yesterday (UTC).
"""
from datetime import date
from typing import Literal

from callables import Group, Next

from providers.umami import umami_api as api

umami = Group(
    "umami",
    title="Umami",
    description="Website analytics from Umami, live: visitors, pages, referrers, countries, devices and custom "
                "events, for finding what to improve.",
    secrets=api.SECRETS,
)

Dimension = Literal["Page", "Entry page", "Exit page", "Page title", "Query string", "Referrer", "Channel",
                    "Country", "Region", "City", "Device", "Browser", "OS", "Language", "Screen", "Event",
                    "UTM source", "UTM medium", "UTM campaign", "UTM content", "UTM term", "Hostname"]


@umami.deploy(title="Overview")
def overview(start: date | None = None, end: date | None = None, filters: str | None = None,
             website: str | None = None) -> list[dict]:
    """Website totals against the period just before, plus visitors on the site right now.

    Filters narrow it, like "path=c./blog" or "country=US".
    """
    return api.overview(start, end, filters, website)


@umami.deploy(title="Traffic trend")
def traffic(start: date | None = None, end: date | None = None,
            unit: Literal["hour", "day", "week", "month"] = "day", filters: str | None = None,
            website: str | None = None) -> list[dict]:
    """Pageviews and visitors per day (or hour, week, month)."""
    return api.trend(start, end, unit, filters, website)


@umami.deploy(title="Pages")
def pages(start: date | None = None, end: date | None = None, filters: str | None = None, limit: int = 100,
          website: str | None = None) -> list[dict]:
    """Each page: visitors, pageviews, entries, exits, exit rate and time per visit.

    Pages with many entries and a high exit rate are where visitors land and leave.
    """
    return api.pages(start, end, filters, limit, website)


@umami.deploy(title="Breakdown")
def breakdown(dimension: Dimension = "Referrer", start: date | None = None, end: date | None = None,
              filters: str | None = None, limit: int = 100, website: str | None = None) -> list[dict]:
    """Visitors, visits and bounce rate by referrer, channel, country, device, page or UTM campaign."""
    return api.breakdown(dimension, start, end, filters, limit, website)


@umami.deploy(title="Event values")
def event_values(event: str, property: str, start: date | None = None, end: date | None = None,
                 filters: str | None = None, website: str | None = None) -> list[dict]:
    """How often each value of an event's property occurs, such as which button a signup-click came from."""
    return api.event_values(event, property, start, end, filters, website)


@umami.deploy(title="Events", next=[Next(event_values, label="Property values", event="event")])
def events(start: date | None = None, end: date | None = None, filters: str | None = None, limit: int = 100,
           website: str | None = None) -> list[dict]:
    """Custom events (data-umami-event clicks and umami.track calls): count, visitors and each property's split."""
    return api.events(start, end, filters, limit, website)


@umami.deploy(title="Websites")
def websites() -> list[dict]:
    """The Umami websites this account can see, with their ids."""
    return api.websites()
