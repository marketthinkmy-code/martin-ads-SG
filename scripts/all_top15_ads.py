"""Top 15 ad names by paid sales across the ENTIRE Paid Student List.

No country / phone-prefix filter — every row with a non-empty UTM ad name is
counted. Groups by normalised UTM ad name, sums lifetime paid sales +
revenue, prints top 15 (with a phone-prefix breakdown for context).
"""
from __future__ import annotations

import re
from collections import defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.settings import load_settings


def _clean_phone(raw: str) -> str:
    return re.sub(r"[^\d+]", "", raw or "").lstrip("+")


def _hkey(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").casefold())


def _find_phone_col(header) -> int:
    keys = [_hkey(h) for h in header]
    for needle in ("phone", "phonenumber", "mobile", "whatsapp", "wsn", "contact"):
        for i, k in enumerate(keys):
            if needle in k:
                return i
    return -1


def main() -> None:
    s = load_settings()
    values = SheetsClient(s.secrets.google_sa_json).read_tab(
        s.cpa.spreadsheet_id, s.cpa.sales_tab)
    if not values:
        print("(sheet is empty)")
        return

    header_idx, cols = 0, cpa.find_columns(values[0])
    for i, row in enumerate(values[:8]):
        cand = cpa.find_columns(row)
        if cand.get("campaign", -1) >= 0 and cand.get("ad", -1) >= 0:
            header_idx, cols = i, cand
            break
    header = values[header_idx]
    phone_col = _find_phone_col(header)

    print(f"Sheet '{s.cpa.sales_tab}'  ·  header row #{header_idx}  ·  "
          f"data rows: {len(values) - header_idx - 1}")

    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)

    # ---- aggregate ---------------------------------------------------------
    name_sales = defaultdict(int)
    name_rev = defaultdict(float)
    for sale in sales:
        if not sale.ad:
            continue
        name_sales[sale.ad] += 1
        name_rev[sale.ad] += sale.amount

    # ---- phone-prefix breakdown for the whole sheet (context) -------------
    prefix_hist = defaultdict(int)
    for row in values[header_idx + 1:]:
        raw = row[phone_col] if 0 <= phone_col < len(row) else ""
        p = _clean_phone(raw)
        prefix_hist[(p[:2] or "∅")] += 1

    tag = {"65": "SG", "60": "MY", "01": "MY-local", "85": "HK", "61": "AU",
           "62": "ID", "66": "TH", "67": "MY-Sarawak", "88": "BN"}
    print("\nRows by phone-prefix (top 8):")
    for p, n in sorted(prefix_hist.items(), key=lambda kv: -kv[1])[:8]:
        print(f"   {p:>3}: {n:>4}  {'← ' + tag[p] if p in tag else ''}")

    ranked = sorted(name_sales.items(), key=lambda kv: -kv[1])
    total = sum(name_sales.values())
    total_rev = sum(name_rev.values())
    print(f"\nGrouped by UTM ad name — {len(ranked)} distinct names · "
          f"{total} matched sales · RM {total_rev:,.0f}\n")

    print(f"{'#':>3} {'sales':>5} {'revenue':>11}  ad name")
    print("-" * 90)
    for i, (name, cnt) in enumerate(ranked[:15], 1):
        print(f"{i:>3} {cnt:>5} RM {name_rev[name]:>8,.0f}  {name[:66]}")


if __name__ == "__main__":
    main()
