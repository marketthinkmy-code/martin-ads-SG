"""Full breakdown of where every Paid Student List sale lands on UTM Ads Set.

Answers: "if the top 3 targeting-flavor adsets only sum to 95 sales, where did
the other ~1000 go?" Shows total row count, blank counts, and prints every
distinct UTM Ads Set with a [TARGETING] / [CREATIVE] label so the operator
can see the full distribution.
"""
from __future__ import annotations

import re
from collections import defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.settings import load_settings

ADSET_COL = 14

MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul",
          "aug", "sep", "oct", "nov", "dec")
CREATIVE_PREFIXES = (
    "video", "extra video", "single image", "carousel",
    "si1", "si2", "si3", "si4", "si5", "si6",
    "见证", "見證", "自然", "懒人包", "懶人包", "tc ",
)
CREATIVE_RE_HOOK = re.compile(r"^hook[\s:：\-\d]", re.IGNORECASE)


def is_creative(name: str) -> bool:
    n = (name or "").strip().lower()
    if not n:
        return False
    if n.startswith(CREATIVE_PREFIXES):
        return True
    if CREATIVE_RE_HOOK.match(n):
        return True
    for m in MONTHS:
        if n.startswith(m + " "):
            rest = n[len(m) + 1:]
            if rest.startswith(("video", "hook", "single", "carousel",
                                 "si1", "si2", "si3", "si4", "si5", "si6",
                                 "extra")):
                return True
    return False


def main() -> None:
    s = load_settings()
    values = SheetsClient(s.secrets.google_sa_json).read_tab(
        s.cpa.spreadsheet_id, s.cpa.sales_tab)
    if not values:
        print("(sheet empty)"); return

    # Find header row
    header_idx = 0
    for i, row in enumerate(values[:8]):
        cand = cpa.find_columns(row)
        if cand.get("adset", -1) >= 0:
            header_idx = i
            break

    data = values[header_idx + 1:]
    total_rows = len(data)

    # Bucket each row
    counts = defaultdict(int)   # adset name (raw, incl blank) -> count
    for row in data:
        val = row[ADSET_COL].strip() if 0 <= ADSET_COL < len(row) else ""
        counts[val] += 1

    blank = counts.pop("", 0)
    matched = total_rows - blank
    creative_names = {k: v for k, v in counts.items() if is_creative(k)}
    targeting_names = {k: v for k, v in counts.items() if not is_creative(k)}
    creative_sum = sum(creative_names.values())
    targeting_sum = sum(targeting_names.values())

    print(f"═════════════════════════════════════════════════════════════════════════════════")
    print(f" WHERE THE {total_rows} PAID STUDENT LIST ROWS LAND ON UTM Ads Set (col 14)")
    print(f"═════════════════════════════════════════════════════════════════════════════════")
    print(f"  Total rows:                  {total_rows}")
    print(f"  ├─ BLANK UTM Ads Set:        {blank:>4}  ({blank/total_rows*100:>4.1f}%)  ← cannot attribute")
    print(f"  └─ Filled UTM Ads Set:       {matched:>4}  ({matched/total_rows*100:>4.1f}%)")
    print(f"       ├─ CREATIVE-flavor:     {creative_sum:>4}  ({creative_sum/total_rows*100:>4.1f}%)"
          f"  · {len(creative_names)} distinct names")
    print(f"       └─ TARGETING-flavor:    {targeting_sum:>4}  ({targeting_sum/total_rows*100:>4.1f}%)"
          f"  · {len(targeting_names)} distinct names")
    print()

    # Full ranking with labels
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    print(f"═════════════════════════════════════════════════════════════════════════════════")
    print(f" ALL {len(ranked)} DISTINCT UTM Ads Set VALUES — ranked by sales count")
    print(f"═════════════════════════════════════════════════════════════════════════════════")
    print(f"{'#':>3} {'sales':>5} {'kind':<10}  UTM Ads Set")
    print("-" * 90)
    for i, (name, cnt) in enumerate(ranked, 1):
        kind = "[CREATIVE]" if is_creative(name) else "[TARGET]  "
        print(f"{i:>3} {cnt:>5} {kind}  {name[:66]}")


if __name__ == "__main__":
    main()
