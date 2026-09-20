"""Reopen scan (read-only): 30d-CPA-qualified names that are currently OFF.

Operator (20 Sep): "paid student list 里面，有哪些 30 天 cpa 达标，但被我关掉了？（可能
cpl 很高，所以我关了），你建议我。"

For every ad name with ≥1 provably-SG sale in the last 30 days and NO live copy:
    30d spend · 30d leads · 30d CPL (the number that scared the operator)
    30d CPA = 30d spend ÷ 30d sales, classified against RM960 / RM1,200
    headroom = how much more the name could spend in-window before flunking RM960
    lifetime sales/CPA + last sale date for context
Read-only; the reopen decision stays with the operator.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Dict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings


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
    d30 = today - dt.timedelta(days=30)
    acc, hard = s.cpa.max_acceptable_myr, s.cpa.hard_stop_myr

    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    s30: Dict[str, int] = defaultdict(int)
    life_n: Dict[str, int] = defaultdict(int)
    last_sale: Dict[str, dt.date] = {}
    disp_sheet: Dict[str, str] = {}
    for x in sales:
        if not _sg(x.campaign):
            continue
        k = cpa.ad_key(x.ad)
        if not k:
            continue
        life_n[k] += 1
        disp_sheet.setdefault(k, (x.ad or "").strip())
        if x.date:
            if x.date >= d30:
                s30[k] += 1
            if k not in last_sale or x.date > last_sale[k]:
                last_sale[k] = x.date

    ads = g._get_all(f"{acct}/ads",
                     {"fields": "id,name,effective_status", "limit": 500})
    live = set()
    disp: Dict[str, str] = {}
    for a in ads:
        k = cpa.ad_key(a.get("name") or "")
        disp.setdefault(k, (a.get("name") or "").strip())
        if a.get("effective_status") == "ACTIVE":
            live.add(k)

    def fold(**kw):
        sp: Dict[str, float] = defaultdict(float)
        ld: Dict[str, float] = defaultdict(float)
        for r in g.account_insights(acct, level="ad", fields="ad_id,ad_name,spend,actions", **kw):
            k = cpa.ad_key(r.get("ad_name") or "")
            try:
                sp[k] += float(r.get("spend") or 0)
            except (TypeError, ValueError):
                pass
            ld[k] += extract_results(r.get("actions"), token)
        return sp, ld

    sp30, ld30 = fold(time_range={"since": d30.isoformat(), "until": today.isoformat()})
    spL, _ = fold(date_preset="maximum")

    rows = []
    for k, n in s30.items():
        if k in live:
            continue
        sp = sp30.get(k, 0.0)
        cpa30 = sp / n
        if cpa30 > hard:
            continue
        rows.append((cpa30, k, n, sp))
    rows.sort()

    log.info("═" * 116)
    log.info("30d 有单、CPA ≤ RM%.0f、但现在没在投的名字 · 窗口 %s → %s", hard, d30, today)
    log.info("═" * 116)
    for cpa30, k, n, sp in rows:
        ld = ld30.get(k, 0.0)
        cpl = f"RM{sp / ld:,.0f}" if ld else ("∞" if sp else "—")
        lcpa = spL.get(k, 0.0) / life_n[k] if life_n.get(k) else 0.0
        headroom = n * acc - sp
        band = "✅ 达标" if cpa30 <= acc else "🤔 边缘(960-1200)"
        name = (disp.get(k) or disp_sheet.get(k) or k)[:42]
        log.info("▸ %-42s %s", name, band)
        log.info("    30d: 花 RM%-7.0f %2.0fL CPL %-8s %d单 → CPA RM%-7.0f · 余量 RM%-6.0f "
                 "· 终身 %d单/CPA RM%-6.0f · 最后成交 %s",
                 sp, ld, cpl, n, cpa30, max(0, headroom), life_n[k], lcpa,
                 last_sale.get(k))
    if not rows:
        log.info("（没有 —— 30d 内有单的名字要么在投、要么 CPA 超硬线）")
    final_summary(log, f"Reopen scan: {len(rows)} qualified-but-off names "
                       f"(30d sale, CPA ≤ RM{hard:.0f}, not live). Read-only.")


if __name__ == "__main__":
    main()
