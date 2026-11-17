"""The App Store Connect group, declared once: review.py and changes.py both add callables to it."""
from callables import Group

from providers.apple.app_store_connect.app_store_api import SECRETS

app_store = Group(
    "app_store",
    title="App Store Connect",
    description="Your App Store listing, custom product pages and reviews, live: read them, and change keywords, "
                "promotional text, screenshots and videos. Changes preview first.",
    secrets=SECRETS,
)
