"""Yesterday's paid sales (SG sheet) → ad name / ad set, cross-referenced against
the LIVE monitor verdict for every active ad — so we can confirm each winning ad
is (a) still ACTIVE and (b) NOT about to be wrongly auto-paused.

Read-only. Uses the monitor's own evaluate_account(), so what it prints is exactly
what the cron would decide right now.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.monitor_cpl import evaluate_account
from adbot.settings import load_settings


def _cpl(d) -> str:
    import math
    if d.cpl is None:
        return "n/a"
    return "∞" if d.cpl == math.inf else f"{d.cpl:.0f}"


def _cpa(d) -> str:
    import math
    if d.cpa is None:
        return ""
    v = "∞" if d.cpa == math.inf else f"{d.cpa:.0f}"
    return f" · CPA={v}(60d {d.cpa_sales} sale, age {d.age_days}d)"


def main() -> None:
    s = load_settings()
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()   # MYT, same as the monitor
    yday = today - dt.timedelta(days=1)

    # 1) yesterday's sales from the SG sheet
    values = SheetsClient(s.secrets.google_sa_json).read_tab(
        s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, cols, _hdr = cpa.parse_sales(values, s.cpa.price_myr)
    y = [x for x in sales if x.date == yday]

    print(f"Sheet tab : {s.cpa.sales_tab!r}")
    print(f"cpa columns detected: {cols}")
    print(f"Today (MYT)={today} · Yesterday={yday} · sales dated yesterday: {len(y)}\n")
    print("Yesterday's sales (ad · adset · campaign · amount):")
    for x in y:
        print(f"  · ad={x.ad[:38]!r:40} adset={x.adset[:26]!r:30} camp={x.campaign[:24]!r:28} RM{x.amount:.0f}")

    per_ad = defaultdict(int)
    ad_to_adset = defaultdict(set)
    for x in y:
        if x.ad:
            per_ad[x.ad] += 1
            ad_to_adset[x.ad].add(x.adset)
    print(f"\nDistinct winning ad names yesterday: {len(per_ad)}")

    # 2) the monitor's live verdict for every active ad
    g = graph_client(s)
    decisions = evaluate_account(g, s)
    by_name = defaultdict(list)
    for d in decisions:
        by_name[cpa.norm(d.name)].append(d)
    print(f"Monitor evaluated {len(decisions)} active registration-optimized ads in the SG account.\n")

    # 3) cross-reference
    print("═" * 92)
    print(" STATUS of each yesterday-winning ad (as the cron sees it RIGHT NOW)")
    print("═" * 92)
    at_risk, not_running, safe = [], [], []
    for adn in sorted(per_ad, key=lambda a: -per_ad[a]):
        n = per_ad[adn]
        adsets = " / ".join(sorted(a for a in ad_to_adset[adn] if a)) or "(blank)"
        ds = by_name.get(adn, [])
        if not ds:
            not_running.append(adn)
            print(f"  ❌ NOT RUNNING  ({n} sale)  ad={adn[:44]!r}")
            print(f"                  adset(sheet)={adsets[:60]!r}  — no ACTIVE reg-optimized ad by this name")
            continue
        for d in ds:
            if d.should_pause:
                at_risk.append((adn, d))
                tag = "⚠️  WOULD PAUSE"
            else:
                safe.append((adn, d))
                tag = "✅ SAFE (keep)"
            print(f"  {tag}  ({n} sale)  ad={adn[:44]!r}")
            print(f"                  spend=RM{d.spend:.0f} reg={d.results:.0f} CPL={_cpl(d)}{_cpa(d)} — {d.reason}")

    print("\n" + "═" * 92)
    print(f" SUMMARY: {len(per_ad)} winning ad(s) yesterday · "
          f"{len(safe)} SAFE · {len(at_risk)} AT RISK of wrongful pause · {len(not_running)} NOT running")
    print("═" * 92)
    if at_risk:
        print(" ⚠️  AT-RISK — the monitor WOULD pause these winners. Protect via kpi.cpl_hold:")
        for adn, d in at_risk:
            print(f"      {adn!r}   (CPL={_cpl(d)}, reason={d.reason})")
    if not_running:
        print(" ❌ NOT RUNNING — made a sale yesterday but no active ad by this name (paused? old creative?):")
        for adn in not_running:
            print(f"      {adn!r}")
    if not at_risk and not not_running:
        print(" 🎉 All yesterday's winners are ACTIVE and SAFE — the monitor will NOT pause them.")


if __name__ == "__main__":
    main()
