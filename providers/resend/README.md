# Resend

Email your audience with [Resend](https://resend.com): list your segments and templates, and send a template to a segment as a broadcast. Sending previews first.

It's part of the [Announce](../../recipes/announce/) recipe, which posts to LinkedIn and X and then emails a segment with links to the posts.

| Callable | What it does |
|---|---|
| **Segments** | Your segments: the groups of contacts a broadcast goes to |
| **Templates** | Your templates, with the variables each takes and their fallbacks |
| **Send email to a segment** | A broadcast to a segment from one of your templates. **Variables** fill its `{{{KEYS}}}` (`KEY=value; KEY2=value`), and **Send at** schedules it (`in 1 hour`, or an ISO time) |
| **Broadcasts** | Your broadcasts, with their status and when they were sent or scheduled |

Resend's API can't send a broadcast from a template; only single emails can use one. So **Send email to a segment** fetches the template, fills its variables, and sends the result as the broadcast. Per-person placeholders like `{{{contact.first_name|there}}}` and the unsubscribe link are left for Resend to fill for each contact. If the template has no unsubscribe link, a small one is added at the bottom.

## Set it up

1. In Resend, verify the domain you send from (**Domains**).
2. Create an API key with **Full access** (**API Keys**). Sending-only keys can't create broadcasts or read templates.
3. Add your contacts to a segment (**Audience > Segments**), and make a template (**Templates**).
4. In the project's secrets, set `RESEND_API_KEY`, and `RESEND_FROM` as the default sender, like `Dan <dan@example.com>`. A sender set on the template, or **From address** on a run, wins over it.

## Run locally

Put the secrets in `.env` at the top of the repo, then:

    pip install callables -r requirements.txt
    call resend templates
    call resend send_broadcast --template launch --segment Newsletter --variables "TITLE=We shipped"

That's a dry run. Add `--no-dry-run` to send.
