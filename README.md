# Callables Cookbook

Complete, working automations for [Callables](https://callables.app). Each one solves a real problem and is written up in a guide.

`providers/` has one folder per service, grouped by vendor, with that service's API client and its callables. `recipes/` holds jobs that cross services. Recipes import the same API clients the provider folders use, so nothing is copied, and next actions can hand off from one service to another.

Deploy the whole cookbook as one project, or [just one recipe](#deploy-just-one-recipe).

## Recipes

| Recipe | What it does |
|---|---|
| [`recipes/seo/`](recipes/seo/) | **SEO toolkit**: Google Search Console, Bing Webmaster Tools and Umami together. A search scorecard, the pages to fix next, a full report on one page, and which pages Google or Bing haven't indexed |
| [`invoices/`](invoices/) | Finding the invoices in your Gmail or Outlook: Claude reads the attachments, you get a CSV and a zip of the files. Shared by both mail providers' **Find invoices** |

## Providers

| Folder | What's in it |
|---|---|
| [`providers/apple/ads/`](providers/apple/ads/) | Your Apple Ads account, live: campaign, ad group, keyword and search-term reviews, keyword rankings by CPA, and bid, keyword, negative and budget changes (dry run first). With the [MCP server](https://callables.app/docs/mcp) it's an Apple Ads MCP for Claude or ChatGPT |
| [`providers/google/gmail/`](providers/google/gmail/) | Your own Gmail inbox: summaries, top senders, bulk archive, subscriptions, unsubscribe, and setting your Gmail signature to the company's. Each person uses their own account |
| [`providers/google/search_console/`](providers/google/search_console/) | Your site's Google search data, live: queries, pages, what changed, quick wins and URL inspection. Each person uses their own Google account |
| [`providers/google/drive/`](providers/google/drive/) | Google Drive automations (coming) |
| [`providers/microsoft/outlook/`](providers/microsoft/outlook/) | The same inbox automations for your own Outlook (Microsoft 365) mailbox, plus exporting attachments as a zip per thread and making a company email signature |
| [`providers/microsoft/bing/`](providers/microsoft/bing/) | Bing Webmaster Tools, live: queries, pages, crawl issues, which pages Bing hasn't crawled, and submitting them (dry run first) |
| [`providers/microsoft/teams/`](providers/microsoft/teams/) | Microsoft Teams automations (coming) |
| [`providers/revenuecat/`](providers/revenuecat/) | Your subscription numbers live: the overview, any dashboard chart split and filtered, revenue, customer lookups, and granting or revoking promotional access (dry run first). With the [MCP server](https://callables.app/docs/mcp) it's a RevenueCat MCP |
| [`providers/umami/`](providers/umami/) | Website analytics from Umami, live: visitors, pages, exit rates, referrers, channels and custom events |
| [`providers/salesforce/`](providers/salesforce/) | Salesforce automations (coming) |

## Layout

    providers/apple/ads/apple_ads_api.py      an API client: no callables in it, so any folder can import it
    providers/apple/ads/review.py             callables (tables), using the group from providers/apple/ads/group.py
    providers/google/gmail/gmail_api.py
    providers/google/gmail/inbox.py           callables, plus the Gmail connection and group
    providers/microsoft/outlook/graph_api.py
    providers/microsoft/outlook/inbox.py
    brand/signature.py                        the company's email signature, shared by Gmail and Outlook
    invoices/                                 reading invoices out of email attachments, shared by Gmail and Outlook
    recipes/seo/seo.py                        imports from providers/ as it needs
    recipes/seo/callables.toml                the provider folders it needs, for deploying it on its own
    requirements.txt                          one list for the whole cookbook

Import across folders by path: `from providers.google.gmail.gmail_api import Gmail`. Each connection is defined once and imported where it's needed.

## Deploy it

1. Fork this repo.
2. In Callables, open **New project**, pick your fork, and leave **Folder** empty.
3. Set the secrets for the connections you want to use, listed in each folder's README.

## Deploy just one recipe

Set **Folder** to the recipe, such as `recipes/seo`. Its `callables.toml` lists the provider folders it needs:

```toml
include = ["providers/google/search_console", "providers/microsoft/bing", "providers/umami"]
```

The project gets the recipe and those providers' callables, nothing else, and a push that changes any of them redeploys it. Its dependencies come from the recipe's own `requirements.txt`. See [Share code between folders](https://callables.app/docs/builds#share-code-between-folders).

## Run one locally

    pip install callables -r requirements.txt
    call check                          # every callable loads, and what each connection needs
    call check --root recipes/seo       # what a project with Folder = recipes/seo gets
    call connect outlook                # once per connection, with its secrets in .env
    call outlook export_attachments --count 50

Run `call check` before you push: the build imports every file, so a broken one stops the whole deploy.
