"""Top 5 ad SET names by paid sales across the ENTIRE Paid Student List.

Same shape as all_top15_ads.py but groups by normalised UTM ad-set name.
No country / phone filter — every row with a non-empty UTM ad-set is counted.
"""
from __future__ import annotations

from collections import defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.settings import load_settings


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

    print(f"Sheet '{s.cpa.sales_tab}'  ·  header row #{header_idx}  ·  "
          f"data rows: {len(values) - header_idx - 1}")

    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    adset_sales = defaultdict(int)
    adset_rev = defaultdict(float)
    for sale in sales:
        if not sale.adset:
            continue
        adset_sales[sale.adset] += 1
        adset_rev[sale.adset] += sale.amount

    ranked = sorted(adset_sales.items(), key=lambda kv: -kv[1])
    total = sum(adset_sales.values())
    total_rev = sum(adset_rev.values())
    print(f"\nGrouped by UTM ad SET — {len(ranked)} distinct ad sets · "
          f"{total} matched sales · RM {total_rev:,.0f}\n")

    print(f"{'#':>3} {'sales':>5} {'revenue':>11}  ad set name")
    print("-" * 90)
    for i, (name, cnt) in enumerate(ranked[:5], 1):
        print(f"{i:>3} {cnt:>5} RM {adset_rev[name]:>8,.0f}  {name[:66]}")


if __name__ == "__main__":
    main()
