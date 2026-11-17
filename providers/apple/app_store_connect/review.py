"""App Store Connect reads: the listing, custom product pages, reviews and downloads. Every run calls Apple and
stores nothing."""
from datetime import date, timedelta

from callables import Next

from providers.apple.app_store_connect.app_store_api import (SALES_SECRETS, AppStoreConnect, download_counts,
                                                             vendor_number)
from providers.apple.app_store_connect.changes import (copy_product_page, set_promotional_text, submit_product_page,
                                                       update_listing)
from providers.apple.app_store_connect.group import app_store

LIVE_STATES = ("READY_FOR_SALE", "READY_FOR_DISTRIBUTION")


def _image_url(asset: dict | None, width: int = 600) -> str | None:
    if not asset or not asset.get("templateUrl"):
        return None
    height = int(width * (asset.get("height") or 1) / (asset.get("width") or 1))
    return asset["templateUrl"].replace("{w}", str(width)).replace("{h}", str(height)).replace("{f}", "png")


@app_store.deploy(title="Product page details")
def product_page_details(product_page_id: str) -> list[dict]:
    """Everything on a custom product page's latest version: promotional text, screenshots and videos per locale and
    device size."""
    asc = AppStoreConnect()
    page = asc.get(f"/v1/appCustomProductPages/{product_page_id}")["data"]["attributes"]
    version = asc.latest_page_version(product_page_id)
    if not version:
        raise ValueError("That product page has no versions.")
    rows = []
    for loc in asc.page_localizations(version["id"]):
        la = loc["attributes"]
        base = {"product_page": page.get("name"), "version_state": version["attributes"].get("state"),
                "locale": la.get("locale")}
        rows.append({**base, "item": "promotional text", "detail": la.get("promotionalText"), "link": None})
        for s in asc.all(f"/v1/appCustomProductPageLocalizations/{loc['id']}/appPreviewSets"):
            for v in asc.all(f"/v1/appPreviewSets/{s['id']}/appPreviews"):
                va = v["attributes"]
                rows.append({**base, "item": f"video ({s['attributes'].get('previewType')})",
                             "detail": f"{va.get('fileName')}, poster at {va.get('previewFrameTimeCode')}, "
                                       f"{(va.get('assetDeliveryState') or {}).get('state')}",
                             "link": va.get("videoUrl") or _image_url(va.get("previewImage"))})
        for s in asc.all(f"/v1/appCustomProductPageLocalizations/{loc['id']}/appScreenshotSets"):
            for n, shot in enumerate(asc.all(f"/v1/appScreenshotSets/{s['id']}/appScreenshots"), 1):
                sa = shot["attributes"]
                rows.append({**base, "item": f"screenshot {n} ({s['attributes'].get('screenshotDisplayType')})",
                             "detail": sa.get("fileName"), "link": _image_url(sa.get("imageAsset"))})
    return rows


@app_store.deploy(title="Custom product pages", next=[
    product_page_details,
    Next(copy_product_page, label="Copy page", source_product_page_id="product_page_id"),
    Next(set_promotional_text, label="Change promotional text"),
    Next(submit_product_page, label="Submit for review"),
])
def custom_product_pages() -> list[dict]:
    """Every custom product page with its review state, whether it has a video, its promotional text and its link.
    The product page id is what Apple Ads uses to run an ad group on the page."""
    asc = AppStoreConnect()
    rows = []
    for p in asc.all(f"/v1/apps/{asc.app_id}/appCustomProductPages"):
        a = p["attributes"]
        versions = asc.page_versions(p["id"])
        promo, previews, shots = None, 0, 0
        latest = asc.latest_page_version(p["id"])
        for loc in asc.page_localizations(latest["id"]) if latest else []:
            promo = promo or loc["attributes"].get("promotionalText")
            previews += len(asc.all(f"/v1/appCustomProductPageLocalizations/{loc['id']}/appPreviewSets"))
            shots += len(asc.all(f"/v1/appCustomProductPageLocalizations/{loc['id']}/appScreenshotSets"))
        rows.append({
            "product_page": a.get("name"), "visible": a.get("visible"),
            "version_states": ", ".join(v["attributes"].get("state", "") for v in versions),
            "has_video": previews > 0, "screenshot_sets": shots, "promotional_text": promo,
            "url": a.get("url"), "product_page_id": p["id"],
        })
    return rows


@app_store.deploy(title="App Store listing", next=[Next(update_listing, label="Change listing")])
def app_listing() -> list[dict]:
    """The App Store listing per language for the newest version: name, subtitle, keywords, promotional text,
    description and what's new."""
    asc = AppStoreConnect()
    versions = asc.get(f"/v1/apps/{asc.app_id}/appStoreVersions", limit=1)["data"]
    if not versions:
        raise ValueError("No App Store versions found.")
    v = versions[0]
    infos = asc.all(f"/v1/apps/{asc.app_id}/appInfos")
    state_of = lambda i: i["attributes"].get("appStoreState") or i["attributes"].get("state")  # noqa: E731
    # The draft app info (for the version being prepared) if there is one, else the live one
    info = next((i for i in infos if state_of(i) not in LIVE_STATES), None) or (infos[0] if infos else None)
    live = next((i for i in infos if state_of(i) in LIVE_STATES), None)

    def locs(app_info):
        return {l["attributes"]["locale"]: l["attributes"]
                for l in asc.all(f"/v1/appInfos/{app_info['id']}/appInfoLocalizations")} if app_info else {}

    info_locs = locs(info)
    live_locs = locs(live) if live and live is not info else {}
    rows = []
    for loc in asc.all(f"/v1/appStoreVersions/{v['id']}/appStoreVersionLocalizations"):
        a = loc["attributes"]
        i = info_locs.get(a.get("locale"), {})
        rows.append({
            "version": v["attributes"].get("versionString"), "state": v["attributes"].get("appStoreState"),
            "locale": a.get("locale"), "name": i.get("name"), "subtitle": i.get("subtitle"),
            "live_subtitle": live_locs.get(a.get("locale"), {}).get("subtitle", i.get("subtitle")),
            "keywords": a.get("keywords"), "promotional_text": a.get("promotionalText"),
            "description": a.get("description"), "whats_new": a.get("whatsNew"),
        })
    return rows


@app_store.deploy(title="App Store reviews")
def reviews(min_rating: int = 1, territory: str | None = None) -> list[dict]:
    """Written App Store reviews, newest first: stars, title, text, nickname and country.

    The last row averages their stars. Apple's API only serves written reviews, so it can differ from the
    listing's average. Territory is a 3-letter code (USA, GBR).
    """
    asc = AppStoreConnect()
    params = {"sort": "-createdDate"}
    if territory:
        params["filter[territory]"] = territory.upper()
    rows = []
    for r in asc.all(f"/v1/apps/{asc.app_id}/customerReviews", **params):
        a = r["attributes"]
        rows.append({"date": (a.get("createdDate") or "")[:10], "rating": a.get("rating"), "title": a.get("title"),
                     "body": a.get("body"), "nickname": a.get("reviewerNickname"), "territory": a.get("territory")})
    stars = [r["rating"] for r in rows if r["rating"]]
    shown = [r for r in rows if (r["rating"] or 0) >= min_rating]
    shown.append({
        "date": "Total", "rating": round(sum(stars) / len(stars), 2) if stars else None,
        "title": f"{len(stars)} reviews" + (f", {len(shown)} at {min_rating}+ stars" if min_rating > 1 else ""),
        "body": None, "nickname": None, "territory": territory.upper() if territory else "all",
    })
    return shown


def daily_downloads(start: date, end: date, vendor: str | None = None, country: str | None = None) -> dict[str, dict]:
    """{date: {"new", "re", "published"}} from the daily sales reports. Plain function, for recipes."""
    asc = AppStoreConnect(sales=True)
    vendor = vendor_number(vendor)
    out, day = {}, start
    while day <= end:
        rows = asc.sales_day(vendor, day)
        out[day.isoformat()] = {**download_counts(rows, country), "published": bool(rows)}
        day += timedelta(days=1)
    return out


@app_store.deploy(title="Downloads", secrets=SALES_SECRETS)
def downloads(start: date | None = None, end: date | None = None, country: str | None = None,
              vendor: str | None = None) -> list[dict]:
    """First-time downloads and redownloads per day, from App Store Connect's daily sales reports.

    Dates default to the last 14 days ending yesterday; Apple publishes each day's report the next morning
    (Pacific). Country is a 2-letter code (US). Needs a key that can read sales reports.
    """
    end = end or date.today() - timedelta(days=1)
    start = start or end - timedelta(days=13)
    days = daily_downloads(start, end, vendor, country.upper() if country else None)
    rows = [{"date": d, "report": "published" if c["published"] else "not published yet",
             "new_downloads": c["new"], "redownloads": c["re"]} for d, c in days.items()]
    rows.append({"date": "Total", "report": f"{sum(1 for c in days.values() if c['published'])} days",
                 "new_downloads": sum(r["new_downloads"] for r in rows),
                 "redownloads": sum(r["redownloads"] for r in rows)})
    return rows
