# Outlook

The [Gmail](../gmail/) automations, for Microsoft 365. They work on the mailbox of **whoever runs them**: each person connects their own work account once, and every run they start reads and changes only their own mail, through Microsoft Graph. It's an example of [connections](https://callables.app/docs/connections).

| Callable | What it does |
|---|---|
| **Summarize my inbox** | Statistics for your inbox: totals and unread now, then the last N days by Focused and Other, by day and by sender |
| **Recent senders** | Who has emailed you most lately, with unread counts. Each row offers **Archive their emails** |
| **Archive emails from a sender** | Moves every inbox email from one address to Archive. Dry run is on by default, so you see what would move first |
| **Subscriptions** | Mailing lists that emailed you in the last N days (found by their `List-Unsubscribe` header), busiest first, with how much you read. Each row offers **Unsubscribe** |
| **Unsubscribe** | Leaves a list the best way it supports: one-click (RFC 8058), else an unsubscribe email sent from your mailbox, else the link for you to open. Then optionally archives everything it sent you, or moves it to Deleted Items |

The connection is declared once in `inbox.py` and shared by the whole group:

```python
outlook = Connection(
    "outlook",
    provider="microsoft",
    scopes=["Mail.ReadWrite", "Mail.Send"],
    client_id=Secret("MS_CLIENT_ID"),
    client_secret=Secret("MS_CLIENT_SECRET"),
    values={"tenant": Secret("MS_TENANT_ID")},
)
mail = Group("outlook", title="Outlook", connections=[outlook])
```

`Secret("...")` names a project secret on Callables, and an environment variable (or `.env`) locally. Nothing about your app is written in the code.

## Set it up

### 1. Register the Microsoft app (once)

Follow [How to create a Microsoft OAuth app for Outlook automations](https://callables.app/blog/create-a-microsoft-oauth-app). In short:

1. In [Microsoft Entra](https://entra.microsoft.com), open **Entra ID → App registrations → New registration**. Choose **Single tenant**, and add the redirect URI `https://callables.app/connections/callback` (platform **Web**).
2. **Certificates & secrets**: create a client secret and copy its **Value** (not the Secret ID).
3. **API permissions**: add the Microsoft Graph **delegated** permissions `Mail.ReadWrite` and `Mail.Send`.
4. Have an admin click **Grant admin consent** for your organization, so people can connect without being blocked.

### 2. Deploy the folder

1. In Callables, open **New project**, pick your fork of this repo, and set **Folder** to `outlook`.
2. In the project's secrets, set:

   | Secret | From the app's Overview page |
   |---|---|
   | `MS_CLIENT_ID` | Application (client) ID |
   | `MS_CLIENT_SECRET` | The client secret's Value |
   | `MS_TENANT_ID` | Directory (tenant) ID (or `common` for a multi-tenant app) |

### 3. Connect and run

Open **Summarize my inbox**. It asks you to **Connect Microsoft**, sends you to Microsoft's sign-in, and brings you back. After that every callable in the project runs on your mailbox. Teammates you share it with connect their own accounts.

## Run locally

1. In the app registration, under **Authentication**, add a second Web redirect URI: `http://localhost:8765/callback`.
2. Put the three secrets in `outlook/.env` (it's ignored by git), or in a `.env` at the top of the repo.
3. Sign in once, then run anything:

       cd outlook
       pip install callables -r requirements.txt
       call connect
       call outlook recent_senders --days 3
       call outlook subscriptions

## Good to know

- **Archive** is Outlook's Archive folder. **Deleted Items** is emptied on your organization's schedule.
- Graph allows 4 requests at once and about 10,000 per 10 minutes for each mailbox. The client in `graph_api.py` stays under both, batches moves 20 at a time, and waits when Outlook asks it to.
- Subscriptions reads up to 2,000 messages from every folder except Sent Items, Drafts, Deleted Items and Junk Email.
