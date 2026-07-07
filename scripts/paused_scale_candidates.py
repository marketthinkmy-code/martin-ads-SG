"""Read-only: paused Meta ads still generating paid sales in the last 30d.

Answers: "Of ads I paused (usually for poor recent CPL), which ones are still
being credited with real sales in the sheet and were historically profitable —
i.e. worth re-activating and scaling?"

Filter: effective_status != ACTIVE  ·  30d paid sales ≥ 1  ·  lifetime ROAS > 1
(ROAS = attributed sheet revenue / Meta lifetime spend on that ad name).
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.monitor_cpl import _mkey
from adbot.settings import load_settings


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def main() -> None:
    s = load_settings()
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    cutoff_30 = today - dt.timedelta(days=30)

    # ---- sheet sales grouped by (campaign match-key, normalised ad name) ----
    values = SheetsClient(s.secrets.google_sa_json).read_tab(
        s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _cols, _hdr = cpa.parse_sales(values, s.cpa.price_myr)
    life_sales = defaultdict(int)      # (camp_key, ad_norm) -> lifetime count
    d30_sales = defaultdict(int)
    life_rev = defaultdict(float)      # (camp_key, ad_norm) -> lifetime revenue
    for sale in sales:
        k = (_mkey(sale.campaign), sale.ad)   # sale.ad already normalised
        life_sales[k] += 1
        life_rev[k] += sale.amount
        if sale.date and sale.date > cutoff_30:
            d30_sales[k] += 1

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

    candidates = []
    also_paused_no_sales = 0
    for ad in ads:
        if ad.get("effective_status") == "ACTIVE":
            continue
        name = ad.get("name", ad["id"])
        camp_name = (ad.get("campaign") or {}).get("name", "")
        adset_name = (ad.get("adset") or {}).get("name", "")
        k = (_mkey(camp_name), cpa.norm(name))
        d30 = d30_sales.get(k, 0)
        life = life_sales.get(k, 0)
        rev = life_rev.get(k, 0.0)
        spend = spend_by_ad_id.get(ad["id"], 0.0)
        if d30 < 1:
            also_paused_no_sales += 1
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
            "d30": d30, "life": life, "rev": rev, "spend": spend, "roas": roas,
            "cpa": cpa_val, "age": age,
        })

    candidates.sort(key=lambda c: (-c["d30"], -c["roas"]))

    print(f"Paused ads worth re-scaling — MYT={today}  ·  "
          f"filters: not ACTIVE · 30d sales ≥ 1 · lifetime ROAS > 1  "
          f"(CPA tiers: keep≤RM{tiers.healthy_max:.0f} / hard-stop>RM{tiers.hard_stop:.0f})\n")
    print(f"Scanned {len(ads)} ads; paused-with-no-30d-sales: {also_paused_no_sales}; "
          f"candidates: {len(candidates)}\n")

    if not candidates:
        print("(no paused ads meet the criteria on this account)")
        return

    hdr = (f"{'#':>2} {'ad_id':>18} {'status':>10} {'campaign':30} {'ad':38} "
           f"{'30d':>3} {'life':>4} {'rev':>7} {'spend':>7} {'ROAS':>5} {'CPA':>6} {'age':>4}")
    print(hdr)
    print("-" * len(hdr))
    for i, c in enumerate(candidates, 1):
        cpa_str = "—" if c["cpa"] is None else ("∞" if c["cpa"] == math.inf else f"{c['cpa']:.0f}")
        roas_str = "∞" if c["roas"] == math.inf else f"{c['roas']:.2f}"
        age_str = "—" if c["age"] is None else f"{c['age']}d"
        print(f"{i:>2} {c['ad_id']:>18} {c['status']:>10} {c['camp'][:30]:30} "
              f"{c['name'][:38]:38} {c['d30']:>3} {c['life']:>4} "
              f"{c['rev']:>7.0f} {c['spend']:>7.0f} {roas_str:>5} {cpa_str:>6} {age_str:>4}")

    # Show enclosing campaign/adset status so the operator knows whether re-activating the ad
    # alone will actually deliver, or whether the parent(s) also need to be flipped ACTIVE.
    print("\nParent status (need to also flip parents ACTIVE when they are PAUSED):")
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
