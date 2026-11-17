# App growth

App Store Connect and Apple Ads together, for the questions neither answers on its own. Your team runs them from forms; connect Claude, ChatGPT or Cursor to the [Callables MCP server](https://callables.app/docs/mcp) and an assistant can too.

- **How many downloads did ads really bring?** Apple Ads counts its own installs and App Store Connect counts every download, but neither shows the organic rest or what each download costs once organic ones are counted.
- **Which product page converts best?** Apple Ads knows each ad's results, App Store Connect knows each page's state and assets. Together you see every page side by side, including the approved ones no ad uses yet.
- **Which searches belong in my App Store keywords?** Apple Ads shows the searches that already bring installs. Checking them against your listing's name, subtitle and keyword field shows which ones your listing doesn't cover.

Ask an assistant "what should we test next on the App Store?" and it runs **Product pages in ads** and **Keyword field ideas**, then proposes a page to copy and words to add. Both changes are previewed with a dry run before anything changes.

| Callable | What it does |
|---|---|
| **Downloads: ads vs organic** | Per day: App Store first-time downloads and redownloads, Apple Ads downloads and spend, organic downloads, ads' share, what an ads download costs, and the blended cost per download (ad spend / every download) |
| **Product pages in ads** | Each custom product page and the default page: ads and ad groups running it, spend, taps, installs, TTR, conversion rate and cost per install, best converting first. Approved pages no ad uses are listed after, and drafts are marked as needing review. Rows offer **Run an ad group on this page**, **Copy page to test a variant** and **Product page details** |
| **Keyword field ideas** | Searches with installs from Apple Ads, checked word by word against your name, subtitle and keyword field (Apple matches words, not phrases). For one that isn't covered: the words to add and your keyword field with them, if they fit in 100 characters. Rows offer **Put in the keyword field**. Searches shaped like another app's name, and searches in another language, are flagged instead |

Everything is live and nothing is stored. Changes are made by the provider callables each row links to, and they all start as a dry run.

## A product page test, start to finish

1. **Product pages in ads**: find your best page, or an idea worth testing.
2. **Copy page to test a variant**: a draft copy of it ([App Store Connect](../../providers/apple/app_store_connect/)).
3. **Set screenshots**, **Add video to product page** or **Change promotional text** on the draft, then **Submit product page for review**.
4. Once Apple approves it, **Run an ad group on this page** from its row. That's **Copy ad group onto another page** from [Apple Ads](../../providers/apple/ads/): the same keywords and bids as an ad group you pick, on the new page.
5. A week or two later, **Product pages in ads** compares them.

## How it's built

    providers/apple/ads/                         the Apple Ads client and callables
    providers/apple/app_store_connect/           the App Store Connect client and callables
    recipes/app_growth/app_growth.py             the app_growth group: imports both and joins them
    recipes/app_growth/callables.toml            include: the two provider folders, for Folder = recipes/app_growth
    recipes/app_growth/requirements.txt          its dependencies when deployed on its own

The recipe joins product pages on the custom product page id, which App Store Connect and Apple Ads share, and downloads on the date.

## Set it up

### Deploy it

Just this recipe: fork the cookbook, open **New project** in Callables, pick your fork and set **Folder** to `recipes/app_growth`. The project gets the three App growth callables and the Apple Ads and App Store Connect callables they use, and nothing else from the cookbook.

Or deploy the whole cookbook with **Folder** empty (see the [top-level README](../../README.md)). App growth works the same there.

### Secrets

Set up both providers. Each README has the steps:

- [Apple Ads](../../providers/apple/ads/#set-it-up): an API user and key pair (`APPLE_ADS_CLIENT_ID`, `APPLE_ADS_TEAM_ID`, `APPLE_ADS_KEY_ID`, `APPLE_ADS_PRIVATE_KEY`, optional `APPLE_ADS_ORG_ID`).
- [App Store Connect](../../providers/apple/app_store_connect/#set-it-up): an API key (`ASC_ISSUER_ID`, `ASC_KEY_ID`, `ASC_PRIVATE_KEY`, optional `ASC_APP_ID`). **Downloads: ads vs organic** also needs `ASC_VENDOR_NUMBER` and a key with the Sales role.

## Run locally

Put the secrets in `.env` at the top of the repo, then:

    pip install callables -r requirements.txt
    call app_growth downloads_vs_ads
    call app_growth product_pages
    call app_growth keyword_ideas --min-installs 3

## Notes

- Organic downloads are App Store downloads minus Apple Ads downloads. Apple Ads also counts view-through downloads (people who saw an ad and downloaded later), so its share runs a little high, and on a slow day organic can even dip below zero.
- Apple publishes each day's sales report the next morning (Pacific). Days without one show "not published yet" and are left out of the totals.
- Apple rejects other apps' names and trademarks in the keyword field. **Keyword field ideas** flags searches shaped like an app's title ("brand - meal planner"), but it can't spot every brand name, so check before you add one. Bidding on them in Apple Ads is allowed.
- The keyword field is per language. Searches in another language are flagged so you add them to that language's listing.
