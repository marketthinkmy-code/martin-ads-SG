"""Rule 3 + rule 4 check for candidate creatives (read-only, 26 Oct).

ADBOT_NAMES = '|'-separated ad names. For each (folded by cpa.ad_key):
  rule 4: spend / registrations on MY, HK, SG old — lifetime and last 30 days (MY read only)
  rule 3: every SG-market ad of it, newest delivery first: last delivery day, and spend +
          registrations over its last 7 delivering days
  sales:  SG sales lifetime / 60 days by UTM ad set; MY sales lifetime
  post:   the newest SG-market ad's id + page post (the build reuses it)
No writes.
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

ACCTS = [("SG老", "act_1024930575770087"), ("HK", "act_1179668409969241"), ("MY", "act_1011719073600566")]


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
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    names = [n.strip() for n in (os.environ.get("ADBOT_NAMES") or "").split("|") if n.strip()]
    keys = {cpa.ad_key(n): n for n in names}

    sales, _c, _h = cpa.parse_sales(SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab),
                                    s.cpa.price_myr)
    sold = defaultdict(lambda: {"SG": 0, "SG60": 0, "MY": 0, "sets": defaultdict(int)})
    for x in sales:
        k = cpa.ad_key(x.ad)
        if k not in keys or not x.date:
            continue
        m = _mkt(x.campaign)
        if m == "SG":
            sold[k]["SG"] += 1
            sold[k]["sets"][(x.adset or "")[:34]] += 1
            if x.date >= today - dt.timedelta(days=60):
                sold[k]["SG60"] += 1
        elif m == "MY":
            sold[k]["MY"] += 1

    life = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    d30 = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    ads = defaultdict(list)
    tr30 = json.dumps({"since": (today - dt.timedelta(days=30)).isoformat(), "until": today.isoformat()})
    for label, acct in ACCTS:
        for window, store in (({"date_preset": "maximum"}, life), ({"time_range": tr30}, d30)):
            for r in g._get_all(f"{acct}/insights", {"level": "ad", "limit": 500, **window,
                                                      "fields": "campaign_name,ad_id,ad_name,adset_name,spend,actions"}):
                k = cpa.ad_key(r.get("ad_name") or "")
                if k not in keys:
                    continue
                o = store[k][label]; o[0] += _f(r.get("spend")); o[1] += extract_results(r.get("actions"), tok)
                if store is life and label != "MY" and _f(r.get("spend")) > 0 and _mkt(r.get("campaign_name") or "") == "SG":
                    ads[k].append((label, acct, r["ad_id"], r.get("adset_name") or "", r.get("campaign_name") or ""))

    for k, nm in keys.items():
        log.info("═" * 110)
        sd = sold[k]
        log.info("▌%s · SG 成交 全部 %d 单 / 60 天 %d 单 · MY 成交 %d 单 · SG 成交 ad set：%s", nm, sd["SG"], sd["SG60"], sd["MY"],
                 " · ".join(f"{a}×{n}" for a, n in sorted(sd["sets"].items(), key=lambda kv: -kv[1])) or "—")
        for label, _ in ACCTS:
            (sp, ld), (sp3, ld3) = life[k][label], d30[k][label]
            log.info("    规矩4 %-4s 全部 RM%.2f · %d 报名 · 每个报名 %s   |   最近30天 RM%.2f · %d 报名 · 每个报名 %s", label,
                     sp, int(ld), f"RM{sp / ld:.0f}" if ld else "—", sp3, int(ld3), f"RM{sp3 / ld3:.0f}" if ld3 else "—")
        rows = []
        for label, acct, aid, aset, camp in ads[k]:
            daily = []
            for i in range(13):
                hi = today - dt.timedelta(days=30 * i); lo = hi - dt.timedelta(days=29)
                for r in g._get_all(f"{acct}/insights", {"level": "ad", "limit": 100, "time_increment": 1,
                                                          "time_range": json.dumps({"since": lo.isoformat(), "until": hi.isoformat()}),
                                                          "filtering": json.dumps([{"field": "ad.id", "operator": "IN", "value": [aid]}]),
                                                          "fields": "spend,actions"}):
                    if _f(r.get("spend")) > 0:
                        daily.append((r["date_start"], _f(r.get("spend")), extract_results(r.get("actions"), tok)))
                if daily and lo.isoformat() < min(d for d, _, _ in daily):
                    break
            if not daily:
                continue
            daily.sort(); last7 = daily[-7:]
            rows.append((daily[-1][0], label, aid, aset, camp, sum(v[1] for v in last7), int(sum(v[2] for v in last7))))
        for last, label, aid, aset, camp, sp7, ld7 in sorted(rows, reverse=True)[:4]:
            log.info("    规矩3 %-4s ad %s · 最后投放 %s · 最后7个投放日 RM%.2f · %d 报名 · %s | %s", label, aid, last, sp7, ld7,
                     aset[:28], camp[:56])
        if rows:
            newest = sorted(rows, reverse=True)[0]
            try:
                post = (g.get_object(newest[2], "creative{effective_object_story_id}").get("creative") or {}).get("effective_object_story_id")
            except Exception as exc:  # noqa: BLE001
                post = f"读不到：{str(exc)[:60]}"
            log.info("    最新 SG 广告 %s %s · 帖子 %s", newest[1], newest[2], post)
    final_summary(log, f"candidate check · {len(keys)} creatives · read-only")


if __name__ == "__main__":
    main()
