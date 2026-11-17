# Bing Webmaster Tools

How your site shows up in Bing, live: queries, pages, daily traffic, crawl stats and issues, which pages Bing hasn't crawled, and submitting them. Bing's index also feeds DuckDuckGo, Yahoo, Ecosia and ChatGPT search.

It's part of the [SEO toolkit](../../../recipes/seo/), which combines it with Google Search Console and Umami. Setup is in that README (secrets: `BING_WEBMASTER_API_KEY`, optional `BING_SITE_URL`).

| Callable | What it does |
|---|---|
| **Bing queries** | Searches that showed the site: clicks, impressions, CTR and position, summed over the weeks in the dates |
| **Bing pages** | Each page's clicks, impressions, CTR and position |
| **Bing traffic** | Clicks and impressions per day (last 90 days by default) |
| **Bing crawl** | Pages crawled and in the index per day, errors by HTTP code, blocked by robots.txt |
| **Bing crawl issues** | URLs Bing had trouble with. Rows offer **Resubmit** |
| **Bing URL status** | Whether Bing has crawled each page in your sitemap (or a list), never-crawled first. Rows offer **Submit to Bing** |
| **Submit URLs to Bing** | Ask Bing to crawl pages now, up to the daily quota. **Dry run** is ticked by default |
| **Bing submission quota** | URLs you can still submit today and this month |

Bing throttles URL checks, so **Bing URL status** goes slowly and stops after about 4 minutes. The rows it didn't reach say which **Start at** to run next.
