# Apple Ads

Your Apple Ads (Search Ads) account as callables: review campaigns, ad groups, keywords, search terms, creatives and impression share with live numbers, then change bids, statuses, keywords, negatives and budgets, test custom product pages and start new campaigns. Every run calls Apple's API directly and stores nothing.

Your team uses it from forms in the web app. Connect Claude, ChatGPT or Cursor to [Callables' MCP server](https://callables.app/docs/mcp) and the same callables become an Apple Ads MCP. Ask "which keywords are wasting money this month?" and the assistant runs **Keyword rankings**, reads the rows and suggests changes. Then it previews them with a dry run, and applies them once you say so. You don't need to run your own server.

| Callable | What it does |
|---|---|
| **Campaigns** | One row per campaign: status, daily budget, spend, impressions, taps, installs, TTR, CVR, CPT and CPA. Start here: each row links to its ad groups, keywords, rankings and search terms. Rows also offer **Change campaign** and **Copy negatives** |
| **Ad groups** | One row per ad group: status, Search Match, default bid, CPA goal, and the same metrics against target. Each row offers **Change ad group** and **Copy onto another page** |
| **Keywords** | One row per keyword: bid, match type, status and metrics. Each row offers **Change bid / pause** |
| **Keyword rankings** | The best and worst keywords in each ad group (or campaign) by CPA, skipping keywords with too few taps to judge |
| **Search terms** | What people actually searched before tapping your ad, from your keywords and Search Match, and whether each is already a keyword. Each row offers **Add as keyword** and **Add as negative** |
| **Creatives** | Every ad, paused campaigns too, with the product page it runs (custom or default) and its results, so you can compare pages on the same keywords. Each row offers **Copy ad group onto another page** |
| **Impression share** | Apple's impression share range, rank and search popularity per search term, next to what you got on it, with a rough spend at full share. Apple allows a few of these reports a day, so the same inputs reuse today's |
| **Change keyword** | A keyword's bid, or pause/re-activate it |
| **Add keywords** | New keywords in an ad group, one per line. Skips ones already there |
| **Add negative keywords** | Negatives for an ad group or a whole campaign |
| **Change ad group** | Default bid, CPA goal, pause/enable, or **Convert broad to exact**: every active broad keyword gets an exact copy at the same bid, and the broad one is paused |
| **Change campaign** | Name, daily budget, pause/enable |
| **Copy negatives** | One campaign's negatives (campaign and ad group level) onto another. **Keywords too** also negates its keywords, so two campaigns stop bidding against each other |
| **Copy ad group onto another page** | A new ad group with the same keywords, bids, negatives and targeting, running a different custom product page: a creative test on the same keywords. **Search match only** copies the targeting with Search Match and no keywords |
| **New campaign** | One ad group of exact keywords (add `(broad)` after one for broad) at one bid, on one custom product page, in one country. The app, placement and billing are copied from **Template campaign id**, or your newest campaign |

Every change has **Dry run** ticked by default: the run shows the current and new values and changes nothing. Untick it to apply.

Report dates default to the last 30 days, ending yesterday. **Target CPA** is optional on every review: leave it empty and each row uses its ad group's CPA goal, else its campaign's.

## How it's built

    providers/apple/ads/apple_ads_api.py   the API client: sign-in, paging, objects, product pages, creatives and reports,
                                           plus ads_with_pages(): every ad with its product page and results. No callables,
                                           so anything can import it
    providers/apple/ads/metrics.py         plain functions: Apple's money objects, date windows, spend/TTR/CVR/CPT/CPA
    providers/apple/ads/group.py           the Apple Ads group and its secrets, declared once
    providers/apple/ads/review.py          the read callables (tables), including Creatives and Impression share
    providers/apple/ads/changes.py         the write callables (dry run by default), including the copies and New campaign

`review.py` imports the changes so its rows can offer them as buttons. A row field with the same name as a change's input fills it, so a keyword row opens **Change keyword** with its ids and current bid already in.

To add your own, import the client and call any endpoint:

```python
from providers.apple.ads.apple_ads_api import AppleAds
from providers.apple.ads.group import apple_ads
from providers.apple.ads.metrics import stats, window

@apple_ads.deploy(title="Spend by day")
def spend_by_day(campaign_id: int) -> list[dict]:
    start, end = window(None, None)
    api = AppleAds()
    ...  # api.get("/campaigns/..."), api.post(...), api.report("/reports/campaigns/...", start, end)
```

The [App growth](../../../recipes/app_growth/) recipe combines it with [App Store Connect](../app_store_connect/): downloads from ads vs organic, product pages compared in ads, and keyword ideas for your listing. A recipe that mixes Apple Ads with another platform goes in [`recipes/`](../../../recipes/) and imports the same client.

## Set it up

### 1. Make an API user in Apple Ads (once)

1. In [Apple Ads](https://app.searchads.apple.com/), open **Account Settings > User Management** and invite a user with an API role. Choose **API Account Read Only** if you only want the reviews, or **API Campaign Manager** to make changes too. You can invite your own Apple ID under a second email.
2. Accept the invite and sign in as that user. Create a key pair on your computer:

       openssl ecparam -genkey -name prime256v1 -noout -out apple-ads-private.pem
       openssl ec -in apple-ads-private.pem -pubout -out apple-ads-public.pem

3. In **Account Settings > API**, paste the contents of `apple-ads-public.pem` and save. Apple shows a **client ID**, **team ID** and **key ID**.

Keep `apple-ads-private.pem` secret, and out of git.

### 2. Deploy the cookbook

1. In Callables, open **New project** and pick your fork of this repo. Leave **Folder** empty: the whole cookbook is one project.
2. In the project's secrets, set:

   | Secret | Value |
   |---|---|
   | `APPLE_ADS_CLIENT_ID` | the client ID from step 1 |
   | `APPLE_ADS_TEAM_ID` | the team ID |
   | `APPLE_ADS_KEY_ID` | the key ID |
   | `APPLE_ADS_PRIVATE_KEY` | the whole of `apple-ads-private.pem`, from `-----BEGIN` to `-----END` |
   | `APPLE_ADS_ORG_ID` | optional: only if the API user can see more than one account. The error lists them |

Then run **Campaigns**.

### 3. Connect your assistant (optional)

Follow [Connect your assistant](https://callables.app/docs/mcp#connect-your-assistant), then ask things like:

> How did my Apple Ads do in the last 30 days? Rank the best and worst keywords in each ad group by CPA.

> Find search terms that converted under my $5 target but aren't keywords yet, and preview adding them.

The assistant asks before each run, and changes are dry runs until you tell it to apply. To keep assistants read-only, open each change callable in the builder console and turn off **Assistants can run this function**. People can still use those callables from the web app. Or give the API user the **API Account Read Only** role, so nothing can change your campaigns.

## Run locally

Put the secrets in `.env` at the top of the repo (it's ignored by git). Locally `APPLE_ADS_PRIVATE_KEY` can be a path to the file:

    APPLE_ADS_CLIENT_ID=SEARCHADS.xxxxxxxx
    APPLE_ADS_TEAM_ID=SEARCHADS.xxxxxxxx
    APPLE_ADS_KEY_ID=xxxxxxxx
    APPLE_ADS_PRIVATE_KEY=~/keys/apple-ads-private.pem

Then:

    pip install callables -r requirements.txt
    call apple_ads campaigns
    call apple_ads keyword_rankings --level Campaign --min-taps 20
    call apple_ads search_terms --campaign-id 123456789

## Notes

- Installs are Apple's total installs (tap-through plus view-through), so CPA matches what the Apple Ads dashboard shows.
- Apple's numbers for the last day or two keep changing as late installs come in. That's why reports end yesterday.
- `APPLE_ADS_PRIVATE_KEY` also accepts the PEM base64-encoded, for secret stores that only take one line.
- Search Match campaigns have no keywords, so **Keywords** and **Keyword rankings** skip them. Their searches show in **Search terms**.
