"""A small RevenueCat REST API v2 client: paging, rate limits, metrics, charts, customers and entitlements.
No callables in here, so any folder (or recipe) can import it: `from revenuecat.revenuecat_api import RevenueCat`.

Set these as project secrets in Callables, or in .env locally:

    REVENUECAT_API_KEY      a v2 secret API key (Project settings > API keys > + New secret API key, version V2)
    REVENUECAT_PROJECT_ID   the project's id, e.g. proj1ab2c3d4 (in the dashboard URL)

API reference: https://www.revenuecat.com/docs/api-v2
"""
import json
import os
import time
from datetime import date, datetime, timezone

import requests

API = "https://api.revenuecat.com/v2"
SECRETS = ["REVENUECAT_API_KEY", "REVENUECAT_PROJECT_ID"]
RESOLUTIONS = {"day": "0", "week": "1", "month": "2", "quarter": "3", "year": "4"}
RETRIES = 4


def day(timestamp: int | float | None) -> str | None:
    """A RevenueCat timestamp as YYYY-MM-DD (UTC). Objects use milliseconds; chart periods use seconds."""
    if not timestamp:
        return None
    seconds = timestamp / 1000 if timestamp > 10**11 else timestamp
    return datetime.fromtimestamp(seconds, timezone.utc).date().isoformat()


class RevenueCat:
    """One RevenueCat project."""

    def __init__(self):
        missing = [name for name in SECRETS if not os.environ.get(name)]
        if missing:
            raise RuntimeError(f"Set the RevenueCat secrets first: {', '.join(missing)} (see revenuecat/README.md).")
        self.project = os.environ["REVENUECAT_PROJECT_ID"].strip()
        self._headers = {"Authorization": f"Bearer {os.environ['REVENUECAT_API_KEY'].strip()}"}

    # ── HTTP ─────────────────────────────────────────────────────────────────

    def request(self, method: str, path: str, **kwargs) -> dict:
        """path is under the project (/customers/...), or a full /v2/... path from a next_page link."""
        url = f"https://api.revenuecat.com{path}" if path.startswith("/v2/") else f"{API}/projects/{self.project}{path}"
        for attempt in range(RETRIES + 1):
            resp = requests.request(method, url, headers=self._headers, timeout=60, **kwargs)
            # Charts allow 25 requests a minute, customers 480: wait as long as RevenueCat says, then retry
            if resp.status_code in (429, 423, 503) and attempt < RETRIES:
                time.sleep(min(float(resp.headers.get("Retry-After") or 2 ** attempt), 60))
                continue
            if not resp.ok:
                try:
                    message = resp.json().get("message") or resp.text[:300]
                except ValueError:
                    message = resp.text[:300]
                raise RuntimeError(f"RevenueCat refused {method} {path} ({resp.status_code}): {message}")
            return resp.json() if resp.content else {}
        raise AssertionError("unreachable")

    def get(self, path: str, **params) -> dict:
        return self.request("GET", path, params={k: v for k, v in params.items() if v is not None} or None)

    def post(self, path: str, body: dict) -> dict:
        return self.request("POST", path, json=body)

    def paged(self, path: str, limit: int | None = None, **params) -> list[dict]:
        """Every item of a list endpoint (or the first `limit`), following next_page."""
        items, page = [], self.get(path, limit=100, **params)
        while True:
            items += page.get("items", [])
            if not page.get("next_page") or (limit and len(items) >= limit):
                return items[:limit] if limit else items
            page = self.request("GET", page["next_page"])

    # ── metrics and charts ───────────────────────────────────────────────────

    def overview(self, currency: str = "USD") -> list[dict]:
        """Active trials and subscriptions, MRR, revenue and new customers (last 28 days), as the dashboard shows."""
        return self.get("/metrics/overview", currency=currency)["metrics"]

    def revenue(self, start: date, end: date, revenue_type: str = "revenue", currency: str = "USD") -> dict:
        return self.get("/metrics/revenue", start_date=start.isoformat(), end_date=end.isoformat(),
                        revenue_type=revenue_type, currency=currency)

    def chart(self, name: str, start: date, end: date, resolution: str = "week", segment: str | None = None,
              filters: dict[str, list[str]] | None = None, selectors: dict[str, str] | None = None,
              currency: str = "USD", top_segments: int | None = None) -> dict:
        """A dashboard chart's raw data. Charts: revenue, mrr, arr, actives, trials, conversion_to_paying, churn,
        refund_rate, customers_new, ltv_per_customer and more; chart_options(name) lists its segments and filters."""
        return self.get(
            f"/charts/{name}",
            start_date=start.isoformat(), end_date=end.isoformat(), resolution=RESOLUTIONS[resolution],
            segment=segment, limit_num_segments=top_segments if segment else None, currency=currency,
            filters=json.dumps([{"name": k, "values": v} for k, v in filters.items()]) if filters else None,
            selectors=json.dumps(selectors) if selectors else None,
        )

    def chart_options(self, name: str) -> dict:
        return self.get(f"/charts/{name}/options")

    @staticmethod
    def chart_rows(data: dict) -> list[dict]:
        """A chart as rows: one per period (and segment), with a column per measure.

        Charts return points like {"cohort": <period start>, "measure": 0, "segment": 1, "value": 12.5}, where
        measure and segment index into the chart's measures and segments lists.
        """
        measures = [m["display_name"] for m in data.get("measures") or []] or ["value"]
        segments = [s["display_name"] for s in data.get("segments") or []]
        rows: dict[tuple, dict] = {}
        for point in data.get("values") or []:
            if not isinstance(point, dict):
                continue
            segment = point.get("segment")
            key = (point.get("cohort"), segment)
            row = rows.setdefault(key, {"period": day(point.get("cohort")),
                                        **({"segment": segments[segment]} if segment is not None and segments else {})})
            measure = point.get("measure") or 0
            row[measures[measure] if measure < len(measures) else f"measure {measure}"] = point.get("value")
            row["_incomplete"] = row.get("_incomplete", False) or bool(point.get("incomplete"))
        return [{**{k: v for k, v in row.items() if k != "_incomplete"}, "incomplete": row["_incomplete"]}
                for row in rows.values()]

    # ── customers and entitlements ───────────────────────────────────────────

    def customers(self, search: str | None = None, limit: int = 100) -> list[dict]:
        """Customers matching an email (exact), app user id or store transaction id; or the first `limit`."""
        return self.paged("/customers", limit=limit, search=search)

    def customer(self, customer_id: str) -> dict:
        return self.get(f"/customers/{customer_id}", expand="attributes")

    def subscriptions(self, customer_id: str) -> list[dict]:
        return self.paged(f"/customers/{customer_id}/subscriptions")

    def purchases(self, customer_id: str) -> list[dict]:
        return self.paged(f"/customers/{customer_id}/purchases")

    def active_entitlements(self, customer_id: str) -> list[dict]:
        return self.paged(f"/customers/{customer_id}/active_entitlements")

    def entitlements(self) -> list[dict]:
        return self.paged("/entitlements")

    def entitlement(self, id_or_lookup_key: str) -> dict:
        """An entitlement by its id (entl...) or lookup key (e.g. "pro")."""
        found = [e for e in self.entitlements() if id_or_lookup_key in (e["id"], e.get("lookup_key"))]
        if not found:
            names = ", ".join(f"{e.get('lookup_key')} ({e['id']})" for e in self.entitlements())
            raise ValueError(f"No entitlement is called {id_or_lookup_key!r}. Entitlements: {names}")
        return found[0]

    def grant(self, customer_id: str, entitlement_id: str, expires_at: datetime) -> dict:
        return self.post(f"/customers/{customer_id}/actions/grant_entitlement",
                         {"entitlement_id": entitlement_id, "expires_at": int(expires_at.timestamp() * 1000)})

    def revoke(self, customer_id: str, entitlement_id: str) -> dict:
        return self.post(f"/customers/{customer_id}/actions/revoke_granted_entitlement", {"entitlement_id": entitlement_id})
