"""What is delivering right now (read-only): SG old + HK, every ACTIVE campaign → ad set → ad,
with budget, spend + registrations since ADBOT_SINCE (default last Thursday), today, and
60d SG sales by ad name. MY is never touched. No writes.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from collections import defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

ACCOUNTS = [("SG老", "act_1024930575770087"), ("HK", "act_1179668409969241")]
RUNNING = ("ACTIVE", "IN_PROCESS", "PENDING_REVIEW", "WITH_ISSUES")


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _sg(c):
    c = cpa.norm(c)
    return "[sg]" in c or "martin-sg" in c or "martin sg" in c


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    tok = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    since = dt.date.fromisoformat(os.environ.get("ADBOT_SINCE") or (today - dt.timedelta(days=(today.weekday() - 3) % 7)).isoformat())
    d60 = today - dt.timedelta(days=60)
    sales, _c, _h = cpa.parse_sales(SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab), s.cpa.price_myr)
    n60 = defaultdict(int)
    for x in sales:
        if x.date and x.date >= d60 and _sg(x.campaign):
            n60[cpa.ad_key(x.ad)] += 1

    def ins(acct, a, b):
        out = defaultdict(lambda: [0.0, 0.0])
        for r in g._get_all(f"{acct}/insights", {"level": "ad", "limit": 500, "fields": "ad_id,spend,actions",
                                                 "time_range": json.dumps({"since": a.isoformat(), "until": b.isoformat()})}):
            out[r["ad_id"]][0] += _f(r.get("spend")); out[r["ad_id"]][1] += extract_results(r.get("actions"), tok)
        return out

    total_budget = 0
    for label, acct in ACCOUNTS:
        camps = [c for c in g._get_all(f"{acct}/campaigns", {"fields": "id,name,status,effective_status,daily_budget", "limit": 300})
                 if c.get("effective_status") == "ACTIVE"]
        sets = [a for a in g._get_all(f"{acct}/adsets", {"fields": "id,name,campaign_id,effective_status,daily_budget,start_time", "limit": 800})
                if a.get("effective_status") == "ACTIVE"]
        ads = [a for a in g._get_all(f"{acct}/ads", {"fields": "id,name,adset_id,effective_status", "limit": 800})
               if a.get("effective_status") in RUNNING]
        wk, td = ins(acct, since, today), ins(acct, today, today)
        log.info("═" * 110)
        log.info("【%s】%s · ACTIVE campaign %d · 数据从 %s 起", label, acct, len(camps), since)
        for c in sorted(camps, key=lambda x: x.get("name") or ""):
            cb = int(c.get("daily_budget") or 0)
            cs = [a for a in sets if a.get("campaign_id") == c["id"]]
            budget = cb if cb else sum(int(a.get("daily_budget") or 0) for a in cs if any(x["adset_id"] == a["id"] for x in ads))
            total_budget += budget
            log.info("▌%s %s · campaign %s · %s RM%d/天", c.get("name"), "", c["id"], "CBO" if cb else "ABO 在投合计", budget // 100)
            for a in cs:
                rows = [x for x in ads if x["adset_id"] == a["id"]]
                log.info("  ├ ad set %s %r%s · 在投广告 %d", a["id"], a.get("name"), "" if cb else f" RM{int(a.get('daily_budget') or 0) // 100}", len(rows))
                for x in rows:
                    sp, ld = wk[x["id"]]; tsp, tld = td[x["id"]]
                    log.info("  │   %s %r %s · 起 RM%.2f %d lead %s · 今 RM%.2f %d lead · 60d 成交 %d", x["id"], x.get("name"), x.get("effective_status"),
                             sp, int(ld), f"CPL {sp / ld:,.0f}" if ld else "零 lead", tsp, int(tld), n60[cpa.ad_key(x.get("name") or "")])
    log.info("═" * 110)
    log.info("在投每日预算合计 RM%d", total_budget // 100)
    final_summary(log, "live now · read-only")


if __name__ == "__main__":
    main()
