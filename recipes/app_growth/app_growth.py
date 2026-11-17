"""App growth: App Store Connect and Apple Ads together, for the questions neither answers alone. How many downloads
came from ads and how many came on their own, which custom product page converts best in ads, and which searches
that already bring installs through ads are missing from your App Store keywords.

Everything is live and nothing is stored. Changes are left to the provider callables each row links to, which all
preview first.
"""
import re
from datetime import date, timedelta

from callables import Group, Next

from providers.apple.ads.apple_ads_api import SECRETS as ADS_SECRETS
from providers.apple.ads.apple_ads_api import AppleAds, ads_with_pages
from providers.apple.ads.changes import copy_ad_group
from providers.apple.ads.metrics import money, window
from providers.apple.ads.review import search_terms
from providers.apple.app_store_connect.app_store_api import SALES_SECRETS
from providers.apple.app_store_connect.app_store_api import SECRETS as STORE_SECRETS
from providers.apple.app_store_connect.changes import copy_product_page, update_listing
from providers.apple.app_store_connect.review import app_listing, custom_product_pages, daily_downloads, \
    product_page_details

app_growth = Group(
    "app_growth",
    title="App growth",
    description="App Store Connect and Apple Ads together: downloads from ads vs organic, which product page "
                "converts best in ads, and keyword ideas for your listing from the searches ads already win.",
    secrets=list(dict.fromkeys(STORE_SECRETS + ADS_SECRETS)),
)


def _rate(part, whole, digits: int = 1) -> float | None:
    return round(100 * part / whole, digits) if whole else None


# ── downloads: ads vs organic ────────────────────────────────────────────────

def _ads_by_day(start: date, end: date) -> dict[str, dict]:
    """Apple Ads spend, new downloads, redownloads and installs per day, over every campaign."""
    api = AppleAds()
    body = {"startTime": start.isoformat(), "endTime": end.isoformat(), "granularity": "DAILY",
            "returnRowTotals": False, "returnGrandTotals": False, "returnRecordsWithNoMetrics": False,
            "selector": {"pagination": {"offset": 0, "limit": 1000},
                         "orderBy": [{"field": "localSpend", "sortOrder": "DESCENDING"}]}}
    days: dict[str, dict] = {}
    for row in api.post("/reports/campaigns", body).get("data", {}).get("reportingDataResponse", {}).get("row", []):
        for d in row.get("granularity") or []:
            day = days.setdefault(str(d.get("date"))[:10], {"spend": 0.0, "new": 0, "re": 0, "installs": 0})
            day["spend"] += money(d.get("localSpend")) or 0
            day["new"] += int(d.get("totalNewDownloads") or d.get("tapNewDownloads") or 0)
            day["re"] += int(d.get("totalRedownloads") or d.get("tapRedownloads") or 0)
            day["installs"] += int(d.get("totalInstalls") or d.get("tapInstalls") or 0)
    return days


@app_growth.deploy(title="Downloads: ads vs organic", name="downloads_vs_ads", secrets=SALES_SECRETS)
def downloads_vs_ads(start: date | None = None, end: date | None = None, vendor: str | None = None) -> list[dict]:
    """App Store downloads per day next to Apple Ads downloads, so you see how many came on their own.

    Organic = App Store first-time downloads minus Apple Ads ones. Blended cost = ad spend / every first-time
    download, what each download really costs once organic ones count. Dates default to the last 14 days ending
    yesterday; Apple publishes each day's sales report the next morning (Pacific).
    """
    end = end or date.today() - timedelta(days=1)
    start = start or end - timedelta(days=13)
    store = daily_downloads(start, end, vendor)
    ads = _ads_by_day(start, end)
    rows = []
    for day, s in store.items():
        a = ads.get(day, {"spend": 0.0, "new": 0, "re": 0, "installs": 0})
        rows.append({
            "date": day, "report": "published" if s["published"] else "not published yet",
            "store_new_downloads": s["new"], "store_redownloads": s["re"],
            "ads_new_downloads": a["new"], "ads_redownloads": a["re"],
            "organic_new_downloads": s["new"] - a["new"] if s["published"] else None,
            "ads_share_pct": _rate(a["new"], s["new"]) if s["published"] else None,
            "ad_spend": round(a["spend"], 2),
            "ads_cost_per_download": round(a["spend"] / a["new"], 2) if a["new"] else None,
            "blended_cost_per_download": round(a["spend"] / s["new"], 2) if s["published"] and s["new"] else None,
        })
    done = [r for r in rows if r["report"] == "published"]
    new, ads_new = sum(r["store_new_downloads"] for r in done), sum(r["ads_new_downloads"] for r in done)
    spend = sum(r["ad_spend"] for r in done)
    rows.append({
        "date": "Total", "report": f"{len(done)} published days",
        "store_new_downloads": new, "store_redownloads": sum(r["store_redownloads"] for r in done),
        "ads_new_downloads": ads_new, "ads_redownloads": sum(r["ads_redownloads"] for r in done),
        "organic_new_downloads": new - ads_new, "ads_share_pct": _rate(ads_new, new), "ad_spend": round(spend, 2),
        "ads_cost_per_download": round(spend / ads_new, 2) if ads_new else None,
        "blended_cost_per_download": round(spend / new, 2) if new else None,
    })
    return rows


# ── product pages in ads ─────────────────────────────────────────────────────

@app_growth.deploy(title="Product pages in ads", name="product_pages", next=[
    product_page_details,
    Next(copy_ad_group, label="Run an ad group on this page"),
    Next(copy_product_page, label="Copy page to test a variant", source_product_page_id="product_page_id"),
])
def product_pages(start: date | None = None, end: date | None = None, include_paused: bool = False) -> list[dict]:
    """Each custom product page (and the default page) with how its ads did: ads running, spend, taps, installs,
    conversion rate (installs / taps) and cost per install, best converting first.

    Pages no ad uses yet are listed last, so you can see what's ready to test. Dates default to the last 30 days.
    """
    start, end = window(start, end)
    pages = {p["product_page_id"]: p for p in custom_product_pages()}
    totals: dict[str, dict] = {}
    for ad in ads_with_pages(start, end):
        if not include_paused and "PAUSED" in (ad.get("ad_status"), ad.get("campaign_status")):
            continue
        key = ad.get("product_page_id") or ""
        t = totals.setdefault(key, {"ads": 0, "ad_groups": set(), "spend": 0.0, "impressions": 0, "taps": 0,
                                    "installs": 0, "name": ad.get("product_page")})
        t["ads"] += 1
        t["ad_groups"].add(ad.get("ad_group"))
        for k in ("spend", "impressions", "taps", "installs"):
            t[k] += ad.get(k) or 0
    rows = []
    for key in list(totals) + [k for k in pages if k not in totals]:
        page, t = pages.get(key, {}), totals.get(key)
        row = {
            "product_page": page.get("product_page") or (t or {}).get("name") or ("Default product page" if not key
                                                                                    else key),
            "review_state": page.get("version_states") if key else "live",
            "has_video": page.get("has_video"),
            "ads": t["ads"] if t else 0,
            "ad_groups": ", ".join(sorted(g for g in t["ad_groups"] if g)) if t else "",
            "spend": round(t["spend"], 2) if t else 0, "impressions": t["impressions"] if t else 0,
            "taps": t["taps"] if t else 0, "installs": t["installs"] if t else 0,
            "ttr": _rate(t["taps"], t["impressions"], 2) if t else None,
            "cvr": _rate(t["installs"], t["taps"], 2) if t else None,
            "cpa": round(t["spend"] / t["installs"], 2) if t and t["installs"] else None,
            "url": page.get("url"),
            "product_page_id": key,
        }
        if not t:
            row["note"] = "Not in any ad yet" if "APPROVED" in (page.get("version_states") or "") or \
                "ACCEPTED" in (page.get("version_states") or "") else "Needs App Review before ads can use it"
        rows.append(row)
    rows.sort(key=lambda r: (r["ads"] == 0, -(r["cvr"] or 0), -r["installs"]))
    return rows


# ── keyword field ideas ──────────────────────────────────────────────────────

# Words Apple ignores or indexes anyway, so they don't need keyword-field space
SKIP_WORDS = {"app", "apps", "the", "a", "an", "and", "or", "for", "of", "to", "in", "on", "with", "my", "free", "&"}


# How App Store titles separate a name from its tagline ("neateat - meal planner"): a search shaped like that is
# usually another app's name, which Apple doesn't allow in your keywords
APP_TITLE = re.compile(r"\s[-–—|:]\s|・|:")


def _latin(text: str) -> bool:
    return all(ord(ch) < 0x250 for ch in text if ch.isalpha())


def _words(text: str | None) -> list[str]:
    return [w for w in re.split(r"[^\w']+", (text or "").lower()) if w]


@app_growth.deploy(title="Keyword field ideas", name="keyword_ideas", next=[
    Next(update_listing, label="Put in the keyword field", keywords="keyword_field_with_it"),
])
def keyword_ideas(start: date | None = None, end: date | None = None, min_installs: int = 2,
                  locale: str = "en-US") -> list[dict]:
    """Searches that already bring installs through Apple Ads, checked against your App Store name, subtitle and
    keyword field.

    A search is covered when all its words are already in one of the three, because Apple matches words, not whole
    phrases. For one that isn't, the row shows the words to add and your keyword field with them (if they fit in
    100 characters), ready for Change listing. Apple rejects other apps' names in keywords: searches shaped like an
    app's title are flagged, but check the rest yourself. Dates default to the last 30 days.
    """
    listing = next((r for r in app_listing() if r["locale"] == locale), None)
    if listing is None:
        raise ValueError(f"The listing has no {locale} text.")
    field = listing.get("keywords") or ""
    indexed = set(_words(listing.get("name"))) | set(_words(listing.get("subtitle"))) | set(_words(field))
    terms: dict[str, dict] = {}
    for r in search_terms(start=start, end=end):
        text = (r.get("search_term") or "").strip().lower()
        if not text or text.startswith("(low-volume"):
            continue
        t = terms.setdefault(text, {"spend": 0.0, "taps": 0, "installs": 0, "sources": set()})
        t["spend"] += r.get("spend") or 0
        t["taps"] += r.get("taps") or 0
        t["installs"] += r.get("installs") or 0
        t["sources"].add(r.get("source") or "")
    rows = []
    for text, t in terms.items():
        if t["installs"] < min_installs:
            continue
        missing = [w for w in dict.fromkeys(_words(text)) if w not in indexed and w not in SKIP_WORDS]
        new_field = ",".join(filter(None, [field, *missing])) if missing else None
        fits = new_field is not None and len(new_field) <= 100
        if missing and not _latin(text) and _latin(field):
            note, new_field, fits = f"Another language: add it to that language's listing, not {locale}.", None, True
        elif missing and APP_TITLE.search(text):
            note, new_field, fits = ("Looks like another app's name. Apple rejects other apps' names in keywords, so "
                                     "bid on it in Apple Ads instead."), None, True
        elif missing and not fits:
            note = f"Doesn't fit: needs {len(new_field) - 100} more characters than the 100 allowed. Swap out a " \
                   "weaker word."
        else:
            note = ""
        rows.append({
            "search_term": text,
            "installs": t["installs"], "taps": t["taps"], "spend": round(t["spend"], 2),
            "cvr": _rate(t["installs"], t["taps"], 2),
            "cpa": round(t["spend"] / t["installs"], 2) if t["installs"] else None,
            "found_by": ", ".join(sorted(s for s in t["sources"] if s)),
            "in_listing": "yes" if not missing else "partly" if len(missing) < len(set(_words(text))) else "no",
            "words_to_add": ", ".join(missing),
            "keyword_field_with_it": new_field if fits else None,
            "note": note,
        })
    rows.sort(key=lambda r: (r["in_listing"] == "yes", -r["installs"]))
    if rows:
        rows.append({"search_term": "Your keyword field now", "words_to_add": f"{len(field)} of 100 characters used",
                     "note": field})
    return rows
