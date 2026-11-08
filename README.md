# Callables Cookbook

Complete, working automations for [Callables](https://callables.app). Each one solves a real problem and is written up in a guide.

Each top-level folder is a topic and deploys as its own Callables project, with its own `requirements.txt` and secrets.

| Folder | Topic |
|---|---|
| [`email/`](email/) | Parsing inboxes and attachments, starting with Outlook |
| [`gmail/`](gmail/) | Your own Gmail inbox: summaries, top senders, bulk archive. Shows connections, where each person uses their own account |
| [`salesforce/`](salesforce/) | Salesforce automations |

## Deploy a topic

1. Fork this repo.
2. In Callables, open **New project** and pick your fork.
3. Set **Folder** to the topic, such as `email`. If you forget, change it on the project page afterwards.
4. Set the secrets listed in that folder's README.

## Run one locally

    pip install callables
    pip install -r email/requirements.txt
    call local --root email <function_name>
