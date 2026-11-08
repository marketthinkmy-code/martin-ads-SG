"""This cycle, every SG ad that spent: still right to be on / off? Budget now and spend forecast. Read-only.

Operator 8 Nov: 有哪些需要我做决定要我关的吗？现在 daily budget 多少？预测花到星期三总花费？确保都符合
CPA CPL 的条件，有没有误关？double check。

Cycle = Thursday ADBOT_CYCLE_FROM (default 2026-11-05) to today (SGT). For every ad on SG old + HK
with spend in the cycle:
  cycle spend / Meta registrations / Register-tab registrations (UTM campaign + ad set + ad, SG rows)
  own sales (paid sheet, same three names): all time, last 60 days (the monitor's protection window),
  newest date; lifetime spend and CPA; current status.
Verdict for an ad that is OFF:
  符合 RM90 线       cycle spend >= RM90, 0 Meta registrations, 0 Register-tab rows, no own sale in 60 days
  ⚠ 疑似误关         Meta says 0 but the Register tab has rows for it, or it has an own sale in 60 days
  手动关             paused below the RM90 line or with registrations (an operator decision, shown as is)
Verdict for an ad that is ON: CPL (Meta and Register tab) against RM82 / RM144, lifetime CPA band,
and whether it already crossed RM90 with 0 registrations.
Budget: live campaigns' daily budget (CBO) or live ad sets' (ABO). Forecast = today's remaining budget
(budget minus today's spend, floored at 0) + budget x each later day up to ADBOT_CYCLE_END (default
Tuesday 2026-11-10); a second line adds Wednesday. No writes.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from collections import Counter, defaultdict

from adbot import cpa
from adbot.clients.graph import TransientGraphError
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

ACCTS = [("SG老户", "act_1024930575770087"), ("HK", "act_1179668409969241")]
NOT_LIVE = ("PAUSED", "ADSET_PAUSED", "CAMPAIGN_PAUSED", "ARCHIVED", "DELETED")
KILL = 90.0


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _sg(c):
    c = cpa.norm(c)
    return "[sg]" in c or "martin-sg" in c or "martin sg" in c


def key3(c, s, a):
    return cpa.ad_key(c), cpa.ad_key(s), cpa.ad_key(a)


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    tok = result_action_type(s.meta.conversion_event)
    cfg = s.cpa
    now = dt.datetime.utcnow() + dt.timedelta(hours=8)
    today = now.date()
    c_from = dt.date.fromisoformat(os.environ.get("ADBOT_CYCLE_FROM") or "2026-11-05")
    c_end = dt.date.fromisoformat(os.environ.get("ADBOT_CYCLE_END") or "2026-11-10")
    d60 = today - dt.timedelta(days=60)
    log.info("读数 %s SGT · 本期 %s ~ 今天 · 本期最后一天 %s（星期二）", now.strftime("%Y-%m-%d %H:%M"), c_from, c_end)

    sh = SheetsClient(s.secrets.google_sa_json)
    sales, _c, _h = cpa.parse_sales(sh.read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab), s.cpa.price_myr)
    own = defaultdict(list)
    for x in sales:
        own[key3(x.campaign, x.adset, x.ad)].append(x.date)
    regs = Counter()
    rows, _c2, _h2 = cpa.parse_sales(sh.read_tab(s.cpa.spreadsheet_id, "Register"), 0.0)
    for x in rows:
        if _sg(x.campaign) and x.date and x.date >= c_from:
            regs[key3(x.campaign, x.adset, x.ad)] += 1

    out, budgets, today_sp = [], [], 0.0
    for label, acct in ACCTS:
        cyc = g._get_all(f"{acct}/insights", {"level": "ad", "limit": 500,
                                              "fields": "ad_id,ad_name,adset_name,campaign_name,spend,actions",
                                              "time_range": json.dumps({"since": c_from.isoformat(), "until": today.isoformat()})})
        cyc = [r for r in cyc if _f(r.get("spend")) > 0]
        tdy = {r["ad_id"]: _f(r.get("spend")) for r in g._get_all(f"{acct}/insights", {
            "level": "ad", "limit": 500, "fields": "ad_id,spend",
            "time_range": json.dumps({"since": today.isoformat(), "until": today.isoformat()})})}
        ids = [r["ad_id"] for r in cyc]
        life = {}
        for i in range(0, len(ids), 50):
            for r in g._get_all(f"{acct}/insights", {"level": "ad", "limit": 500, "fields": "ad_id,spend",
                                                     "date_preset": "maximum",
                                                     "filtering": json.dumps([{"field": "ad.id", "operator": "IN",
                                                                               "value": ids[i:i + 50]}])}):
                life[r["ad_id"]] = _f(r.get("spend"))
        for r in cyc:
            a = g.get_object(r["ad_id"], "effective_status,adset{id,daily_budget,effective_status},"
                                         "campaign{id,daily_budget,effective_status}")
            k = key3(r.get("campaign_name") or "", r.get("adset_name") or "", r.get("ad_name") or "")
            ds = sorted(d for d in own.get(k, []) if d)
            live = a.get("effective_status") not in NOT_LIVE
            out.append({"acct": label, "id": r["ad_id"], "name": r.get("ad_name") or "", "live": live,
                        "st": a.get("effective_status"), "sp": _f(r.get("spend")),
                        "rg": extract_results(r.get("actions"), tok), "sheet": regs.get(k, 0),
                        "own": len(own.get(k, [])), "own60": sum(1 for d in ds if d > d60),
                        "last_sale": ds[-1] if ds else None, "life": life.get(r["ad_id"], 0.0),
                        "today": tdy.get(r["ad_id"], 0.0)})
            if live:
                c, st = a.get("campaign") or {}, a.get("adset") or {}
                owner = ("campaign", c.get("id"), _f(c.get("daily_budget"))) if c.get("daily_budget") else \
                        ("ad set", st.get("id"), _f(st.get("daily_budget")))
                budgets.append((label, owner, tdy.get(r["ad_id"], 0.0)))
                today_sp += tdy.get(r["ad_id"], 0.0)

    def band(v):
        if v is None:
            return "零成交"
        for lim, name in ((cfg.target_myr, "≤目标 740"), (cfg.healthy_max_myr, "健康 ≤860"),
                          (cfg.max_acceptable_myr, "可接受 ≤1,040"), (cfg.hard_stop_myr, "暂停候选 ≤1,300")):
            if v <= lim:
                return name
        return "超硬停线 1,300"

    log.info("═" * 100)
    log.info("A. 已关的（本期有花钱）")
    for r in sorted((r for r in out if not r["live"]), key=lambda r: -r["sp"]):
        if r["sp"] >= KILL and r["rg"] == 0 and r["sheet"] == 0 and r["own60"] == 0:
            v = "符合 RM90 线（花 ≥90、Meta 0 报名、报名表 0、60 天内没有自己的成交）"
        elif r["rg"] == 0 and r["sheet"] > 0 or r["own60"] > 0:
            v = "⚠ 疑似误关（" + ("报名表有报名" if r["sheet"] else "") + (" 60 天内有自己的成交" if r["own60"] else "") + "）"
        else:
            v = "手动关（没到 RM90 线或有报名，是 operator 的决定）"
        cpa_v = r["life"] / r["own"] if r["own"] else None
        log.info("   %s ad %s %r · %s · 本期花 RM%.2f · Meta 报名 %d · 报名表 %d · 自己成交 全期 %d / 60 天 %d（最后 %s）"
                 " · 全期花 RM%.2f CPA %s（%s）→ %s", r["acct"], r["id"], r["name"][:40], r["st"], r["sp"], r["rg"],
                 r["sheet"], r["own"], r["own60"], r["last_sale"], r["life"],
                 f"RM{cpa_v:.2f}" if cpa_v else "—", band(cpa_v), v)

    log.info("═" * 100)
    log.info("B. 在跑的")
    for r in sorted((r for r in out if r["live"]), key=lambda r: -r["sp"]):
        cpa_v = r["life"] / r["own"] if r["own"] else None
        cpl_m = r["sp"] / r["rg"] if r["rg"] else None
        cpl_s = r["sp"] / r["sheet"] if r["sheet"] else None
        flags = []
        if r["sp"] >= KILL and r["rg"] == 0 and r["own60"] == 0:
            flags.append("已过 RM90 线、0 报名（监控下一轮会关）")
        for lab, v in (("Meta", cpl_m), ("报名表", cpl_s)):
            if v is not None:
                flags.append(f"{lab} CPL {'≤82 达标' if v <= 82 else '≤144 可接受' if v <= 144 else '>144 偏高'}")
        log.info("   %s ad %s %r · 本期花 RM%.2f（今天 RM%.2f）· Meta 报名 %d（CPL %s）· 报名表 %d（CPL %s）· 自己成交 全期 %d / 60 天 %d"
                 "（最后 %s）· 全期 CPA %s（%s）· %s", r["acct"], r["id"], r["name"][:40], r["sp"], r["today"], r["rg"],
                 f"RM{cpl_m:.2f}" if cpl_m else "—", r["sheet"], f"RM{cpl_s:.2f}" if cpl_s else "—", r["own"], r["own60"],
                 r["last_sale"], f"RM{cpa_v:.2f}" if cpa_v else "—", band(cpa_v), " · ".join(flags) or "—")

    owners = {}
    for label, (lvl, oid, b) in [(x[0], x[1]) for x in budgets]:
        owners[(label, lvl, oid)] = b / 100
    daily = sum(owners.values())
    rest_today = max(daily - today_sp, 0.0)
    later = max((c_end - today).days, 0)
    spent = sum(r["sp"] for r in out)
    f_tue = spent + rest_today + daily * later
    f_wed = f_tue + daily
    log.info("═" * 100)
    log.info("C. 预算：%s", " · ".join(f"{k[0]} {k[1]} {k[2]} RM{v:.0f}" for k, v in owners.items()))
    log.info("   每天预算合计 RM%.2f · 本期已花 RM%.2f（Meta 报名 %d · 报名表 %d）· 今天已花 RM%.2f · 今天剩 RM%.2f · 之后 %d 天",
             daily, spent, sum(r["rg"] for r in out), sum(r["sheet"] for r in out), today_sp, rest_today, later)
    log.info("   预测（照每天预算花满）：到星期二 %s 本期合计 RM%.2f · 星期三也跑满一天 RM%.2f", c_end, f_tue, f_wed)
    final_summary(log, f"每天 RM{daily:.0f} · 本期已花 RM{spent:.2f} · 预测到星期二 RM{f_tue:.2f} / 含星期三 RM{f_wed:.2f} · "
                       f"已关 {sum(1 for r in out if not r['live'])} 支 · 在跑 {sum(1 for r in out if r['live'])} 支")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min.", str(exc)[:200])
        sys.exit(75)
