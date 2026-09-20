"""Probe board 0920 (read-only): where did the missing live names go?

The 30d-CPA enforcement at 10:25 UTC saw only 3 live names; yesterday there were 7.
The monitor ledger explains only Hook 4 (CPL cut RM80→56, still meant to be live).
Print every copy's effective_status (+ ad set budget/status) for the recent board names,
plus each name's week-to-date spend/leads, so the disappearances are attributable.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict

from adbot import cpa
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

NAMES = [
    "Hook 1：今晚回家检查三件事",
    "Hook 3：倒掉牛奶",
    "Hook 4：保健品叫你丢掉",
    "Hook 6：没有人会告诉你",
    "Hook 8：我劝你，先别买",
    "Video 1: 流鼻涕 咳嗽 allergy 每晚睡不好",
    "Video 12：15歲以上試了五六種方法沒長高",
    "Carousel：别再逼孩子喝牛奶了",
]
WTD_START = dt.date(2026, 9, 14)      # this week's Monday, the monitor's wtd window


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    token = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()

    keys = {cpa.ad_key(n): n for n in NAMES}
    ads = g._get_all(f"{acct}/ads",
                     {"fields": "id,name,status,effective_status,adset_id", "limit": 500})
    adsets = {a["id"]: a for a in g._get_all(
        f"{acct}/adsets",
        {"fields": "id,status,effective_status,daily_budget,campaign_id", "limit": 500})}

    wtd_sp: Dict[str, float] = {}
    wtd_ld: Dict[str, float] = {}
    for r in g.account_insights(acct, level="ad", fields="ad_id,ad_name,spend,actions",
                                time_range={"since": WTD_START.isoformat(),
                                            "until": today.isoformat()}):
        k = cpa.ad_key(r.get("ad_name") or "")
        try:
            wtd_sp[k] = wtd_sp.get(k, 0.0) + float(r.get("spend") or 0)
        except (TypeError, ValueError):
            pass
        wtd_ld[k] = wtd_ld.get(k, 0.0) + extract_results(r.get("actions"), token)

    log.info("═" * 110)
    for k, name in keys.items():
        copies = [a for a in ads if cpa.ad_key(a.get("name") or "") == k]
        log.info("▸ %-38s wtd(%s→) 花 RM%-7.0f %dL", name[:38], WTD_START,
                 wtd_sp.get(k, 0.0), int(wtd_ld.get(k, 0)))
        for a in sorted(copies, key=lambda x: -int(x["id"])):
            aset = adsets.get(a.get("adset_id")) or {}
            log.info("    ad %s  cfg=%-7s eff=%-16s | adset %s cfg=%-7s eff=%-16s RM%s/day",
                     a["id"], a.get("status"), a.get("effective_status"),
                     a.get("adset_id"), aset.get("status"), aset.get("effective_status"),
                     int(aset.get("daily_budget") or 0) // 100 or "CBO")
    final_summary(log, "Board probe complete. Read-only.")


if __name__ == "__main__":
    main()
