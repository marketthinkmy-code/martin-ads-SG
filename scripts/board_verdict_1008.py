"""Per-ad verdicts, both accounts, after the team filled in the sales (read-only, 8 Oct).

① 名单最新 SG 成交日 + 10/1 以来新增的单：按广告名归因，era(9/25→) 两账户合并花费 → CPA
② 在跑板子（SG老 + HK 每条 ACTIVE campaign）每支：本周(10/1→)花/L/CPL · 今天 · 30d/60d 单与
   两账户合并 CPA · 规则判决：
      ✅ CPA30 ≤ 960 留/可加   🤔 960 < CPA30 ≤ 1200 观察   ❌ CPA30 > 1200
      ❌ 30d 花 ≥ RM1,000 仍无单   🤔 60d 有单但 30d 没有
      无单小样本看 lead：▶️ CPL ≤ 70 · ⚠️ CPL > 70 · ⚠️ 零L 接近杀线 · ⏳ 刚起步
No writes — recommendations go to chat.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from typing import Dict, Tuple

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

HK = "act_1179668409969241"
ERA = dt.date(2026, 9, 25)
WEEK = dt.date(2026, 10, 1)
SINCE_REPORT = dt.date(2026, 10, 1)
NEW_TEST_TOKENS = ("15岁以上新片", "线下见证新片", "新片5支重测")


def _sg(campaign: str) -> bool:
    c = cpa.norm(campaign)
    return ("[sg]" in c) or ("martin-sg" in c) or ("martin sg" in c)


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    token = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d30, d60 = today - dt.timedelta(days=30), today - dt.timedelta(days=60)
    acc, hard = s.cpa.max_acceptable_myr, s.cpa.hard_stop_myr
    accounts = [("SG老", s.meta.account_path), ("HK", HK)]

    def pull(acct, since, until) -> Tuple[Dict[str, float], Dict[str, float], Dict[str, float]]:
        sp_id, ld_id, sp_name = defaultdict(float), defaultdict(float), defaultdict(float)
        for r in g._get_all(f"{acct}/insights",
                            {"level": "ad", "limit": 500,
                             "fields": "ad_id,ad_name,spend,actions",
                             "time_range": json.dumps({"since": since.isoformat(),
                                                       "until": until.isoformat()})}):
            try:
                v = float(r.get("spend") or 0)
            except (TypeError, ValueError):
                v = 0.0
            sp_id[r.get("ad_id")] += v
            ld_id[r.get("ad_id")] += extract_results(r.get("actions"), token)
            sp_name[cpa.ad_key(r.get("ad_name") or "")] += v
        return sp_id, ld_id, sp_name

    w_sp, w_ld, _ = {}, {}, None
    t_sp, t_ld = {}, {}
    sp30n, sp60n, spe_n = defaultdict(float), defaultdict(float), defaultdict(float)
    for _, acct in accounts:
        a, b, _c = pull(acct, WEEK, today); w_sp.update(a); w_ld.update(b)
        a, b, _c = pull(acct, today, today); t_sp.update(a); t_ld.update(b)
        for k, v in pull(acct, d30, today)[2].items(): sp30n[k] += v
        for k, v in pull(acct, d60, today)[2].items(): sp60n[k] += v
        for k, v in pull(acct, ERA, today)[2].items(): spe_n[k] += v

    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    n30, n60, nnew = defaultdict(int), defaultdict(int), defaultdict(int)
    new_dates = defaultdict(list)
    disp: Dict[str, str] = {}
    latest = None
    for x in sales:
        if not _sg(x.campaign) or not x.date:
            continue
        latest = x.date if latest is None or x.date > latest else latest
        k = cpa.ad_key(x.ad)
        if not k:
            continue
        disp.setdefault(k, (x.ad or "").strip())
        if x.date >= d30: n30[k] += 1
        if x.date >= d60: n60[k] += 1
        if x.date >= SINCE_REPORT:
            nnew[k] += 1
            new_dates[k].append(x.date.isoformat())

    log.info("① 名单最新 SG 成交日 %s · %s 以来新增 %d 单（按广告名归因，era 9/25→ 两账户合并花费）",
             latest, SINCE_REPORT, sum(nnew.values()))
    for k in sorted(nnew, key=lambda x: -nnew[x]):
        spe = spe_n.get(k, 0.0)
        log.info("  ▸ %-44s %d 单 (%s) · era 花 RM%-7.0f CPA RM%-6.0f %s · 30d %d单 CPA %s",
                 disp[k][:44], nnew[k], ",".join(new_dates[k]), spe,
                 spe / nnew[k] if nnew[k] else 0,
                 "✅" if spe / nnew[k] <= acc else ("🤔" if spe / nnew[k] <= hard else "❌"),
                 n30[k], f"RM{sp30n.get(k, 0.0) / n30[k]:,.0f}" if n30[k] else "—")

    for label, acct in accounts:
        camps = {c["id"]: c for c in g._get_all(
            f"{acct}/campaigns", {"fields": "id,name,effective_status,daily_budget", "limit": 300})
            if c.get("effective_status") == "ACTIVE"}
        adsets = g._get_all(f"{acct}/adsets", {"fields": "id,campaign_id,status,daily_budget", "limit": 800})
        ads = g._get_all(f"{acct}/ads", {"fields": "id,name,status,effective_status,adset_id,created_time", "limit": 800})
        set2camp = {a["id"]: a.get("campaign_id") for a in adsets}
        log.info("═" * 120)
        log.info("② %s %s · %d 条 ACTIVE campaign", label, acct, len(camps))
        tb = 0
        for cid in sorted(camps, key=lambda x: camps[x].get("name") or ""):
            c = camps[cid]
            b = int(c.get("daily_budget") or 0) or sum(int(a.get("daily_budget") or 0) for a in adsets
                                                      if a.get("campaign_id") == cid and a.get("status") == "ACTIVE")
            tb += b
            rows = [a for a in ads if set2camp.get(a.get("adset_id")) == cid and a.get("status") == "ACTIVE"]
            log.info("▌RM%-4d %s", b // 100, (c.get("name") or "")[:80])
            kill = 80.0 if any(tk in (c.get("name") or "") for tk in NEW_TEST_TOKENS) else s.kpi.cpl_min_spend_myr
            csp = cld = 0.0
            for a in sorted(rows, key=lambda x: -w_sp.get(x["id"], 0.0)):
                k = cpa.ad_key(a.get("name") or "")
                sp, ld = w_sp.get(a["id"], 0.0), w_ld.get(a["id"], 0.0)
                tsp, tld = t_sp.get(a["id"], 0.0), t_ld.get(a["id"], 0.0)
                csp += sp; cld += ld
                n3, n6 = n30.get(k, 0), n60.get(k, 0)
                c30 = sp30n.get(k, 0.0) / n3 if n3 else 0.0
                c60 = sp60n.get(k, 0.0) / n6 if n6 else 0.0
                cpl = sp / ld if ld else 0.0
                if n3 and c30 <= acc:
                    hint = f"✅ 30d {n3}单 CPA {c30:,.0f}"
                elif n3 and c30 <= hard:
                    hint = f"🤔 30d {n3}单 CPA {c30:,.0f}"
                elif n3:
                    hint = f"❌ 30d {n3}单 CPA {c30:,.0f} 超硬线"
                elif sp30n.get(k, 0.0) >= s.cpa.min_spend_myr:
                    hint = f"❌ 30d 花 {sp30n.get(k, 0.0):,.0f} 无单"
                elif n6:
                    hint = f"🤔 60d {n6}单 CPA {c60:,.0f}，30d 无单"
                elif ld and cpl <= s.kpi.cpl_target_myr:
                    hint = "▶️ CPL 达标"
                elif ld:
                    hint = "⚠️ CPL 超 70"
                elif sp >= kill * 0.75:
                    hint = f"⚠️ 零L 接近杀线 {kill:.0f}"
                elif sp < 20:
                    hint = "⏳ 刚起步"
                else:
                    hint = "· 零L 观察"
                log.info("   %-40s 周 RM%-7.2f %2dL %-8s 今 RM%-6.2f %dL · %s · %s",
                         (a.get("name") or "")[:40], sp, int(ld), f"CPL{cpl:,.0f}" if ld else "—",
                         tsp, int(tld), hint, (a.get("created_time") or "")[:10])
            log.info("   ── 小计 周 RM%.0f · %dL%s", csp, int(cld), f" · CPL RM{csp / cld:,.0f}" if cld else "")
        log.info("在投总预算 %s RM%d/day", label, tb // 100)
    final_summary(log, "verdict data ready — recommendations in chat")


if __name__ == "__main__":
    main()
