"""Turning Apple Ads values and report rows into flat numbers. No API calls and no callables: plain functions.

Metrics on every row: spend, impressions, taps, installs (Apple's totalInstalls: tap- plus view-through),
ttr = taps / impressions %, cvr = installs / taps %, cpt = spend / taps, cpa = spend / installs, and
cpa_vs_target = cpa / target CPA (under 1 is better than target).
"""
from datetime import date, timedelta


def money(value) -> float | None:
    """A float from Apple's {"amount": "1.50", "currency": "USD"} objects, or a plain number."""
    if isinstance(value, dict):
        value = value.get("amount")
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def currency(*values, default: str = "USD") -> str:
    """The currency of the first Apple money object that has one."""
    for value in values:
        if isinstance(value, dict) and value.get("currency"):
            return value["currency"]
    return default


def amount(value: float, cur: str) -> dict:
    """A number as an Apple money object, for writes."""
    return {"amount": f"{value:.2f}", "currency": cur}


def window(start: date | None, end: date | None, days: int = 30) -> tuple[date, date]:
    """The dates to report on: by default the last 30 days, ending yesterday (today's numbers are still coming in)."""
    end = end or date.today() - timedelta(days=1)
    start = start or end - timedelta(days=days - 1)
    if start > end:
        raise ValueError(f"Start ({start}) is after End ({end}).")
    return start, end


def stats(total: dict | None) -> dict:
    """Spend, volume and rates from a report row's totals."""
    total = total or {}
    spend = money(total.get("localSpend")) or 0.0
    impressions = int(total.get("impressions") or 0)
    taps = int(total.get("taps") or 0)
    installs = int(total.get("totalInstalls") or total.get("tapInstalls") or 0)
    return {
        "spend": round(spend, 2),
        "impressions": impressions,
        "taps": taps,
        "installs": installs,
        "ttr": round(taps / impressions * 100, 2) if impressions else None,
        "cvr": round(installs / taps * 100, 2) if taps else None,
        "cpt": round(spend / taps, 2) if taps else None,
        "cpa": round(spend / installs, 2) if installs else None,
    }


def target(override: float | None, *objects: dict) -> float | None:
    """The CPA to judge against: the one typed in the form, else the ad group's CPA goal, else the campaign's."""
    if override:
        return override
    for obj in objects:
        found = money(obj.get("cpaGoal")) or money(obj.get("targetCpa"))
        if found:
            return found
    return None


def vs_target(row: dict) -> dict:
    """Adds cpa_vs_target to a row that has cpa and target_cpa."""
    row["cpa_vs_target"] = round(row["cpa"] / row["target_cpa"], 2) if row.get("cpa") and row.get("target_cpa") else None
    return row


def split_keywords(text: str) -> list[str]:
    """One keyword per line or comma, de-duplicated (ignoring case), extra spaces removed."""
    seen, out = set(), []
    for part in text.replace("\n", ",").split(","):
        word = " ".join(part.split())
        if word and word.lower() not in seen:
            seen.add(word.lower())
            out.append(word)
    if not out:
        raise ValueError("Keywords is empty: put one keyword per line, or separate them with commas.")
    return out


def change(before, after) -> str:
    """How a value changes, for previews: "1.5 → 2.0", or "no change"."""
    return "no change" if after is None or after == before else f"{before} → {after}"
