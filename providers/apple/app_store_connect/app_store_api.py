"""A small App Store Connect API client: an ES256 JWT per run, JSON:API requests, paging, and the daily sales
report. No callables in here, so any folder (or recipe) can import it:
`from providers.apple.app_store_connect.app_store_api import AppStoreConnect`.

Secrets:
- ASC_ISSUER_ID, ASC_KEY_ID and ASC_PRIVATE_KEY (the .p8 file's contents) or ASC_PRIVATE_KEY_B64 (base64 of it):
  a team API key from Users and Access > Integrations. App Manager is enough for listings and product pages.
- ASC_APP_ID (optional): the app's Apple ID. Without it, the only app the key can see is used.
- Sales reports need a key with the Sales (or Finance) role. If the main key is App Manager, add a second one as
  ASC_SALES_KEY_ID + ASC_SALES_PRIVATE_KEY_B64, and set ASC_VENDOR_NUMBER (Payments and Financial Reports).
"""
import base64
import csv
import gzip
import io
import os
import time
from datetime import date

import jwt
import requests

BASE_URL = "https://api.appstoreconnect.apple.com"
SECRETS = ["ASC_ISSUER_ID", "ASC_KEY_ID", "ASC_PRIVATE_KEY", "ASC_PRIVATE_KEY_B64", "ASC_APP_ID"]
SALES_SECRETS = ["ASC_VENDOR_NUMBER", "ASC_SALES_KEY_ID", "ASC_SALES_PRIVATE_KEY_B64"]

# Sales report product types: first-time downloads and redownloads (the rest are updates and in-app purchases)
NEW_DOWNLOAD_TYPES = ("1", "1F", "1T")
REDOWNLOAD_TYPES = ("3", "3F", "3T")


class AppStoreConnectError(RuntimeError):
    pass


def _key(raw_name: str, b64_name: str) -> str | None:
    if os.environ.get(raw_name):
        return os.environ[raw_name].replace("\\n", "\n")
    if os.environ.get(b64_name):
        return base64.b64decode(os.environ[b64_name]).decode()
    return None


def _error(resp: requests.Response) -> str:
    try:
        errors = resp.json().get("errors", [])
        return "; ".join(f"{e.get('title')}: {e.get('detail')}" for e in errors) or resp.text[:500]
    except ValueError:
        return resp.text[:500]


class AppStoreConnect:
    def __init__(self, sales: bool = False):
        """sales=True signs with the sales key (ASC_SALES_KEY_ID / ASC_SALES_PRIVATE_KEY_B64) when it's set, because
        App Manager keys can't read sales reports."""
        for name in ("ASC_ISSUER_ID", "ASC_KEY_ID"):
            if not os.environ.get(name):
                raise AppStoreConnectError(f"{name} isn't set: add it to the project's secrets.")
        key_id, key = os.environ["ASC_KEY_ID"], None
        if sales and os.environ.get("ASC_SALES_KEY_ID"):
            key_id, key = os.environ["ASC_SALES_KEY_ID"], _key("ASC_SALES_PRIVATE_KEY", "ASC_SALES_PRIVATE_KEY_B64")
        key = key or _key("ASC_PRIVATE_KEY", "ASC_PRIVATE_KEY_B64")
        if not key:
            raise AppStoreConnectError("No App Store Connect key: set ASC_PRIVATE_KEY (the .p8 file's contents) or "
                                       "ASC_PRIVATE_KEY_B64 in the project's secrets.")
        now = int(time.time())
        self.token = jwt.encode(
            {"iss": os.environ["ASC_ISSUER_ID"], "iat": now, "exp": now + 19 * 60, "aud": "appstoreconnect-v1"},
            key, algorithm="ES256", headers={"kid": key_id, "typ": "JWT"},
        )
        self._app_id = os.environ.get("ASC_APP_ID") or None

    # ── requests ─────────────────────────────────────────────────────────────

    def request(self, method: str, path: str, **kwargs) -> dict:
        url = path if path.startswith("http") else f"{BASE_URL}{path}"
        for attempt in range(4):
            resp = requests.request(method, url, headers={"Authorization": f"Bearer {self.token}"}, timeout=60,
                                    **kwargs)
            if resp.status_code in (429, 500, 503) and attempt < 3:
                time.sleep(float(resp.headers.get("Retry-After") or 2 ** attempt))
                continue
            if not resp.ok:
                raise AppStoreConnectError(f"App Store Connect rejected {method} {path.split('?')[0]} "
                                           f"({resp.status_code}): {_error(resp)}")
            return resp.json() if resp.content else {}

    def get(self, path: str, **params) -> dict:
        return self.request("GET", path, params=params or None)

    def all(self, path: str, **params) -> list[dict]:
        """Every item of a paged list."""
        params.setdefault("limit", 200)
        out, data = [], self.get(path, **params)
        while True:
            out.extend(data.get("data", []))
            nxt = (data.get("links") or {}).get("next")
            if not nxt:
                return out
            data = self.request("GET", nxt)

    def post(self, path: str, body: dict) -> dict:
        return self.request("POST", path, json=body)

    def patch(self, path: str, body: dict) -> dict:
        return self.request("PATCH", path, json=body)

    def delete(self, path: str) -> dict:
        return self.request("DELETE", path)

    # ── the app ──────────────────────────────────────────────────────────────

    @property
    def app_id(self) -> str:
        """ASC_APP_ID, else the only app this key can see."""
        if not self._app_id:
            apps = self.all("/v1/apps", **{"fields[apps]": "name,bundleId"})
            if len(apps) != 1:
                listed = ", ".join(f"{a['attributes'].get('name')} ({a['id']})" for a in apps) or "none"
                raise AppStoreConnectError(f"Set ASC_APP_ID to the app's Apple ID. This key sees: {listed}")
            self._app_id = apps[0]["id"]
        return self._app_id

    # ── custom product pages ─────────────────────────────────────────────────
    # page → versions (one live, maybe one draft) → localizations (locale + promotional text) → screenshot and
    # app preview (video) sets per device size. A new or changed version needs App Review before ads can use it.

    def page_versions(self, page_id: str) -> list[dict]:
        return self.all(f"/v1/appCustomProductPages/{page_id}/appCustomProductPageVersions")

    def latest_page_version(self, page_id: str) -> dict | None:
        """The draft version if there is one (edits go there), else the live one."""
        versions = self.page_versions(page_id)
        drafts = [v for v in versions
                  if v["attributes"].get("state") not in ("ACCEPTED", "APPROVED", "REPLACED_WITH_NEW_VERSION")]
        return (drafts or versions or [None])[0]

    def page_localizations(self, version_id: str) -> list[dict]:
        return self.all(f"/v1/appCustomProductPageVersions/{version_id}/appCustomProductPageLocalizations")

    def page_localization(self, page_id: str, locale: str, editable: bool = False) -> tuple[dict, dict]:
        """The page's latest version and its localization for `locale`. editable=True refuses a version that's live
        or in review."""
        version = self.latest_page_version(page_id)
        if not version:
            raise AppStoreConnectError("That product page has no versions.")
        state = version["attributes"].get("state")
        if editable and state in ("ACCEPTED", "APPROVED", "WAITING_FOR_REVIEW", "IN_REVIEW"):
            raise AppStoreConnectError(f"The page's latest version is {state} and can't be edited. Copy the page "
                                       "first (Copy product page).")
        loc = next((l for l in self.page_localizations(version["id"]) if l["attributes"].get("locale") == locale),
                   None)
        if not loc:
            raise AppStoreConnectError(f"The page's latest version has no {locale} localization.")
        return version, loc

    def upload(self, operations: list[dict], data: bytes, what: str) -> None:
        """Send a file's parts to the upload URLs Apple handed out for it."""
        for op in operations or []:
            part = data[op["offset"]:op["offset"] + op["length"]]
            resp = requests.request(op["method"], op["url"], data=part, timeout=300,
                                    headers={h["name"]: h["value"] for h in op.get("requestHeaders") or []})
            if not resp.ok:
                raise AppStoreConnectError(f"Upload of {what} failed ({resp.status_code}).")

    def submit(self, item: dict) -> str:
        """Submit one item (a product page version or app version relationship) for App Review; returns the
        submission id."""
        sub = self.post("/v1/reviewSubmissions", {"data": {
            "type": "reviewSubmissions", "attributes": {"platform": "IOS"},
            "relationships": {"app": {"data": {"type": "apps", "id": self.app_id}}}}})["data"]
        self.post("/v1/reviewSubmissionItems", {"data": {
            "type": "reviewSubmissionItems",
            "relationships": {"reviewSubmission": {"data": {"type": "reviewSubmissions", "id": sub["id"]}}, **item}}})
        self.patch(f"/v1/reviewSubmissions/{sub['id']}", {"data": {
            "type": "reviewSubmissions", "id": sub["id"], "attributes": {"submitted": True}}})
        return sub["id"]

    # ── sales reports ────────────────────────────────────────────────────────

    def sales_day(self, vendor: str, day: date) -> list[dict]:
        """One day's Sales summary rows for this app (Apple's gzip TSV). Empty when Apple hasn't published it yet."""
        params = {"filter[frequency]": "DAILY", "filter[reportType]": "SALES", "filter[reportSubType]": "SUMMARY",
                  "filter[vendorNumber]": vendor, "filter[reportDate]": day.isoformat(), "filter[version]": "1_0"}
        resp = requests.get(f"{BASE_URL}/v1/salesReports", params=params, timeout=60,
                            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/a-gzip"})
        if resp.status_code == 404:
            return []
        if resp.status_code == 403:
            raise AppStoreConnectError("This API key can't read sales reports (App Manager keys can't). Add a key "
                                       "with the Sales role as ASC_SALES_KEY_ID and ASC_SALES_PRIVATE_KEY_B64.")
        if not resp.ok:
            raise AppStoreConnectError(f"Sales report for {day} failed ({resp.status_code}): {resp.text[:300]}")
        text = gzip.decompress(resp.content).decode("utf-8")
        return [row for row in csv.DictReader(io.StringIO(text), delimiter="\t")
                if str(row.get("Apple Identifier")) == str(self.app_id)]


def vendor_number(value: str | None = None) -> str:
    vendor = value or os.environ.get("ASC_VENDOR_NUMBER")
    if not vendor:
        raise AppStoreConnectError("Set ASC_VENDOR_NUMBER (Payments and Financial Reports, top left) or enter Vendor "
                                   "number.")
    return vendor


def download_counts(rows: list[dict], country: str | None = None) -> dict[str, int]:
    """First-time downloads and redownloads in a day's sales rows, optionally for one country (US)."""
    counts = {"new": 0, "re": 0}
    for row in rows:
        if country and row.get("Country Code") != country:
            continue
        kind = row.get("Product Type Identifier") or ""
        units = int(float(row.get("Units") or 0))
        if kind in NEW_DOWNLOAD_TYPES:
            counts["new"] += units
        elif kind in REDOWNLOAD_TYPES:
            counts["re"] += units
    return counts
