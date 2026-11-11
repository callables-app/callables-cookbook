"""RevenueCat review: the overview, any dashboard chart, revenue for a date range, and customer lookups.

Each callable returns flat rows, so they read well as tables in the web app and as data for an assistant to analyze.
Customer rows keep their ids, and the row buttons hand them to the changes in changes.py.
"""
from datetime import date, timedelta
from typing import Literal

from callables import Next

from revenuecat.changes import grant_entitlement, revoke_entitlement
from revenuecat.group import revenuecat
from revenuecat.revenuecat_api import RevenueCat, day

Chart = Literal[
    "revenue", "mrr", "arr", "mrr_movement", "actives", "actives_new", "actives_movement", "trials", "trials_new",
    "trials_movement", "trial_conversion_rate", "conversion_to_paying", "initial_conversion", "churn", "refund_rate",
    "customers_new", "customers_active", "subscription_status", "ltv_per_customer", "ltv_per_paying_customer",
]
Resolution = Literal["day", "week", "month", "quarter", "year"]


def _window(start: date | None, end: date | None, days: int) -> tuple[date, date]:
    end = end or date.today()
    start = start or end - timedelta(days=days - 1)
    if start > end:
        raise ValueError(f"Start ({start}) is after End ({end}).")
    return start, end


def _filters(text: str | None) -> dict[str, list[str]] | None:
    """"store=app_store; first_country=US,GB" -> {"store": ["app_store"], "first_country": ["US", "GB"]}."""
    if not text or not text.strip():
        return None
    out = {}
    for part in text.split(";"):
        if part.strip():
            name, sep, values = part.partition("=")
            if not sep:
                raise ValueError(f"Write filters as name=value, like store=app_store; first_country=US,GB (got {part!r}).")
            out[name.strip()] = [v.strip() for v in values.split(",") if v.strip()]
    return out


@revenuecat.deploy(title="Overview")
def overview() -> list[dict]:
    """The numbers on RevenueCat's overview: active trials and subscriptions, MRR, and revenue, new customers and
    active users over the last 28 days."""
    return [{"metric": m["name"], "value": m["value"], "unit": m["unit"],
             "period": "now" if m.get("period") == "P0D" else "last 28 days", "description": m.get("description"),
             "id": m["id"]} for m in RevenueCat().overview()]


@revenuecat.deploy(title="Revenue")
def revenue(start: date | None = None, end: date | None = None,
            revenue_type: Literal["revenue", "revenue_net_of_taxes", "proceeds"] = "revenue") -> dict:
    """Total revenue between two dates (inclusive), in USD. Proceeds is after store fees and taxes.
    Dates default to the last 30 days, including today."""
    start, end = _window(start, end, 30)
    out = RevenueCat().revenue(start, end, revenue_type)
    return {"revenue": out["value"], "currency": out["currency"], "type": revenue_type, "start": str(start), "end": str(end)}


@revenuecat.deploy(title="Chart")
def chart(chart: Chart = "revenue", start: date | None = None, end: date | None = None,
          resolution: Resolution = "week", segment: str | None = None, filters: str | None = None,
          top_segments: int = 10) -> list[dict]:
    """Any chart from the RevenueCat dashboard as a table: one row per period, a column per measure.

    Segment splits it, e.g. by store, product_id, first_country or attribution_keyword (Chart options lists each
    chart's segments and filters). Filters narrow it, e.g. store=app_store; first_country=US,GB. Dates default to
    the last 90 days. The last period is marked incomplete while it's still running.
    """
    start, end = _window(start, end, 90)
    api = RevenueCat()
    data = api.chart(chart, start, end, resolution, segment or None, _filters(filters), top_segments=top_segments)
    rows = api.chart_rows(data)
    if not rows:
        raise ValueError(f"The {chart} chart has no data between {start} and {end}.")
    return rows


@revenuecat.deploy(title="Chart options", next=[Next(chart, label="Open chart")])
def chart_options(chart: Chart = "revenue") -> list[dict]:
    """The segments and filters a chart accepts, with each filter's values. Use the ids in Chart."""
    options = RevenueCat().chart_options(chart)
    rows = [{"chart": chart, "kind": "segment", "id": s["id"], "name": s["display_name"], "values": None}
            for s in options.get("segments") or []]
    rows += [{"chart": chart, "kind": "filter", "id": f["id"], "name": f["display_name"],
              "values": ", ".join(o["id"] for o in f.get("options") or [])[:500] or None}
             for f in options.get("filters") or []]
    return rows


def _customer_row(c: dict) -> dict:
    return {
        "customer_id": c["id"],
        "first_seen": day(c.get("first_seen_at")),
        "last_seen": day(c.get("last_seen_at")),
        "country": c.get("last_seen_country"),
        "platform": c.get("last_seen_platform"),
        "app_version": c.get("last_seen_app_version"),
    }


@revenuecat.deploy(title="Customer", next=[
    Next(grant_entitlement, label="Grant access", entitlement="entitlement_id"),
    Next(revoke_entitlement, label="Revoke promotional access", entitlement="entitlement_id"),
])
def customer(customer_id: str) -> list[dict]:
    """Everything about one customer: their active entitlements, each subscription (status, store, product,
    renewal, revenue) and one-off purchases. Customer id is their app user id, as in RevenueCat."""
    api = RevenueCat()
    c = api.customer(customer_id)
    rows = [{"kind": "entitlement", "customer_id": customer_id, "entitlement_id": e["entitlement_id"],
             "status": "active", "ends": day(e.get("expires_at")) or "no end date"}
            for e in api.active_entitlements(customer_id)]
    for s in api.subscriptions(customer_id):
        rows.append({
            "kind": "subscription",
            "customer_id": customer_id,
            "product": s.get("product_id"),
            "status": s.get("status"),
            "gives_access": s.get("gives_access"),
            "store": s.get("store"),
            "environment": s.get("environment"),
            "started": day(s.get("starts_at")),
            "ends": day(s.get("current_period_ends_at")),
            "auto_renew": s.get("auto_renewal_status"),
            "revenue_usd": (s.get("total_revenue_in_usd") or {}).get("gross"),
            "country": s.get("country"),
        })
    for p in api.purchases(customer_id):
        rows.append({
            "kind": "purchase",
            "customer_id": customer_id,
            "product": p.get("product_id"),
            "status": p.get("status"),
            "store": p.get("store"),
            "environment": p.get("environment"),
            "started": day(p.get("purchased_at")),
            "revenue_usd": (p.get("revenue_in_usd") or {}).get("gross"),
            "country": p.get("country"),
        })
    attributes = {a["name"]: a["value"] for a in (c.get("attributes") or {}).get("items", [])}
    if attributes.get("$email"):
        rows.insert(0, {"kind": "email", "customer_id": customer_id, "status": attributes["$email"]})
    return rows or [{"kind": "customer", **_customer_row(c), "status": "no entitlements, subscriptions or purchases"}]


@revenuecat.deploy(title="Find customers", next=[customer])
def find_customers(search: str) -> list[dict]:
    """Find customers by email (exact), app user id, or an App Store, Play Store or Amazon transaction id or Apple
    order id. Each row opens the customer."""
    rows = [_customer_row(c) for c in RevenueCat().customers(search.strip(), limit=50)]
    if not rows:
        raise ValueError(f"No customer matches {search!r}. Email has to match exactly.")
    return rows


@revenuecat.deploy(title="Entitlements")
def entitlements() -> list[dict]:
    """The project's entitlements (what a purchase unlocks), with their ids and lookup keys."""
    return [{"lookup_key": e.get("lookup_key"), "name": e.get("display_name"), "state": e.get("state"),
             "created": day(e.get("created_at")), "entitlement_id": e["id"]} for e in RevenueCat().entitlements()]
