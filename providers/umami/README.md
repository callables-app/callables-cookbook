# Umami

Your website analytics from [Umami](https://umami.is), live: visitors against last period, traffic per day, which pages people land on and leave from, where they come from, and which buttons they click. Works with self-hosted Umami and Umami Cloud.

It's part of the [SEO toolkit](../../recipes/seo/), which combines it with Google Search Console and Bing. Setup is in that README (secrets: `UMAMI_URL`, then `UMAMI_API_KEY` or `UMAMI_USERNAME` + `UMAMI_PASSWORD`, optional `UMAMI_WEBSITE_ID`).

| Callable | What it does |
|---|---|
| **Overview** | Visitors, visits, pageviews, bounce rate and time per visit against the period before, plus visitors right now |
| **Traffic trend** | Pageviews and visitors per hour, day, week or month |
| **Pages** | Each page's visitors, pageviews, entries, exits, exit rate and time per visit |
| **Breakdown** | Visitors, visits and bounce rate by referrer, channel, country, device, entry page, UTM and more |
| **Events** | Custom events (`data-umami-event`): count, visitors, and each property's split by value. Rows open **Event values** |
| **Event values** | How often each value of one event property occurs |
| **Websites** | The websites the account can see, with their ids |

**Filters** narrow any of them, as `name=value; name2=value`: `path`, `referrer`, `country` (US), `device`, `event`, `utmSource`, `utmCampaign` and more. A value matches exactly unless it starts with `c.` (contains), `neq.` (not equal) or `re.` (regex), like `path=c./blog`. Dates default to the last 30 days ending yesterday (UTC).
