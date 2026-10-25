"""SG registrations per day from the Register tab vs Meta registrations (read-only, 25 Oct).

Answers "is today really zero, or is the pixel missing them?": rows in the register tab(s)
(title contains regist / 报名) dated on/after ADBOT_SINCE, SG by UTM campaign, counted per day
and per UTM ad; next to Meta's registrations per day for the SG campaigns on HK. Counts only —
no names, phones or emails printed. No writes.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from collections import Counter, defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

HK = "act_1179668409969241"


def _sg(c):
    c = cpa.norm(c)
    return "[sg]" in c or "martin-sg" in c or "martin sg" in c


def main():
    log = get_logger()
    s = load_settings()
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    since = dt.date.fromisoformat(os.environ.get("ADBOT_SINCE") or "2026-10-18")
    sh = SheetsClient(s.secrets.google_sa_json)
    meta = sh._svc.spreadsheets().get(spreadsheetId=s.cpa.spreadsheet_id, fields="sheets.properties.title").execute()
    per_day, per_ad, undated, latest = Counter(), defaultdict(Counter), 0, None
    for t in (x["properties"]["title"] for x in meta.get("sheets", [])):
        if not ("regist" in t.lower() or "报名" in t or "報名" in t):
            continue
        rows, _c, hdr = cpa.parse_sales(sh.read_tab(s.cpa.spreadsheet_id, t), 0.0)
        sg = [x for x in rows if _sg(x.campaign)]
        dated = [x.date for x in sg if x.date]
        latest = max(dated + ([latest] if latest else []), default=latest)
        log.info("分页 %r：SG 带 UTM 的 %d 行 · 最近一行日期 %s", t, len(sg), max(dated, default=None))
        for x in sg:
            if not x.date:
                undated += 1
            elif x.date >= since:
                per_day[x.date] += 1
                per_ad[x.date][x.ad[:34]] += 1
    tok = result_action_type(s.meta.conversion_event)
    g = graph_client(s)
    meta_day = Counter()
    for r in g._get_all(f"{HK}/insights", {"level": "campaign", "limit": 500, "time_increment": 1,
                                            "fields": "campaign_name,actions",
                                            "time_range": json.dumps({"since": since.isoformat(), "until": today.isoformat()})}):
        if _sg(r.get("campaign_name") or ""):
            meta_day[dt.date.fromisoformat(r["date_start"])] += extract_results(r.get("actions"), tok)
    log.info("═" * 90)
    log.info("日期        报名表 SG 行数   Meta 记到的报名（HK 账户 SG campaign）")
    d = since
    while d <= today:
        log.info("%s %s   %-14d %d   %s", d, "一二三四五六日"[d.weekday()], per_day[d], int(meta_day[d]),
                 " · ".join(f"{k}×{v}" for k, v in per_ad[d].most_common(4)))
        d += dt.timedelta(days=1)
    log.info("没有日期的 SG 行：%d · 报名表最近一行 %s", undated, latest)
    final_summary(log, "register vs meta · read-only")


if __name__ == "__main__":
    main()
