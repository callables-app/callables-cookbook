"""Apple Ads review: campaigns, ad groups, keywords, search terms, keyword rankings, creatives and impression share,
read live from the API.

Each callable returns flat rows (current settings plus metrics over a date window, the last 30 days by default), so
they read well as tables in the web app and as data for an assistant to analyze. Every row keeps its ids, and the
row buttons hand them to the changes in changes.py. A row field with the same name as an input fills it (current
bid, default bid, budget), so statuses are named keyword_status, ad_group_status and campaign_status here: the
change forms' Status starts at "No change".

Target CPA: type one in the form, or each row uses its ad group's CPA goal, else its campaign's. Without one,
cpa_vs_target stays empty and keyword rankings judge keywords on taps alone.
"""
import csv
import gzip
import io
import math
import time
from datetime import date
from typing import Literal

from callables import Next

from providers.apple.ads.apple_ads_api import AppleAds, ads_with_pages
from providers.apple.ads.changes import (add_keywords, add_negatives, copy_ad_group, copy_negatives, update_ad_group,
                                         update_campaign, update_keyword)
from providers.apple.ads.group import apple_ads
from providers.apple.ads.metrics import money, stats, target, vs_target, window


def _pick_campaigns(api: AppleAds, campaign_id: int | None, include_paused: bool) -> list[dict]:
    campaigns = api.campaigns()
    if campaign_id:
        picked = [c for c in campaigns if c["id"] == campaign_id]
        if not picked:
            options = ", ".join(f"{c['name']} ({c['id']})" for c in campaigns)
            raise ValueError(f"No campaign has id {campaign_id}. Campaigns: {options}")
        return picked
    return campaigns if include_paused else [c for c in campaigns if c.get("status") == "ENABLED"]


def _keyword_rows(campaign_id: int | None, ad_group_id: int | None, start: date | None, end: date | None,
                  include_paused: bool, target_cpa: float | None) -> list[dict]:
    """One row per keyword, including keywords with no impressions in the window."""
    start, end = window(start, end)
    api = AppleAds()
    rows = []
    for c in _pick_campaigns(api, campaign_id, include_paused):
        groups = {g["id"]: g for g in api.ad_groups(c["id"])}
        for r in api.report(f"/reports/campaigns/{c['id']}/keywords", start, end, with_empty=True):
            m = r["metadata"]
            group = groups.get(m.get("adGroupId"))
            if m.get("deleted") or group is None or (ad_group_id and m["adGroupId"] != ad_group_id):
                continue
            if not include_paused and (m.get("keywordStatus") != "ACTIVE" or group.get("status") != "ENABLED"):
                continue
            rows.append(vs_target({
                "campaign": c["name"],
                "ad_group": group["name"],
                "keyword": m.get("keyword"),
                "match_type": (m.get("matchType") or "").lower(),
                "keyword_status": m.get("keywordStatus"),
                "bid": money(m.get("bidAmount")),
                "target_cpa": target(target_cpa, group, c),
                **stats(r.get("total")),
                "campaign_id": c["id"],
                "ad_group_id": m["adGroupId"],
                "keyword_id": m["keywordId"],
            }))
    if ad_group_id and not rows:
        raise ValueError(f"No keywords found in ad group {ad_group_id}: check it belongs to that campaign, or tick "
                         "Include paused.")
    return sorted(rows, key=lambda r: -r["spend"])


@apple_ads.deploy(title="Keywords", next=[Next(update_keyword, label="Change bid / pause")])
def keywords(campaign_id: int | None = None, ad_group_id: int | None = None, start: date | None = None,
             end: date | None = None, include_paused: bool = False, target_cpa: float | None = None) -> list[dict]:
    """One row per keyword: bid, match type, status, and spend, installs, TTR, CVR, CPT and CPA against target.

    Leave Campaign id empty for every enabled campaign. Dates default to the last 30 days.
    """
    return _keyword_rows(campaign_id, ad_group_id, start, end, include_paused, target_cpa)


@apple_ads.deploy(title="Search terms", next=[
    Next(add_keywords, label="Add as keyword", keywords="search_term"),
    Next(add_negatives, label="Add as negative", keywords="search_term"),
])
def search_terms(campaign_id: int | None = None, ad_group_id: int | None = None, start: date | None = None,
                 end: date | None = None, target_cpa: float | None = None) -> list[dict]:
    """What people actually searched before tapping your ad (from your keywords and Search Match), with spend,
    installs and CPA, and whether it's already a keyword.

    Leave Campaign id empty for every enabled campaign. Dates default to the last 30 days. Apple groups
    low-volume searches it doesn't name into one row.
    """
    start, end = window(start, end)
    api = AppleAds()
    rows = []
    for c in _pick_campaigns(api, campaign_id, include_paused=False):
        groups = {g["id"]: g for g in api.ad_groups(c["id"])}
        existing = {(r["metadata"].get("keyword") or "").lower().strip()
                    for r in api.report(f"/reports/campaigns/{c['id']}/keywords", start, end, with_empty=True)
                    if not r["metadata"].get("deleted")}
        for r in api.report(f"/reports/campaigns/{c['id']}/searchterms", start, end, order_by="impressions"):
            m = r.get("metadata", {})
            if ad_group_id and m.get("adGroupId") != ad_group_id:
                continue
            text, source = m.get("searchTermText"), m.get("searchTermSource")
            group = groups.get(m.get("adGroupId")) or {}
            rows.append(vs_target({
                "campaign": c["name"],
                "ad_group": group.get("name", m.get("adGroupName")),
                "search_term": text or "(low-volume searches Apple doesn't name)",
                "source": {"AUTO": "search match", "TARGETED": "keyword"}.get(source, source),
                "matched_keyword": m.get("keyword") if source == "TARGETED" else None,
                "already_a_keyword": text.lower().strip() in existing if text else None,
                "target_cpa": target(target_cpa, group, c),
                **stats(r.get("total")),
                "campaign_id": c["id"],
                "ad_group_id": m.get("adGroupId"),
            }))
    return sorted(rows, key=lambda r: -r["spend"])


@apple_ads.deploy(title="Keyword rankings", next=[Next(update_keyword, label="Change bid / pause")])
def keyword_rankings(level: Literal["Ad group", "Campaign"] = "Ad group", campaign_id: int | None = None,
                     start: date | None = None, end: date | None = None, top: int = 3, min_taps: int = 10,
                     target_cpa: float | None = None) -> list[dict]:
    """The best and worst active keywords in each ad group (or campaign), by CPA.

    A keyword is judged once it has Min taps taps, or has spent the target CPA (so one spending money with no
    installs still shows). Best is the lowest CPA among keywords with installs. Worst puts keywords with spend and
    no installs first, then the highest CPA. Dates default to the last 30 days.
    """
    if top < 1:
        raise ValueError("Top must be at least 1.")
    by_ad_group = level == "Ad group"
    groups: dict[tuple, list[dict]] = {}
    for r in _keyword_rows(campaign_id, None, start, end, False, target_cpa):
        if r["taps"] >= min_taps or (r["target_cpa"] and r["spend"] >= r["target_cpa"]):
            groups.setdefault((r["campaign"], r["ad_group"] if by_ad_group else None), []).append(r)

    out = []
    for (_, _), items in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        best = sorted([i for i in items if i["installs"]], key=lambda i: (i["cpa"], -i["installs"]))[:top]
        chosen = {i["keyword_id"] for i in best}
        worst = sorted([i for i in items if i["keyword_id"] not in chosen],
                       key=lambda i: (-(i["cpa"] or math.inf), -i["spend"]))[:top]
        group_spend = sum(i["spend"] for i in items)
        for label, picked in (("Best", best), ("Worst", worst)):
            for n, i in enumerate(picked, 1):
                out.append({
                    "campaign": i["campaign"],
                    "ad_group": i["ad_group"],
                    "rank": f"{label} {n}",
                    **{k: i[k] for k in ("keyword", "match_type", "bid", "spend")},
                    "share_of_spend": round(i["spend"] / group_spend * 100, 1) if group_spend else None,
                    **{k: i[k] for k in ("taps", "installs", "ttr", "cvr", "cpt", "cpa", "target_cpa", "cpa_vs_target")},
                    "keywords_judged": len(items),
                    **{k: i[k] for k in ("campaign_id", "ad_group_id", "keyword_id")},
                })
    if not out:
        raise ValueError(f"No active keyword has {min_taps}+ taps in that window. Lower Min taps or widen the dates.")
    return out


@apple_ads.deploy(title="Ad groups", next=[keywords, search_terms, Next(update_ad_group, label="Change ad group"),
                                           Next(copy_ad_group, label="Copy onto another page")])
def ad_groups(campaign_id: int | None = None, start: date | None = None, end: date | None = None,
              include_paused: bool = False, target_cpa: float | None = None) -> list[dict]:
    """One row per ad group: status, Search Match, default bid, CPA goal, and spend, installs and CPA against target.

    Leave Campaign id empty for every enabled campaign. Dates default to the last 30 days.
    """
    start, end = window(start, end)
    api = AppleAds()
    rows = []
    for c in _pick_campaigns(api, campaign_id, include_paused):
        report = {r["metadata"]["adGroupId"]: r.get("total")
                  for r in api.report(f"/reports/campaigns/{c['id']}/adgroups", start, end)}
        for g in api.ad_groups(c["id"]):
            if not include_paused and g.get("status") != "ENABLED":
                continue
            rows.append(vs_target({
                "campaign": c["name"],
                "ad_group": g["name"],
                "ad_group_status": g.get("status"),
                "search_match": bool(g.get("automatedKeywordsOptIn")),
                "default_bid": money(g.get("defaultBidAmount")),
                "cpa_goal": money(g.get("cpaGoal")),
                "target_cpa": target(target_cpa, g, c),
                **stats(report.get(g["id"])),
                "campaign_id": c["id"],
                "ad_group_id": g["id"],
            }))
    return sorted(rows, key=lambda r: -r["spend"])


@apple_ads.deploy(title="Campaigns", next=[ad_groups, keywords, keyword_rankings, search_terms,
                                           Next(update_campaign, label="Change campaign"),
                                           Next(copy_negatives, label="Copy negatives", from_campaign_id="campaign_id")])
def campaigns(start: date | None = None, end: date | None = None, include_paused: bool = False,
              target_cpa: float | None = None) -> list[dict]:
    """One row per campaign: status, daily budget, and spend, impressions, taps, installs, TTR, CVR, CPT and CPA.

    Start here: each row links to its ad groups, keywords, rankings and search terms. Dates default to the last
    30 days.
    """
    start, end = window(start, end)
    api = AppleAds()
    report = {r["metadata"]["campaignId"]: r.get("total") for r in api.report("/reports/campaigns", start, end)}
    rows = [vs_target({
        "campaign": c["name"],
        "campaign_status": c.get("status"),
        "serving_status": c.get("servingStatus"),
        "daily_budget": money(c.get("dailyBudgetAmount")),
        "target_cpa": target(target_cpa, c),
        **stats(report.get(c["id"])),
        "campaign_id": c["id"],
    }) for c in _pick_campaigns(api, None, include_paused)]
    return sorted(rows, key=lambda r: -r["spend"])


@apple_ads.deploy(title="Creatives", next=[Next(copy_ad_group, label="Copy ad group onto another page")])
def creatives(product_page_ids: list[str] = [], start: date | None = None, end: date | None = None,
              target_cpa: float | None = None) -> list[dict]:
    """Every ad, paused campaigns too, with the product page it runs and its results.

    Compare custom product pages on the same keywords. Product page ids keeps only ads running those pages. Dates
    default to the last 180 days.
    """
    start, end = window(start, end, days=180)
    api = AppleAds()
    by_id = {c["id"]: c for c in api.campaigns()}
    rows = [vs_target({**r, "target_cpa": target(target_cpa, by_id.get(r["campaign_id"], {}))})
            for r in ads_with_pages(start, end, product_page_ids, api)]
    if product_page_ids and not rows:
        raise ValueError("No ad runs those product page ids. Leave Product page ids empty to see every ad.")
    for r in rows:  # the copy form's own Product page id is the page to copy onto, so don't prefill it
        r["running_page_id"] = r.pop("product_page_id")
    return rows


# ── impression share: Apple's custom report ──────────────────────────────────

SHARE_PERIODS = {"Last week": ("LAST_WEEK", 7), "Last 2 weeks": ("LAST_2_WEEKS", 14),
                 "Last 4 weeks": ("LAST_4_WEEKS", 28)}
RANKS = {"ONE": "1", "TWO": "2", "THREE": "3", "FOUR": "4", "FIVE": "5", "GREATER_THAN_FIVE": "6+"}


def _share_pct(value) -> float | None:
    """Apple's share bounds as a percentage (they come as 0-1 or 0-100)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return round(v * 100 if v <= 1 else v, 1) if math.isfinite(v) else None


def _csv_rows(raw: bytes) -> list[dict]:
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in row.items()} for row in reader]


def _share_report(api: AppleAds, start: date, end: date, preset: str | None, country: str,
                  wait_seconds: int) -> list[dict]:
    """Apple's impression share report rows: reuses today's report for the same inputs, else creates one (Apple
    allows only a few a day) and waits for it."""
    span = preset or f"{start:%Y%m%d}-{end:%Y%m%d}"
    name = f"impression-share {country} {span} {end:%Y%m%d}"[:50]  # Apple caps names at 50 characters
    existing = api.get("/custom-reports", limit=50, offset=0, field="creationTime",
                       sortOrder="DESCENDING").get("data") or []
    report = next((r for r in existing if r.get("name") == name and r.get("state") != "FAILED"), None)
    if report is None:
        body = {"name": name, "granularity": "WEEKLY" if preset else "DAILY",
                "selector": {"conditions": [{"field": "countryOrRegion", "operator": "IN", "values": [country]}]}}
        if preset:  # weekly reports only take Apple's preset ranges
            body["dateRange"] = preset
        else:
            body.update({"dateRange": "CUSTOM", "startTime": start.isoformat(), "endTime": end.isoformat()})
        report = api.post("/custom-reports", body).get("data") or {}
    deadline = time.monotonic() + wait_seconds
    while report.get("state") != "COMPLETED":
        if report.get("state") == "FAILED":
            raise RuntimeError("Apple couldn't build the impression share report. Try other dates.")
        if time.monotonic() > deadline:
            raise RuntimeError("Apple is still building the impression share report. Run this again in a few "
                               "minutes with the same inputs: it picks up the same report.")
        time.sleep(15)
        report = api.get(f"/custom-reports/{report['id']}").get("data") or {}
    if not report.get("downloadUri"):
        raise RuntimeError("Apple finished the report but gave no download link.")
    return _csv_rows(api.download(report["downloadUri"]))


@apple_ads.deploy(title="Impression share", timeout=600)
def impression_share(period: Literal["Last 2 weeks", "Last 4 weeks", "Last week", "Custom dates (daily)"] = "Last 2 weeks",
                     start: date | None = None, end: date | None = None, country: str = "US",
                     min_popularity: int = 0, limit: int = 100) -> list[dict]:
    """Your impression share, rank and search popularity per search term, with a rough spend at full share.

    Next to what you got on each term across enabled campaigns. Custom dates cover up to 31 days. Apple allows a
    few of these reports a day, so the same inputs reuse today's.
    """
    if period in SHARE_PERIODS:
        preset, days = SHARE_PERIODS[period]
        start, end = window(None, None, days=days)
    else:
        preset = None
        start, end = window(start, end, days=14)
        if (end - start).days > 30:
            raise ValueError("Custom dates can cover 31 days at most. For longer, pick Last 4 weeks.")
    country = country.strip().upper()
    api = AppleAds()
    raw = _share_report(api, start, end, preset, country, wait_seconds=480)

    def col(row: dict, *names: str) -> str:
        return next((row[n.lower()] for n in names if row.get(n.lower()) not in (None, "")), "")

    terms: dict[str, dict] = {}
    for row in raw:
        term = col(row, "searchTerm", "search_term")
        if term:
            terms.setdefault(term.lower(), {"term": term, "periods": []})["periods"].append({
                "date": col(row, "date", "startTime", "week"),
                "low": _share_pct(col(row, "lowImpressionShare", "low_impression_share")),
                "high": _share_pct(col(row, "highImpressionShare", "high_impression_share")),
                "rank": col(row, "rank"),
                "popularity": col(row, "searchPopularity", "search_popularity"),
            })

    ours: dict[str, dict] = {}  # what we got on each named search term in the same dates
    for c in _pick_campaigns(api, None, include_paused=False):
        for r in api.report(f"/reports/campaigns/{c['id']}/searchterms", start, end, order_by="impressions"):
            text = (r.get("metadata", {}).get("searchTermText") or "").lower().strip()
            if not text:
                continue
            s = stats(r.get("total"))
            o = ours.setdefault(text, {"spend": 0.0, "impressions": 0, "taps": 0, "installs": 0, "campaigns": set()})
            for k in ("spend", "impressions", "taps", "installs"):
                o[k] += s[k]
            o["campaigns"].add(c["name"])

    days = (end - start).days + 1
    rows = []
    for key, t in terms.items():
        periods = sorted(t["periods"], key=lambda p: p["date"])
        lows = [p["low"] for p in periods if p["low"] is not None]
        highs = [p["high"] for p in periods if p["high"] is not None]
        pops = [int(p["popularity"]) for p in periods if str(p["popularity"]).isdigit()]
        popularity = max(pops) if pops else None
        if min_popularity and (popularity or 0) < min_popularity:
            continue
        low = round(sum(lows) / len(lows), 1) if lows else None
        high = round(sum(highs) / len(highs), 1) if highs else None
        o = ours.get(key, {})
        imps, taps, spend = o.get("impressions", 0), o.get("taps", 0), o.get("spend", 0.0)
        mid = (low + high) / 2 if low is not None and high is not None else None
        est_imps = round(imps / (mid / 100) / days) if mid and imps else None
        est_spend = round(est_imps * (taps / imps) * (spend / taps), 2) if est_imps and taps else None
        rank = periods[-1]["rank"]
        rows.append({
            "search_term": t["term"],
            "popularity": popularity,
            "impression_share": f"{low:.0f}-{high:.0f}%" if low is not None and high is not None else None,
            "share_low": low,
            "share_high": high,
            "rank": RANKS.get(rank, rank or None),
            "our_impressions_per_day": round(imps / days, 1),
            "our_taps": taps,
            "our_installs": o.get("installs", 0),
            "our_spend": round(spend, 2),
            "our_cpa": round(spend / o["installs"], 2) if o.get("installs") else None,
            "est_impressions_per_day_at_100pct": est_imps,
            "est_spend_per_day_at_100pct": est_spend,
            "campaigns": ", ".join(sorted(o.get("campaigns", []))) or None,
        })
    if not rows:
        raise ValueError(f"Apple's report had no search terms for {country} between {start} and {end}"
                         + (f" with popularity {min_popularity}+." if min_popularity else "."))
    rows.sort(key=lambda r: (-(r["popularity"] or 0), -(r["our_spend"] or 0), -(r["share_high"] or 0)))
    return rows[:limit] if limit else rows
