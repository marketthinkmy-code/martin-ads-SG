"""Top 5 targeting-flavor UTM Ads Sets (col 14) + top 5 Campaign Names (col 13)
across the entire Paid Student List.

The plain top-5 UTM Ads Set list is dominated by ad-set names that the operator
copied from the creative (Video / Hook / Single Image / Carousel / month +
Video). Filter those out so what remains is genuinely audience-defining:
Interest:*, Broad, Lookalike/LAL, Advantage+, Housewife, Parenting, Family,
Retargeting, etc.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, Tuple

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.settings import load_settings

ADSET_COL = 14      # 'UTM Ads Set'      (verified)
CAMPAIGN_COL = 13   # 'Campaign Name'    (find_columns misses this; wired by hand)
AD_COL = 15         # 'UTM Ads Name'
AMOUNT_COL = 7      # 'Purchase amount'

MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul",
          "aug", "sep", "oct", "nov", "dec")
CREATIVE_PREFIXES = (
    "video", "extra video", "single image", "carousel",
    "si1", "si2", "si3", "si4", "si5", "si6",
    "见证", "見證", "自然",
)
CREATIVE_RE_HOOK = re.compile(r"^hook[\s:：\-\d]", re.IGNORECASE)


def is_creative_flavor(name: str) -> bool:
    """True if the ad-set NAME looks like a creative label (video / hook / single image
    / carousel / month + creative)."""
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


def _cell(row, i: int) -> str:
    return row[i].strip() if 0 <= i < len(row) else ""


def main() -> None:
    s = load_settings()
    values = SheetsClient(s.secrets.google_sa_json).read_tab(
        s.cpa.spreadsheet_id, s.cpa.sales_tab)
    if not values:
        print("(sheet is empty)")
        return

    # Locate header row using cpa.find_columns as the anchor.
    header_idx = 0
    for i, row in enumerate(values[:8]):
        cand = cpa.find_columns(row)
        if cand.get("adset", -1) >= 0 and cand.get("ad", -1) >= 0:
            header_idx = i
            break
    header = values[header_idx]
    print(f"Sheet '{s.cpa.sales_tab}' · header row #{header_idx} · "
          f"data rows: {len(values) - header_idx - 1}")
    print(f"Reading: campaign=col {CAMPAIGN_COL} ({header[CAMPAIGN_COL]!r}) · "
          f"adset=col {ADSET_COL} ({header[ADSET_COL]!r}) · "
          f"amount=col {AMOUNT_COL} ({header[AMOUNT_COL]!r})\n")

    # Aggregate
    campaign_sales: Dict[str, int] = defaultdict(int)
    campaign_rev: Dict[str, float] = defaultdict(float)
    adset_sales: Dict[str, int] = defaultdict(int)
    adset_rev: Dict[str, float] = defaultdict(float)
    adset_camps: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

    total_rows = 0
    for row in values[header_idx + 1:]:
        camp = _cell(row, CAMPAIGN_COL)
        aset = _cell(row, ADSET_COL)
        amt = cpa._money(_cell(row, AMOUNT_COL), s.cpa.price_myr) if hasattr(cpa, "_money") else 0
        total_rows += 1
        if camp:
            campaign_sales[camp] += 1
            campaign_rev[camp] += amt
        if aset:
            adset_sales[aset] += 1
            adset_rev[aset] += amt
            if camp:
                adset_camps[aset][camp] += 1

    # Split adsets into targeting-flavor vs creative-flavor
    targeting_sales = {k: v for k, v in adset_sales.items() if not is_creative_flavor(k)}

    print(f"── Distinct counts ─────────────────────────────────────────")
    print(f"  Campaign Names: {len(campaign_sales)}")
    print(f"  UTM Ads Sets  : {len(adset_sales)}  (targeting-flavor: {len(targeting_sales)} · "
          f"creative-flavor: {len(adset_sales) - len(targeting_sales)})\n")

    # ── TOP 5 CAMPAIGN NAMES ────────────────────────────────────────
    print("═" * 90)
    print("TOP 5 — Campaign Name (col 13)")
    print("═" * 90)
    ranked = sorted(campaign_sales.items(), key=lambda kv: -kv[1])
    print(f"{'#':>3} {'sales':>5} {'revenue':>11}  Campaign Name")
    print("-" * 90)
    for i, (name, cnt) in enumerate(ranked[:5], 1):
        print(f"{i:>3} {cnt:>5} RM {campaign_rev[name]:>8,.0f}  {name[:66]}")

    # ── TOP 5 TARGETING-FLAVOR ADSETS ──────────────────────────────
    print("\n" + "═" * 90)
    print("TOP 5 — UTM Ads Set (col 14) — TARGETING-FLAVOR ONLY "
          "(creative names filtered out)")
    print("═" * 90)
    ranked = sorted(targeting_sales.items(), key=lambda kv: -kv[1])
    print(f"{'#':>3} {'sales':>5} {'revenue':>11}  Ad Set Name")
    print("-" * 90)
    for i, (name, cnt) in enumerate(ranked[:5], 1):
        print(f"{i:>3} {cnt:>5} RM {adset_rev[name]:>8,.0f}  {name[:66]}")
        top_camps = sorted(adset_camps[name].items(), key=lambda kv: -kv[1])[:3]
        for camp, camp_cnt in top_camps:
            print(f"       └ {camp_cnt:>3}  in campaign  {camp[:60]}")

    # ── Also dump top 25 targeting-flavor for full picture ─────────
    print("\n" + "═" * 90)
    print("TOP 25 targeting-flavor ad sets (for full picture)")
    print("═" * 90)
    for i, (name, cnt) in enumerate(ranked[:25], 1):
        print(f"{i:>3} {cnt:>5}  {name[:80]}")


if __name__ == "__main__":
    main()
