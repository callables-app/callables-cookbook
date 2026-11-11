# RevenueCat

Your subscription numbers as callables, live from RevenueCat: the overview, any dashboard chart (revenue, MRR, trials, conversion, churn and more, split and filtered how you like), revenue for any dates, and customer lookups. You can also give or take away promotional access. Every run calls RevenueCat's API directly and stores nothing.

Your team uses it from forms in the web app. Connect Claude, ChatGPT or Cursor to [Callables' MCP server](https://callables.app/docs/mcp) and the same callables become a RevenueCat MCP. Ask "how did trial conversion change since we raised the price?" and the assistant opens the **Chart** it needs, splits it by product, and explains what moved. You don't need to run your own server.

| Callable | What it does |
|---|---|
| **Overview** | The overview numbers: active trials and subscriptions, MRR, and revenue, new customers and active users over the last 28 days |
| **Revenue** | Total revenue between two dates: revenue, net of taxes, or proceeds after store fees |
| **Chart** | Any dashboard chart as a table, one row per day, week, month, quarter or year. **Segment** splits it (by store, product, country, attribution keyword...) and **Filters** narrow it, like `store=app_store; first_country=US,GB` |
| **Chart options** | The segments and filters a chart accepts, with each filter's values |
| **Find customers** | Customers by email (exact), app user id, or a store transaction or order id. Each row opens the customer |
| **Customer** | One customer's email, active entitlements, subscriptions (status, store, product, renewal, revenue) and purchases. Entitlement rows offer **Grant access** and **Revoke promotional access** |
| **Entitlements** | Your entitlements, with their ids and lookup keys |
| **Grant promotional access** | Give a customer an entitlement free for a number of days, e.g. for support or a giveaway |
| **Revoke promotional access** | End a customer's promotional grants of an entitlement. Paid access isn't touched |

Both changes have **Dry run** ticked by default: the run shows the customer's current access and what would change, and changes nothing. Untick it to apply.

## How it's built

    revenuecat/revenuecat_api.py   the API client: paging, rate limits, metrics, charts, customers, entitlements. No callables
    revenuecat/group.py            the RevenueCat group and its secrets, declared once
    revenuecat/review.py           the read callables (tables)
    revenuecat/changes.py          grant and revoke (dry run by default)

`review.py` imports the changes so a customer's entitlement rows can offer them as buttons, with the customer and entitlement already filled in.

RevenueCat limits charts to 25 requests a minute. The client waits and retries when it hits a limit, so a busy assistant slows down instead of failing.

To add your own, import the client:

```python
from revenuecat.group import revenuecat
from revenuecat.revenuecat_api import RevenueCat

@revenuecat.deploy(title="Trials by keyword")
def trials_by_keyword() -> list[dict]:
    api = RevenueCat()
    ...  # api.chart("trials", start, end, segment="attribution_keyword"), api.get("/customers/..."), api.post(...)
```

A recipe that mixes RevenueCat with another platform, such as Apple Ads spend against trials per keyword, goes in [`recipes/`](../recipes/) and imports this client and [`apple/ads/`](../apple/ads/)'s.

## Set it up

### 1. Make a secret API key (once)

In the [RevenueCat dashboard](https://app.revenuecat.com/), open your project's **Project settings > API keys** and choose **+ New secret API key**. Pick **V2** and give it:

- **Charts & metrics**: read
- **Customer information**: read, or read & write to grant and revoke access
- **Project configuration**: read (for entitlements)

The project id is in the dashboard's address, after `/projects/`.

### 2. Deploy the cookbook

1. In Callables, open **New project** and pick your fork of this repo. Leave **Folder** empty: the whole cookbook is one project.
2. In the project's secrets, set `REVENUECAT_API_KEY` (the key from step 1, starting `sk_`) and `REVENUECAT_PROJECT_ID`.

Then run **Overview**.

### 3. Connect your assistant (optional)

Follow [Connect your assistant](https://callables.app/docs/mcp#connect-your-assistant), then ask things like:

> What's my MRR trend over the last 6 months, by month? Which product is growing fastest?

> Look up jane@example.com in RevenueCat and give her a week of pro access. Show me the preview first.

The assistant asks before each run, and grants are dry runs until you say to apply. To keep assistants read-only, open **Grant promotional access** and **Revoke promotional access** in the builder console and turn off **Assistants can run this function**. Or give the key read-only customer access.

## Run locally

Put the secrets in `.env` at the top of the repo (it's ignored by git):

    REVENUECAT_API_KEY=sk_...
    REVENUECAT_PROJECT_ID=proj...

Then:

    pip install callables -r requirements.txt
    call revenuecat overview
    call revenuecat chart --chart trials --resolution month --segment store
    call revenuecat find_customers --search jane@example.com

## Notes

- Chart values match the dashboard, including its definitions: see each chart's page in [RevenueCat's chart docs](https://www.revenuecat.com/docs/dashboard-and-metrics/charts).
- The current period is marked `incomplete` while it's still running, so compare it with care.
- Segmenting by `attribution_keyword` or `attribution_campaign` needs RevenueCat's [Apple Search Ads integration](https://www.revenuecat.com/docs/integrations/attribution/apple-search-ads). Without it everything shows as "No keyword".
- Customer search matches an email only when it's exactly the `$email` attribute your app set.
