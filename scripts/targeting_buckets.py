"""Classify every sale into a targeting bucket by scanning BOTH Campaign Name
(col 13) and UTM Ads Set (col 14).

Operator-embedded targeting: campaigns are often named like
"[SG] 儿童长高方程式 - 3 - Interest: Family and Relationships - 17/10/2025"
where the ad-set-flavor lives inside the campaign name — not the UTM Ads Set
column, which is often either blank or a creative title.

The classifier looks at the concatenated (campaign + adset) text and buckets
the sale into the first matching category. Buckets are ordered specific →
generic so, e.g., "Advantage+ Parents" wins over the bare "Advantage+".
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.settings import load_settings

SOURCE_COL = 12     # 'source '  — operator also embeds targeting like "webinar_jul30 High income job- 30-50 MY - Manual placement" here
CAMPAIGN_COL = 13   # 'Campaign Name'
ADSET_COL = 14      # 'UTM Ads Set'

# (bucket label, list of lowercase substrings — ALL must appear, in any order)
BUCKETS: list[tuple[str, list[str]]] = [
    ("Interest: Family and Relationships",  ["family", "relationship"]),
    ("Interest: Food and Drink + Milk",     ["food", "drink", "milk"]),
    ("Interest: Food and Drink",            ["food", "drink"]),
    ("Interest: Business & Industry",       ["business", "industry"]),
    ("Interest: Parenting match healthy",   ["parenting", "healthy"]),
    ("Interest: Parenting match healthy",   ["parents match healthy"]),
    ("Interest: Parenting",                 ["parenting"]),
    ("Interest: Parents (bare)",            ["parents"]),
    ("Interest: Milk & Bread",              ["milk", "bread"]),
    ("Interest: Health & Wellness",         ["health", "wellness"]),
    ("Interest: Housewife",                 ["housewife"]),
    ("Interest: Luxury",                    ["luxury"]),
    ("Interest: Kids/Children",             ["kids related"]),
    ("Interest: Kids/Children",             ["children"]),
    ("Interest: Sports & Outdoors",         ["sports"]),
    ("Interest: Beauty",                    ["beauty"]),
    ("Interest: Education / Tuition",       ["tuition"]),
    ("Interest: Education / Tuition",       ["international school"]),
    ("Interest: Education / Tuition",       ["education"]),
    ("Interest: High Income Job",           ["high income"]),
    ("Interest: Travel",                    ["travel"]),
    ("Interest: Fastfood/Foodie",           ["fast food"]),
    ("Interest: Fastfood/Foodie",           ["fastfood"]),
    ("Interest: Fastfood/Foodie",           ["foodie"]),
    ("Interest: TVB/Astro/FM",              ["tvb"]),
    ("Interest: TVB/Astro/FM",              ["astro"]),
    ("Interest: Coffee/Tea",                ["coffee", "tea"]),
    ("Interest: Day care / Kid education",  ["day care"]),
    ("Interest: Kid Education",             ["kid education"]),
    ("Interest: Cartoon",                   ["cartoon"]),
    ("Interest: Bio / Ig Bio",              ["ig bio"]),
    ("Interest: Bio / Ig Bio",              ["martinigbio"]),
    ("Lookalike (Cust List)",               ["lookalike"]),
    ("Lookalike (Cust List)",               ["lal ", "cust list"]),
    ("Retargeting / RET",                   ["retargeting"]),
    ("Retargeting / RET",                   ["ret video"]),
    ("Video Viewers",                       ["video view"]),
    ("Reactivate Old Leads",                ["reactivate"]),
    ("Purchase List",                       ["purchase list"]),
    ("Height Anxiety",                      ["height anxiety"]),
    ("Advantage+ Shopping",                 ["advantage+", "shopping"]),
    ("Advantage+ Shopping",                 ["advantage plus", "shopping"]),
    ("Advantage+ Sales",                    ["advantage+", "sales"]),
    ("Advantage+ Parents + Engaged",        ["advantage", "parents", "engaged"]),
    ("Advantage+ (bare)",                   ["advantage+"]),
    ("Advantage+ (bare)",                   ["advantage plus"]),
    ("Broad",                               ["broad"]),
    ("Manual placement",                    ["manual placement"]),
    ("Meta Andro",                          ["meta andro"]),
    ("FB tag (fb/fbmsg/ig)",                ["fbmsg"]),
    ("FB tag (fb/fbmsg/ig)",                [" fb "]),
    ("FB tag (fb/fbmsg/ig)",                [" ig "]),
    ("Milk (bare)",                         [" milk"]),
    ("Bread (bare)",                        [" bread"]),
]


def classify(source: str, camp: str, aset: str) -> Optional[str]:
    """Return the first bucket whose substring set is fully present in the
    combined (source + campaign + adset) text; None if nothing matches."""
    combined = f" {(source or '').lower()} | {(camp or '').lower()} | {(aset or '').lower()} "
    for label, needles in BUCKETS:
        if all(n in combined for n in needles):
            return label
    return None


def _cell(row, i: int) -> str:
    return row[i].strip() if 0 <= i < len(row) else ""


def main() -> None:
    s = load_settings()
    values = SheetsClient(s.secrets.google_sa_json).read_tab(
        s.cpa.spreadsheet_id, s.cpa.sales_tab)
    if not values:
        print("(sheet empty)"); return

    header_idx = 0
    for i, row in enumerate(values[:8]):
        cand = cpa.find_columns(row)
        if cand.get("adset", -1) >= 0:
            header_idx = i
            break

    data = values[header_idx + 1:]
    total = len(data)

    bucket_counts: dict[str, int] = defaultdict(int)
    bucket_examples: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    unclassified: list[tuple[str, str, str]] = []
    all_blank = 0

    for row in data:
        source = _cell(row, SOURCE_COL)
        camp = _cell(row, CAMPAIGN_COL)
        aset = _cell(row, ADSET_COL)
        if not source and not camp and not aset:
            all_blank += 1
            continue
        label = classify(source, camp, aset)
        if label is None:
            unclassified.append((source, camp, aset))
        else:
            bucket_counts[label] += 1
            if len(bucket_examples[label]) < 3:
                bucket_examples[label].append((source, camp, aset))

    classified = sum(bucket_counts.values())
    unclass = len(unclassified)

    print(f"═════════════════════════════════════════════════════════════════════════════════")
    print(f" TARGETING-BUCKET breakdown across {total} rows")
    print(f"═════════════════════════════════════════════════════════════════════════════════")
    print(f"  All 3 cols (source/camp/adset) BLANK: {all_blank:>4}  ({all_blank/total*100:>4.1f}%)")
    print(f"  Classified into a bucket:             {classified:>4}  ({classified/total*100:>4.1f}%)")
    print(f"  Unclassified (some text):             {unclass:>4}  ({unclass/total*100:>4.1f}%)  ← name doesn't hit any known targeting keyword")
    print()

    ranked = sorted(bucket_counts.items(), key=lambda kv: -kv[1])
    print(f"═════════════════════════════════════════════════════════════════════════════════")
    print(f" TOP TARGETING BUCKETS  (scanned source + Campaign Name + UTM Ads Set)")
    print(f"═════════════════════════════════════════════════════════════════════════════════")
    print(f"{'#':>3} {'sales':>5}  bucket  (top-3 raw source/camp/adset shown for verification)")
    print("-" * 90)
    for i, (label, cnt) in enumerate(ranked, 1):
        print(f"{i:>3} {cnt:>5}  {label}")
        for src, camp, aset in bucket_examples[label]:
            print(f"           ↳  src  ={src[:60]!r}")
            print(f"              camp ={camp[:60]!r}")
            print(f"              adset={aset[:60]!r}")

    print()
    print(f"═════════════════════════════════════════════════════════════════════════════════")
    print(f" TOP 20 UNCLASSIFIED (raw triples) — audit for missing buckets")
    print(f"═════════════════════════════════════════════════════════════════════════════════")
    unclass_counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for src, camp, aset in unclassified:
        unclass_counts[(src, camp, aset)] += 1
    top_unclass = sorted(unclass_counts.items(), key=lambda kv: -kv[1])[:20]
    for (src, camp, aset), cnt in top_unclass:
        print(f"  {cnt:>3}  src={src[:40]!r}  ·  camp={camp[:40]!r}  ·  adset={aset[:30]!r}")


if __name__ == "__main__":
    main()
