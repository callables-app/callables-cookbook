"""Sets your Gmail signature to the company's (see brand/signature.py), through the Gmail API.

Unlike Outlook, Gmail lets apps set the signature, so there's nothing to paste: run it and new emails have it.
"""
from typing import Literal

from brand.signature import COMPANY, page, plain, render
from callables import save_file
from google.gmail.gmail_api import Gmail
from google.gmail.inbox import gmail, google

MAX_SIGNATURE = 10_000  # characters Gmail takes in a signature


@gmail.deploy(title="Set my Gmail signature", timeout=60)
def set_signature(style: Literal["classic", "compact"] = "classic", name: str = "", job_title: str = "",
                  department: str = "", phone: str = "", save_to_gmail: bool = True) -> str:
    """Your signature in the company's style, set in Gmail for you. Your name and address come from Gmail; add your
    job title and phone to include them. Turn off "save to Gmail" to only preview it. Your old signature is kept as a
    download, in case you want it back."""
    client = Gmail(google.token)
    account = client.send_as()
    address = account.get("sendAsEmail", "")
    person = {
        "name": name.strip() or account.get("displayName") or "",
        "title": job_title.strip(),
        "department": department.strip(),
        "phone": phone.strip(),
        "email": address,
    }
    if not person["name"]:
        raise ValueError("Gmail has no name for your address. Type the name to use.")

    signature = render(person, style)
    if len(signature) > MAX_SIGNATURE:
        raise ValueError(f"The signature is {len(signature):,} characters and Gmail takes {MAX_SIGNATURE:,}. "
                         "Shorten the name or job title, or use the compact style.")
    save_file(page(signature), name=f"{COMPANY['name']} signature.html")
    left_out = [label for key, label in (("title", "job title"), ("phone", "phone number")) if not person[key]]
    note = (f"\n\nIt has no {' or '.join(left_out)}: Gmail doesn't know {'them' if len(left_out) > 1 else 'it'}. "
            f"Fill {'them' if len(left_out) > 1 else 'it'} in above and run again to add {'them' if len(left_out) > 1 else 'it'}."
            if left_out else "")

    if not save_to_gmail:
        return (f"**Preview only:** this is the **{style}** signature for {address}. Download "
                f"**{COMPANY['name']} signature.html** to see it, then run again with \"save to Gmail\" on to use it.{note}")

    old = account.get("signature") or ""
    if old == signature:
        return f"Your Gmail signature for {address} is already this one. Nothing changed.{note}"
    if old:
        save_file(page(old, "Previous signature"), name="Previous signature.html")
    client.set_signature(address, signature)
    kept = ("\n\nYour old signature is in **Previous signature.html**: to go back, open it, copy everything, and paste "
            "it into Gmail's Settings → General → Signature.") if old else ""
    return f"""Your Gmail signature for **{address}** is now the **{style}** {COMPANY['name']} one. New emails you write \
in Gmail have it.{note}{kept}

### Check it in Gmail

Open Gmail's **Settings → See all settings → General → Signature**. Under **Signature defaults**, make sure it's picked \
for new emails and for replies and forwards (Gmail keeps your earlier choice). The Gmail app on your phone uses its own \
mobile signature, which you set in the app.

### Plain text version

For plain-text emails:

```
{plain(person)}
```"""
