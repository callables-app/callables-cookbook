"""App Store Connect changes: listing text, custom product pages, screenshots, videos and review submissions.

Every change has Dry run ticked by default: the run shows what would change and changes nothing. Untick it to apply.
"""
import hashlib
import io
import re
import time
import zipfile
from pathlib import Path
from typing import Annotated, Literal

import requests

from callables import File, accept

from providers.apple.app_store_connect.app_store_api import AppStoreConnect
from providers.apple.app_store_connect.group import app_store

PREVIEW = "Preview only: nothing changed. Untick Dry run and run again to apply."
APPLIED = "Done in App Store Connect."

ScreenshotSize = Literal["APP_IPHONE_67", "APP_IPHONE_65", "APP_IPHONE_61", "APP_IPHONE_55", "APP_IPAD_PRO_3GEN_129"]
PreviewSize = Literal["IPHONE_67", "IPHONE_65", "IPHONE_61", "IPHONE_55", "IPAD_PRO_3GEN_129"]
# App versions in these states can have their text changed
EDITABLE = ("PREPARE_FOR_SUBMISSION", "DEVELOPER_REJECTED", "REJECTED", "METADATA_REJECTED", "INVALID_BINARY")
LIVE_STATES = ("READY_FOR_SALE", "READY_FOR_DISTRIBUTION")


# ── custom product pages ─────────────────────────────────────────────────────

@app_store.deploy(title="Copy product page")
def copy_product_page(source_product_page_id: str, name: str, locale: str = "en-US", dry_run: bool = True) -> dict:
    """A new custom product page that starts as a copy of an existing one: screenshots, videos and text.

    It's created as a draft. Change it, then submit it for review.
    """
    asc = AppStoreConnect()
    src = asc.get(f"/v1/appCustomProductPages/{source_product_page_id}")["data"]["attributes"]
    if any(p["attributes"].get("name") == name for p in asc.all(f"/v1/apps/{asc.app_id}/appCustomProductPages")):
        raise ValueError(f"A product page called {name!r} already exists.")
    result = {"source": src.get("name"), "new_product_page": name}
    if dry_run:
        return {"result": PREVIEW, **result}
    body = {
        "data": {
            "type": "appCustomProductPages",
            "attributes": {"name": name},
            "relationships": {
                "app": {"data": {"type": "apps", "id": asc.app_id}},
                "customProductPageTemplate": {"data": {"type": "appCustomProductPages", "id": source_product_page_id}},
                "appCustomProductPageVersions": {"data": [{"type": "appCustomProductPageVersions", "id": "${v}"}]},
            },
        },
        "included": [
            {"type": "appCustomProductPageVersions", "id": "${v}",
             "relationships": {"appCustomProductPageLocalizations": {
                 "data": [{"type": "appCustomProductPageLocalizations", "id": "${l}"}]}}},
            {"type": "appCustomProductPageLocalizations", "id": "${l}", "attributes": {"locale": locale}},
        ],
    }
    created = asc.post("/v1/appCustomProductPages", body)["data"]
    return {"result": APPLIED, **result, "product_page_id": created["id"],
            "next": "Change its screenshots, video or promotional text, then submit it for review."}


@app_store.deploy(title="Change promotional text")
def set_promotional_text(product_page_id: str, promotional_text: str, locale: str = "en-US",
                         dry_run: bool = True) -> dict:
    """A custom product page's promotional text (up to 170 characters), on its draft or live version.

    Apple lets promotional text change without a new review.
    """
    if len(promotional_text) > 170:
        raise ValueError(f"Promotional text is {len(promotional_text)} characters; the limit is 170.")
    asc = AppStoreConnect()
    version, loc = asc.page_localization(product_page_id, locale)
    before = loc["attributes"].get("promotionalText")
    if not dry_run:
        asc.patch(f"/v1/appCustomProductPageLocalizations/{loc['id']}",
                  {"data": {"type": "appCustomProductPageLocalizations", "id": loc["id"],
                            "attributes": {"promotionalText": promotional_text}}})
    return {"result": PREVIEW if dry_run else APPLIED, "locale": locale, "before": before, "after": promotional_text,
            "version_state": version["attributes"].get("state")}


def _png_size(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return f"{int.from_bytes(data[16:20], 'big')}x{int.from_bytes(data[20:24], 'big')}"
    return "?"


def _images(image_urls: str | None, images_zip: File | None) -> list[tuple[str, bytes]]:
    """The screenshots, in order: from a .zip (sorted by file name) or from URLs (one per line)."""
    if images_zip is not None:
        with zipfile.ZipFile(images_zip.path) as z:
            names = sorted(n for n in z.namelist() if re.search(r"\.(png|jpe?g)$", n, re.I)
                           and not n.startswith("__MACOSX") and not n.split("/")[-1].startswith("."))
            return [(n.split("/")[-1], z.read(n)) for n in names]
    out = []
    for n, url in enumerate([u.strip() for u in (image_urls or "").splitlines() if u.strip()], 1):
        resp = requests.get(url, timeout=120)
        if not resp.ok:
            raise ValueError(f"Image {n} couldn't be downloaded ({resp.status_code}).")
        out.append((f"screenshot-{n:02d}.png", resp.content))
    return out


@app_store.deploy(title="Set screenshots")
def set_screenshots(product_page_id: str, image_urls: str | None = None,
                    images_zip: Annotated[File, accept(".zip")] | None = None,
                    display_type: ScreenshotSize = "APP_IPHONE_67", locale: str = "en-US",
                    dry_run: bool = True) -> dict:
    """Replace one device size's screenshots on a product page draft, in order.

    Give image URLs (one per line) or a .zip of PNG or JPEG files (used in file-name order). Up to 10.
    """
    asc = AppStoreConnect()
    version, loc = asc.page_localization(product_page_id, locale, editable=True)
    images = _images(image_urls, images_zip)
    if not 1 <= len(images) <= 10:
        raise ValueError(f"Give between 1 and 10 images (got {len(images)}).")
    sets = asc.all(f"/v1/appCustomProductPageLocalizations/{loc['id']}/appScreenshotSets")
    target = next((s for s in sets if s["attributes"].get("screenshotDisplayType") == display_type), None)
    old = asc.all(f"/v1/appScreenshotSets/{target['id']}/appScreenshots") if target else []
    result = {"version_state": version["attributes"].get("state"), "locale": locale, "display_type": display_type,
              "replacing": len(old), "new_images": len(images),
              "sizes": ", ".join(_png_size(data) for _, data in images)}
    if dry_run:
        return {"result": PREVIEW, **result}
    if not target:
        target = asc.post("/v1/appScreenshotSets", {"data": {
            "type": "appScreenshotSets", "attributes": {"screenshotDisplayType": display_type},
            "relationships": {"appCustomProductPageLocalization": {
                "data": {"type": "appCustomProductPageLocalizations", "id": loc["id"]}}}}})["data"]
    for o in old:
        asc.delete(f"/v1/appScreenshots/{o['id']}")
    ids = []
    for name, data in images:
        shot = asc.post("/v1/appScreenshots", {"data": {
            "type": "appScreenshots", "attributes": {"fileName": name, "fileSize": len(data)},
            "relationships": {"appScreenshotSet": {"data": {"type": "appScreenshotSets", "id": target["id"]}}}}})["data"]
        asc.upload(shot["attributes"].get("uploadOperations"), data, name)
        asc.patch(f"/v1/appScreenshots/{shot['id']}", {"data": {
            "type": "appScreenshots", "id": shot["id"],
            "attributes": {"uploaded": True, "sourceFileChecksum": hashlib.md5(data).hexdigest()}}})
        ids.append(shot["id"])
    asc.patch(f"/v1/appScreenshotSets/{target['id']}/relationships/appScreenshots",
              {"data": [{"type": "appScreenshots", "id": i} for i in ids]})
    return {"result": APPLIED, **result,
            "next": "Apple processes the images for a minute; check them with Product page details."}


@app_store.deploy(title="Add video to product page")
def add_preview(product_page_id: str, video: Annotated[File, accept(".mp4", ".mov")],
                preview_type: PreviewSize = "IPHONE_67", locale: str = "en-US", poster_time: str | None = None,
                dry_run: bool = True) -> dict:
    """Upload an app preview video to a product page draft. Poster time picks the frame shown before it plays, like
    00:00:05:00."""
    asc = AppStoreConnect()
    version, loc = asc.page_localization(product_page_id, locale, editable=True)
    data = Path(video.path).read_bytes()
    sets = asc.all(f"/v1/appCustomProductPageLocalizations/{loc['id']}/appPreviewSets")
    existing = next((s for s in sets if s["attributes"].get("previewType") == preview_type), None)
    result = {"locale": locale, "preview_type": preview_type, "file": video.name,
              "size_mb": round(len(data) / 1e6, 1), "version_state": version["attributes"].get("state"),
              "preview_set": "existing" if existing else "new"}
    if dry_run:
        return {"result": PREVIEW, **result}
    if not existing:
        existing = asc.post("/v1/appPreviewSets", {"data": {
            "type": "appPreviewSets", "attributes": {"previewType": preview_type},
            "relationships": {"appCustomProductPageLocalization": {
                "data": {"type": "appCustomProductPageLocalizations", "id": loc["id"]}}}}})["data"]
    attrs = {"fileName": video.name, "fileSize": len(data),
             "mimeType": "video/quicktime" if video.name.lower().endswith(".mov") else "video/mp4"}
    if poster_time:
        attrs["previewFrameTimeCode"] = poster_time
    preview = asc.post("/v1/appPreviews", {"data": {
        "type": "appPreviews", "attributes": attrs,
        "relationships": {"appPreviewSet": {"data": {"type": "appPreviewSets", "id": existing["id"]}}}}})["data"]
    asc.upload(preview["attributes"].get("uploadOperations"), data, video.name)
    asc.patch(f"/v1/appPreviews/{preview['id']}", {"data": {
        "type": "appPreviews", "id": preview["id"],
        "attributes": {"uploaded": True, "sourceFileChecksum": hashlib.md5(data).hexdigest()}}})
    return {"result": APPLIED, **result, "preview_id": preview["id"],
            "next": "Apple processes the video for a few minutes; check it with Product page details."}


CREATIVE = {"header": "PRODUCT_PAGE_HEADER_ASSET", "search": "APP_STORE_SEARCH_RESULTS_ASSET"}


def _opaque_png(data: bytes) -> tuple[bytes, tuple[int, int]]:
    """Apple refuses images with an alpha channel: flatten onto white and save as an RGB PNG."""
    from PIL import Image

    im = Image.open(io.BytesIO(data))
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        background = Image.new("RGB", im.size, (255, 255, 255))
        background.paste(im, mask=im.split()[-1])
        im = background
    elif im.mode != "RGB":
        im = im.convert("RGB")
    out = io.BytesIO()
    im.save(out, "PNG", optimize=True)
    return out.getvalue(), im.size


@app_store.deploy(title="Header & search images")
def set_creative_assets(product_page_id: str, header_url: str | None = None, search_url: str | None = None,
                        locale: str = "en-US", dry_run: bool = True) -> dict:
    """The header and search-results images on a product page draft, from image URLs."""
    asc = AppStoreConnect()
    page = asc.get(f"/v1/appCustomProductPages/{product_page_id}")["data"]["attributes"]
    version, loc = asc.page_localization(product_page_id, locale, editable=True)
    urls = {k: v.strip() for k, v in (("header", header_url), ("search", search_url)) if v and v.strip()}
    if not urls:
        raise ValueError("Give a Header url, a Search url, or both.")
    library = asc.get(f"/v1/apps/{asc.app_id}/assetLibrary")["data"]["id"]
    ref = asc.get("/v1/appAssetLibraryRefData", **{"filter[features]": "CUSTOM_PRODUCT_PAGES"})["data"][0]["attributes"]
    specs = {s["specId"]: s for s in ref.get("imageSpecs") or []}
    types = {t["placementTypeId"]: t for t in ref.get("placementTypes") or []}
    plan, notes = [], []
    for kind, url in urls.items():
        ptype = CREATIVE[kind]
        resp = requests.get(url, timeout=120)
        if not resp.ok:
            raise ValueError(f"The {kind} image couldn't be downloaded ({resp.status_code}).")
        data, (w, h) = _opaque_png(resp.content)
        mappings = (types.get(ptype) or {}).get("specMappings") or []
        group = next((m["placementGroupId"] for m in mappings for sid in m.get("specs") or []
                      if (d := (specs.get(sid) or {}).get("dimensions") or {})
                      and d.get("minWidth", 0) <= w <= d.get("maxWidth", 10 ** 6)
                      and d.get("minHeight", 0) <= h <= d.get("maxHeight", 10 ** 6)), None)
        if not group:
            raise ValueError(f"{kind}: {w}x{h} matches none of Apple's sizes for {ptype}.")
        plan.append((kind, ptype, group, data))
        notes.append(f"{kind}: {w}x{h}, {round(len(data) / 1e6, 1)} MB")
    existing = [p for p in asc.all(f"/v1/appCustomProductPageLocalizations/{loc['id']}/placements")
                if p["attributes"].get("placementType") in {CREATIVE[k] for k in urls}]
    result = {"product_page": page.get("name"), "version_state": version["attributes"].get("state"),
              "locale": locale, "assets": "; ".join(notes), "replacing": len(existing)}
    if dry_run:
        return {"result": PREVIEW, **result}
    for p in existing:
        asc.delete(f"/v1/appAssetLibraryPlacements/{p['id']}")
    placed = []
    for kind, ptype, group, data in plan:
        img = asc.post("/v1/appAssetLibraryImages", {"data": {
            "type": "appAssetLibraryImages",
            "attributes": {"fileName": f"{kind}.png", "fileSize": len(data), "category": "CREATIVE_ASSETS",
                           "referenceName": f"{page.get('name')} {kind} {time.strftime('%Y-%m-%d %H%M')}"},
            "relationships": {"assetLibrary": {"data": {"type": "appAssetLibraries", "id": library}}}}})["data"]
        asc.upload(img["attributes"].get("uploadOperations"), data, f"the {kind} image")
        asc.patch(f"/v1/appAssetLibraryImages/{img['id']}", {"data": {
            "type": "appAssetLibraryImages", "id": img["id"], "attributes": {"uploaded": True}}})
        placement = asc.post("/v1/appAssetLibraryPlacements", {"data": {
            "type": "appAssetLibraryPlacements", "attributes": {"placementType": ptype, "placementGroup": group},
            "relationships": {"image": {"data": {"type": "appAssetLibraryImages", "id": img["id"]}},
                              "appCustomProductPageLocalization": {
                                  "data": {"type": "appCustomProductPageLocalizations", "id": loc["id"]}}}}})["data"]
        placed.append(f"{kind}: {placement['attributes'].get('state')}")
    return {"result": APPLIED, **result, "placements": "; ".join(placed),
            "next": "They're reviewed with the page when you submit it."}


@app_store.deploy(title="Submit product page for review")
def submit_product_page(product_page_id: str, dry_run: bool = True) -> dict:
    """Send a custom product page's draft to App Review. Once it's approved, Apple Ads can run ads on it."""
    asc = AppStoreConnect()
    page = asc.get(f"/v1/appCustomProductPages/{product_page_id}")["data"]["attributes"]
    version = asc.latest_page_version(product_page_id)
    state = (version or {}).get("attributes", {}).get("state")
    if state not in ("PREPARE_FOR_SUBMISSION", "READY_FOR_REVIEW", "REJECTED", "DEVELOPER_REJECTED"):
        raise ValueError(f"The page's latest version is {state}: nothing to submit.")
    result = {"product_page": page.get("name"), "version_state": state}
    if dry_run:
        return {"result": PREVIEW, **result}
    sub = asc.submit({"appCustomProductPageVersion": {"data": {"type": "appCustomProductPageVersions",
                                                               "id": version["id"]}}})
    return {"result": "Submitted for review.", **result, "review_submission_id": sub}


# ── the listing ──────────────────────────────────────────────────────────────

def _version_state(v: dict) -> str:
    return v["attributes"].get("appStoreState") or v["attributes"].get("appVersionState") or ""


def _clean(text: str) -> str:
    """Trailing spaces off every line, and no runs of blank lines."""
    lines = [line.rstrip() for line in text.replace("\r", "").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _version_localization(asc: AppStoreConnect, version_id: str, locale: str) -> dict | None:
    return next((l for l in asc.all(f"/v1/appStoreVersions/{version_id}/appStoreVersionLocalizations")
                 if l["attributes"].get("locale") == locale), None)


@app_store.deploy(title="Change listing")
def update_listing(keywords: str | None = None, subtitle: str | None = None, promotional_text: str | None = None,
                   whats_new: str | None = None, version: str | None = None, copy_whats_new: bool = False,
                   locale: str = "en-US", remove_from_review: bool = False, resubmit: bool = False,
                   dry_run: bool = True) -> dict:
    """Change the listing's keywords (100 characters), subtitle (30), promotional text (170) and what's new.

    Version picks an app version, creating it if it doesn't exist yet (it copies the live version's text);
    otherwise the newest is used. A version waiting for review must be pulled first: tick Remove from review, and
    Resubmit to send it back.
    """
    asc = AppStoreConnect()
    app = asc.app_id
    if promotional_text is not None and len(promotional_text) > 170:
        raise ValueError(f"Promotional text is {len(promotional_text)} characters; the limit is 170.")
    if keywords is not None:
        keywords = ",".join(k.strip() for k in keywords.split(",") if k.strip())
        if len(keywords) > 100:
            raise ValueError(f"Keywords are {len(keywords)} characters; the limit is 100.")
    if subtitle is not None and len(subtitle) > 30:
        raise ValueError(f"Subtitle is {len(subtitle)} characters; the limit is 30.")
    live = next((v for v in asc.get(f"/v1/apps/{app}/appStoreVersions", limit=10)["data"]
                 if _version_state(v) in LIVE_STATES), None)
    if copy_whats_new and whats_new is None and live:
        prev = _version_localization(asc, live["id"], locale)
        whats_new = _clean((prev or {}).get("attributes", {}).get("whatsNew") or "") or None
    if keywords is None and subtitle is None and promotional_text is None and whats_new is None and not version:
        raise ValueError("Nothing to change: set Keywords, Subtitle, Promotional text or What's new.")

    created = False
    if version:
        found = asc.get(f"/v1/apps/{app}/appStoreVersions",
                        **{"filter[versionString]": version, "filter[platform]": "IOS"})["data"]
        if found:
            target = found[0]
        elif dry_run:
            return {"result": PREVIEW, "version": version, "version_state": "would be created",
                    "copied_from": live["attributes"].get("versionString") if live else None,
                    "keywords": keywords or "copied from the live version", "subtitle": subtitle or "no change",
                    "promotional_text": promotional_text or "copied from the live version",
                    "whats_new": whats_new or "empty"}
        else:
            target = asc.post("/v1/appStoreVersions", {"data": {
                "type": "appStoreVersions", "attributes": {"platform": "IOS", "versionString": version},
                "relationships": {"app": {"data": {"type": "apps", "id": app}}}}})["data"]
            created = True
            time.sleep(3)  # Apple copies the live version's text into the new one
    else:
        target = asc.get(f"/v1/apps/{app}/appStoreVersions", limit=1)["data"][0]
    state = _version_state(target)

    vloc = _version_localization(asc, target["id"], locale)
    if vloc is None:
        if dry_run:
            raise ValueError(f"That version has no {locale} text yet; untick Dry run to create it from the live one.")
        src = (_version_localization(asc, live["id"], locale) or {}).get("attributes", {}) if live else {}
        attrs = {"locale": locale, **{k: src[k] for k in ("description", "keywords", "promotionalText",
                                                          "marketingUrl", "supportUrl") if src.get(k)}}
        vloc = asc.post("/v1/appStoreVersionLocalizations", {"data": {
            "type": "appStoreVersionLocalizations", "attributes": attrs,
            "relationships": {"appStoreVersion": {"data": {"type": "appStoreVersions", "id": target["id"]}}}}})["data"]
    infos = asc.all(f"/v1/apps/{app}/appInfos")
    # The editable app info is the one that isn't live on the store
    info = next((i for i in infos if (i["attributes"].get("appStoreState") or i["attributes"].get("state"))
                 not in LIVE_STATES), infos[0])
    iloc = next((l for l in asc.all(f"/v1/appInfos/{info['id']}/appInfoLocalizations")
                 if l["attributes"].get("locale") == locale), None)
    if subtitle is not None and iloc is None:
        raise ValueError(f"The app has no {locale} name and subtitle to change.")
    result = {
        "version": target["attributes"].get("versionString"), "version_state": state, "locale": locale,
        "keywords": f"{vloc['attributes'].get('keywords')} → {keywords}" if keywords is not None else "no change",
        "subtitle": f"{iloc['attributes'].get('subtitle')} → {subtitle}" if subtitle is not None else "no change",
        "promotional_text": f"{vloc['attributes'].get('promotionalText')} → {promotional_text}"
                            if promotional_text is not None else "no change",
        "whats_new": whats_new if whats_new is not None else "no change",
    }
    if created:
        result["note"] = f"Version {version} created."
    if state not in EDITABLE and not remove_from_review:
        raise ValueError(f"Version {result['version']} is {state} and can't be edited. Tick Remove from review to "
                         "pull it from review first.")
    if dry_run:
        steps = (["pull the version from review"] if state not in EDITABLE else []) + ["update the text"] + \
                (["resubmit for review"] if resubmit else [])
        return {"result": PREVIEW, **result, "steps": ", then ".join(steps)}

    if state not in EDITABLE:
        open_subs = [s for s in asc.all(f"/v1/apps/{app}/reviewSubmissions")
                     if s["attributes"].get("state") in ("WAITING_FOR_REVIEW", "IN_REVIEW", "UNRESOLVED_ISSUES")]
        if not open_subs:
            raise RuntimeError(f"Version is {state} but no open review submission was found.")
        for s in open_subs:
            asc.patch(f"/v1/reviewSubmissions/{s['id']}",
                      {"data": {"type": "reviewSubmissions", "id": s["id"], "attributes": {"canceled": True}}})
        for _ in range(20):  # cancelling takes a few seconds
            time.sleep(3)
            state = _version_state(asc.get(f"/v1/appStoreVersions/{target['id']}")["data"])
            if state in EDITABLE:
                break
        else:
            raise RuntimeError(f"Pulled from review, but the version is still {state}. Run this again in a minute "
                               "with Remove from review unticked.")
    vattrs = {k: v for k, v in (("keywords", keywords), ("promotionalText", promotional_text),
                                ("whatsNew", whats_new)) if v is not None}
    if vattrs:
        asc.patch(f"/v1/appStoreVersionLocalizations/{vloc['id']}", {"data": {
            "type": "appStoreVersionLocalizations", "id": vloc["id"], "attributes": vattrs}})
    if subtitle is not None:
        asc.patch(f"/v1/appInfoLocalizations/{iloc['id']}", {"data": {
            "type": "appInfoLocalizations", "id": iloc["id"], "attributes": {"subtitle": subtitle}}})
    out = {"result": APPLIED, **result, "version_state": state}
    if resubmit:
        asc.submit({"appStoreVersion": {"data": {"type": "appStoreVersions", "id": target["id"]}}})
        out["result"] = "Updated and resubmitted for review."
    return out
