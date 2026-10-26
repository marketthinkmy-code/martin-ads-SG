"""Top SG sellers, lifetime vs 60 days (read-only, 26 Oct).

Operator: list top 5 成交广告（SG/HK 户口）· lifetime 成交 vs last 60 day 成交 vs total 成交 ·
lifetime CPA vs lifetime CPL vs lifetime ads spent. Per ad name (cpa.ad_key):
  SG sales lifetime and last 60 days (paid sheet, [SG] UTM campaign)
  total sales = SG + MY (all markets in the sheet)
  lifetime spend / registrations on SG old + HK, [SG] campaigns (date_preset maximum)
  lifetime CPA = spend / SG sales, lifetime CPL = spend / registrations
Ranked by SG lifetime sales, then 60-day sales. ADBOT_TOP rows (default 10). No writes.
"""
from __future__ import annotations

import datetime as dt
import os
from collections import defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

SG_ACCTS = [("SG老", "act_1024930575770087"), ("HK", "act_1179668409969241")]


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _mkt(c):
    c = cpa.norm(c)
    return "SG" if ("[sg]" in c or "martin-sg" in c or "martin sg" in c) else "MY" if ("[my]" in c or "martin-my" in c or "martin my" in c) else ""


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    tok = result_action_type(s.meta.conversion_event)
    top = int(os.environ.get("ADBOT_TOP") or 10)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d60 = today - dt.timedelta(days=60)

    sales, _c, _h = cpa.parse_sales(SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab),
                                    s.cpa.price_myr)
    sg, sg60, my, names = defaultdict(int), defaultdict(int), defaultdict(int), {}
    for x in sales:
        k = cpa.ad_key(x.ad)
        m = _mkt(x.campaign)
        if m == "SG":
            sg[k] += 1
            names.setdefault(k, x.ad)
            if x.date and x.date >= d60:
                sg60[k] += 1
        elif m == "MY":
            my[k] += 1
    log.info("成交表：SG 全部 %d 单（其中最近 60 天 %d 单）· MY 全部 %d 单", sum(sg.values()), sum(sg60.values()), sum(my.values()))

    spend = defaultdict(lambda: [0.0, 0.0])
    for _, acct in SG_ACCTS:
        for r in g._get_all(f"{acct}/insights", {"level": "ad", "limit": 500, "date_preset": "maximum",
                                                  "fields": "campaign_name,ad_name,spend,actions"}):
            if _mkt(r.get("campaign_name") or "") != "SG":
                continue
            k = cpa.ad_key(r.get("ad_name") or "")
            o = spend[k]; o[0] += _f(r.get("spend")); o[1] += extract_results(r.get("actions"), tok)
            names[k] = r.get("ad_name") or names.get(k)

    log.info("═" * 110)
    log.info("排名 · 片 · SG 全部成交 · SG 60天成交 · 总成交(SG+MY) · 全部花费(SG老+HK) · 全部报名 · 每单(CPA) · 每个报名(CPL)")
    for i, k in enumerate(sorted(sg, key=lambda k: (-sg[k], -sg60[k], spend[k][0]))[:top], 1):
        sp, ld = spend[k]
        log.info("%2d | %s | %d | %d | %d | RM%.2f | %d | %s | %s", i, names.get(k), sg[k], sg60[k], sg[k] + my[k], sp, int(ld),
                 f"RM{sp / sg[k]:.0f}" if sg[k] and sp else "—", f"RM{sp / ld:.0f}" if ld else "—")
    final_summary(log, "SG top sellers lifetime · read-only")


if __name__ == "__main__":
    main()
