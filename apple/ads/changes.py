"""Apple Ads changes: bids, statuses, new keywords, negatives, ad group and campaign settings.

Each one looks up the current values first and has Dry run ticked by default, so a run shows exactly what would
change and changes nothing. Untick Dry run (dry_run=False) to apply. The review tables in review.py offer these as
row buttons, with the ids filled in.
"""
from typing import Literal

from apple.ads.apple_ads_api import AppleAds
from apple.ads.group import apple_ads
from apple.ads.metrics import amount, change, currency, money, split_keywords

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


@apple_ads.deploy(title="Change ad group")
def update_ad_group(campaign_id: int, ad_group_id: int, default_bid: float | None = None,
                    cpa_goal: float | None = None, status: Status = "No change", dry_run: bool = True) -> dict:
    """Change an ad group's default bid or CPA goal, or pause or enable it. Untick Dry run to apply."""
    api = AppleAds()
    group = api.ad_group(campaign_id, ad_group_id)
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
def update_campaign(campaign_id: int, daily_budget: float | None = None, status: Status = "No change",
                    dry_run: bool = True) -> dict:
    """Change a campaign's daily budget, or pause or enable it. Untick Dry run to apply."""
    api = AppleAds()
    campaign = api.campaign(campaign_id)
    new_status = {"Enabled": "ENABLED", "Paused": "PAUSED"}.get(status)
    body: dict = {}
    if daily_budget is not None:
        if daily_budget <= 0:
            raise ValueError("Daily budget must be more than 0.")
        body["dailyBudgetAmount"] = amount(daily_budget, currency(campaign.get("dailyBudgetAmount")))
    if new_status and new_status != campaign.get("status"):
        body["status"] = new_status
    if not body:
        raise ValueError("Nothing to change: set a Daily budget or Status.")
    if not dry_run:
        api.put(f"/campaigns/{campaign_id}", {"campaign": body})
    return {
        "result": PREVIEW if dry_run else APPLIED,
        "campaign": campaign.get("name"),
        "daily_budget": change(money(campaign.get("dailyBudgetAmount")), daily_budget),
        "status": change(campaign.get("status"), new_status),
        "campaign_id": campaign_id,
    }
