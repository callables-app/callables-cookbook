# Google Search Console

Your site's Google search data as callables, live: what people searched before they saw you, which page ranks for which query, what changed since last period, where the quick wins are, and whether a page is indexed. Each person signs in with their own Google account, and nothing is stored.

It's part of the [SEO toolkit](../../../recipes/seo/), which combines it with Bing Webmaster Tools and Umami. Setup is in that README.

| Callable | What it does |
|---|---|
| **Queries** | Searches that showed the site: clicks, impressions, CTR and average position. Filter by page, country, device or search type |
| **Pages** | Each page's clicks, impressions, CTR and position. Rows link to **Queries for this page** and **Inspect** |
| **Query pages** | Which page ranks for which query. Several pages on one query split its clicks |
| **Search trend** | Clicks, impressions, CTR and position per day |
| **Search totals** | The site (or a page or query) against the period just before |
| **What changed** | Pages or queries now against the period before, biggest change in clicks first |
| **Opportunities** | Striking-distance (position 5 to 20) and low-CTR query + page pairs, most extra clicks first |
| **Inspect URL** | Whether Google has indexed a page and why not: coverage, robots.txt, Google's canonical vs yours, last crawl, rich results |
| **Sitemaps** | Submitted sitemaps: last read, errors, warnings, URLs submitted |
| **Properties** | The properties your account can see |

Page and Query filters mean "contains". Start with `=` for an exact match, `!` to exclude, or `~` for a regex. Dates default to the last 28 days ending 2 days ago.

The connection is called `search_console` and uses the same Google OAuth app (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`) as Gmail, but signs in separately with only the read-only `webmasters.readonly` scope.
