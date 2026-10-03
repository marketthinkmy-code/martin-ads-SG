"""Opening roll call (read-only): what is delivering on both accounts.

v2 (3 Oct morning): two windows per ad — 昨天 (full day) and 今天 (so far),
Asia/KL dates — so the overnight readout shows the opening day's final
numbers next to this morning's. Ads that SPENT in the window but are no
longer delivering (operator or monitor paused them) get their own section,
so an overnight auto-pause is visible instead of silently missing.
Flags kept from v1: live Hook 1 copies; MILK on both accounts at once.
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
    yday = today - dt.timedelta(days=1)
    accounts = [("SG 老账户", s.meta.account_path), ("HK", HK_ACCT)]
    log.info("窗口：昨天 %s 整天 · 今天 %s 截至现在（MYT）", yday, today)

    hook1, milk_live = [], []
    for label, acct in accounts:
        perf: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {"y_sp": 0.0, "y_ld": 0.0, "t_sp": 0.0, "t_ld": 0.0})
        for r in g._get_all(f"{acct}/insights",
                            {"level": "ad", "limit": 500, "time_increment": 1,
                             "fields": "ad_id,ad_name,date_start,spend,actions",
                             "time_range": json.dumps({"since": yday.isoformat(),
                                                       "until": today.isoformat()})}):
            pre = "y_" if r.get("date_start") == yday.isoformat() else "t_"
            d = perf[r.get("ad_id")]
            try:
                d[pre + "sp"] += float(r.get("spend") or 0)
            except (TypeError, ValueError):
                pass
            d[pre + "ld"] += extract_results(r.get("actions"), token)
            d.setdefault("name", r.get("ad_name") or "")

        by_camp = defaultdict(list)
        camp_meta, seen, stopped = {}, set(), []
        for a in g._get_all(f"{acct}/ads",
                            {"fields": "id,name,effective_status,"
                                       "campaign{id,name,effective_status},"
                                       "adset{name}", "limit": 500}):
            delivering = (a.get("effective_status") in ("ACTIVE", "LEARNING",
                                                        "IN_PROCESS", "PENDING_REVIEW"))
            c = a.get("campaign") or {}
            camp_live = c.get("effective_status") in ("ACTIVE", "IN_PROCESS")
            if delivering and camp_live:
                camp_meta[c.get("id")] = c
                by_camp[c.get("id")].append(a)
                seen.add(a["id"])
            elif a["id"] in perf and (perf[a["id"]]["y_sp"] or perf[a["id"]]["t_sp"]):
                stopped.append((a.get("name") or "", a["id"], a.get("effective_status"),
                                c.get("name") or ""))

        def fmt(aid: str) -> str:
            p = perf.get(aid) or {"y_sp": 0.0, "y_ld": 0.0, "t_sp": 0.0, "t_ld": 0.0}
            ycpl = f" CPL{p['y_sp'] / p['y_ld']:,.0f}" if p["y_ld"] else ""
            tcpl = f" CPL{p['t_sp'] / p['t_ld']:,.0f}" if p["t_ld"] else ""
            return (f"昨 RM{p['y_sp']:>6.2f}/{int(p['y_ld'])}L{ycpl} · "
                    f"今 RM{p['t_sp']:>5.2f}/{int(p['t_ld'])}L{tcpl}")

        log.info("═══ %s %s · %d 条 campaign 在跑 ═══", label, acct, len(by_camp))
        for cid, ads in sorted(by_camp.items(),
                               key=lambda kv: camp_meta[kv[0]].get("name") or ""):
            cname = camp_meta[cid].get("name") or ""
            ysp = sum((perf.get(a["id"]) or {}).get("y_sp", 0.0) for a in ads)
            yld = sum((perf.get(a["id"]) or {}).get("y_ld", 0.0) for a in ads)
            tsp = sum((perf.get(a["id"]) or {}).get("t_sp", 0.0) for a in ads)
            tld = sum((perf.get(a["id"]) or {}).get("t_ld", 0.0) for a in ads)
            log.info("📣 %s · 昨 RM%.0f/%dL · 今 RM%.0f/%dL", cname, ysp, int(yld),
                     tsp, int(tld))
            if "milk" in cpa.norm(cname):
                milk_live.append(f"{label}:{cname}")
            for a in sorted(ads, key=lambda x: x.get("name") or ""):
                nm = (a.get("name") or "").strip()
                log.info("   ▸ %-40s %s · %s", nm[:40], fmt(a["id"]),
                         a.get("effective_status"))
                if "hook 1" in cpa.norm(nm) or "今晚回家" in nm:
                    hook1.append(f"{label} · {cname[:28]} · {nm[:30]} ({a['id']})")
        if stopped:
            log.info("⏸ 窗口内有花费、现已停投：")
            for nm, aid, eff, cname in stopped:
                log.info("   ▸ %-40s %s · %s · %s", nm[:40], fmt(aid), eff, cname[:34])

    log.info("═" * 100)
    if hook1:
        log.info("⚠️ Hook 1 仍开着:")
        for h in hook1:
            log.info("   %s", h)
    if len(milk_live) > 1:
        log.info("⚠️ 两个账户的 MILK 同时在跑: %s", milk_live)
    final_summary(log, f"roll call v2: hook1_live={len(hook1)} · "
                       f"milk_both={'YES' if len(milk_live) > 1 else 'no'}")


if __name__ == "__main__":
    main()
