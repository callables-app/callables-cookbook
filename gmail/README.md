# Gmail

Automations that work on the inbox of **whoever runs them**. Each person connects their own Google account once, and every run they start reads and changes only their own mail. It's the example for [connections](https://callables.app/docs/connections).

| Callable | What it does |
|---|---|
| **Summarize my inbox** | A short written digest of recent mail: what needs you, what's worth knowing, what's noise |
| **Recent senders** | Who has emailed you most lately, with unread counts. Each row offers **Archive their emails** |
| **Archive emails from a sender** | Archives every inbox email from one address. Dry run is on by default, so you see what would move first |

The connection is declared once in `inbox.py` and shared by the whole group:

```python
google = Connection("google", provider="google", scopes=["gmail.modify"])
gmail = Group("gmail", title="Gmail", connections=[google])
```

## Set it up

### 1. Create the Google OAuth app (once)

1. In the [Google Cloud console](https://console.cloud.google.com/), create or pick a project.
2. **APIs & Services → Library**: enable the **Gmail API**.
3. **APIs & Services → OAuth consent screen**: choose **Internal** if you're on Google Workspace and only your organization will use it. Otherwise choose **External**, and add yourself and your testers under **Test users**.
4. Add the scope `https://www.googleapis.com/auth/gmail.modify` (plus `openid` and `email`, which show which account people connected).
5. **APIs & Services → Credentials → Create credentials → OAuth client ID**, type **Web application**. Under **Authorized redirect URIs**, add the URI shown on the project page's **Connections** card: `https://callables.app/connections/callback` in production, or `http://localhost:3000/connections/callback` for a local Callables.
6. Copy the client ID and client secret.

`gmail.modify` is a restricted scope. While an External app is in **Testing** status, Google expires its refresh tokens after 7 days, so people have to reconnect weekly. An **Internal** app doesn't have that limit.

### 2. Deploy the folder

1. In Callables, open **New project**, pick your fork of this repo, and set **Folder** to `gmail`.
2. In the project's secrets, set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` from step 1.
3. Optional: set `ANTHROPIC_API_KEY` so **Summarize my inbox** writes a summary with Claude. Without it, you get the messages grouped by sender.

### 3. Connect and run

Open **Summarize my inbox**. It asks you to **Connect Google**, sends you to Google's consent screen, and brings you back. After that every callable in the project runs on your inbox. Teammates you share it with connect their own accounts.

## Run locally

Get an access token for your own account, for example from Google's [OAuth Playground](https://developers.google.com/oauthplayground/) with the `gmail.modify` scope, and put it in `gmail/.env`:

    GOOGLE_ACCESS_TOKEN=ya29....
    ANTHROPIC_API_KEY=sk-ant-...

Then:

    pip install callables
    pip install -r gmail/requirements.txt
    call local --root gmail gmail.recent_senders -i days=3
    call local --root gmail gmail.archive_from_sender -i sender=news@example.com

Playground tokens last an hour.
