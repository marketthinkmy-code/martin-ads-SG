"""JOIN the Paid Student List conversion ranking (which audiences convert most)
with the REAL Meta Detailed-Targeting spec (what interests/behaviors those ad
sets actually target).

Why two sources:
  • The sheet knows *which* audience converted (bucket, by ad-set/campaign name).
  • Only Meta knows the *actual* Detailed Targeting config (flexible_spec →
    interests / behaviors / family_statuses / …).

Join key = ad-set name. The SAME bucket classifier used on the sheet is run on
each Meta ad-set name, so a Meta ad set lands in the same bucket as the sales
attributed to it. For each top bucket (ranked by sheet sales) we print the
distinct Detailed-Targeting combos found on the Meta ad sets in that bucket.

Read-only. Lists every ad account the system-user token can see first, so we can
tell whether the historical (MY) interest ad sets are even reachable.
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # allow `import targeting_buckets`

from adbot import cpa
from adbot.clients.graph import GraphClient
from adbot.clients.sheets import SheetsClient
from adbot.settings import load_settings
from targeting_buckets import (
    BUCKETS, classify, SOURCE_COL, CAMPAIGN_COL, ADSET_COL, _cell,
)

TOP_BUCKETS = 10          # resolve real targeting for this many top buckets
MAX_COMBOS = 8            # distinct targeting combos to show per bucket
MAX_ADSETS_PER_ACCT = 2000

# Detailed-Targeting sub-keys that live inside flexible_spec / top-level targeting.
DETAIL_KEYS = [
    "interests", "behaviors", "life_events", "family_statuses", "industries",
    "income", "education_statuses", "education_majors", "work_positions",
    "work_employers", "relationship_statuses", "user_adclusters",
    "college_years", "fields_of_study", "moms",
]


# ── sheet side: bucket -> sales count ─────────────────────────────────────────
def sheet_bucket_counts(s) -> dict[str, int]:
    values = SheetsClient(s.secrets.google_sa_json).read_tab(
        s.cpa.spreadsheet_id, s.cpa.sales_tab)
    header_idx = 0
    for i, row in enumerate(values[:8]):
        if cpa.find_columns(row).get("adset", -1) >= 0:
            header_idx = i
            break
    counts: dict[str, int] = defaultdict(int)
    for row in values[header_idx + 1:]:
        label = classify(_cell(row, SOURCE_COL), _cell(row, CAMPAIGN_COL),
                         _cell(row, ADSET_COL))
        if label:
            counts[label] += 1
    return counts


# ── meta side: pull every ad set (name + targeting) across all accounts ───────
def pull_all_adsets(g) -> list[tuple[str, str, dict]]:
    try:
        accts = g._get_all("me/adaccounts",
                           {"fields": "account_id,name", "limit": 200})
    except Exception as e:
        print(f"  ! me/adaccounts failed: {e}")
        accts = []
    print(f"Accessible ad accounts: {len(accts)}")
    out: list[tuple[str, str, dict]] = []
    for a in accts:
        acct_id = a.get("account_id", "")
        acct_name = a.get("name", "")
        path = f"act_{acct_id}"
        try:
            adsets = g._get_all(
                f"{path}/adsets",
                {"fields": "name,effective_status,targeting", "limit": 500})
        except Exception as e:
            print(f"   • {path:22} {acct_name[:30]:30} !! {str(e)[:60]}")
            continue
        adsets = adsets[:MAX_ADSETS_PER_ACCT]
        print(f"   • {path:22} {acct_name[:30]:30} {len(adsets):>5} ad sets")
        for ad in adsets:
            out.append((acct_id, acct_name, ad))
    return out


def detailed_combo(t: dict):
    """Extract a hashable (details, meta) view of an ad set's Detailed Targeting."""
    if not isinstance(t, dict):
        return None
    details: list[tuple[str, str]] = []

    def collect(spec: dict):
        for k in DETAIL_KEYS:
            for it in (spec.get(k) or []):
                if isinstance(it, dict):
                    details.append((k, it.get("name") or str(it.get("id"))))
                else:
                    details.append((k, str(it)))

    collect(t)                                   # legacy top-level
    for grp in (t.get("flexible_spec") or []):   # AND-groups
        collect(grp)

    age = f"{t.get('age_min', '?')}-{t.get('age_max', '?')}"
    genders = t.get("genders")
    gender_s = {(): "all", (1,): "M", (2,): "F"}.get(
        tuple(genders) if genders else (), str(genders))
    adv = (t.get("targeting_automation") or {}).get("advantage_audience")
    geo = (t.get("geo_locations") or {}).get("countries") or []
    excl = len(t.get("excluded_custom_audiences") or [])
    ca = len(t.get("custom_audiences") or [])

    meta = f"age {age} · {gender_s} · adv_aud={adv} · geo={','.join(geo) or '?'}"
    if ca:
        meta += f" · CA={ca}"
    if excl:
        meta += f" · excl_CA={excl}"
    key = (tuple(sorted(set(details))), age, tuple(genders or []), adv)
    return details, meta, key


def main() -> None:
    s = load_settings()
    g = GraphClient(s.secrets.meta_token, "")

    print("═" * 90)
    print("STEP 1 — enumerate accessible ad accounts + pull ad-set targeting")
    print("═" * 90)
    adsets = pull_all_adsets(g)
    print(f"\nTotal ad sets pulled across all accounts: {len(adsets)}")

    # Bucket each Meta ad set by NAME, keep its targeting.
    bucket_adsets: dict[str, list[tuple[str, str, dict]]] = defaultdict(list)
    for acct_id, acct_name, ad in adsets:
        label = classify(ad.get("name", ""), "", "")
        if label:
            bucket_adsets[label].append((acct_id, acct_name, ad))

    print("\n" + "═" * 90)
    print("STEP 2 — sheet conversion ranking (which audiences convert most)")
    print("═" * 90)
    counts = sheet_bucket_counts(s)
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    for i, (label, cnt) in enumerate(ranked[:TOP_BUCKETS + 6], 1):
        n_meta = len(bucket_adsets.get(label, []))
        print(f"{i:>3} {cnt:>5} sales  ·  {n_meta:>3} live/hist Meta ad sets  ·  {label}")

    print("\n" + "═" * 90)
    print(f"STEP 3 — REAL Detailed Targeting for the top {TOP_BUCKETS} converting buckets")
    print("═" * 90)
    for i, (label, cnt) in enumerate(ranked[:TOP_BUCKETS], 1):
        mine = bucket_adsets.get(label, [])
        print(f"\n#{i}  {label}   —   {cnt} sales   ·   {len(mine)} Meta ad sets matched")
        print("-" * 90)
        if not mine:
            print("     (no Meta ad set with this name pattern is reachable — spec not "
                  "recoverable from the accounts this token can see)")
            continue

        combos: dict[tuple, dict] = {}
        for acct_id, acct_name, ad in mine:
            res = detailed_combo(ad.get("targeting") or {})
            if res is None:
                continue
            details, meta, key = res
            slot = combos.setdefault(key, {"n": 0, "details": details,
                                           "meta": meta, "ex": ad.get("name", "")})
            slot["n"] += 1

        ordered = sorted(combos.values(), key=lambda c: -c["n"])
        for c in ordered[:MAX_COMBOS]:
            if c["details"]:
                by_type: dict[str, list[str]] = defaultdict(list)
                for typ, name in c["details"]:
                    by_type[typ].append(name)
                parts = []
                for typ, names in by_type.items():
                    uniq = sorted(set(names))
                    parts.append(f"{typ}: {', '.join(uniq)}")
                detail_s = "  ||  ".join(parts)
            else:
                detail_s = "BROAD — no detailed targeting (Advantage+/automated)"
            print(f"   [{c['n']:>3} ad sets]  {c['meta']}")
            print(f"                {detail_s}")
            print(f"                e.g. ad set: {c['ex'][:70]!r}")


if __name__ == "__main__":
    main()
