"""Audit of everything delivering, campaign → ad set → ad, with a reason per ad (read-only).

Operator (8 Oct): 有什么我现在开着的广告是不该开着的吗？并告诉我原因。
Accounts: SG old, HK (SG rules: CPL 70, zero-lead kill 105 / 80 for test campaigns,
CPA 960 / 1200, RM1,000 no-sale line) and MY (MY rules: CPL 60, zero-lead kill 90).
Per ad: 本周(10/1→) spend/leads/CPL · today · 30d/60d sales from the sheet folded by ad
name across accounts → CPA · age · verdict + reason. Per ad set: budget (ABO) and whether
it is spending at all. Per campaign: CBO/ABO and daily budget. No writes.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from typing import Any, Dict, List

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

ACCOUNTS = [("SG老", "act_1024930575770087", "sg"), ("HK", "act_1179668409969241", "sg"),
            ("MY", "act_1011719073600566", "my")]
WEEK = dt.date(2026, 10, 1)
TEST_TOKENS = ("15岁以上新片", "线下见证新片", "新片5支重测")
RULES = {"sg": {"cpl": 70.0, "kill": 105.0}, "my": {"cpl": 60.0, "kill": 90.0}}


def _mkt(campaign: str) -> str:
    c = cpa.norm(campaign)
    if "[sg]" in c or "martin-sg" in c or "martin sg" in c:
        return "sg"
    if "[my]" in c or "martin-my" in c or "martin my" in c:
        return "my"
    return "other"


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    token = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d30, d60 = today - dt.timedelta(days=30), today - dt.timedelta(days=60)
    acc, hard, nosale = s.cpa.max_acceptable_myr, s.cpa.hard_stop_myr, s.cpa.min_spend_myr

    def pull(acct, since, until):
        sp_id, ld_id, sp_name = defaultdict(float), defaultdict(float), defaultdict(float)
        for r in g._get_all(f"{acct}/insights",
                            {"level": "ad", "limit": 500, "fields": "ad_id,ad_name,spend,actions",
                             "time_range": json.dumps({"since": since.isoformat(), "until": until.isoformat()})}):
            try:
                v = float(r.get("spend") or 0)
            except (TypeError, ValueError):
                v = 0.0
            sp_id[r.get("ad_id")] += v
            ld_id[r.get("ad_id")] += extract_results(r.get("actions"), token)
            sp_name[cpa.ad_key(r.get("ad_name") or "")] += v
        return sp_id, ld_id, sp_name

    w_sp, w_ld, t_sp, t_ld = {}, {}, {}, {}
    sp30n: Dict[str, Dict[str, float]] = {"sg": defaultdict(float), "my": defaultdict(float)}
    sp60n: Dict[str, Dict[str, float]] = {"sg": defaultdict(float), "my": defaultdict(float)}
    for _, acct, mkt in ACCOUNTS:
        a, b, _c = pull(acct, WEEK, today); w_sp.update(a); w_ld.update(b)
        a, b, _c = pull(acct, today, today); t_sp.update(a); t_ld.update(b)
        for k, v in pull(acct, d30, today)[2].items(): sp30n[mkt][k] += v
        for k, v in pull(acct, d60, today)[2].items(): sp60n[mkt][k] += v

    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    n30: Dict[str, Dict[str, int]] = {"sg": defaultdict(int), "my": defaultdict(int)}
    n60: Dict[str, Dict[str, int]] = {"sg": defaultdict(int), "my": defaultdict(int)}
    for x in sales:
        mkt = _mkt(x.campaign)
        if mkt == "other" or not x.date:
            continue
        k = cpa.ad_key(x.ad)
        if x.date >= d30: n30[mkt][k] += 1
        if x.date >= d60: n60[mkt][k] += 1

    flags: List[str] = []
    for label, acct, mkt in ACCOUNTS:
        R = RULES[mkt]
        camps = {c["id"]: c for c in g._get_all(f"{acct}/campaigns",
                 {"fields": "id,name,effective_status,daily_budget,lifetime_budget", "limit": 300})
                 if c.get("effective_status") == "ACTIVE"}
        adsets = [a for a in g._get_all(f"{acct}/adsets",
                  {"fields": "id,name,campaign_id,status,effective_status,daily_budget,targeting", "limit": 800})
                  if a.get("campaign_id") in camps and a.get("effective_status") == "ACTIVE"]
        ads = [a for a in g._get_all(f"{acct}/ads",
               {"fields": "id,name,status,effective_status,adset_id,created_time", "limit": 800})
               if a.get("effective_status") in ("ACTIVE", "IN_PROCESS", "PENDING_REVIEW")]
        by_set = defaultdict(list)
        for a in ads:
            by_set[a["adset_id"]].append(a)
        log.info("═" * 118)
        log.info("【%s】%s · ACTIVE campaign %d · 规则 CPL %.0f / 零lead杀线 %.0f", label, acct, len(camps), R["cpl"], R["kill"])
        for cid in sorted(camps, key=lambda x: camps[x].get("name") or ""):
            c = camps[cid]
            cb = int(c.get("daily_budget") or 0)
            sets = [a for a in adsets if a.get("campaign_id") == cid]
            kill = 80.0 if any(t in (c.get("name") or "") for t in TEST_TOKENS) else R["kill"]
            log.info("▌%s %s · %s", "CBO RM%d" % (cb // 100) if cb else "ABO RM%d" % (sum(int(a.get("daily_budget") or 0) for a in sets) // 100),
                     (c.get("name") or "")[:78], f"{len(sets)} ad set")
            csp = cld = 0.0
            for a_set in sets:
                tg = a_set.get("targeting") or {}
                ints = [x.get("name") for fs in tg.get("flexible_spec") or [] for kind in ("interests", "behaviors", "family_statuses") for x in fs.get(kind) or []]
                sig = f"{tg.get('age_min')}-{tg.get('age_max')} · Adv+{'ON' if (tg.get('targeting_automation') or {}).get('advantage_audience') else 'OFF'} · {'/'.join(ints[:3]) if ints else 'broad'}"
                rows = by_set.get(a_set["id"], [])
                ssp = sum(w_sp.get(a["id"], 0.0) for a in rows)
                log.info("  ├ adset %s %r%s · %s · %d ads · 本周 RM%.0f%s", a_set["id"], (a_set.get("name") or "")[:34],
                         f" RM{int(a_set.get('daily_budget') or 0) // 100}" if not cb else "", sig, len(rows), ssp,
                         "" if rows else " · ⚠️ 空 ad set（开着没有广告）")
                if not rows:
                    flags.append(f"{label} · {c.get('name')[:40]} · adset {a_set['id']} 没有广告")
                for a in sorted(rows, key=lambda x: -w_sp.get(x["id"], 0.0)):
                    k = cpa.ad_key(a.get("name") or "")
                    sp, ld = w_sp.get(a["id"], 0.0), w_ld.get(a["id"], 0.0)
                    tsp, tld = t_sp.get(a["id"], 0.0), t_ld.get(a["id"], 0.0)
                    csp += sp; cld += ld
                    n3, n6 = n30[mkt].get(k, 0), n60[mkt].get(k, 0)
                    c30 = sp30n[mkt].get(k, 0.0) / n3 if n3 else 0.0
                    c60 = sp60n[mkt].get(k, 0.0) / n6 if n6 else 0.0
                    s30 = sp30n[mkt].get(k, 0.0)
                    cpl = sp / ld if ld else 0.0
                    created = cpa.parse_date((a.get("created_time") or "")[:10])
                    age = (today - created).days if created else 99
                    if n3 and c30 <= acc:
                        v, why = "✅ 留", f"30d {n3}单 CPA {c30:,.0f}"
                    elif n3 and c30 <= hard:
                        v, why = "🤔 观察", f"30d {n3}单 CPA {c30:,.0f}（960-1200）"
                    elif n3:
                        v, why = "❌ 关", f"30d {n3}单 CPA {c30:,.0f} 超硬线 1200"
                    elif s30 >= nosale:
                        v, why = "❌ 关", f"30d 花 RM{s30:,.0f} 无单（≥1000 线）"
                    elif ld and sp >= kill and cpl > R["cpl"] * 1.5:
                        v, why = "❌ 关", f"本周 CPL {cpl:,.0f} 超线 1.5 倍且无单"
                    elif not ld and sp >= kill:
                        v, why = "❌ 关", f"本周 RM{sp:,.0f} 零 lead ≥ 杀线 {kill:.0f}"
                    elif n6:
                        v, why = "🤔 观察", f"60d {n6}单 CPA {c60:,.0f}，30d 无单"
                    elif ld and cpl <= R["cpl"]:
                        v, why = "▶️ 留", f"本周 CPL {cpl:,.0f} 达标，无单先看 lead"
                    elif ld:
                        v, why = "⚠️ 减", f"本周 CPL {cpl:,.0f} 超 {R['cpl']:.0f}"
                    elif age <= 2 or sp < 30:
                        v, why = "⏳ 新", f"{age} 天 · RM{sp:.0f}，不判"
                    else:
                        v, why = "· 观察", f"RM{sp:.0f} 零 lead，离杀线 {kill:.0f} 还有 RM{kill - sp:.0f}"
                    if v.startswith("❌") or v.startswith("⚠️"):
                        flags.append(f"{label} · {(c.get('name') or '')[:38]} · {(a.get('name') or '')[:28]} → {v} {why}")
                    log.info("  │   %-6s %-38s 周 RM%-7.2f %2dL %-8s 今 RM%-6.2f %dL · %s · %s",
                             v, (a.get("name") or "")[:38], sp, int(ld), f"CPL{cpl:,.0f}" if ld else "—",
                             tsp, int(tld), why, a.get("effective_status"))
            log.info("  └ campaign 小计 本周 RM%.0f · %dL%s", csp, int(cld), f" · CPL RM{csp / cld:,.0f}" if cld else "")
    log.info("═" * 118)
    log.info("🚩 需要处理的（%d）：", len(flags))
    for f in flags:
        log.info("   %s", f)
    final_summary(log, f"audit done · {len(flags)} flags")


if __name__ == "__main__":
    main()
