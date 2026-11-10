# Gmail

Automations that work on the inbox of **whoever runs them** (for Microsoft 365, see [microsoft/outlook/](../../microsoft/outlook/)). Each person connects their own Google account once, and every run they start reads and changes only their own mail. It's the example for [connections](https://callables.app/docs/connections).

| Callable | What it does |
|---|---|
| **Summarize my inbox** | Statistics for your inbox: totals and unread now, then the last N days by tab, by day and by sender |
| **Recent senders** | Who has emailed you most lately, with unread counts. Each row offers **Archive their emails** |
| **Archive emails from a sender** | Archives every inbox email from one address. Dry run is on by default, so you see what would move first |
| **Subscriptions** | Mailing lists that emailed you in the last N days (found by their `List-Unsubscribe` header), busiest first, with how much you read. Each row offers **Unsubscribe** |
| **Unsubscribe** | Leaves a list the best way it supports: one-click (RFC 8058), else an unsubscribe email sent from your Gmail, else the link for you to open. Then optionally archives or trashes everything it sent you |

The connection is declared once in `inbox.py` and shared by the whole group:

```python
google = Connection("google", provider="google", scopes=["gmail.modify"])
gmail = Group("gmail", title="Gmail", connections=[google])
```

## Set it up

### 1. Create the Google OAuth app (once)

Follow the [Google connector guide](https://callables.app/connectors/google). In short:

1. In the [Google Cloud console](https://console.cloud.google.com/), create a project and enable the **Gmail API**.
2. In **Google Auth Platform**, choose the audience: **Internal** if you're on Google Workspace and only your organization will use it. Otherwise **External**, with yourself and your testers as **Test users**.
3. Add the scope `gmail.modify`.
4. Create a **Web application** client with the redirect URI `https://callables.app/connections/callback`, and copy the client ID and secret.

`gmail.modify` is a restricted scope. While an External app is in **Testing**, Google expires sign-ins after 7 days, so people have to reconnect weekly. An **Internal** app doesn't have that limit.

### 2. Deploy the cookbook

1. In Callables, open **New project** and pick your fork of this repo. Leave **Folder** empty: the whole cookbook is one project.
2. In the project's secrets, set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` from step 1.

### 3. Connect and run

Open **Summarize my inbox**. It asks you to **Connect Google**, sends you to Google's consent screen, and brings you back. After that every Gmail callable runs on your inbox. Teammates you share it with connect their own accounts.

## Run locally

1. In the OAuth client from step 1, add a second redirect URI: `http://localhost:8765/callback`.
2. Put the client ID and secret in `.env` at the top of the repo (it's ignored by git):

       GOOGLE_CLIENT_ID=...apps.googleusercontent.com
       GOOGLE_CLIENT_SECRET=...

3. Sign in once, then run anything:

       pip install callables -r requirements.txt
       call connect google
       call gmail recent_senders --days 3
       call gmail subscriptions

`call connect google` opens Google's sign-in (tick every box). It keeps the tokens in your user config folder and refreshes them, so you don't sign in again. `call disconnect` forgets them.
