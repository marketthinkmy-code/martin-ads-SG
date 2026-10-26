"""Which SG ads sold the most in the last 60 days? (read-only, 26 Oct)

Operator: 如果我要 60 天有出单最多的广告，是什么广告？ Per ad (name folded by cpa.ad_key):
SG sales in the last ADBOT_DAYS days (default 60) from the paid sheet, with the UTM ad set and
date of every sale; Meta spend / registrations for the same window on SG old + HK ([SG]
campaigns only); spend in the last 7 days (is it still running); MY's numbers for the same
creative in the same window (rule 4, MY read only). No writes.
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

SG_ACCTS = [("SG老", "act_1024930575770087"), ("HK", "act_1179668409969241")]
MY_ACCT = "act_1011719073600566"


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
    days = int(os.environ.get("ADBOT_DAYS") or 60)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    since = today - dt.timedelta(days=days)
    tr = json.dumps({"since": since.isoformat(), "until": today.isoformat()})
    tr7 = json.dumps({"since": (today - dt.timedelta(days=7)).isoformat(), "until": today.isoformat()})

    sales, _c, _h = cpa.parse_sales(SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab),
                                    s.cpa.price_myr)
    sg = defaultdict(list)
    my_sales = defaultdict(int)
    names = {}
    for x in sales:
        if not x.date or x.date < since:
            continue
        k = cpa.ad_key(x.ad)
        if _mkt(x.campaign) == "SG":
            sg[k].append(x)
            names.setdefault(k, x.ad)
        elif _mkt(x.campaign) == "MY":
            my_sales[k] += 1
    n_all = sum(len(v) for v in sg.values())
    log.info("成交表：%s 起 SG 共 %d 单，分布在 %d 支片", since, n_all, len(sg))

    def pull(acct, window, market):
        out = defaultdict(lambda: [0.0, 0.0])
        for r in g._get_all(f"{acct}/insights", {"level": "ad", "limit": 500, "time_range": window,
                                                  "fields": "campaign_name,ad_name,spend,actions"}):
            if _mkt(r.get("campaign_name") or "") != market:
                continue
            k = cpa.ad_key(r.get("ad_name") or "")
            o = out[k]; o[0] += _f(r.get("spend")); o[1] += extract_results(r.get("actions"), tok)
            names.setdefault(k, r.get("ad_name"))
        return out

    meta, last7 = defaultdict(lambda: [0.0, 0.0]), defaultdict(float)
    for _, acct in SG_ACCTS:
        for k, v in pull(acct, tr, "SG").items():
            meta[k][0] += v[0]; meta[k][1] += v[1]
        for k, v in pull(acct, tr7, "SG").items():
            last7[k] += v[0]
    my = pull(MY_ACCT, tr, "MY")

    log.info("═" * 120)
    log.info("SG %d 天成交排名（成交表 UTM ad name）· 每行：SG 单 · SG 花费 · 报名 · 每个报名 · 每单 · 报名转买家 · 最近 7 天花费 · MY 同窗口", days)
    for k, xs in sorted(sg.items(), key=lambda kv: (-len(kv[1]), meta[kv[0]][0])):
        sp, ld = meta[k]
        n = len(xs)
        mysp, myld = my.get(k, [0.0, 0.0])
        log.info("▌%-44s SG %d 单 · RM%.2f · %d 报名 · 每个报名 %s · 每单 %s · 转化 %s · 最近7天 RM%.2f · MY RM%.0f/%d 报名/%d 单",
                 (names.get(k) or k)[:44], n, sp, int(ld), f"RM{sp / ld:.0f}" if ld else "—", f"RM{sp / n:.0f}" if sp else "—",
                 f"{n / ld * 100:.0f}%" if ld else "—", last7.get(k, 0.0), mysp, int(myld), my_sales.get(k, 0))
        by_set = defaultdict(list)
        for x in xs:
            by_set[(x.adset or "（没有 ad set）")[:40]].append(x.date.isoformat())
        for st, ds in sorted(by_set.items(), key=lambda kv: -len(kv[1])):
            log.info("      成交 ad set：%-40s ×%d · %s", st, len(ds), " ".join(sorted(ds)))
    final_summary(log, f"SG top sellers {days}d · read-only")


if __name__ == "__main__":
    main()
