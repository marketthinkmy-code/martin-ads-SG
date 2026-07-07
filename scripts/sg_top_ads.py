"""Read-only: top ad names ranked by SG paid sales.

The Paid Student List is shared across MY / SG / BRUNEI and has no country
column, so we filter to Singapore by phone-number prefix (+65). Groups by UTM
ad name, sums lifetime paid sales + revenue, prints the top 25.
"""
from __future__ import annotations

import re
from collections import defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.settings import load_settings

PHONE_HEADERS = (
    "phone", "phonenumber", "phoneno", "mobile", "mobilenumber", "mobileno",
    "contact", "contactnumber", "contactno", "tel", "telephone",
    "whatsapp", "wa", "wsn", "whatsappnumber",
)


def _hkey(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").casefold())


def _find_phone_col(header) -> int:
    keys = [_hkey(h) for h in header]
    for needle in PHONE_HEADERS:          # exact-ish match
        for i, k in enumerate(keys):
            if k == needle:
                return i
    for needle in ("phone", "mobile", "whatsapp", "contact"):   # substring
        for i, k in enumerate(keys):
            if needle in k:
                return i
    return -1


def _is_sg(phone_raw: str) -> bool:
    """Singapore country code is 65. Strip everything but digits + leading '+'."""
    phone = re.sub(r"[^\d+]", "", phone_raw or "").lstrip("+")
    return phone.startswith("65")


def main() -> None:
    s = load_settings()
    values = SheetsClient(s.secrets.google_sa_json).read_tab(
        s.cpa.spreadsheet_id, s.cpa.sales_tab)
    if not values:
        print("(sheet is empty)")
        return

    # Find header row (first row that exposes both campaign + ad UTM cols).
    header_idx, cols = 0, cpa.find_columns(values[0])
    for i, row in enumerate(values[:8]):
        candidate = cpa.find_columns(row)
        if candidate.get("campaign", -1) >= 0 and candidate.get("ad", -1) >= 0:
            header_idx, cols = i, candidate
            break
    header = values[header_idx]
    phone_col = _find_phone_col(header)

    print(f"Sheet '{s.cpa.sales_tab}'  ·  header row #{header_idx}  ·  "
          f"total data rows: {len(values) - header_idx - 1}")
    if phone_col == -1:
        print("!!! could not find a phone column in the header — dumping header for triage:")
        for i, h in enumerate(header):
            print(f"   col {i:>2}: {h!r}")
        print("(aborting — nothing to filter on)")
        return
    print(f"Phone column: #{phone_col} ({header[phone_col]!r})")

    # Filter to SG rows by phone prefix.
    sg_rows = [header]
    prefix_hist = defaultdict(int)
    for row in values[header_idx + 1:]:
        phone_raw = row[phone_col] if phone_col < len(row) else ""
        cleaned = re.sub(r"[^\d+]", "", phone_raw or "").lstrip("+")
        prefix = cleaned[:2] if cleaned else "∅"
        prefix_hist[prefix] += 1
        if _is_sg(phone_raw):
            sg_rows.append(row)

    print(f"\nRows by phone-prefix (top 8):")
    for p, n in sorted(prefix_hist.items(), key=lambda kv: -kv[1])[:8]:
        tag = "  ← SG" if p == "65" else ("  ← MY" if p == "60" else "")
        print(f"   {p:>3}: {n:>4}{tag}")

    sg_data_rows = len(sg_rows) - 1
    print(f"\nSG rows (phone starts with 65): {sg_data_rows}\n")

    sales, _c, _h = cpa.parse_sales(sg_rows, s.cpa.price_myr)
    name_sales = defaultdict(int)
    name_rev = defaultdict(float)
    for sale in sales:
        if not sale.ad:
            continue
        name_sales[sale.ad] += 1
        name_rev[sale.ad] += sale.amount

    ranked = sorted(name_sales.items(), key=lambda kv: -kv[1])
    total_sg = sum(name_sales.values())
    total_rev = sum(name_rev.values())
    print(f"Grouped by UTM ad name — {len(ranked)} distinct names · "
          f"{total_sg} matched sales · RM {total_rev:,.0f}\n")

    print(f"{'#':>3} {'sales':>5} {'revenue':>11}  ad name")
    print("-" * 90)
    for i, (name, cnt) in enumerate(ranked[:25], 1):
        print(f"{i:>3} {cnt:>5} RM {name_rev[name]:>8,.0f}  {name[:66]}")

    unnamed = sum(1 for sale in sales if not sale.ad)
    if unnamed:
        print(f"\n(SG rows with blank UTM ad name — not ranked: {unnamed})")


if __name__ == "__main__":
    main()
