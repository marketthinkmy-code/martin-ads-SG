"""Opening-day roll call (read-only, 2 Oct): operator 我开了，你盯着.

The operator just hand-opened part of the PAUSED SG board (and HK MILK stays
running). Dump everything delivering on BOTH accounts — campaign budget, every
ACTIVE ad with today's spend/leads — so chat can confirm exactly what is open,
plus two flags the opening advice hinged on:
  · Hook 1 copies ACTIVE (advice was to kill those before opening EW/FAMILY)
  · MILK ACTIVE on both accounts at once (same posts + same SG audience =
    self-competition)
No writes; the hourly monitor owns enforcement (RM70 / RM105).
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from typing import Dict

from adbot import cpa
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

HK_ACCT = "act_1179668409969241"


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    token = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    accounts = [("SG 老账户", s.meta.account_path), ("HK", HK_ACCT)]

    hook1, milk_live = [], []
    total_budget: Dict[str, int] = defaultdict(int)
    for label, acct in accounts:
        sp: Dict[str, float] = defaultdict(float)
        ld: Dict[str, float] = defaultdict(float)
        for r in g._get_all(f"{acct}/insights",
                            {"level": "ad", "limit": 500,
                             "fields": "ad_id,spend,actions",
                             "time_range": json.dumps({"since": today.isoformat(),
                                                       "until": today.isoformat()})}):
            try:
                sp[r.get("ad_id")] += float(r.get("spend") or 0)
            except (TypeError, ValueError):
                pass
            ld[r.get("ad_id")] += extract_results(r.get("actions"), token)

        by_camp = defaultdict(list)
        camp_meta = {}
        for a in g._get_all(f"{acct}/ads",
                            {"fields": "id,name,effective_status,"
                                       "campaign{id,name,daily_budget,effective_status},"
                                       "adset{name}", "limit": 500}):
            if a.get("effective_status") not in ("ACTIVE", "LEARNING", "IN_PROCESS",
                                                 "PENDING_REVIEW"):
                continue
            c = a.get("campaign") or {}
            if c.get("effective_status") not in ("ACTIVE", "IN_PROCESS"):
                continue
            camp_meta[c.get("id")] = c
            by_camp[c.get("id")].append(a)

        log.info("═══ %s %s · %d 条 campaign 在跑 ═══", label, acct, len(by_camp))
        for cid, ads in sorted(by_camp.items(), key=lambda kv: camp_meta[kv[0]].get("name") or ""):
            c = camp_meta[cid]
            try:
                total_budget[label] += int(c.get("daily_budget") or 0)
            except (TypeError, ValueError):
                pass
            cname = c.get("name") or ""
            log.info("📣 %s · RM%s/日 · %d ads", cname,
                     int(c.get("daily_budget") or 0) // 100, len(ads))
            if "milk" in cpa.norm(cname):
                milk_live.append(f"{label}:{cname}")
            for a in sorted(ads, key=lambda x: x.get("name") or ""):
                aid = a["id"]
                nm = (a.get("name") or "").strip()
                line = f"   ▸ {nm[:44]:<44} 今天 RM{sp.get(aid, 0.0):>6.2f} / {int(ld.get(aid, 0.0))}L · {a.get('effective_status')}"
                log.info("%s", line)
                if "hook 1" in cpa.norm(nm) or "今晚回家" in nm:
                    hook1.append(f"{label} · {cname[:28]} · {nm[:30]} ({aid})")

    log.info("═" * 100)
    if hook1:
        log.info("⚠️ Hook 1 仍开着（建议是先关再开 campaign）:")
        for h in hook1:
            log.info("   %s", h)
    if len(milk_live) > 1:
        log.info("⚠️ 两个账户的 MILK 同时在跑（同帖同 SG 受众，自我竞价）: %s", milk_live)
    final_summary(log, f"roll call: 预算 SG RM{total_budget['SG 老账户'] // 100}/日 + "
                       f"HK RM{total_budget['HK'] // 100}/日 · hook1_live={len(hook1)} · "
                       f"milk_both={'YES' if len(milk_live) > 1 else 'no'}")


if __name__ == "__main__":
    main()
