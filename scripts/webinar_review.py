"""Webinar review (read-only, 22 Oct; operator: 看看最新成交纪录，复盘，复读，告诉我 what's next).

Same report as webinar_1014_review.py, dates from env (defaults = the 21/10 webinar):
ADBOT_CYCLE_FROM / ADBOT_CYCLE_TO = ads delivered in the cycle (the leads that could attend),
ADBOT_WEBINAR = sales dated on/after this day count as this webinar's. Also names the sheet tab
the operator linked (ADBOT_GID). Sales = SG rows in the paid sheet, folded by ad name
(cpa.ad_key) across SG old + HK. Prints
every sale with its UTM campaign / ad set / ad, per-ad 花 · lead · 单 · CPA · lead→买家,
sales not matching any cycle ad, 30d / 60d per-creative CPA, and current status. No writes.
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


def _d(env, default):
    return dt.date.fromisoformat(os.environ.get(env) or default)


C0, C1, WEB = _d("ADBOT_CYCLE_FROM", "2026-10-15"), _d("ADBOT_CYCLE_TO", "2026-10-21"), _d("ADBOT_WEBINAR", "2026-10-21")
RUNNING = ("ACTIVE", "IN_PROCESS", "PENDING_REVIEW")


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
    d30, d60 = today - dt.timedelta(days=30), today - dt.timedelta(days=60)

    sh = SheetsClient(s.secrets.google_sa_json)
    gid = os.environ.get("ADBOT_GID") or "1500782859"
    meta = sh._svc.spreadsheets().get(spreadsheetId=s.cpa.spreadsheet_id, fields="sheets.properties").execute()
    for p in (x["properties"] for x in meta.get("sheets", [])):
        if str(p.get("sheetId")) == gid:
            log.info("你给的链接 gid=%s 是分页 %r（%s 行）· 成交用的分页是 %r", gid, p.get("title"),
                     (p.get("gridProperties") or {}).get("rowCount"), s.cpa.sales_tab)
    values = sh.read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    sg = [x for x in sales if x.date and _sg(x.campaign)]
    latest = max((x.date for x in sg), default=None)
    new = [x for x in sg if x.date >= WEB]
    log.info("成交表：SG 最近一笔 %s · %s 起 SG 单 %d 笔 · 全表最近一笔(任何市场) %s", latest, WEB, len(new),
             max((x.date for x in sales if x.date), default=None))
    for x in sorted(new, key=lambda x: x.date):
        log.info("   %s · campaign %s · ad set %s · ad %s", x.date, x.campaign[:50], (x.adset or "")[:30], x.ad[:40])
    n_new, n30, n60 = defaultdict(int), defaultdict(int), defaultdict(int)
    for x in sg:
        k = cpa.ad_key(x.ad)
        if x.date >= WEB: n_new[k] += 1
        if x.date >= d30: n30[k] += 1
        if x.date >= d60: n60[k] += 1

    def pull(since, until):
        out = defaultdict(lambda: [0.0, 0.0, 0.0, set(), set()])
        for label, acct in ACCOUNTS:
            for r in g._get_all(f"{acct}/insights", {"level": "ad", "limit": 500,
                    "fields": "ad_id,ad_name,adset_name,spend,actions,inline_link_clicks",
                    "time_range": json.dumps({"since": since.isoformat(), "until": until.isoformat()})}):
                k = cpa.ad_key(r.get("ad_name") or "")
                o = out[k]
                o[0] += _f(r.get("spend")); o[1] += extract_results(r.get("actions"), tok)
                o[2] += _f(r.get("inline_link_clicks")); o[3].add(r.get("ad_id")); o[4].add(f"{label}:{(r.get('adset_name') or '')[:24]}")
                o.append(r.get("ad_name"))
        return out

    cyc, after, m30, m60 = pull(C0, C1), pull(C1 + dt.timedelta(days=1), today), pull(d30, today), pull(d60, today)
    status = {}
    for _, acct in ACCOUNTS:
        for a in g._get_all(f"{acct}/ads", {"fields": "id,effective_status", "limit": 800}):
            status[a["id"]] = a.get("effective_status")

    log.info("═" * 110)
    log.info("本轮 %s→%s 每支片：花 · lead · %s起单 · CPA · lead→买家 · 30d/60d · 现状 · 受众", C0, C1, WEB)
    tot = [0.0, 0.0, 0]
    rows = []
    for k, v in cyc.items():
        if v[0] < 1:
            continue
        rows.append((n_new[k], -v[0], k, v))
    for nn, _, k, v in sorted(rows, key=lambda r: (-r[0], r[1])):
        sp, ld = v[0], v[1]
        on = any(status.get(i) in RUNNING for i in v[3])
        tot[0] += sp; tot[1] += ld; tot[2] += nn
        log.info("▌%s %-38s RM%-8.2f %2d lead · %d单 · CPA %s · 转化 %s · 30d %d单 CPA %s · 60d %d单 · 之后花 RM%.0f · %s",
                 "▶️" if on else "⏸", (v[5] if len(v) > 5 else k)[:38], sp, int(ld), nn,
                 f"{sp / nn:,.0f}" if nn else "—", f"{nn / ld * 100:.0f}%" if ld and nn else "—",
                 n30[k], f"{m30[k][0] / n30[k]:,.0f}" if n30[k] else "—", n60[k], after[k][0], " / ".join(sorted(v[4]))[:80])
    log.info("合计 本轮 RM%.0f · %d lead · %d 单（能对上本轮广告）· CPA %s", tot[0], int(tot[1]), tot[2],
             f"RM{tot[0] / tot[2]:,.0f}" if tot[2] else "—")
    unmatched = [x for x in new if cpa.ad_key(x.ad) not in cyc or cyc[cpa.ad_key(x.ad)][0] < 1]
    log.info("%s 起的单里，对不上本轮在投广告的：%d 笔", WEB, len(unmatched))
    for x in unmatched:
        k = cpa.ad_key(x.ad)
        log.info("   %s · %s · 30d 花 RM%.0f · 60d 花 RM%.0f", x.date, x.ad[:40], m30[k][0], m60[k][0])
    final_summary(log, f"webinar review · {len(new)} new SG sales")


if __name__ == "__main__":
    main()
