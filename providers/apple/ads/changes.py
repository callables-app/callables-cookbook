"""Apple Ads changes: bids, statuses, new keywords, negatives, ad group and campaign settings, copying negatives and
ad groups, and new campaigns.

Each one looks up the current values first and has Dry run ticked by default, so a run shows exactly what would
change and changes nothing. Untick Dry run (dry_run=False) to apply. The review tables in review.py offer these as
row buttons, with the ids filled in.
"""
from datetime import datetime, timedelta, timezone
from typing import Literal

from providers.apple.ads.apple_ads_api import AppleAds
from providers.apple.ads.group import apple_ads
from providers.apple.ads.metrics import amount, change, currency, money, split_keywords

PREVIEW = "Preview only: nothing changed. Untick Dry run and run again to apply."
APPLIED = "Applied in Apple Ads."

KeywordStatus = Literal["No change", "Active", "Paused"]
Status = Literal["No change", "Enabled", "Paused"]
Match = Literal["Exact", "Broad"]


@apple_ads.deploy(title="Change keyword")
def update_keyword(campaign_id: int, ad_group_id: int, keyword_id: int, bid: float | None = None,
                   status: KeywordStatus = "No change", dry_run: bool = True) -> dict:
    """Change one keyword's bid, or pause or re-activate it. Untick Dry run to apply."""
    api = AppleAds()
    kw = api.keyword(campaign_id, ad_group_id, keyword_id)
    old_bid = money(kw.get("bidAmount"))
    new_status = {"Active": "ACTIVE", "Paused": "PAUSED"}.get(status)
    body: dict = {"id": keyword_id}
    if bid is not None:
        if bid <= 0:
            raise ValueError("Bid must be more than 0.")
        body["bidAmount"] = amount(bid, currency(kw.get("bidAmount")))
    if new_status and new_status != kw.get("status"):
        body["status"] = new_status
    if len(body) == 1:
        raise ValueError("Nothing to change: set a new Bid or Status.")
    if not dry_run:
        api.put(f"/campaigns/{campaign_id}/adgroups/{ad_group_id}/targetingkeywords/bulk", [body])
    return {
        "result": PREVIEW if dry_run else APPLIED,
        "keyword": kw.get("text"),
        "match_type": (kw.get("matchType") or "").lower(),
        "bid": change(old_bid, bid),
        "status": change(kw.get("status"), new_status),
        "warning": f"The new bid is more than double the current {old_bid:.2f}." if bid and old_bid and bid > old_bid * 2
        else None,
        "campaign_id": campaign_id,
        "ad_group_id": ad_group_id,
        "keyword_id": keyword_id,
    }


@apple_ads.deploy(title="Add keywords")
def add_keywords(campaign_id: int, ad_group_id: int, keywords: str, match_type: Match = "Exact",
                 bid: float | None = None, dry_run: bool = True) -> list[dict]:
    """Add keywords to bid on in an ad group, one per line or comma. Bid defaults to the ad group's default bid.

    Keywords already in the ad group with that match type are skipped. Untick Dry run to apply.
    """
    api = AppleAds()
    group = api.ad_group(campaign_id, ad_group_id)
    cur = currency(group.get("defaultBidAmount"))
    use_bid = bid if bid is not None else money(group.get("defaultBidAmount"))
    if not use_bid or use_bid <= 0:
        raise ValueError("Set a Bid: the ad group has no default bid to use.")
    existing = {((k.get("text") or "").lower(), k.get("matchType")) for k in api.keywords(campaign_id, ad_group_id)}

    mt = match_type.upper()
    rows, new = [], []
    for word in split_keywords(keywords):
        skip = (word.lower(), mt) in existing
        if not skip:
            new.append({"text": word, "matchType": mt, "bidAmount": amount(use_bid, cur), "status": "ACTIVE"})
        rows.append({"keyword": word, "match_type": match_type.lower(), "bid": use_bid, "ad_group": group.get("name"),
                     "result": "Skipped: already in this ad group" if skip else "Would be added" if dry_run else "Added"})
    if new and not dry_run:
        api.post(f"/campaigns/{campaign_id}/adgroups/{ad_group_id}/targetingkeywords/bulk", new)
    if new and dry_run:
        rows.append({"keyword": "", "result": PREVIEW})
    return rows


@apple_ads.deploy(title="Add negative keywords")
def add_negatives(campaign_id: int, keywords: str, ad_group_id: int | None = None, match_type: Match = "Exact",
                  dry_run: bool = True) -> list[dict]:
    """Stop your ads showing for these searches, one per line or comma.

    With an Ad group id they're negatives for that ad group only; leave it empty for the whole campaign.
    Untick Dry run to apply.
    """
    api = AppleAds()
    if ad_group_id:
        scope = f"ad group {api.ad_group(campaign_id, ad_group_id).get('name')}"
    else:
        scope = f"campaign {api.campaign(campaign_id).get('name')}"
    existing = {((k.get("text") or "").lower(), k.get("matchType")) for k in api.negatives(campaign_id, ad_group_id)}

    mt = match_type.upper()
    rows, new = [], []
    for word in split_keywords(keywords):
        skip = (word.lower(), mt) in existing
        if not skip:
            new.append({"text": word, "matchType": mt})
        rows.append({"negative": word, "match_type": match_type.lower(), "scope": scope,
                     "result": "Skipped: already a negative here" if skip else "Would be added" if dry_run else "Added"})
    if new and not dry_run:
        api.post(f"{api.negatives_path(campaign_id, ad_group_id)}/bulk", new)
    if new and dry_run:
        rows.append({"negative": "", "result": PREVIEW})
    return rows


def _convert_to_exact(api: AppleAds, campaign_id: int, ad_group_id: int, dry_run: bool) -> dict:
    kws = api.keywords(campaign_id, ad_group_id)
    exact = {(k.get("text") or "").lower() for k in kws if k.get("matchType") == "EXACT" and k.get("status") == "ACTIVE"}
    broad = [k for k in kws if k.get("matchType") == "BROAD" and k.get("status") == "ACTIVE"]
    new = [{"text": k["text"], "matchType": "EXACT", "bidAmount": k["bidAmount"], "status": "ACTIVE"}
           for k in broad if (k.get("text") or "").lower() not in exact]
    if not dry_run:
        path = f"/campaigns/{campaign_id}/adgroups/{ad_group_id}/targetingkeywords/bulk"
        if new:
            api.post(path, new)
        if broad:
            api.put(path, [{"id": k["id"], "status": "PAUSED"} for k in broad])
    return {
        "exact_added": ", ".join(f"{k['text']} ({money(k['bidAmount']):.2f})" for k in new) or "none",
        "broad_paused": ", ".join(k["text"] for k in broad) or "none",
        "already_exact": ", ".join(sorted({(k.get("text") or "").lower() for k in broad} & exact)) or "none",
    }


@apple_ads.deploy(title="Change ad group")
def update_ad_group(campaign_id: int, ad_group_id: int, default_bid: float | None = None,
                    cpa_goal: float | None = None, status: Status = "No change", convert_broad_to_exact: bool = False,
                    dry_run: bool = True) -> dict:
    """Change an ad group's default bid or CPA goal, or pause or enable it. Untick Dry run to apply.

    Convert broad to exact gives every active broad keyword an exact copy at the same bid, then pauses the broad
    one (the other settings are ignored when it's ticked).
    """
    api = AppleAds()
    group = api.ad_group(campaign_id, ad_group_id)
    if convert_broad_to_exact:
        return {"result": PREVIEW if dry_run else APPLIED, "ad_group": group.get("name"),
                **_convert_to_exact(api, campaign_id, ad_group_id, dry_run),
                "campaign_id": campaign_id, "ad_group_id": ad_group_id}
    cur = currency(group.get("defaultBidAmount"))
    new_status = {"Enabled": "ENABLED", "Paused": "PAUSED"}.get(status)
    body: dict = {}
    if default_bid is not None:
        if default_bid <= 0:
            raise ValueError("Default bid must be more than 0.")
        body["defaultBidAmount"] = amount(default_bid, cur)
    if cpa_goal is not None:
        body["cpaGoal"] = amount(cpa_goal, cur)
    if new_status and new_status != group.get("status"):
        body["status"] = new_status
    if not body:
        raise ValueError("Nothing to change: set a Default bid, CPA goal or Status.")
    if not dry_run:
        api.put(f"/campaigns/{campaign_id}/adgroups/{ad_group_id}", body)
    return {
        "result": PREVIEW if dry_run else APPLIED,
        "ad_group": group.get("name"),
        "default_bid": change(money(group.get("defaultBidAmount")), default_bid),
        "cpa_goal": change(money(group.get("cpaGoal")), cpa_goal),
        "status": change(group.get("status"), new_status),
        "campaign_id": campaign_id,
        "ad_group_id": ad_group_id,
    }


@apple_ads.deploy(title="Change campaign")
def update_campaign(campaign_id: int, name: str | None = None, daily_budget: float | None = None,
                    status: Status = "No change", dry_run: bool = True) -> dict:
    """Rename a campaign, change its daily budget, or pause or enable it. Untick Dry run to apply."""
    api = AppleAds()
    campaign = api.campaign(campaign_id)
    new_status = {"Enabled": "ENABLED", "Paused": "PAUSED"}.get(status)
    body: dict = {}
    name = (name or "").strip() or None
    if name and name != campaign.get("name"):
        if any(c.get("name") == name for c in api.campaigns()):
            raise ValueError(f"A campaign called {name!r} already exists.")
        body["name"] = name
    if daily_budget is not None:
        if daily_budget <= 0:
            raise ValueError("Daily budget must be more than 0.")
        body["dailyBudgetAmount"] = amount(daily_budget, currency(campaign.get("dailyBudgetAmount")))
    if new_status and new_status != campaign.get("status"):
        body["status"] = new_status
    if not body:
        raise ValueError("Nothing to change: set a Name, Daily budget or Status.")
    if not dry_run:
        api.put(f"/campaigns/{campaign_id}", {"campaign": body})
    return {
        "result": PREVIEW if dry_run else APPLIED,
        "campaign": campaign.get("name"),
        "name": change(campaign.get("name"), body.get("name")),
        "daily_budget": change(money(campaign.get("dailyBudgetAmount")), daily_budget),
        "status": change(campaign.get("status"), new_status),
        "campaign_id": campaign_id,
    }


@apple_ads.deploy(title="Copy negatives")
def copy_negatives(from_campaign_id: int, to_campaign_id: int, keywords_too: bool = False,
                   dry_run: bool = True) -> list[dict]:
    """Copy a campaign's negatives (campaign and ad group level) to another campaign, as campaign negatives.

    Keywords too also negates the source's active keywords (exact), so two campaigns stop competing for the same
    searches. Untick Dry run to apply.
    """
    api = AppleAds()
    src, dst = api.campaign(from_campaign_id), api.campaign(to_campaign_id)
    have = {((k.get("text") or "").lower(), k.get("matchType")) for k in api.negatives(to_campaign_id)}
    found = [(n["text"], n["matchType"], "campaign negative") for n in api.negatives(from_campaign_id)]
    for g in api.ad_groups(from_campaign_id):
        found += [(n["text"], n["matchType"], f"negative in {g.get('name')}")
                  for n in api.negatives(from_campaign_id, g["id"])]
        if keywords_too and g.get("status") == "ENABLED":
            found += [(k["text"], "EXACT", f"keyword in {g.get('name')}")
                      for k in api.keywords(from_campaign_id, g["id"]) if k.get("status") == "ACTIVE"]
    rows, new, seen = [], [], set()
    for text, mt, source in found:
        key = (text.lower(), mt)
        if key in seen:
            continue
        seen.add(key)
        if key in have:
            result = "Skipped: already a negative here"
        else:
            new.append({"text": text, "matchType": mt})
            result = "Would be added" if dry_run else "Added"
        rows.append({"negative": text, "match_type": mt.lower(), "from": source, "to": dst.get("name"),
                     "result": result})
    if new and not dry_run:
        api.post(f"{api.negatives_path(to_campaign_id)}/bulk", new)
    rows.sort(key=lambda r: (r["result"].startswith("Skipped"), r["from"], r["negative"]))
    if dry_run and new:
        rows.append({"negative": "", "from": src.get("name"), "result": f"{len(new)} new. {PREVIEW}"})
    return rows


# Targeting copied to a new ad group (everything but the device list, which iPhone only can override)
COPY_DIMENSIONS = ("age", "gender", "deviceClass", "daypart", "adminArea", "locality", "appDownloaders")


def _start_soon() -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%S.000")


@apple_ads.deploy(title="Copy ad group onto another page")
def copy_ad_group(campaign_id: int, ad_group_id: int, product_page_id: str, name: str | None = None,
                  iphone_only: bool = True, search_match_only: bool = False, default_bid: float | None = None,
                  dry_run: bool = True) -> dict:
    """A new ad group with the source's keywords, bids, negatives and targeting, running another custom product page.

    For testing a creative on the same keywords. Search match only copies the targeting but no keywords, with
    Search Match on. Default bid overrides the source's. Untick Dry run to apply.
    """
    api = AppleAds()
    campaign = api.campaign(campaign_id)
    src = api.ad_group(campaign_id, ad_group_id)
    adam = campaign.get("adamId")
    page = api.product_page(adam, product_page_id)
    new_name = (name or "").strip() or f"{src.get('name')} - {page.get('name')}"
    if any(g.get("name") == new_name for g in api.ad_groups(campaign_id)):
        raise ValueError(f"The campaign already has an ad group called {new_name!r}.")
    keywords = [] if search_match_only else [k for k in api.keywords(campaign_id, ad_group_id)
                                             if k.get("status") == "ACTIVE"]
    bid = amount(default_bid, currency(src.get("defaultBidAmount"))) if default_bid else src.get("defaultBidAmount")
    negatives = [n for n in api.negatives(campaign_id, ad_group_id) if n.get("status", "ACTIVE") == "ACTIVE"]
    dims = {k: v for k, v in (src.get("targetingDimensions") or {}).items() if k in COPY_DIMENSIONS and v}
    if iphone_only:
        dims["deviceClass"] = {"included": ["IPHONE"]}
    summary = {
        "campaign": campaign.get("name"),
        "source_ad_group": src.get("name"),
        "new_ad_group": new_name,
        "devices": ", ".join((dims.get("deviceClass") or {}).get("included") or ["IPHONE", "IPAD"]),
        "product_page": page.get("name"),
        "default_bid": money(bid),
        "search_match": search_match_only,
        "keywords_copied": len(keywords),
        "keyword_list": ", ".join(f"{k.get('text')} ({(k.get('matchType') or '').lower()} "
                                  f"{money(k.get('bidAmount')):.2f})" for k in keywords),
        "negatives_copied": len(negatives),
    }
    if dry_run:
        return {"result": PREVIEW, **summary}
    body = {"name": new_name, "pricingModel": src.get("pricingModel") or "CPC", "startTime": _start_soon(),
            "defaultBidAmount": bid, "automatedKeywordsOptIn": search_match_only, "targetingDimensions": dims,
            "status": "ENABLED"}
    if src.get("cpaGoal"):
        body["cpaGoal"] = src["cpaGoal"]
    gid = api.post(f"/campaigns/{campaign_id}/adgroups", body).get("data", {})["id"]
    if keywords:
        api.post(f"/campaigns/{campaign_id}/adgroups/{gid}/targetingkeywords/bulk",
                 [{"text": k["text"], "matchType": k["matchType"], "bidAmount": k["bidAmount"], "status": "ACTIVE"}
                  for k in keywords])
    if negatives:
        api.post(f"{api.negatives_path(campaign_id, gid)}/bulk",
                 [{"text": n["text"], "matchType": n["matchType"]} for n in negatives])
    creative = api.page_creative(adam, product_page_id, page.get("name"))
    api.post(f"/campaigns/{campaign_id}/adgroups/{gid}/ads",
             {"creativeId": creative["id"], "name": page.get("name"), "status": "ENABLED"})
    return {"result": APPLIED, "new_ad_group_id": gid, **summary}


# Campaign settings copied from the template: which app, where it runs, and how it's billed
CAMPAIGN_COPY = ("adamId", "supplySources", "adChannelType", "billingEvent", "paymentModel")


@apple_ads.deploy(title="New campaign")
def new_campaign(name: str, product_page_id: str, keywords: str, bid: float, daily_budget: float,
                 target_cpa: float | None = None, country: str = "US", iphone_only: bool = True,
                 template_campaign_id: int | None = None, dry_run: bool = True) -> dict:
    """A new campaign with one ad group of exact keywords at one bid on one custom product page, no Search Match.

    Keywords go one per line or comma; end one with (broad) for broad match. The app, placement and billing are
    copied from Template campaign id, or from your newest campaign when it's empty. Untick Dry run to apply.
    """
    if daily_budget <= 0 or bid <= 0:
        raise ValueError("Daily budget and Bid must be more than 0.")
    api = AppleAds()
    campaigns = api.campaigns()
    if any(c.get("name") == name for c in campaigns):
        raise ValueError(f"A campaign called {name!r} already exists.")
    if template_campaign_id:
        template = api.campaign(template_campaign_id)
    else:
        api.app_id(campaigns)  # several apps: the template has to be picked
        template = max((c for c in campaigns if c.get("adamId")), key=lambda c: c.get("creationTime") or "")
    adam = template.get("adamId")
    page = api.product_page(adam, product_page_id)
    words, broad = [], set()
    for w in split_keywords(keywords):
        if w.lower().endswith("(broad)"):
            w = w[: -len("(broad)")].strip()
            broad.add(w)
        words.append(w)
    cur = currency(template.get("dailyBudgetAmount"))
    country = country.strip().upper()
    devices = ["IPHONE"] if iphone_only else ["IPHONE", "IPAD"]
    summary = {
        "campaign": name,
        "daily_budget": daily_budget,
        "target_cpa": target_cpa,
        "country": country,
        "devices": ", ".join(devices),
        "ad_group": page.get("name"),
        "product_page": page.get("name"),
        "keywords": ", ".join(f"{w} ({'broad' if w in broad else 'exact'} {bid:.2f})" for w in words),
        "copied_settings_from": template.get("name"),
    }
    if dry_run:
        return {"result": PREVIEW, **summary}
    body = {k: template[k] for k in CAMPAIGN_COPY if template.get(k) is not None}
    body.update({"orgId": api.org_id, "name": name, "dailyBudgetAmount": amount(daily_budget, cur),
                 "countriesOrRegions": [country], "status": "ENABLED"})
    if target_cpa:
        body["targetCpa"] = amount(target_cpa, cur)
    cid = api.post("/campaigns", body).get("data", {})["id"]
    gid = api.post(f"/campaigns/{cid}/adgroups", {
        "name": page.get("name"), "pricingModel": "CPC", "startTime": _start_soon(),
        "defaultBidAmount": amount(bid, cur), "automatedKeywordsOptIn": False,
        "targetingDimensions": {"deviceClass": {"included": devices}}, "status": "ENABLED",
    }).get("data", {})["id"]
    api.post(f"/campaigns/{cid}/adgroups/{gid}/targetingkeywords/bulk",
             [{"text": w, "matchType": "BROAD" if w in broad else "EXACT", "bidAmount": amount(bid, cur),
               "status": "ACTIVE"} for w in words])
    creative = api.page_creative(adam, product_page_id, page.get("name"))
    api.post(f"/campaigns/{cid}/adgroups/{gid}/ads",
             {"creativeId": creative["id"], "name": page.get("name"), "status": "ENABLED"})
    return {"result": APPLIED, "campaign_id": cid, "ad_group_id": gid, **summary}
