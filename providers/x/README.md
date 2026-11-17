# X

Post to X (Twitter) as yourself. Each person signs in with their own X account. Posting previews first.

It's part of the [Announce](../../recipes/announce/) recipe, which posts to LinkedIn and X and emails your audience in one run.

| Callable | What it does |
|---|---|
| **Post on X** | A post as you, up to 280 characters (each link counts as 23). **Reply to** takes a post id, so you can build a thread |

The dry run shows how X counts the text and roughly what the post will cost.

## Set it up

### 1. Create an X app (once)

1. In the [X Developer Console](https://console.x.com/), create an app.
2. Under **User authentication settings**, turn on **OAuth 2.0**. Choose **Web App, Automated App or Bot** as the type and **Read and write** as the permission.
3. Add the callback URL `https://callables.app/connections/callback` (and `http://localhost:8765/callback` to run it locally), and your website.
4. Copy the **OAuth 2.0 Client ID** and **Client Secret**. Not the API key and secret: those are for the older OAuth 1.0a.
5. Add credits. The X API is pay-per-use.

### 2. Set the secrets

`X_CLIENT_ID` and `X_CLIENT_SECRET`, from step 1.

### 3. Connect

Open **Post on X**. It asks you to **Connect X**, then runs as you.

## Notes

- **Each post costs money.** At the time of writing, about $0.015 for a post and about $0.20 for a post with a link. Check X's current pricing in the Developer Console.
- X sign-ins stay connected: Callables refreshes X's two-hour tokens with the `offline.access` scope.
- Posts over 280 characters need X Premium on the account, and this callable refuses them.
