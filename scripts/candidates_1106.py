"""Which paused SG sellers can be reopened now? (read-only, 6 Nov)

Operator: 新加坡没有什么广告在跑了呢。。。。 怎么办呢？ Every SG sale in the paid sheet (any date) is
grouped by its UTM campaign + ad set + ad (cpa.ad_key folded; a sheet campaign cut short is matched as
a prefix of the Meta name). For each group, every ad on SG old + HK with those three names that is NOT
running now: lifetime spend / registrations (one daily insights call), last day it spent, the 7 days
ending on that day (rule 3), its last 30 delivery days, created date. Copies sharing the three names
split the sales: the group CPA = all copies' lifetime spend / the group's sales. Verdict per ad:
  ✅ 可以复活  group CPA <= max acceptable (1,040) and >= 1 registration in its last 7 days
  ⚠ 规矩 3 不过  CPA ok but 0 registrations in its last 7 days
  ❌ CPA 超     group CPA > 1,040
No names, phones or emails are read. No writes.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from collections import defaultdict

from adbot import cpa
from adbot.clients.graph import TransientGraphError
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

ACCTS = [("SG老户", "act_1024930575770087"), ("HK", "act_1179668409969241")]
AD_F = ("id,name,effective_status,created_time,adset{id,name,daily_budget,effective_status},"
        "campaign{id,name,effective_status,daily_budget}")


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
    cfg = s.cpa
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    sales, _c, _h = cpa.parse_sales(SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab),
                                    s.cpa.price_myr)
    sg = [x for x in sales if _sg(x.campaign)]
    groups = defaultdict(list)
    for x in sg:
        groups[(cpa.ad_key(x.campaign), cpa.ad_key(x.adset), cpa.ad_key(x.ad))].append(x)
    log.info("成交表 SG 成交 %d 笔 · %d 组 campaign + ad set + ad", len(sg), len(groups))

    ads = []
    for label, acct in ACCTS:
        for a in g._get_all(f"{acct}/ads", {"fields": AD_F, "limit": 500}):
            a["_acct"] = label
            a["_k"] = (cpa.ad_key((a.get("campaign") or {}).get("name") or ""),
                       cpa.ad_key((a.get("adset") or {}).get("name") or ""), cpa.ad_key(a.get("name") or ""))
            ads.append(a)

    def same(sk, ak):
        c, st, d = sk
        return st == ak[1] and d == ak[2] and (c == ak[0] or (len(c) >= 12 and ak[0].startswith(c)))

    hits = {k: [a for a in ads if same(k, a["_k"])] for k in groups}
    hits = {k: v for k, v in hits.items() if v}
    life = {}                                    # lifetime spend per ad: one call per 50 ids per account
    for label, acct in ACCTS:
        ids = sorted({a["id"] for v in hits.values() for a in v if a["_acct"] == label})
        for i in range(0, len(ids), 50):
            for r in g._get_all(f"{acct}/insights", {"level": "ad", "limit": 500, "fields": "ad_id,spend",
                                                     "date_preset": "maximum",
                                                     "filtering": json.dumps([{"field": "ad.id", "operator": "IN",
                                                                               "value": ids[i:i + 50]}])}):
                life[r["ad_id"]] = _f(r.get("spend"))
    rows, cache, skipped = [], {}, 0
    for k, xs in groups.items():
        hit = hits.get(k)
        if not hit:
            continue
        group_sp = sum(life.get(a["id"], 0.0) for a in hit)
        g_cpa = group_sp / len(xs)
        if g_cpa > cfg.max_acceptable_myr:       # CPA already over 1,040: no daily read needed
            skipped += sum(1 for a in hit if life.get(a["id"], 0.0) > 0)
            continue
        for a in hit:
            if a["id"] not in cache:
                daily = g._get_all(f"{a['id']}/insights", {"date_preset": "maximum", "time_increment": 1,
                                                           "fields": "spend,actions"})
                cache[a["id"]] = [(d["date_start"], _f(d.get("spend")), extract_results(d.get("actions"), tok))
                                  for d in daily if _f(d.get("spend")) > 0]
        live = [a for a in hit if a.get("effective_status") == "ACTIVE"
                and (a.get("campaign") or {}).get("effective_status") == "ACTIVE"
                and (a.get("adset") or {}).get("effective_status") == "ACTIVE"]
        for a in hit:
            if a in live:
                continue
            days = cache[a["id"]]
            if not days:
                continue
            last = dt.date.fromisoformat(days[-1][0])
            seg7 = [v for v in days if dt.date.fromisoformat(v[0]) > last - dt.timedelta(days=7)]
            seg30 = days[-30:]
            rows.append({
                "acct": a["_acct"], "id": a["id"], "name": a.get("name") or "", "camp": (a.get("campaign") or {}).get("name") or "",
                "cid": (a.get("campaign") or {}).get("id"), "set": (a.get("adset") or {}).get("name") or "",
                "sid": (a.get("adset") or {}).get("id"), "budget": _f((a.get("adset") or {}).get("daily_budget")) / 100,
                "cbudget": _f((a.get("campaign") or {}).get("daily_budget")) / 100,
                "st": a.get("effective_status"), "created": (a.get("created_time") or "")[:10],
                "sales": len(xs), "last_sale": max((x.date for x in xs if x.date), default=None),
                "copies": len(hit), "live_copies": len(live), "group_sp": group_sp, "g_cpa": g_cpa,
                "sp": sum(v[1] for v in days), "rg": sum(v[2] for v in days), "last": last,
                "sp7": sum(v[1] for v in seg7), "rg7": sum(v[2] for v in seg7),
                "sp30": sum(v[1] for v in seg30), "rg30": sum(v[2] for v in seg30), "d30": len(seg30),
            })

    def verdict(r):
        if r["live_copies"]:
            return "↺ 同名副本在跑"
        if r["g_cpa"] > cfg.max_acceptable_myr:
            return "❌ CPA 超 1,040"
        if r["rg7"] < 1:
            return "⚠ 规矩 3 不过（停前 7 天 0 报名）"
        return "✅ 可以复活"

    order = {"✅": 0, "⚠": 1, "↺": 2, "❌": 3}
    rows.sort(key=lambda r: (order[verdict(r)[0]], r["g_cpa"]))
    for r in rows:
        v = verdict(r)
        log.info("═" * 100)
        log.info("%s · %s ad %s %r · 现在 %s · 建于 %s", v, r["acct"], r["id"], r["name"][:45], r["st"], r["created"])
        log.info("   campaign %s %r（预算 %s）· ad set %s %r（日预算 %s）", r["cid"], r["camp"][:75],
                 f"RM{r['cbudget']:.0f}" if r["cbudget"] else "—", r["sid"], r["set"][:40],
                 f"RM{r['budget']:.0f}" if r["budget"] else "—")
        log.info("   自己的成交 %d 笔（最后一笔 %s）· 同名副本 %d 支（在跑 %d）· 副本合计花 RM%.2f · CPA RM%.2f · 下一单来 RM%.2f",
                 r["sales"], r["last_sale"], r["copies"], r["live_copies"], r["group_sp"], r["g_cpa"],
                 r["group_sp"] / (r["sales"] + 1))
        log.info("   这支全期 花 RM%.2f 报名 %d CPL %s · 最后花钱 %s · 停前 7 天 花 RM%.2f 报名 %d CPL %s · 最后 %d 个投放日 花 RM%.2f 报名 %d CPL %s",
                 r["sp"], r["rg"], f"RM{r['sp'] / r['rg']:.2f}" if r["rg"] else "—", r["last"], r["sp7"], r["rg7"],
                 f"RM{r['sp7'] / r['rg7']:.2f}" if r["rg7"] else "—", r["d30"], r["sp30"], r["rg30"],
                 f"RM{r['sp30'] / r['rg30']:.2f}" if r["rg30"] else "—")
    ok = [r for r in rows if verdict(r).startswith("✅")]
    log.info("全期 CPA 已经超 RM1,040 的广告 %d 支（没有逐日读）", skipped)
    final_summary(log, f"CPA ≤1,040 但没在跑的卖家广告 {len(rows)} 支 · 可以复活 {len(ok)} · " +
                  " | ".join(f"{r['acct']} {r['id']} {r['name'][:20]} CPA RM{r['g_cpa']:.0f} 停前7天 {r['rg7']:.0f} 报名" for r in ok))


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min.", str(exc)[:200])
        sys.exit(75)
