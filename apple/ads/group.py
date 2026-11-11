"""The Apple Ads group, declared once: review.py and changes.py both add callables to it, and share its secrets."""
from callables import Group

from apple.ads.apple_ads_api import SECRETS

apple_ads = Group(
    "apple_ads",
    title="Apple Ads",
    description="Review your Apple Ads campaigns, ad groups, keywords and search terms live, then change bids, "
                "statuses, keywords, negatives and budgets. Changes preview first.",
    secrets=SECRETS,
)
