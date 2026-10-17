import os
import time
from datetime import date, timedelta
from typing import Literal

from shipfn import deploy


@deploy(title="Hello", description="Says hello. The smallest possible automation.")
def hello(name: str = "world") -> str:
    return f"# Hello, {name}!\n\nThis ran in a Shipfn sandbox."


@deploy(
    title="Weekly sales report",
    secrets=["SALES_API_TOKEN"],
    schedule="0 9 * * MON",
    timeout=120,
)
def weekly_report(region: Literal["NA", "EMEA", "APAC"] = "NA", days: int = 7) -> list[dict]:
    """Fake deals for the last N days in a region, as a table."""
    token = os.environ.get("SALES_API_TOKEN", "")
    print(f"Pulling {days} days of deals for {region} (token set: {bool(token)})")
    rows = []
    for i in range(days):
        print(f"  day {i + 1}/{days}")
        time.sleep(0.2)
        rows.append({
            "date": (date.today() - timedelta(days=i)).isoformat(),
            "region": region,
            "deals": (i * 7 + len(region)) % 11,
            "revenue_usd": ((i * 7 + len(region)) % 11) * 1250,
        })
    return rows


@deploy(title="Invoice lookup")
def invoice_lookup(invoice_id: str, include_lines: bool = False, as_of: date | None = None) -> dict:
    """Look up one invoice by id."""
    result = {"invoice_id": invoice_id, "status": "paid", "amount_usd": 4200, "as_of": (as_of or date.today()).isoformat()}
    if include_lines:
        result["lines"] = 3
    return result


@deploy(title="Always fails")
def always_fails(reason: str = "on purpose") -> None:
    """Raises, so you can see how failures look."""
    print("about to fail...")
    raise RuntimeError(f"Failed {reason}")
