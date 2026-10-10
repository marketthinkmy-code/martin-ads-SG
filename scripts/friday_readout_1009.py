"""周五早上读数 (read-only, 9 Oct 09:00 MYT), SG old + HK only.

Operator: 周五早上跑一次读数给我. Goal E for the 14/10 webinar: 提高有证据支持的新 Lead
买家／报名转化率, so every ad carries two ratios besides spend/leads/CPL:
  报名率 = leads ÷ link clicks (Meta)      买家转化 = sheet SG sales ÷ leads (same ad, folded)
Part ①  the three 新片5支重测 CBO RM100 campaigns: per ad 周四开板日 / 周五 spend+leads,
        who the CBO fed, who is starving, who the RM80 zero-lead line already paused.
        Then every other delivering campaign on SG old and HK.
Part ②  sales: SG sales dated ≥ 10/7 (the Wednesday webinar) folded by ad name across both
        accounts; 30d/60d CPA; if the sheet has no new SG sale since 10/7, say so and do not
        judge the webinar. Suggestions only, nothing is written.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from collections import defaultdict
from typing import Any, Dict, List

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

ACCOUNTS = [("SG老", "act_1024930575770087"), ("HK", "act_1179668409969241")]
WEBINAR, OPEN, NEXT = dt.date(2026, 10, 7), dt.date(2026, 10, 8), dt.date(2026, 10, 14)
WEEK = OPEN                                   # 10 Oct operator: 从星期四到现在 — the window starts Thursday 10/8
DAY_LABELS = {3: "四", 4: "五", 5: "六", 6: "日", 0: "一", 1: "二", 2: "三"}
RETEST = "新片5支重测"
TEST_TOKENS = ("15岁以上新片", "线下见证新片", RETEST)
CPL, KILL = 70.0, 105.0
RUNNING = ("ACTIVE", "IN_PROCESS", "PENDING_REVIEW")
LISTABLE = ["ACTIVE", "PAUSED", "ARCHIVED", "PENDING_REVIEW", "DISAPPROVED", "PREAPPROVED",
            "PENDING_BILLING_INFO", "CAMPAIGN_PAUSED", "ADSET_PAUSED", "IN_PROCESS", "WITH_ISSUES"]


def _sg(campaign: str) -> bool:
    c = cpa.norm(campaign)
    return ("[sg]" in c) or ("martin-sg" in c) or ("martin sg" in c)


def _f(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    token = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d30, d60 = today - dt.timedelta(days=30), today - dt.timedelta(days=60)
    acc, hard, nosale = s.cpa.max_acceptable_myr, s.cpa.hard_stop_myr, s.cpa.min_spend_myr

    # ── Meta: per ad id (spend, leads, clicks) per window; per ad name folded across accounts ──
    def pull(acct, since, until):
        by_id: Dict[str, List[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
        by_key: Dict[str, List[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
        for r in g._get_all(f"{acct}/insights",
                            {"level": "ad", "limit": 500, "fields": "ad_id,ad_name,spend,actions,inline_link_clicks",
                             "time_range": json.dumps({"since": since.isoformat(), "until": until.isoformat()})}):
            v = [_f(r.get("spend")), extract_results(r.get("actions"), token), _f(r.get("inline_link_clicks"))]
            for i in range(3):
                by_id[r.get("ad_id")][i] += v[i]
                by_key[cpa.ad_key(r.get("ad_name") or "")][i] += v[i]
        return by_id, by_key

    W: Dict[str, Dict[str, List[float]]] = {}          # window → ad_id → [spend, leads, clicks]
    K: Dict[str, Dict[str, List[float]]] = {}          # window → ad_key → [...] folded over both accounts
    days = [OPEN + dt.timedelta(days=i) for i in range((today - OPEN).days + 1)]
    for name, since, until in ([(d.isoformat(), d, d) for d in days] + [("week", WEEK, today),
                               ("pre", dt.date(2026, 10, 1), WEBINAR), ("d30", d30, today), ("d60", d60, today)]):
        W[name], K[name] = {}, defaultdict(lambda: [0.0, 0.0, 0.0])
        for _, acct in ACCOUNTS:
            a, b = pull(acct, since, until)
            W[name].update(a)
            for k, v in b.items():
                for i in range(3):
                    K[name][k][i] += v[i]

    # ── sheet: SG sales by ad key ──
    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    n_web: Dict[str, int] = defaultdict(int)
    n30: Dict[str, int] = defaultdict(int)
    n60: Dict[str, int] = defaultdict(int)
    web_rows: List[str] = []
    latest_sg = None
    for x in sales:
        if not x.date or not _sg(x.campaign):
            continue
        k = cpa.ad_key(x.ad)
        latest_sg = max(latest_sg, x.date) if latest_sg else x.date
        if x.date >= WEBINAR:
            n_web[k] += 1
            web_rows.append(f"{x.date.isoformat()} · {x.ad[:40]}")
        if x.date >= d30:
            n30[k] += 1
        if x.date >= d60:
            n60[k] += 1
    log.info("═" * 118)
    log.info("成交表：SG 最近一笔日期 %s · 10/7 直播起 SG 新单 %d 笔%s", latest_sg, len(web_rows),
             "" if web_rows else " → 名单还没填，本场不下成交判断")
    for r in sorted(web_rows):
        log.info("   %s", r)

    # monitor pause log since 10/8 (which ads the RM80 / RM105 lines closed)
    killed: Dict[str, str] = {}
    try:
        with open(os.path.join(os.environ.get("ADBOT_ROOT", "."), "state", "pause_log.json"), encoding="utf-8") as fh:
            plog = json.load(fh)
        rows = plog if isinstance(plog, list) else plog.get("entries") or plog.get("pauses") or list(plog.values())
        for e in rows:
            if not isinstance(e, dict):
                continue
            ts = str(e.get("ts") or e.get("time") or e.get("at") or e.get("timestamp") or "")
            if ts[:10] >= OPEN.isoformat():
                killed[str(e.get("ad_id") or e.get("id") or e.get("entity_id") or "")] = \
                    f"{ts[:16]} {str(e.get('reason') or e.get('why') or e.get('rule') or '')[:60]}"
    except Exception as exc:  # noqa: BLE001
        log.info("（pause_log 读不到：%s）", exc)
    if killed:
        log.info("监控 10/8 起关掉的：%d 支", len(killed))
        for k, v in killed.items():
            log.info("   %s · %s", k, v)

    def ratio(a, b):
        return f"{a / b * 100:.0f}%" if b else "—"

    flags: List[str] = []
    rank: List[tuple] = []
    seen_keys = set()
    for label, acct in ACCOUNTS:
        camps = {c["id"]: c for c in g._get_all(f"{acct}/campaigns",
                 {"fields": "id,name,effective_status,daily_budget", "limit": 300})
                 if c.get("effective_status") == "ACTIVE"}
        adsets = [a for a in g._get_all(f"{acct}/adsets",
                  {"fields": "id,name,campaign_id,effective_status,daily_budget", "limit": 800})
                  if a.get("campaign_id") in camps and a.get("effective_status") == "ACTIVE"]
        ads = g._get_all(f"{acct}/ads", {"fields": "id,name,status,effective_status,adset_id,created_time",
                                         "effective_status": json.dumps(LISTABLE), "limit": 800})
        by_set = defaultdict(list)
        for a in ads:
            by_set[a["adset_id"]].append(a)
        log.info("═" * 118)
        log.info("【%s】%s · ACTIVE campaign %d", label, acct, len(camps))
        for cid in sorted(camps, key=lambda x: (RETEST not in (camps[x].get("name") or ""), camps[x].get("name") or "")):
            c = camps[cid]
            cname = c.get("name") or ""
            cb = int(c.get("daily_budget") or 0)
            sets = [a for a in adsets if a.get("campaign_id") == cid]
            retest = RETEST in cname
            kill = 80.0 if any(t in cname for t in TEST_TOKENS) else KILL
            log.info("▌%s %s · %d ad set", "CBO RM%d" % (cb // 100) if cb else "ABO RM%d" % (sum(int(a.get("daily_budget") or 0) for a in sets) // 100),
                     cname[:80], len(sets))
            csp = cld = cth = cfr = 0.0
            for a_set in sets:
                rows = by_set.get(a_set["id"], [])
                if retest:
                    rows = [a for a in rows if a.get("effective_status") in RUNNING or W["week"].get(a["id"], [0])[0] > 0]
                else:
                    rows = [a for a in rows if a.get("effective_status") in RUNNING]
                log.info("  ├ adset %s %r%s · %d ads", a_set["id"], (a_set.get("name") or "")[:34],
                         f" RM{int(a_set.get('daily_budget') or 0) // 100}" if not cb else "", len(rows))
                for a in sorted(rows, key=lambda x: -W["week"].get(x["id"], [0])[0]):
                    k = cpa.ad_key(a.get("name") or "")
                    wk, fr = W["week"].get(a["id"], [0, 0, 0]), W[today.isoformat()].get(a["id"], [0, 0, 0])
                    per_day = [W[d.isoformat()].get(a["id"], [0, 0, 0]) for d in days]
                    th = per_day[0]
                    pre = K["pre"].get(k, [0, 0, 0])
                    k30, k60 = K["d30"].get(k, [0, 0, 0]), K["d60"].get(k, [0, 0, 0])
                    sp, ld, ck = wk
                    csp += sp; cld += ld; cth += th[0]; cfr += fr[0]
                    c30 = k30[0] / n30[k] if n30[k] else 0.0
                    c60 = k60[0] / n60[k] if n60[k] else 0.0
                    cpl = sp / ld if ld else 0.0
                    on = a.get("effective_status") in RUNNING
                    created = cpa.parse_date((a.get("created_time") or "")[:10])
                    age = (today - created).days if created else 99
                    if not on:
                        v, why = "⏸ 已关", killed.get(a["id"], f"status {a.get('effective_status')}")
                    elif n30[k] and c30 <= acc:
                        v, why = "✅ 留", f"30d {n30[k]}单 CPA {c30:,.0f}"
                    elif n30[k] and c30 <= hard:
                        v, why = "🤔 观察", f"30d {n30[k]}单 CPA {c30:,.0f}（960-1200）"
                    elif n30[k]:
                        v, why = "❌ 关", f"30d {n30[k]}单 CPA {c30:,.0f} 超 1200"
                    elif k30[0] >= nosale:
                        v, why = "❌ 关", f"30d 花 RM{k30[0]:,.0f} 无单（≥1000 线）"
                    elif not ld and sp >= kill:
                        v, why = "❌ 关", f"零 lead 已过 RM{kill:.0f} 线（监控应已关，若还开着请手动）"
                    elif ld and sp >= kill and cpl > CPL * 1.5:
                        v, why = "❌ 关", f"CPL {cpl:,.0f} 超线 1.5 倍且无单"
                    elif retest or any(t in cname for t in TEST_TOKENS):
                        v, why = "⏳ 待直播后判", (f"CPL {cpl:,.0f}" if ld else f"零 lead，离 RM{kill:.0f} 线还有 RM{kill - sp:.0f}")
                    elif n60[k]:
                        v, why = "🤔 观察", f"60d {n60[k]}单 CPA {c60:,.0f}，30d 无单"
                    elif ld and cpl <= CPL:
                        v, why = "▶️ 留", f"CPL {cpl:,.0f} 达标，无单先看 lead"
                    elif ld:
                        v, why = "⚠️ 减", f"CPL {cpl:,.0f} 超 70"
                    elif age <= 2 or sp < 30:
                        v, why = "⏳ 新", f"{age} 天 · RM{sp:.0f}"
                    else:
                        v, why = "· 观察", f"RM{sp:.0f} 零 lead，离 RM{kill:.0f} 线还有 RM{kill - sp:.0f}"
                    if v.startswith("❌") or v.startswith("⚠️"):
                        flags.append(f"{label} · {cname[:36]} · {(a.get('name') or '')[:28]} → {v} {why}")
                    if retest:
                        feed = "被饿" if sp < 10 and on else ("吃到钱" if sp >= 40 else "")
                        day_txt = " · ".join(f"{DAY_LABELS[d.weekday()]} RM{x[0]:.0f}/{int(x[1])}L" for d, x in zip(days, per_day))
                        log.info("  │   %-9s %-36s %s · 周四起 RM%-6.2f %dL %-7s 报名率 %-4s · 30d单 %d · %s%s",
                                 v, (a.get("name") or "")[:36], day_txt, sp, int(ld),
                                 f"CPL{cpl:,.0f}" if ld else "—", ratio(ld, ck), n30[k], why, f" · {feed}" if feed else "")
                    else:
                        log.info("  │   %-9s %-36s 周四起 RM%-7.2f %2dL %-7s 今 RM%-5.2f %dL · 报名率 %-4s · 本场 %d单/%dL · 30d %d单 %s · %s",
                                 v, (a.get("name") or "")[:36], sp, int(ld), f"CPL{cpl:,.0f}" if ld else "—", fr[0], int(fr[1]),
                                 ratio(ld, ck), n_web[k], int(pre[1]), n30[k], f"CPA{c30:,.0f}" if n30[k] else "", why)
                    if k not in seen_keys and (n30[k] or n_web[k]):
                        seen_keys.add(k)
                        rank.append((n_web[k] / pre[1] if pre[1] else 0.0, n_web[k], int(pre[1]), n30[k], k30[0], int(k30[1]), (a.get("name") or "")[:36]))
            log.info("  └ 小计 周四起 RM%.0f · %dL%s%s", csp, int(cld), f" · CPL RM{csp / cld:,.0f}" if cld else "",
                     f" · 今 RM{cfr:.0f}" if retest else "")
        # 开 candidates: one line per CREATIVE (the old SG account holds ~100 paused copies),
        # only creatives with a 30d sale, or a 60d sale at CPA ≤ 1200
        by_key: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for a in ads:
            if a.get("effective_status") in RUNNING:
                continue
            k = cpa.ad_key(a.get("name") or "")
            k60 = K["d60"].get(k, [0, 0, 0])
            if n30.get(k, 0) or (n60.get(k, 0) and k60[0] / n60[k] <= hard):
                by_key[k].append(a)
        if by_key:
            log.info("  ▽ 停着但有成交证据的片（开的候选，每支片一行）：")
            for k, lst in sorted(by_key.items(), key=lambda kv: (-n30.get(kv[0], 0), -n60.get(kv[0], 0))):
                k30, k60 = K["d30"].get(k, [0, 0, 0]), K["d60"].get(k, [0, 0, 0])
                newest = max(lst, key=lambda x: x.get("created_time") or "")
                running_elsewhere = any(cpa.ad_key(x.get("name") or "") == k and x.get("effective_status") in RUNNING for x in ads)
                log.info("     ⏸ %-36s %d 支停着 · 最新 ad %s (%s, 建 %s)%s · 30d %d单 RM%.0f %dL%s · 60d %d单%s",
                         (newest.get("name") or "")[:36], len(lst), newest["id"], newest.get("effective_status"),
                         (newest.get("created_time") or "")[:10], " · 同片另有在跑" if running_elsewhere else "",
                         n30.get(k, 0), k30[0], int(k30[1]), f" CPA {k30[0] / n30[k]:,.0f}" if n30.get(k) else "",
                         n60.get(k, 0), f" CPA {k60[0] / n60[k]:,.0f}" if n60.get(k) else "")
    log.info("═" * 118)
    log.info("买家转化排名（本场 = 10/7 起单 ÷ 10/1-10/7 lead；30d 列 = 单 / 花 / lead）：")
    for conv, nw, pl, n3, sp3, ld3, nm in sorted(rank, reverse=True):
        log.info("   %-36s 本场 %d/%d = %s · 30d %d单 RM%.0f %dL → CPA %s · 30d 转化 %s", nm, nw, pl, ratio(nw, pl), n3, sp3, ld3,
                 f"{sp3 / n3:,.0f}" if n3 else "—", ratio(n3, ld3))
    log.info("🚩 建议处理（%d）：", len(flags))
    for f in flags:
        log.info("   %s", f)
    final_summary(log, f"friday readout done · {len(flags)} flags · {len(web_rows)} new SG sales since 10/7")


if __name__ == "__main__":
    main()
