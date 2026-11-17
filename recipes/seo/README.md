# SEO toolkit

Google Search Console, Bing Webmaster Tools and Umami together, as callables your team runs from forms. Connect Claude, ChatGPT or Cursor to the [Callables MCP server](https://callables.app/docs/mcp) and an assistant can use them too. One run answers questions that usually take three dashboards and a spreadsheet: how search is doing, which pages to fix next and what to do about them, what's going on with one page, and which pages Google or Bing haven't picked up.

Ask an assistant "what should I work on this week to get more search traffic?" and it runs **Pages to fix next**. It reads each page's Google ranking, Bing ranking and how long visitors stay, then gives you a short list of edits. Ask "why isn't /pricing showing up?" and it runs **Page report**, then **Index check**, and submits the page to Bing once you say so.

Everything is live: each run calls the three APIs and stores nothing.

| Callable | What it does |
|---|---|
| **SEO scorecard** | Search at a glance against the period just before: Google clicks, impressions, CTR and position, Bing clicks and impressions, and the visitors Umami saw arrive from organic search. Schedule it weekly |
| **Pages to fix next** | Query + page pairs from Google worth working on, most extra clicks first. *Striking distance* pages rank 5 to 20. *Low CTR* pages are on page one but get under half the usual clicks. Each row adds the query's Bing position and the page's Umami visitors and exit rate, plus a suggestion. Rows link to **Inspect in Google** and **Other pages for this query** |
| **Page report** | Everything about one page: Google clicks, position, top queries, index status and canonical; Bing clicks and crawl status; Umami visitors, entries and exit rate |
| **Index check** | For each page in your sitemap (or a list): whether Google has indexed it and whether Bing has crawled it, missing pages first. Rows link to **Submit to Bing** |

Each platform is optional. If Bing or Umami isn't set up, a run uses the others and says what it skipped. Only Google is required, because it does the ranking.

The single-platform callables underneath are in their own folders, for when you want to dig into one:

| Folder | Group | What's in it |
|---|---|---|
| [`providers/google/search_console/`](../../providers/google/search_console/) | Google Search Console | Queries, pages, query ↔ page, trend, totals, what changed, opportunities, URL inspection, sitemaps |
| [`providers/microsoft/bing/`](../../providers/microsoft/bing/) | Bing Webmaster | Queries, pages, traffic, crawl stats, crawl issues, URL status, submit URLs (dry run first), quota |
| [`providers/umami/`](../../providers/umami/) | Umami | Overview, traffic trend, pages (entries, exits, exit rate), breakdown by referrer/channel/country/device/UTM, custom events |

## How it's built

    providers/google/search_console/search_console_api.py   API client and reports. No callables, so anything can import it
    providers/google/search_console/review.py               the search_console connection, group and callables
    providers/microsoft/bing/bing_api.py                    API client and reports
    providers/microsoft/bing/review.py                      the bing group and callables
    providers/umami/umami_api.py                            API client and reports
    providers/umami/review.py                               the umami group and callables
    recipes/seo/seo.py                                      the seo group: imports all three clients and joins them
    recipes/seo/callables.toml                              include: the provider folders above, for Folder = recipes/seo
    recipes/seo/requirements.txt                            its dependencies when deployed on its own

The recipe joins the platforms on the page path, so Google's `https://example.com/blog/post/`, Bing's page URL and Umami's `/blog/post` line up. Search queries are matched case-insensitively.

To add your own, import the clients:

```python
from providers.google.search_console import search_console_api as gsc_api
from providers.google.search_console.review import search_console
from recipes.seo.seo import seo
from providers.umami import umami_api

@seo.deploy(title="Search landing pages that lose people")
def leaky_pages(site: str | None = None) -> list[dict]:
    google = gsc_api.report(search_console.token, ["page"], site=site)
    visits = umami_api.pages(filters="referrer=c.google", website=site)
    ...
```

## Set it up

### Deploy it

Just this recipe: fork the cookbook, open **New project** in Callables, pick your fork and set **Folder** to `recipes/seo`. The project gets the four SEO callables and the Search Console, Bing and Umami ones they're built on, and nothing else from the cookbook. `recipes/seo/callables.toml` brings those provider folders along.

Or deploy the whole cookbook with **Folder** empty (see the [top-level README](../../README.md)). The SEO toolkit works the same there.

Then set up whichever platforms you use.

### Google Search Console (required)

Each person signs in with their own Google account and sees the Search Console properties that account can see.

1. In the [Google Cloud console](https://console.cloud.google.com/), use the same project as the Gmail callables, or create one. Enable the **Google Search Console API**.
2. In **Google Auth Platform**, add the scope `https://www.googleapis.com/auth/webmasters.readonly`. Create a **Web application** client with the redirect URI `https://callables.app/connections/callback` if you don't have one yet.
3. In the project's secrets, set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.

`webmasters.readonly` isn't a restricted scope, so an External app in Testing works for you and your test users without Google's review. The Search Console sign-in is separate from the Gmail one: it asks only for read-only Search Console access.

### Bing Webmaster Tools (optional)

1. In [Bing Webmaster Tools](https://www.bing.com/webmasters), add and verify your site. You can import it from Search Console in one click.
2. Open **Settings > API access** and generate an API key.
3. Set `BING_WEBMASTER_API_KEY`. If the account has several sites, set `BING_SITE_URL` (like `https://www.example.com/`) or pass **Site** on each run.

Bing's numbers also cover the search engines that use Bing's index: DuckDuckGo, Yahoo, Ecosia and ChatGPT search.

### Umami (optional)

Self-hosted:

1. Set `UMAMI_URL` to your instance, like `https://umami.example.com`.
2. Set `UMAMI_API_KEY` (Settings > API keys), or a user with `UMAMI_USERNAME` and `UMAMI_PASSWORD`. A **view-only** user is enough. Users with two-factor sign-in won't work.

Umami Cloud: set `UMAMI_URL=https://api.umami.is` and `UMAMI_API_KEY`.

If the account has several websites, set `UMAMI_WEBSITE_ID` or pass **Site** on each run.

Tag your calls to action with `data-umami-event` (and where they sit with `data-umami-event-location`), and **Events** in the Umami group shows which ones search visitors click.

## Run locally

1. Add `http://localhost:8765/callback` as a second redirect URI on the Google OAuth client.
2. Put the secrets in `.env` at the top of the repo (ignored by git):

       GOOGLE_CLIENT_ID=...apps.googleusercontent.com
       GOOGLE_CLIENT_SECRET=...
       BING_WEBMASTER_API_KEY=...
       UMAMI_URL=https://umami.example.com
       UMAMI_API_KEY=...

3. Sign in once, then run anything:

       pip install callables -r requirements.txt
       call connect search_console
       call seo scorecard --site example.com
       call seo opportunities --site example.com --limit 20
       call seo page_report --page /pricing/

## Notes

- Google's numbers end 2 days ago, because the last two days are still filling in. Bing updates query and page stats weekly. Umami ends yesterday (UTC).
- Google allows 2,000 URL inspections a day per property, so **Index check** takes 50 pages at a time by default. A run stops after about 4 minutes and tells you the **Start at** for the next batch.
- **Submit to Bing** has **Dry run** ticked by default. It shows which URLs it would send, up to today's quota, and sends nothing until you untick it.
- Google doesn't offer an API to request indexing for ordinary pages. To ask Google to recrawl a page, use **Request indexing** in Search Console (**Inspect in Google** links to it).
