# App Store Connect

Your App Store listing, custom product pages, reviews and downloads as callables, live from App Store Connect. Change keywords, subtitle, promotional text and what's new, make and edit custom product pages (screenshots, video, header images), and send them to App Review. Every run calls Apple's API directly and stores nothing.

Your team uses it from forms in the web app. Connect Claude, ChatGPT or Cursor to [Callables' MCP server](https://callables.app/docs/mcp) and the same callables become an App Store Connect MCP. Ask "what do our 1 and 2 star reviews complain about?" and the assistant runs **App Store reviews** and sums them up. Ask it to tighten the subtitle and it previews **Change listing** first. You don't need to run your own server.

| Callable | What it does |
|---|---|
| **App Store listing** | The listing per language for the newest version: name, subtitle (and the live one, if a new one is waiting), keywords, promotional text, description, what's new. Each row offers **Change listing** |
| **Custom product pages** | Every custom product page: review state, video, screenshot sets, promotional text, link, and the id Apple Ads uses. Rows offer **Product page details**, **Copy page**, **Change promotional text** and **Submit for review** |
| **Product page details** | Everything on a page's latest version: promotional text, each screenshot and video, per language and device size |
| **App Store reviews** | Written reviews, newest first, with a closing row averaging their stars |
| **Downloads** | First-time downloads and redownloads per day from the daily sales reports, for every country or one |
| **Change listing** | Keywords (100 characters), subtitle (30), promotional text (170) and what's new. **Version** creates a new app version if it doesn't exist yet. A version waiting for review can be pulled (**Remove from review**) and sent back (**Resubmit**) |
| **Copy product page** | A new custom product page that starts as a copy of another: a draft to change and submit |
| **Change promotional text** | A custom product page's promotional text. Apple doesn't review promotional text changes |
| **Set screenshots** | Replace one device size's screenshots on a page draft, from image URLs or a .zip (in file-name order) |
| **Add video to product page** | Upload an app preview video (.mp4 or .mov) to a page draft |
| **Header & search images** | The header and search-results images on a page draft |
| **Submit product page for review** | Send a page draft to App Review. Once it's approved, Apple Ads can run ads on it |

Every change has **Dry run** ticked by default: the run shows what would change and changes nothing. Untick it to apply.

## How it's built

    providers/apple/app_store_connect/app_store_api.py   the API client: JWT sign-in, paging, uploads, review submissions, sales reports. No callables
    providers/apple/app_store_connect/group.py           the App Store Connect group and its secrets, declared once
    providers/apple/app_store_connect/review.py          the read callables (tables)
    providers/apple/app_store_connect/changes.py         the write callables (dry run by default)

`review.py` imports the changes so its rows can offer them as buttons, with the page id already filled in. Custom product pages work like this: a page has versions (one live, maybe a draft), each version has a localization per language, and each localization has screenshot and video sets per device size. Edits go to the draft; a live page is changed by copying it.

To add your own, import the client:

```python
from providers.apple.app_store_connect.app_store_api import AppStoreConnect
from providers.apple.app_store_connect.group import app_store

@app_store.deploy(title="In-app events")
def in_app_events() -> list[dict]:
    asc = AppStoreConnect()
    return [e["attributes"] for e in asc.all(f"/v1/apps/{asc.app_id}/appEvents")]
```

The [App growth](../../../recipes/app_growth/) recipe combines this folder with [Apple Ads](../ads/): downloads from ads vs organic, product pages compared in ads, and keyword ideas for your listing.

## Set it up

### 1. Make an API key (once)

1. In [App Store Connect](https://appstoreconnect.apple.com/), open **Users and Access > Integrations > App Store Connect API** and create a **Team key**. Give it the **App Manager** role for listings and product pages.
2. Download the `.p8` file (Apple only lets you do this once) and note the **Key ID** and the **Issuer ID** at the top of the page.
3. For **Downloads**, the key needs the **Sales** (or Finance) role. Either give the main key that role too, or make a second key with it.

### 2. Set the secrets

In the project's secrets:

| Secret | Value |
|---|---|
| `ASC_ISSUER_ID` | The Issuer ID |
| `ASC_KEY_ID` | The Key ID |
| `ASC_PRIVATE_KEY` | The `.p8` file's contents, from `-----BEGIN PRIVATE KEY-----` to the end. Or `ASC_PRIVATE_KEY_B64`: the file base64-encoded (`base64 -i AuthKey.p8`), handy where a secret can only be one line |
| `ASC_APP_ID` | Optional: the app's Apple ID (App Information > General). Needed if the key can see more than one app |
| `ASC_VENDOR_NUMBER` | For **Downloads**: in **Payments and Financial Reports**, top left |
| `ASC_SALES_KEY_ID`, `ASC_SALES_PRIVATE_KEY_B64` | For **Downloads**, if the main key doesn't have the Sales role: the second key's ID and base64 `.p8` |

### 3. Run it

Open **App Store listing** to check the key works, then **Custom product pages**.

## Run locally

Put the same secrets in `.env` at the top of the repo, then:

    pip install callables -r requirements.txt
    call app_store app_listing
    call app_store reviews --min-rating 4
    call app_store update_listing --subtitle "Plan dinners in minutes"     # a dry run

## Notes

- Apple publishes each day's sales report the next morning (Pacific), so yesterday may show "not published yet".
- Apple's API only serves written reviews. Star-only ratings aren't available, so the average in **App Store reviews** can differ from the one on your listing.
- Screenshots and videos take Apple a minute or two to process after upload. **Product page details** shows their state.
