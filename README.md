# Callables Cookbook

Complete, working automations for [Callables](https://callables.app). Each one solves a real problem and is written up in a guide.

The whole cookbook deploys as **one project**. Folders are grouped by vendor and product. Each folder has single-platform automations, and `recipes/` holds jobs that cross platforms. Recipes import the same API clients the product folders use, so nothing is copied, and next actions can hand off from one platform to another.

| Folder | What's in it |
|---|---|
| [`apple/ads/`](apple/ads/) | Your Apple Ads account, live: campaign, ad group, keyword and search-term reviews, keyword rankings by CPA, and bid, keyword, negative and budget changes (dry run first). With the [MCP server](https://callables.app/docs/mcp) it's an Apple Ads MCP for Claude or ChatGPT |
| [`google/gmail/`](google/gmail/) | Your own Gmail inbox: summaries, top senders, bulk archive, subscriptions, unsubscribe, and setting your Gmail signature to the company's. Each person uses their own account |
| [`google/drive/`](google/drive/) | Google Drive automations (coming) |
| [`microsoft/outlook/`](microsoft/outlook/) | The same inbox automations for your own Outlook (Microsoft 365) mailbox, plus exporting attachments as a zip per thread and making a company email signature |
| [`microsoft/teams/`](microsoft/teams/) | Microsoft Teams automations (coming) |
| [`salesforce/`](salesforce/) | Salesforce automations (coming) |
| [`recipes/`](recipes/) | Jobs across platforms, such as receipts from your inbox into your accounting (coming) |

## Layout

    apple/ads/apple_ads_api.py       an API client: no callables in it, so any folder can import it
    apple/ads/review.py              callables (tables), using the group from apple/ads/group.py
    google/gmail/gmail_api.py
    google/gmail/inbox.py            callables, plus the Gmail connection and group
    microsoft/outlook/graph_api.py
    microsoft/outlook/inbox.py
    brand/signature.py               the company's email signature, shared by Gmail and Outlook
    recipes/<job>.py                 imports from google/ and microsoft/ as it needs
    requirements.txt                 one list for everything

Import across folders by path: `from google.gmail.gmail_api import Gmail`. Each connection is defined once and imported where it's needed.

## Deploy it

1. Fork this repo.
2. In Callables, open **New project**, pick your fork, and leave **Folder** empty.
3. Set the secrets for the connections you want to use, listed in each folder's README.

## Run one locally

    pip install callables -r requirements.txt
    call check                          # every callable loads, and what each connection needs
    call connect outlook                # once per connection, with its secrets in .env
    call outlook export_attachments --count 50

Run `call check` before you push: the build imports every file, so a broken one stops the whole deploy.
