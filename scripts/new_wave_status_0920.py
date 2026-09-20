"""New Wave 0914 status (read-only): how are the 15 new videos doing?

Operator (20 Sep): "我最近的新广告有 15 个新视频，那个情况如何？"

Sums spend/leads since the build (2026-09-14) across each unit's THREE campaign copies —
by the exact ad ids in state/entities_new_wave_0914.json, so historical spend of the
same-named old ads (Hook 1 / Hook 2) cannot pollute the numbers. Adds current copy
statuses + budgets, and provably-SG sheet sales since 9/14 per name.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Dict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

sys.path.insert(0, str(Path(__file__).parent))
from build_new_wave_0914 import FIXED_ADS, STATE_PATH, VIDEOS  # noqa: E402

LAUNCH = dt.date(2026, 9, 14)


def _sg(campaign: str) -> bool:
    c = cpa.norm(campaign)
    return ("[sg]" in c) or ("martin-sg" in c) or ("martin sg" in c)


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    token = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()

    st = json.loads(STATE_PATH.read_text())
    name_of = {v["key"]: v["ad_name"] for v in VIDEOS}
    name_of.update({f["key"]: f["ad_name"] for f in FIXED_ADS})
    unit_ads: Dict[str, list] = {k: [] for k in name_of}
    for camp in st["campaigns"].values():
        for key, rec in camp.get("units", {}).items():
            if rec.get("ad_id"):
                unit_ads.setdefault(key, []).append(rec["ad_id"])

    ads = {a["id"]: a for a in g._get_all(
        f"{acct}/ads", {"fields": "id,status,effective_status,adset_id", "limit": 500})}
    adsets = {a["id"]: a for a in g._get_all(
        f"{acct}/adsets", {"fields": "id,daily_budget", "limit": 500})}

    sp: Dict[str, float] = {}
    ld: Dict[str, float] = {}
    for r in g.account_insights(acct, level="ad", fields="ad_id,spend,actions",
                                time_range={"since": LAUNCH.isoformat(),
                                            "until": today.isoformat()}):
        aid = r.get("ad_id")
        try:
            sp[aid] = sp.get(aid, 0.0) + float(r.get("spend") or 0)
        except (TypeError, ValueError):
            pass
        ld[aid] = ld.get(aid, 0.0) + extract_results(r.get("actions"), token)

    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    sold: Dict[str, int] = {}
    for x in sales:
        if _sg(x.campaign) and x.date and x.date >= LAUNCH:
            k = cpa.ad_key(x.ad)
            sold[k] = sold.get(k, 0) + 1

    rows = []
    for key, name in name_of.items():
        ids = unit_ads.get(key) or []
        tsp = sum(sp.get(i, 0.0) for i in ids)
        tld = sum(ld.get(i, 0.0) for i in ids)
        n_live = 0
        live_budget = 0
        for i in ids:
            a = ads.get(i) or {}
            if a.get("effective_status") == "ACTIVE":
                n_live += 1
                live_budget += int((adsets.get(a.get("adset_id")) or {}).get("daily_budget") or 0)
        rows.append((tsp, tld, key, name, n_live, live_budget,
                     sold.get(cpa.ad_key(name), 0)))
    rows.sort(reverse=True)

    log.info("═" * 112)
    log.info("NEW WAVE 0914 · 15 条新视频 · 自 %s 起（按 45 条链的 ad id 精确统计）", LAUNCH)
    log.info("═" * 112)
    tested = 0
    for tsp, tld, key, name, n_live, lb, n_sold in rows:
        if tsp <= 0:
            continue
        tested += 1
        cpl = f"RM{tsp / tld:,.0f}" if tld else "∞"
        state = f"{n_live} live @RM{lb // 100}" if n_live else "全 paused"
        log.info("▸ %-38s 花 RM%-7.0f %2dL CPL %-8s 成交 %d · %s",
                 name[:38], tsp, int(tld), cpl, n_sold, state)
    log.info("─" * 112)
    untested = [name for tsp, _t, _k, name, _n, _b, _s in rows if tsp <= 0]
    log.info("还没测过（0 花费）%d 条: %s", len(untested), " / ".join(n[:22] for n in untested))
    total_sp = sum(r[0] for r in rows)
    total_ld = sum(r[1] for r in rows)
    final_summary(log, f"New Wave status: {tested}/15 tested, RM{total_sp:,.0f} spent, "
                       f"{int(total_ld)} leads, {sum(r[6] for r in rows)} SG sales since "
                       f"{LAUNCH}; {len(untested)} units still untouched. Read-only.")


if __name__ == "__main__":
    main()
