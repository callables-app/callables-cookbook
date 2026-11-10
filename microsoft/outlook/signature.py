"""An email signature in the company's style (see brand/signature.py), filled in from each person's Microsoft 365 profile.

Microsoft Graph can't set an Outlook signature (there's no API for it), so this hands back the signature as a file to
open and paste into Outlook's signature settings, which keeps the formatting.
"""
from typing import Literal

from brand.signature import COMPANY, missing_note, page, plain, render
from callables import save_file
from microsoft.outlook.graph_api import Graph
from microsoft.outlook.inbox import mail, outlook

PROFILE = "displayName,jobTitle,department,mail,userPrincipalName,mobilePhone,businessPhones,officeLocation"


@mail.deploy(title="Make my email signature", timeout=60)
def make_signature(style: Literal["classic", "compact"] = "classic", name: str = "", job_title: str = "",
                   phone: str = "") -> str:
    """Your signature in the company's style, filled in from your Microsoft 365 profile, ready to paste into Outlook.
    Leave a field blank to use your profile; fill it in to use something else."""
    profile = Graph(outlook.token).me(PROFILE)
    person = {
        "name": name.strip() or profile.get("displayName") or "",
        "title": job_title.strip() or profile.get("jobTitle") or "",
        "department": profile.get("department") or "",
        "phone": phone.strip() or profile.get("mobilePhone") or next(iter(profile.get("businessPhones") or []), ""),
        "email": profile.get("mail") or profile.get("userPrincipalName") or "",
        "office": profile.get("officeLocation") or "",
    }
    if not person["name"]:
        raise ValueError("Your Microsoft profile has no name. Type the name to use.")

    save_file(page(render(person, style)), name=f"{COMPANY['name']} signature.html")
    note = missing_note(person)
    return f"""Your **{style}** signature is ready: download **{COMPANY['name']} signature.html** below.{note}

### Put it in Outlook

Outlook doesn't let apps set your signature, so it takes one paste:

1. Open the downloaded file in your browser, press **Ctrl+A** then **Ctrl+C** (on a Mac, **⌘A** then **⌘C**).
2. In Outlook:
   - **New Outlook and Outlook on the web:** Settings → Account → Signatures
   - **Classic Outlook for Windows:** File → Options → Mail → Signatures
   - **Outlook for Mac:** Outlook → Settings → Signatures
3. Create a signature, paste it in, choose it for new messages and replies, and save.

### Plain text version

For plain-text emails:

```
{plain(person)}
```"""
