"""Webinar 4 Nov review: every SG ad that spent in the cycle, judged on sales (read-only, 5 Nov).

Operator: paid student list update 好了，告诉我广告方面要我做什么决定. Cycle = Thursday 29 Oct to Tuesday
3 Nov (ADBOT_CYCLE_FROM / ADBOT_CYCLE_TO). Webinar sales = paid-sheet rows dated on/after
ADBOT_SALES_FROM (default 2026-11-04). Per ad on SG old + HK with cycle spend: cycle spend /
registrations, webinar sales carrying its own UTM campaign + ad set + ad, all-time spend /
registrations / own sales and CPA, current status. Totals: cycle spend, SG webinar sales (with and
without an ad match), cycle CPA. No names, phones or emails are read. No writes.
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

ACCTS = [("SG老户", "act_1024930575770087"), ("HK", "act_1179668409969241")]


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def market(c: str) -> str:
    c = cpa.norm(c)
    if "[sg]" in c or "martin-sg" in c or "martin sg" in c:
        return "SG"
    if "[my]" in c or "martin-my" in c or "martin my" in c:
        return "MY"
    return "没有 UTM / 其他"


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    tok = result_action_type(s.meta.conversion_event)
    c_from = os.environ.get("ADBOT_CYCLE_FROM") or "2026-10-29"
    c_to = os.environ.get("ADBOT_CYCLE_TO") or "2026-11-03"
    s_from = dt.date.fromisoformat(os.environ.get("ADBOT_SALES_FROM") or "2026-11-04")

    sales, _c, _h = cpa.parse_sales(SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab),
                                    s.cpa.price_myr)
    web = [x for x in sales if x.date and x.date >= s_from]
    own_all = defaultdict(int)
    for x in sales:
        own_all[(cpa.ad_key(x.campaign), cpa.ad_key(x.adset), cpa.ad_key(x.ad))] += 1
    web_by_key = defaultdict(list)
    for x in web:
        web_by_key[(cpa.ad_key(x.campaign), cpa.ad_key(x.adset), cpa.ad_key(x.ad))].append(x)
    log.info("%s 起的成交 %d 笔：", s_from, len(web))
    for x in sorted(web, key=lambda x: x.date):
        log.info("   %s · %s · RM%.0f · campaign %r · ad set %r · ad %r", x.date, market(x.campaign), x.amount,
                 x.campaign[:70], x.adset[:35], x.ad[:45])

    rows, matched = [], set()
    tot_sp = tot_rg = 0.0
    for label, acct in ACCTS:
        cyc = g._get_all(f"{acct}/insights", {"level": "ad", "limit": 200,
                                              "fields": "ad_id,ad_name,adset_name,campaign_name,spend,actions",
                                              "time_range": json.dumps({"since": c_from, "until": c_to})})
        cyc = [r for r in cyc if _f(r.get("spend")) > 0]
        ids = [r["ad_id"] for r in cyc]
        life = {}
        if ids:
            for r in g._get_all(f"{acct}/insights", {"level": "ad", "limit": 200, "fields": "ad_id,spend,actions",
                                                     "date_preset": "maximum",
                                                     "filtering": json.dumps([{"field": "ad.id", "operator": "IN", "value": ids}])}):
                life[r["ad_id"]] = (_f(r.get("spend")), extract_results(r.get("actions"), tok))
        for r in cyc:
            k = (cpa.ad_key(r.get("campaign_name") or ""), cpa.ad_key(r.get("adset_name") or ""), cpa.ad_key(r.get("ad_name") or ""))
            sp, rg = _f(r.get("spend")), extract_results(r.get("actions"), tok)
            tot_sp, tot_rg = tot_sp + sp, tot_rg + rg
            ws = web_by_key.get(k, [])
            if ws:
                matched.add(k)
            lsp, lrg = life.get(r["ad_id"], (sp, rg))
            st = g.get_object(r["ad_id"], "effective_status").get("effective_status")
            rows.append((label, r["ad_id"], r.get("ad_name") or "", r.get("campaign_name") or "", sp, rg, len(ws),
                         lsp, lrg, own_all.get(k, 0), st))
    for row in sorted(rows, key=lambda r: (-r[6], -r[9], -r[4])):
        label, aid, name, camp, sp, rg, nws, lsp, lrg, nall, st = row
        log.info("%s ad %s %r · %s · campaign %r", label, aid, name[:40], st, camp[:60])
        log.info("    本期花 RM%.2f 报名 %d · 这场直播成交 %d · 全期花 RM%.2f 报名 %d 自己成交 %d · 全期 CPA %s",
                 sp, rg, nws, lsp, lrg, nall, f"RM{lsp / nall:.0f}" if nall else "—")
    sg_web = [x for x in web if market(x.campaign) == "SG"]
    sg_matched = sum(len(web_by_key[k]) for k in matched)
    final_summary(log, f"本期 {c_from}~{c_to} 花 RM{tot_sp:.2f} 报名 {tot_rg:.0f} · {s_from} 起成交 {len(web)} 笔"
                       f"（SG {len(sg_web)}，对上本期广告 {sg_matched}）· 本期 CPA "
                       f"{'RM%.0f' % (tot_sp / len(sg_web)) if sg_web else '—（SG 0 单）'}")


if __name__ == "__main__":
    main()
