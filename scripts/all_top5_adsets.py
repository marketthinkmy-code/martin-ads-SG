"""Top 5 ad SET names by paid sales across the ENTIRE Paid Student List.

Dumps the sheet header + which column index was matched for each UTM field,
so the operator can verify we're actually reading UTM Ads Set (col 14) and
not UTM Ads Name (col 15) or Campaign Name (col 13). Then groups by
normalised UTM ad-set value, prints top 5 + a side-by-side sample.
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
    header = values[header_idx]

    print(f"Sheet '{s.cpa.sales_tab}'  ·  header row #{header_idx}  ·  "
          f"data rows: {len(values) - header_idx - 1}\n")

    print("Full header:")
    for i, h in enumerate(header):
        print(f"   col {i:>2}: {h!r}")

    print(f"\nfind_columns matched:")
    for key, idx in cols.items():
        name = header[idx] if 0 <= idx < len(header) else "MISS"
        print(f"   {key:>10}  ->  col {idx:>2}  ({name!r})")

    adset_col = cols.get("adset", -1)
    ad_col = cols.get("ad", -1)
    print(f"\nSanity — first 5 data rows: col {adset_col} (UTM Ads Set) vs col {ad_col} (UTM Ads Name):")
    for i, row in enumerate(values[header_idx + 1:header_idx + 6], 1):
        aset = row[adset_col] if 0 <= adset_col < len(row) else ""
        aname = row[ad_col] if 0 <= ad_col < len(row) else ""
        print(f"   row {i}:  adset={aset!r}  ·  ad={aname!r}")

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
    print(f"\nGrouped by UTM ad SET (col {adset_col}) — {len(ranked)} distinct ad sets · "
          f"{total} matched sales · RM {total_rev:,.0f}\n")

    print(f"{'#':>3} {'sales':>5} {'revenue':>11}  ad set name")
    print("-" * 90)
    for i, (name, cnt) in enumerate(ranked[:5], 1):
        print(f"{i:>3} {cnt:>5} RM {adset_rev[name]:>8,.0f}  {name[:66]}")


if __name__ == "__main__":
    main()
