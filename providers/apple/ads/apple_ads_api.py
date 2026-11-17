"""A small Apple Ads (Search Ads) API client: sign-in, paging, and the objects and reports the ads callables use.
No callables in here, so any folder (or recipe) can import it: `from providers.apple.ads.apple_ads_api import AppleAds`.

It signs in with an API user's private key (Apple's client-credentials flow), so it acts as that API user, not as
whoever runs the callable. Set these as project secrets in Callables, or in .env locally:

    APPLE_ADS_CLIENT_ID, APPLE_ADS_TEAM_ID, APPLE_ADS_KEY_ID   from Apple Ads > Account Settings > API
    APPLE_ADS_PRIVATE_KEY   the private key: the PEM's contents, the PEM base64-encoded, or (locally) a path to it
    APPLE_ADS_ORG_ID        optional: which account, when the API user can see more than one

API reference: https://developer.apple.com/documentation/apple_search_ads
"""
import base64
import os
import time
from datetime import date
from pathlib import Path

import jwt
import requests

API = "https://api.searchads.apple.com/api/v5"
TOKEN_URL = "https://appleid.apple.com/auth/oauth2/token"
PAGE = 1000  # Apple's largest page size

SECRETS = ["APPLE_ADS_CLIENT_ID", "APPLE_ADS_TEAM_ID", "APPLE_ADS_KEY_ID", "APPLE_ADS_PRIVATE_KEY", "APPLE_ADS_ORG_ID"]


def private_key() -> str:
    """APPLE_ADS_PRIVATE_KEY as PEM text, whether it holds the PEM, the PEM base64-encoded, or a path to the file."""
    value = os.environ.get("APPLE_ADS_PRIVATE_KEY", "").strip()
    if not value:
        raise RuntimeError("Set the APPLE_ADS_PRIVATE_KEY secret to your Apple Ads private key (the .pem's contents).")
    if value.startswith("-----BEGIN"):
        return value
    if len(value) < 400 and Path(value).expanduser().is_file():
        return Path(value).expanduser().read_text()
    try:
        decoded = base64.b64decode(value, validate=True).decode()
    except ValueError:
        decoded = ""
    if decoded.startswith("-----BEGIN"):
        return decoded
    raise RuntimeError("APPLE_ADS_PRIVATE_KEY isn't a private key: paste the whole .pem, from -----BEGIN to -----END.")


def _apple_error(resp: requests.Response) -> str:
    """Apple's own error messages from a failed response, else the start of the body."""
    try:
        errors = (resp.json().get("error") or {}).get("errors") or []
        messages = [f"{e['field'] + ': ' if e.get('field') else ''}{e.get('message')}" for e in errors]
        if messages:
            return "; ".join(messages)
    except (ValueError, AttributeError):
        pass
    return resp.text[:500]


class AppleAds:
    """One Apple Ads account (org): APPLE_ADS_ORG_ID if set, else the only account the API user can see."""

    def __init__(self):
        missing = [name for name in SECRETS[:3] if not os.environ.get(name)]
        if missing:
            raise RuntimeError(f"Set the Apple Ads API secrets first: {', '.join(missing)} (see providers/apple/ads/README.md).")
        self._token = self._sign_in()
        self.org_id = self._pick_org()

    # ── sign-in ──────────────────────────────────────────────────────────────

    def _sign_in(self) -> str:
        client_id, team_id = os.environ["APPLE_ADS_CLIENT_ID"], os.environ["APPLE_ADS_TEAM_ID"]
        now = int(time.time())
        assertion = jwt.encode(
            {"iss": team_id, "sub": client_id, "aud": "https://appleid.apple.com", "iat": now, "exp": now + 3600},
            private_key(), algorithm="ES256", headers={"kid": os.environ["APPLE_ADS_KEY_ID"]},
        )
        resp = requests.post(TOKEN_URL, timeout=30, data={
            "grant_type": "client_credentials", "client_id": client_id, "client_secret": assertion,
            "scope": "searchadsorg",
        })
        if not resp.ok:
            raise RuntimeError(f"Apple refused the sign-in ({resp.status_code}): {resp.text[:300]}. Check the client, "
                               "team and key ids, and that the private key matches the public key uploaded to Apple.")
        return resp.json()["access_token"]

    def _pick_org(self) -> int:
        if os.environ.get("APPLE_ADS_ORG_ID", "").strip():
            return int(os.environ["APPLE_ADS_ORG_ID"].split(",")[0])
        orgs = self.request("GET", "/acls", org=False).get("data", [])
        if not orgs:
            raise RuntimeError("This Apple Ads API user can't see any account. Invite it in Apple Ads > Account Settings.")
        if len(orgs) > 1:
            names = ", ".join(f"{o.get('orgName')} ({o['orgId']})" for o in orgs)
            raise RuntimeError(f"This API user can see several accounts: {names}. Set APPLE_ADS_ORG_ID to one of them.")
        return orgs[0]["orgId"]

    # ── HTTP ─────────────────────────────────────────────────────────────────

    def request(self, method: str, path: str, org: bool = True, **kwargs) -> dict:
        headers = {"Authorization": f"Bearer {self._token}"}
        if org:
            headers["X-AP-Context"] = f"orgId={self.org_id}"
        resp = requests.request(method, f"{API}{path}", headers=headers, timeout=60, **kwargs)
        if not resp.ok:
            raise RuntimeError(f"Apple Ads refused {method} {path} ({resp.status_code}): {_apple_error(resp)}")
        return resp.json() if resp.content else {}

    def get(self, path: str, **params) -> dict:
        return self.request("GET", path, params=params or None)

    def post(self, path: str, body) -> dict:
        return self.request("POST", path, json=body)

    def put(self, path: str, body) -> dict:
        return self.request("PUT", path, json=body)

    def paged(self, path: str) -> list[dict]:
        """Every item of a list endpoint, skipping deleted ones."""
        items, offset = [], 0
        while True:
            page = self.get(path, limit=PAGE, offset=offset).get("data", [])
            items += [item for item in page if not item.get("deleted")]
            if len(page) < PAGE:
                return items
            offset += PAGE

    # ── objects ──────────────────────────────────────────────────────────────

    def campaigns(self) -> list[dict]:
        return self.paged("/campaigns")

    def campaign(self, campaign_id: int) -> dict:
        return self.get(f"/campaigns/{campaign_id}")["data"]

    def ad_groups(self, campaign_id: int) -> list[dict]:
        return self.paged(f"/campaigns/{campaign_id}/adgroups")

    def ad_group(self, campaign_id: int, ad_group_id: int) -> dict:
        return self.get(f"/campaigns/{campaign_id}/adgroups/{ad_group_id}")["data"]

    def app_id(self, campaigns: list[dict] | None = None) -> int:
        """The App Store id (adamId) the campaigns advertise. Raises if they advertise several apps."""
        apps = {c["adamId"] for c in (campaigns if campaigns is not None else self.campaigns()) if c.get("adamId")}
        if not apps:
            raise RuntimeError("No campaign says which app it advertises: create a campaign in Apple Ads first.")
        if len(apps) > 1:
            raise RuntimeError(f"These campaigns advertise several apps ({', '.join(map(str, sorted(apps)))}): "
                               "pick a campaign of the right app.")
        return apps.pop()

    def product_pages(self, adam_id: int) -> list[dict]:
        """The app's custom product pages, as Apple Ads sees them (id, name, state)."""
        return self.get(f"/apps/{adam_id}/product-pages").get("data", [])

    def product_page(self, adam_id: int, product_page_id: str) -> dict:
        page = next((p for p in self.product_pages(adam_id) if p.get("id") == product_page_id), None)
        if not page:
            raise ValueError(f"{product_page_id} isn't one of this app's custom product pages. Run Creatives or "
                             "App Store Connect's Custom product pages for the ids.")
        return page

    def ads(self, campaign_id: int, ad_group_id: int) -> list[dict]:
        return self.paged(f"/campaigns/{campaign_id}/adgroups/{ad_group_id}/ads")

    def creative(self, creative_id) -> dict:
        return self.get(f"/creatives/{creative_id}").get("data", {}) if creative_id else {}

    def page_creative(self, adam_id: int, product_page_id: str, name: str) -> dict:
        """The Apple Ads creative for a custom product page, created if the account doesn't have one yet."""
        found = next((c for c in self.paged("/creatives")
                      if c.get("productPageId") == product_page_id and c.get("adamId") == adam_id), None)
        return found or self.post("/creatives", {"adamId": adam_id, "name": name, "type": "CUSTOM_PRODUCT_PAGE",
                                                 "productPageId": product_page_id}).get("data", {})

    def download(self, uri: str) -> bytes:
        """A report file from Apple's download link (signed, or needing this sign-in)."""
        resp = requests.get(uri, timeout=120)
        if not resp.ok:
            resp = requests.get(uri, timeout=120, headers={"Authorization": f"Bearer {self._token}",
                                                          "X-AP-Context": f"orgId={self.org_id}"})
        resp.raise_for_status()
        return resp.content

    def keywords(self, campaign_id: int, ad_group_id: int) -> list[dict]:
        return self.paged(f"/campaigns/{campaign_id}/adgroups/{ad_group_id}/targetingkeywords")

    def keyword(self, campaign_id: int, ad_group_id: int, keyword_id: int) -> dict:
        return self.get(f"/campaigns/{campaign_id}/adgroups/{ad_group_id}/targetingkeywords/{keyword_id}")["data"]

    def negatives(self, campaign_id: int, ad_group_id: int | None = None) -> list[dict]:
        return self.paged(self.negatives_path(campaign_id, ad_group_id))

    @staticmethod
    def negatives_path(campaign_id: int, ad_group_id: int | None = None) -> str:
        if ad_group_id:
            return f"/campaigns/{campaign_id}/adgroups/{ad_group_id}/negativekeywords"
        return f"/campaigns/{campaign_id}/negativekeywords"

    # ── reports ──────────────────────────────────────────────────────────────

    def report(self, path: str, start: date, end: date, with_empty: bool = False,
               order_by: str = "localSpend") -> list[dict]:
        """Every row of a report (totals over start..end, all pages). with_empty includes rows with no impressions.

        Paths: /reports/campaigns, /reports/campaigns/{id}/adgroups, /reports/campaigns/{id}/keywords,
        /reports/campaigns/{id}/searchterms.
        """
        rows, offset = [], 0
        while True:
            body = {
                "startTime": start.isoformat(),
                "endTime": end.isoformat(),
                "returnRowTotals": True,
                "returnGrandTotals": False,
                "selector": {
                    "pagination": {"offset": offset, "limit": PAGE},
                    "orderBy": [{"field": order_by, "sortOrder": "DESCENDING"}],
                },
            }
            if with_empty:
                body["returnRecordsWithNoMetrics"] = True
            page = self.post(path, body).get("data", {}).get("reportingDataResponse", {}).get("row", [])
            rows += page
            if len(page) < PAGE:
                return rows
            offset += PAGE


# ── ads and their product pages (for recipes) ────────────────────────────────

def ads_with_pages(start: date, end: date, product_page_ids: list[str] | None = None,
                   api: "AppleAds | None" = None) -> list[dict]:
    """One row per ad in every campaign (paused ones too), with the product page it runs and its results over
    start..end, biggest spend first.

    Rows: campaign, campaign_status, ad_group, ad, ad_status, product_page (name), product_page_id ("" for the
    default product page), creative_type, spend, impressions, taps, installs, ttr, cvr, cpt, cpa, and campaign_id,
    ad_group_id, ad_id, creative_id, adam_id. product_page_ids keeps only ads running those custom pages.
    """
    from providers.apple.ads.metrics import stats

    api = api or AppleAds()
    campaigns = api.campaigns()
    wanted = {p.strip() for p in product_page_ids or [] if p.strip()}
    names: dict = {}
    for adam in {c["adamId"] for c in campaigns if c.get("adamId")}:
        try:
            names.update({p.get("id"): p.get("name") for p in api.product_pages(adam)})
        except RuntimeError:
            pass
    creatives: dict = {}
    rows = []
    for c in campaigns:
        try:
            report = {r["metadata"].get("adId"): r for r in api.report(f"/reports/campaigns/{c['id']}/ads", start, end)}
        except RuntimeError:
            report = {}
        for g in api.ad_groups(c["id"]):
            try:
                ads = api.ads(c["id"], g["id"])
            except RuntimeError:
                ads = []
            for ad in ads:
                cid = ad.get("creativeId")
                if cid not in creatives:
                    try:
                        creatives[cid] = api.creative(cid)
                    except RuntimeError:
                        creatives[cid] = {}
                cr = creatives[cid]
                row = report.get(ad.get("id")) or {}
                page_id = cr.get("productPageId") or row.get("metadata", {}).get("productPageId") or ""
                if wanted and page_id not in wanted:
                    continue
                rows.append({
                    "campaign": c["name"],
                    "campaign_status": c.get("status"),
                    "ad_group": g["name"],
                    "ad": ad.get("name"),
                    "ad_status": ad.get("status"),
                    "product_page": names.get(page_id) or cr.get("name") or ("Default product page" if not page_id
                                                                             else None),
                    "product_page_id": page_id,
                    "creative_type": cr.get("type") or ad.get("creativeType"),
                    **stats(row.get("total")),
                    "campaign_id": c["id"],
                    "ad_group_id": g["id"],
                    "ad_id": ad.get("id"),
                    "creative_id": cid,
                    "adam_id": c.get("adamId"),
                })
    return sorted(rows, key=lambda r: -r["spend"])
