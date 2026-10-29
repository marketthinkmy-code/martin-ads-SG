"""What is running on SG old + HK right now, and at what daily budget? (read-only, 29 Oct)

Operator: 你建议我现在跑新广告吗？每日花费多少？HK + SG. Per account: every ACTIVE campaign with its daily
budget (CBO: the campaign's; ABO: the sum of its ACTIVE ad sets), ads by effective status, and
spend / registrations today and since Thursday (the weekly cycle). No writes.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import Counter

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type, _week_start_thursday
from adbot.settings import load_settings

ACCTS = [("SG老户", "act_1024930575770087"), ("HK", "act_1179668409969241")]


def _c(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    tok = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    thu = _week_start_thursday(today)
    out = []
    for label, acct in ACCTS:
        camps = [c for c in g._get_all(f"{acct}/campaigns", {"fields": "id,name,effective_status,daily_budget", "limit": 300})
                 if c.get("effective_status") == "ACTIVE"]
        total = 0
        log.info("═" * 100)
        for c in camps:
            sets = [a for a in g._get_all(f"{c['id']}/adsets", {"fields": "id,name,effective_status,daily_budget", "limit": 100})
                    if a.get("effective_status") == "ACTIVE"]
            ads = g._get_all(f"{c['id']}/ads", {"fields": "id,name,effective_status,adset_id", "limit": 200})
            live = [a for a in ads if a.get("effective_status") not in ("PAUSED", "ADSET_PAUSED", "CAMPAIGN_PAUSED",
                                                                          "ARCHIVED", "DELETED")]
            st = Counter(a.get("effective_status") for a in live)
            live_sets = {a.get("adset_id") for a in live}
            # ABO: only ad sets with a live ad spend — an ACTIVE ad set whose ads are all paused does not
            budget = _c(c.get("daily_budget")) or sum(_c(a.get("daily_budget")) for a in sets if a["id"] in live_sets)
            for a in live:
                log.info("      ad %s %r · %s", a["id"], a.get("name"), a.get("effective_status"))
            total += budget
            log.info("%s · campaign %s %r · 每天 RM%.0f · %s", label, c["id"], c.get("name"), budget / 100, dict(st))
        ins = {}
        for key, tr in (("today", {"since": today.isoformat(), "until": today.isoformat()}),
                        ("week", {"since": thu.isoformat(), "until": today.isoformat()})):
            r = (g._get_all(f"{acct}/insights", {"fields": "spend,actions", "time_range": json.dumps(tr)}) or [{}])[0]
            ins[key] = (float(r.get("spend") or 0), extract_results(r.get("actions"), tok))
        log.info("▌%s · 在跑的 campaign %d 个 · 每天预算合计 RM%.0f · 今天花 RM%.2f 报名 %d · 星期四(%s)起花 RM%.2f 报名 %d",
                 label, len(camps), total / 100, ins["today"][0], ins["today"][1], thu, ins["week"][0], ins["week"][1])
        out.append((label, len(camps), total, ins))
    t = sum(o[2] for o in out)
    final_summary(log, f"SG老户 + HK 每天预算合计 RM{t / 100:.0f} · " + " | ".join(
        f"{o[0]}: {o[1]} campaign RM{o[2] / 100:.0f}/天 · 今天 RM{o[3]['today'][0]:.2f}/{o[3]['today'][1]:.0f} 报名 · "
        f"本周 RM{o[3]['week'][0]:.2f}/{o[3]['week'][1]:.0f} 报名" for o in out))


if __name__ == "__main__":
    main()
