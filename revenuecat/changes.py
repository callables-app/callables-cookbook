"""RevenueCat changes: give a customer promotional access to an entitlement, or take it away.

Both have Dry run ticked by default: the run shows the customer's current access and what would change, and changes
nothing. Untick Dry run (dry_run=False) to apply. They need a secret key with read/write customer access.
"""
from datetime import datetime, timedelta, timezone

from revenuecat.group import revenuecat
from revenuecat.revenuecat_api import RevenueCat, day

PREVIEW = "Preview only: nothing changed. Untick Dry run and run again to apply."


def _access(api: RevenueCat, customer_id: str) -> dict[str, str | None]:
    """The customer's active entitlements: id -> expiry date (None for no expiry)."""
    return {e["entitlement_id"]: day(e.get("expires_at")) for e in api.active_entitlements(customer_id)}


@revenuecat.deploy(title="Grant promotional access")
def grant_entitlement(customer_id: str, entitlement: str = "pro", days: int = 30, dry_run: bool = True) -> dict:
    """Give a customer an entitlement for free for a number of days, e.g. for support or a giveaway.

    Entitlement is its lookup key (like "pro") or id. Granting again with a later end date extends it. To shorten
    access, revoke it first. Untick Dry run to apply.
    """
    if not 1 <= days <= 3650:
        raise ValueError("Days must be between 1 and 3650.")
    api = RevenueCat()
    ent = api.entitlement(entitlement)
    api.customer(customer_id)  # a clear error for a wrong id, before anything changes
    before = _access(api, customer_id)
    until = datetime.now(timezone.utc) + timedelta(days=days)
    if not dry_run:
        api.grant(customer_id, ent["id"], until)
    return {
        "result": PREVIEW if dry_run else f"Granted until {until.date()}.",
        "customer_id": customer_id,
        "entitlement": ent.get("lookup_key") or ent["id"],
        "entitlement_id": ent["id"],
        "access_before": "none" if ent["id"] not in before else f"until {before[ent['id']] or 'no end date'}",
        "access_after": f"until {until.date()} (or later, if they already have it for longer)",
    }


@revenuecat.deploy(title="Revoke promotional access")
def revoke_entitlement(customer_id: str, entitlement: str = "pro", dry_run: bool = True) -> dict:
    """End every promotional grant of an entitlement for a customer, at once. Access they paid for through the
    App Store, Play Store or Stripe isn't affected. Untick Dry run to apply.
    """
    api = RevenueCat()
    ent = api.entitlement(entitlement)
    # A subscription's entitlements list isn't expanded here, so check the customer's active access instead
    promotional = [s for s in api.subscriptions(customer_id) if s.get("store") == "promotional" and s.get("gives_access")]
    if ent["id"] not in _access(api, customer_id) or not promotional:
        raise ValueError(f"This customer has no active promotional grant of {ent.get('lookup_key') or ent['id']}.")
    if not dry_run:
        api.revoke(customer_id, ent["id"])
    return {
        "result": PREVIEW if dry_run else "Revoked: the promotional access has ended.",
        "customer_id": customer_id,
        "entitlement": ent.get("lookup_key") or ent["id"],
        "promotional_grants": len(promotional),
        "paid_access_kept": any(s.get("gives_access") and s.get("store") != "promotional"
                                for s in api.subscriptions(customer_id)),
    }
