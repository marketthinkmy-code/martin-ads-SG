"""Live-board per-ad verdict scan (read-only, 1 Oct).

Operator: 看看我目前開著的廣告，有哪些需要關/scale/開/調整的嗎？

Every delivering ad on the NEW account, grouped campaign → ad set:
  era (9/25 →) spend / leads / CPL per ad id · today's spend/leads ·
  30d sheet sales + folded 30d CPA (both accounts) · a rule-based hint:
    ✅ 有单达标 (CPA ≤ 960)   ▶️ CPL ≤ 95   ⚠️ CPL > 95 / 零L接近杀线   ⏳ 太新
Campaign subtotal with budget. Read-only — verdicts go to the operator in chat.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from typing import Dict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

NEW_ACCT = "act_1179668409969241"
ERA = dt.date(2026, 9, 25)


def _sg(campaign: str) -> bool:
    c = cpa.norm(campaign)
    return ("[sg]" in c) or ("martin-sg" in c) or ("martin sg" in c)


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    token = result_action_type(s.meta.conversion_event)
    old_acct = s.meta.account_path
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d30 = today - dt.timedelta(days=30)
    acc, hard = s.cpa.max_acceptable_myr, s.cpa.hard_stop_myr

    def pull(acct, since, until, by_name=False):
        sp: Dict[str, float] = defaultdict(float)
        ld: Dict[str, float] = defaultdict(float)
        for r in g._get_all(f"{acct}/insights",
                            {"level": "ad", "limit": 500,
                             "fields": "ad_id,ad_name,spend,actions",
                             "time_range": json.dumps({"since": since.isoformat(),
                                                       "until": until.isoformat()})}):
            k = cpa.ad_key(r.get("ad_name") or "") if by_name else r.get("ad_id")
            try:
                sp[k] += float(r.get("spend") or 0)
            except (TypeError, ValueError):
                pass
            ld[k] += extract_results(r.get("actions"), token)
        return sp, ld

    e_sp, e_ld = pull(NEW_ACCT, ERA, today)
    t_sp, t_ld = pull(NEW_ACCT, today, today)
    sp30, _ = pull(old_acct, d30, today, by_name=True)
    sp30n, _ = pull(NEW_ACCT, d30, today, by_name=True)
    for k, v in sp30n.items():
        sp30[k] += v

    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id,
                                                             s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    n30: Dict[str, int] = defaultdict(int)
    latest = None
    for x in sales:
        if not _sg(x.campaign) or not x.date:
            continue
        if latest is None or x.date > latest:
            latest = x.date
        if x.date >= d30:
            n30[cpa.ad_key(x.ad)] += 1

    camps = {c["id"]: c for c in g._get_all(
        f"{NEW_ACCT}/campaigns",
        {"fields": "id,name,effective_status,daily_budget", "limit": 200})
        if c.get("effective_status") == "ACTIVE"}
    adsets = g._get_all(f"{NEW_ACCT}/adsets",
                        {"fields": "id,name,status,campaign_id,daily_budget", "limit": 500})
    ads = g._get_all(f"{NEW_ACCT}/ads",
                     {"fields": "id,name,status,effective_status,adset_id,created_time",
                      "limit": 500})
    set2camp = {a["id"]: a.get("campaign_id") for a in adsets}

    log.info("名单最新 SG 成交 %s · era=%s起 · 今天=%s（周四 CPL 周期今晨重置）", latest, ERA, today)
    total_b = total_e = 0.0
    for cid in sorted(camps, key=lambda x: camps[x].get("name") or ""):
        c = camps[cid]
        b = int(c.get("daily_budget") or 0) or sum(
            int(a.get("daily_budget") or 0) for a in adsets
            if a.get("campaign_id") == cid and a.get("status") == "ACTIVE")
        total_b += b
        rows = [a for a in ads if set2camp.get(a.get("adset_id")) == cid
                and a.get("status") == "ACTIVE"]
        log.info("═" * 112)
        log.info("▌RM%-4d %s", b // 100, (c.get("name") or "")[:70])
        csp = cld = 0.0
        for a in sorted(rows, key=lambda x: -e_sp.get(x["id"], 0.0)):
            k = cpa.ad_key(a.get("name") or "")
            sp, ld = e_sp.get(a["id"], 0.0), e_ld.get(a["id"], 0.0)
            tsp, tld = t_sp.get(a["id"], 0.0), t_ld.get(a["id"], 0.0)
            csp += sp
            cld += ld
            total_e += sp
            n = n30.get(k, 0)
            cpa30 = sp30.get(k, 0.0) / n if n else 0.0
            cpl = sp / ld if ld else 0.0
            age = (a.get("created_time") or "")[:10]
            if n and cpa30 <= acc:
                hint = f"✅ 30d {n}单 CPA RM{cpa30:,.0f}"
            elif n:
                hint = f"{'🤔' if cpa30 <= hard else '❌'} 30d {n}单 CPA RM{cpa30:,.0f}"
            elif ld and cpl <= 95:
                hint = "▶️ CPL 达标"
            elif ld:
                hint = f"⚠️ CPL 超标"
            elif sp >= 100:
                hint = "⚠️ 零L · 接近杀线142.5"
            elif sp < 20:
                hint = "⏳ 刚起步"
            else:
                hint = "· 零L 观察"
            log.info("   %-46s era RM%-7.2f %2dL %-9s 今天 RM%-6.2f %dL · %s · %s",
                     (a.get("name") or "")[:46], sp, int(ld),
                     f"CPL {cpl:,.0f}" if ld else "CPL —", tsp, int(tld), hint, age)
        log.info("   ── 小计 era RM%.0f · %dL%s", csp, int(cld),
                 f" · CPL RM{csp / cld:,.0f}" if cld else "")
    log.info("═" * 112)
    log.info("在投总预算 RM%d/day · era 总花 RM%.0f", int(total_b) // 100, total_e)
    final_summary(log, f"Per-ad board verdict data ready; budget RM{int(total_b) // 100}/day, "
                       f"{len(camps)} campaigns. Read-only.")


if __name__ == "__main__":
    main()
