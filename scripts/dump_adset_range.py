"""Dump UTM Ads Set (col 14) for a row range of the Paid Student List.

Interpret row numbers as Google-Sheets-style 1-indexed (row 1 = header),
so ROW_START=939 means the value in the spreadsheet's row 939 cell.
"""
from __future__ import annotations

from collections import defaultdict

from adbot.clients.sheets import SheetsClient
from adbot.settings import load_settings

ROW_START = 939     # inclusive, 1-indexed (Google Sheets row number)
ROW_END = 1209      # inclusive
ADSET_COL = 14      # col 14 = 'UTM Ads Set' (verified earlier)


def main() -> None:
    s = load_settings()
    values = SheetsClient(s.secrets.google_sa_json).read_tab(
        s.cpa.spreadsheet_id, s.cpa.sales_tab)
    if not values:
        print("(sheet is empty)")
        return

    print(f"Sheet '{s.cpa.sales_tab}' · total rows in returned range: {len(values)}")
    print(f"Requested Google-Sheets rows {ROW_START}..{ROW_END} (inclusive)\n")

    # Slice using 0-indexed Python indices (sheet row N -> values[N-1]).
    lo = ROW_START - 1
    hi = ROW_END          # slice exclusive end
    subset = values[lo:hi]
    print(f"Extracted {len(subset)} rows (indexes {lo}..{hi - 1})\n")

    # Row-by-row dump
    print(f"{'sheet_row':>10}  UTM Ads Set (col {ADSET_COL})")
    print("-" * 90)
    for i, row in enumerate(subset):
        sheet_row = ROW_START + i
        val = row[ADSET_COL] if 0 <= ADSET_COL < len(row) else ""
        print(f"{sheet_row:>10}  {val}")

    # Grouped counts
    counts = defaultdict(int)
    for row in subset:
        val = (row[ADSET_COL] if 0 <= ADSET_COL < len(row) else "").strip()
        counts[val] += 1

    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    print(f"\n== Grouped ({len(ranked)} distinct values, incl blanks) ==\n")
    print(f"{'count':>5}  UTM Ads Set")
    print("-" * 90)
    for val, cnt in ranked:
        shown = val if val else "(blank)"
        print(f"{cnt:>5}  {shown}")


if __name__ == "__main__":
    main()
