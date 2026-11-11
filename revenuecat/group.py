"""The RevenueCat group, declared once: review.py and changes.py both add callables to it, and share its secrets."""
from callables import Group

from revenuecat.revenuecat_api import SECRETS

revenuecat = Group(
    "revenuecat",
    title="RevenueCat",
    description="Your subscription numbers live from RevenueCat: the overview, any dashboard chart, revenue, and "
                "customer lookups, plus granting and revoking promotional access. Changes preview first.",
    secrets=SECRETS,
)
