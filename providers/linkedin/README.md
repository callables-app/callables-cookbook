# LinkedIn

Post to LinkedIn as yourself or as a company page you admin. Each person signs in with their own LinkedIn account. Posting previews first.

It's part of the [Announce](../../recipes/announce/) recipe, which posts to LinkedIn and X and emails your audience in one run.

| Callable | Sign-in | What it does |
|---|---|---|
| **Post on LinkedIn** | `linkedin` | A text post as you, public or to your connections. Links in the text become clickable, and #hashtags work |
| **My LinkedIn pages** | `linkedin_pages` | The company pages you can post as, with your role on each |
| **Post on a LinkedIn page** | `linkedin_pages` | A text post as one of your pages |

There are two sign-ins on one LinkedIn app. LinkedIn approves page access separately, and asking for scopes your app doesn't have yet fails the whole sign-in. So posting as yourself works on day one, and the page sign-in only works once LinkedIn approves it.

LinkedIn's post text has reserved characters (`( ) [ ] { } < > @ # * _ ~ | \`). `escape()` in `linkedin_api.py` handles them, so you write normal text.

## Set it up

### 1. Create a LinkedIn app (once)

1. Open the [LinkedIn Developer Portal](https://www.linkedin.com/developers/apps) and **Create app**. LinkedIn asks for a company page to associate it with. Any page you admin works.
2. On **Products**, add **Sign In with LinkedIn using OpenID Connect** and **Share on LinkedIn**. Both are self-serve.
3. On **Auth**, add the redirect URL `https://callables.app/connections/callback` (and `http://localhost:8765/callback` to run it locally). Copy the **Client ID** and **Client Secret**.
4. To post as a page, also request **Community Management API** on **Products**. LinkedIn reviews the request, which can take a while. Until then, use **Post on LinkedIn**.

### 2. Set the secrets

`LINKEDIN_CLIENT_ID` and `LINKEDIN_CLIENT_SECRET`, from step 1. Both sign-ins use them.

### 3. Connect

Open **Post on LinkedIn**. It asks you to **Connect LinkedIn**, then runs as you.

## Notes

- LinkedIn sign-ins last 60 days and LinkedIn doesn't give ordinary apps refresh tokens, so people reconnect every two months.
- LinkedIn doesn't fetch link previews for posts made through its API, so a link shows as a plain clickable link.
- Posts allow up to 3,000 characters.
