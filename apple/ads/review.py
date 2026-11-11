"""Apple Ads review: campaigns, ad groups, keywords, search terms and keyword rankings, read live from the API.

Each callable returns flat rows (current settings plus metrics over a date window, the last 30 days by default), so
they read well as tables in the web app and as data for an assistant to analyze. Every row keeps its ids, and the
row buttons hand them to the changes in changes.py. A row field with the same name as an input fills it (current
bid, default bid, budget), so statuses are named keyword_status, ad_group_status and campaign_status here: the
change forms' Status starts at "No change".

Target CPA: type one in the form, or each row uses its ad group's CPA goal, else its campaign's. Without one,
cpa_vs_target stays empty and keyword rankings judge keywords on taps alone.
"""
import math
from datetime import date
from typing import Literal

from callables import Next

from apple.ads.apple_ads_api import AppleAds
from apple.ads.changes import add_keywords, add_negatives, update_ad_group, update_campaign, update_keyword
from apple.ads.group import apple_ads
from apple.ads.metrics import money, stats, target, vs_target, window


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


@apple_ads.deploy(title="Ad groups", next=[keywords, search_terms, Next(update_ad_group, label="Change ad group")])
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
                                           Next(update_campaign, label="Change campaign")])
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
