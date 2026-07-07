"""Read-only: paused Meta ads whose ad-NAME still shows lifetime paid sales.

Answers: "Of ads I paused (usually for poor recent CPL), which ones are still
being credited with real sales in the sheet and were historically profitable —
i.e. worth re-activating and scaling?"

Join key: normalised ad NAME only (the sheet's UTM campaign column is empty for
this account, so the (campaign, ad) join in cpa_report misses everything).
Filter: effective_status != ACTIVE  ·  lifetime paid sales ≥ 1  ·  lifetime ROAS > 1
(ROAS = attributed sheet revenue / Meta lifetime spend on that ad name).

Caveat of the ad-name-only join: if multiple Meta ads share the same name (rare
but happens across campaigns), each is credited with the FULL sales/revenue for
that name — the report over-counts on those. The "name-shared-by" column flags
this so the operator can spot it. For scaling triage that's fine; for precise
attribution, the sheet needs its UTM campaign column back-filled.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.settings import load_settings


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def main() -> None:
    s = load_settings()
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()

    # ---- sheet sales grouped by normalised ad NAME only --------------------
    values = SheetsClient(s.secrets.google_sa_json).read_tab(
        s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _cols, _hdr = cpa.parse_sales(values, s.cpa.price_myr)
    life_sales = defaultdict(int)      # ad_norm -> lifetime count
    life_rev = defaultdict(float)      # ad_norm -> lifetime revenue
    for sale in sales:
        if not sale.ad:                # skip rows with no UTM ad name
            continue
        life_sales[sale.ad] += 1
        life_rev[sale.ad] += sale.amount

    # ---- Meta: all ads (all statuses) + lifetime spend per ad --------------
    g = graph_client(s)
    acct = s.meta.account_path
    ads = g._get_all(f"{acct}/ads", {
        "fields": "id,name,effective_status,created_time,"
                  "campaign{name,effective_status},"
                  "adset{name,effective_status}",
        "limit": 500,
    })
    spend_by_ad_id = {r.get("ad_id"): _f(r.get("spend")) for r in g.account_insights(
        acct, level="ad", fields="ad_id,spend", date_preset="maximum")}

    tiers = cpa.CpaTiers(s.cpa.healthy_max_myr, s.cpa.max_acceptable_myr, s.cpa.hard_stop_myr)

    # Count how many Meta ads share each name — for the name-shared-by caveat.
    ads_per_name = defaultdict(int)
    for ad in ads:
        ads_per_name[cpa.norm(ad.get("name", ""))] += 1

    candidates = []
    scanned_paused = 0
    for ad in ads:
        if ad.get("effective_status") == "ACTIVE":
            continue
        scanned_paused += 1
        name = ad.get("name", ad["id"])
        camp_name = (ad.get("campaign") or {}).get("name", "")
        adset_name = (ad.get("adset") or {}).get("name", "")
        ad_key = cpa.norm(name)
        life = life_sales.get(ad_key, 0)
        rev = life_rev.get(ad_key, 0.0)
        spend = spend_by_ad_id.get(ad["id"], 0.0)
        if life < 1:
            continue
        roas = (rev / spend) if spend > 0 else math.inf   # revenue with 0 spend = pure win
        if roas <= 1.0:
            continue
        cpa_val = cpa.cpa(spend, life)
        created = cpa.parse_date((ad.get("created_time") or "")[:10])
        age = (today - created).days if created else None
        candidates.append({
            "ad_id": ad["id"], "name": name, "camp": camp_name, "adset": adset_name,
            "status": ad.get("effective_status"),
            "camp_status": (ad.get("campaign") or {}).get("effective_status"),
            "adset_status": (ad.get("adset") or {}).get("effective_status"),
            "life": life, "rev": rev, "spend": spend, "roas": roas,
            "cpa": cpa_val, "age": age,
            "shared_by": ads_per_name.get(ad_key, 1),
        })

    # Sort: highest lifetime sales first, then highest ROAS.
    candidates.sort(key=lambda c: (-c["life"], -c["roas"]))

    print(f"Paused ads worth re-scaling — MYT={today}  ·  "
          f"filters: not ACTIVE · lifetime sales ≥ 1 · lifetime ROAS > 1  "
          f"(CPA tiers: keep≤RM{tiers.healthy_max:.0f} / hard-stop>RM{tiers.hard_stop:.0f})")
    print("Join: ad NAME only (UTM campaign column is empty in this sheet).\n")
    print(f"Scanned {len(ads)} ads · paused/non-active: {scanned_paused} · "
          f"candidates: {len(candidates)}\n")

    if not candidates:
        print("(no paused ads meet the criteria on this account)")
        return

    hdr = (f"{'#':>2} {'ad_id':>18} {'st':>8} {'ad name':44} "
           f"{'life':>4} {'rev':>7} {'spend':>7} {'ROAS':>5} {'CPA':>6} {'age':>4} {'name×':>5}")
    print(hdr)
    print("-" * len(hdr))
    for i, c in enumerate(candidates, 1):
        cpa_str = "—" if c["cpa"] is None else ("∞" if c["cpa"] == math.inf else f"{c['cpa']:.0f}")
        roas_str = "∞" if c["roas"] == math.inf else f"{c['roas']:.2f}"
        age_str = "—" if c["age"] is None else f"{c['age']}d"
        # name× = how many Meta ads share this ad name (>1 means sales are shared credit)
        print(f"{i:>2} {c['ad_id']:>18} {c['status']:>8} {c['name'][:44]:44} "
              f"{c['life']:>4} {c['rev']:>7.0f} {c['spend']:>7.0f} {roas_str:>5} "
              f"{cpa_str:>6} {age_str:>4} {c['shared_by']:>5}")

    # Show enclosing campaign/adset status so the operator knows whether re-activating the ad
    # alone will actually deliver, or whether the parent(s) also need to be flipped ACTIVE.
    print("\nParent status (flip parents ACTIVE too when they are PAUSED):")
    for c in candidates:
        marks = []
        if c["camp_status"] != "ACTIVE":
            marks.append(f"campaign {c['camp_status']}")
        if c["adset_status"] != "ACTIVE":
            marks.append(f"ad set {c['adset_status']}")
        marks = ", ".join(marks) if marks else "parents ACTIVE — flipping the ad alone is enough"
        print(f"  · {c['ad_id']}  {c['name'][:44]:44}  →  {marks}")


if __name__ == "__main__":
    main()
