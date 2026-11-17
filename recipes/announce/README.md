# Announce

Post to LinkedIn and X, then email your audience through Resend with links to both posts, in one run. Write it once, preview everything with a dry run, then untick **Dry run** to post and send.

Your team runs it from a form. Connect Claude, ChatGPT or Cursor to the [Callables MCP server](https://callables.app/docs/mcp) and an assistant can draft the posts, run the dry run for you to check, and send it when you say so.

| Callable | What it does |
|---|---|
| **Post everywhere** | Post to LinkedIn and X as yourself, then send a Resend broadcast to a segment, built from your Resend template with the new posts' links filled in. Untick any of **Post linkedin**, **Post x** and **Email** to skip it |
| **Post everywhere as a page** | The same, with LinkedIn posting as a company page you admin. Needs LinkedIn's approval for page posting (see [LinkedIn](../../providers/linkedin/)) |

**X text** replaces the text on X, so a long LinkedIn post can have a short X version. X allows 280 characters and counts every link as 23.

The email fills these variables in your Resend template, besides any you pass in **Variables** (`KEY=value; KEY2=value`):

| Variable | Filled with |
|---|---|
| `{{{LINKEDIN_URL}}}` | The new LinkedIn post's link (empty if you skip LinkedIn) |
| `{{{X_URL}}}` | The new X post's link (empty if you skip X) |
| `{{{POST_TEXT}}}` | The post's text |

If a post fails, the email isn't sent. The result says what went wrong and offers **Send the email** with the template, segment and links already filled in, so nothing gets posted twice.

The single-network callables are in their own folders, for posting to just one:

| Folder | Group | What's in it |
|---|---|---|
| [`providers/linkedin/`](../../providers/linkedin/) | LinkedIn | Post as yourself, post as a page, list your pages |
| [`providers/x/`](../../providers/x/) | X | Post (or reply, for a thread) |
| [`providers/resend/`](../../providers/resend/) | Resend | Segments, templates with their variables, broadcasts, and sending a template to a segment |

## How it's built

    providers/linkedin/linkedin_api.py   the client: who's signed in, your pages, posts (with LinkedIn's text escaping)
    providers/linkedin/review.py         the linkedin and linkedin_pages connections, and the callables
    providers/x/x_api.py                 the client: who's signed in, posts, X's character counting
    providers/x/review.py                the x connection and the callable
    providers/resend/resend_api.py       the client: segments, templates, broadcasts, and filling a template's variables
    providers/resend/review.py           the callables, and prepare_broadcast() for recipes
    recipes/announce/announce.py         the announce group: posts, then emails
    recipes/announce/callables.toml      include: the three provider folders, for Folder = recipes/announce

Resend's API can't send a broadcast from a template; only single emails can use one. So the run fetches the template, fills its variables, and sends the result as the broadcast. Per-person placeholders like `{{{contact.first_name|there}}}` and the unsubscribe link are left for Resend to fill. `{{{FIRST_NAME}}}`, `{{{LAST_NAME}}}`, `{{{EMAIL}}}` and `{{{UNSUBSCRIBE_URL}}}` in a template are converted to the broadcast spelling. If the template has no unsubscribe link, a small one is added at the bottom.

## Set it up

### Deploy it

Just this recipe: fork the cookbook, open **New project** in Callables, pick your fork and set **Folder** to `recipes/announce`. Or deploy the whole cookbook with **Folder** empty.

### LinkedIn, X and Resend

Each provider's README has the steps:

1. [LinkedIn](../../providers/linkedin/#set-it-up): a LinkedIn app, then `LINKEDIN_CLIENT_ID` and `LINKEDIN_CLIENT_SECRET`.
2. [X](../../providers/x/#set-it-up): an X app with OAuth 2.0 and some credits, then `X_CLIENT_ID` and `X_CLIENT_SECRET`.
3. [Resend](../../providers/resend/#set-it-up): `RESEND_API_KEY` (full access), `RESEND_FROM`, a segment and a template.

### Make the email template

In Resend, open **Templates** and make one with the variables `LINKEDIN_URL`, `X_URL` and `POST_TEXT` (plus any of your own), for example:

```html
<p>Hi {{{contact.first_name|there}}},</p>
<p>{{{POST_TEXT}}}</p>
<p>Join the conversation on <a href="{{{LINKEDIN_URL}}}">LinkedIn</a> or <a href="{{{X_URL}}}">X</a>.</p>
<p><a href="{{{RESEND_UNSUBSCRIBE_URL}}}">Unsubscribe</a></p>
```

To link a blog post, pass `BLOG_URL=https://...; BLOG_TITLE=...` in **Variables** and wrap that part of the template in an optional section, which is dropped when there's no blog post (see [Resend](../../providers/resend/)):

```html
<!--if:BLOG_URL--><p>On the blog: <a href="{{{BLOG_URL}}}">{{{BLOG_TITLE|Read the post}}}</a></p><!--endif:BLOG_URL-->
```

Wrap the LinkedIn and X links the same way (`<!--if:X_URL-->...<!--endif:X_URL-->`), so a network you skip doesn't leave an empty link. **Templates** in the Resend group lists your templates and the variables each takes.

## Run locally

Put the secrets in `.env` at the top of the repo, add `http://localhost:8765/callback` as a redirect URL on the LinkedIn and X apps, then:

    pip install callables -r requirements.txt
    call connect linkedin
    call connect x
    call announce post_everywhere --text "We just shipped include" --template launch --segment Newsletter

That's a dry run. Add `--no-dry-run` to post and send.

## Notes

- **X costs money per post.** The X API is pay-per-use. At the time of writing a post costs about $0.015, and a post containing a link about $0.20. The dry run shows which one you're about to pay.
- **LinkedIn sign-ins last 60 days.** LinkedIn doesn't give ordinary apps refresh tokens, so you'll be asked to reconnect every two months.
- A broadcast goes to everyone subscribed in the segment, and Resend handles unsubscribes.
