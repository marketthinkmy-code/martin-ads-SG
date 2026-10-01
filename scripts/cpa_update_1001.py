"""CPA update (read-only, 1 Oct) — the Paid Student List has fresh sales.

① Sheet freshness: latest SG sale; every SG sale dated ≥ 9/25 (the new-account era)
  attributed by folded ad name with era spend (both accounts) and era CPA.
② 30d-CPA qualification for EVERY name with a 30d SG sale: 30d spend / sales / CPA /
  verdict vs RM960/1200, marked LIVE (which active campaign carries it now) or OFF.
③ Live board: each ACTIVE campaign on the new account — daily budget, spend/leads/sales
  since 9/25 across its live ads.
④ 判决复核: the 新片 5 支 names re-judged with the fresh sheet (the 9/28 verdict was
  CPA-blind — sheet stopped at 9/23).
Read-only; proposal follows in chat.
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
TEST5 = ["Hook 1：今晚回家检查三件事", "Hook 4：保健品叫你丢掉", "Hook 7：算给你看",
         "Hook 3：倒掉牛奶", "Hook 6：没有人会告诉你"]


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

    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id,
                                                             s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    n30: Dict[str, int] = defaultdict(int)
    nera: Dict[str, int] = defaultdict(int)
    era_dates: Dict[str, list] = defaultdict(list)
    disp: Dict[str, str] = {}
    latest = None
    for x in sales:
        if not _sg(x.campaign) or not x.date:
            continue
        if latest is None or x.date > latest:
            latest = x.date
        k = cpa.ad_key(x.ad)
        if not k:
            continue
        disp.setdefault(k, (x.ad or "").strip())
        if x.date >= d30:
            n30[k] += 1
        if x.date >= ERA:
            nera[k] += 1
            era_dates[k].append(x.date.isoformat())
    log.info("① 名单最新 SG 成交日: %s · 新账户时代（≥%s）共 %d 单 · 30d 窗口共 %d 单",
             latest, ERA, sum(nera.values()), sum(n30.values()))

    def fold(acct, since):
        sp: Dict[str, float] = defaultdict(float)
        ld: Dict[str, float] = defaultdict(float)
        for r in g._get_all(f"{acct}/insights",
                            {"level": "ad", "limit": 500,
                             "fields": "ad_id,ad_name,spend,actions",
                             "time_range": json.dumps({"since": since.isoformat(),
                                                       "until": today.isoformat()})}):
            k = cpa.ad_key(r.get("ad_name") or "")
            try:
                sp[k] += float(r.get("spend") or 0)
            except (TypeError, ValueError):
                pass
            ld[k] += extract_results(r.get("actions"), token)
        return sp, ld

    sp30, _ = fold(old_acct, d30)
    sp30n, _ = fold(NEW_ACCT, d30)
    for k, v in sp30n.items():
        sp30[k] += v
    spe_o, lde_o = fold(old_acct, ERA)
    spe, lde = fold(NEW_ACCT, ERA)
    for k, v in spe_o.items():
        spe[k] += v
    for k, v in lde_o.items():
        lde[k] += v

    camps = {c["id"]: c for c in g._get_all(
        f"{NEW_ACCT}/campaigns",
        {"fields": "id,name,effective_status,daily_budget", "limit": 200})
        if c.get("effective_status") == "ACTIVE"}
    adsets = g._get_all(f"{NEW_ACCT}/adsets",
                        {"fields": "id,campaign_id,daily_budget", "limit": 500})
    ads = g._get_all(f"{NEW_ACCT}/ads",
                     {"fields": "id,name,effective_status,adset_id", "limit": 500})
    set2camp = {a["id"]: a.get("campaign_id") for a in adsets}
    live_in: Dict[str, str] = {}
    camp_keys: Dict[str, set] = defaultdict(set)
    for a in ads:
        cid = set2camp.get(a.get("adset_id"))
        if cid in camps and a.get("effective_status") in ("ACTIVE", "IN_PROCESS",
                                                          "PENDING_REVIEW"):
            k = cpa.ad_key(a.get("name") or "")
            live_in[k] = (camps[cid].get("name") or "")[:40]
            camp_keys[cid].add(k)
            disp.setdefault(k, (a.get("name") or "").strip())

    log.info("═" * 112)
    log.info("② 新账户时代成交（≥ %s）· era 花费两账户合并", ERA)
    for k in sorted(nera, key=lambda x: -nera[x]):
        cpa_e = spe.get(k, 0.0) / nera[k]
        log.info("  ▸ %-42s %d 单（%s）· era 花 RM%-8.0f CPA RM%-7.0f %s · %s",
                 disp.get(k, k)[:42], nera[k], ", ".join(era_dates[k]),
                 spe.get(k, 0.0), cpa_e,
                 "✅" if cpa_e <= acc else ("🤔" if cpa_e <= hard else "❌"),
                 ("在投: " + live_in[k]) if k in live_in else "OFF")
    if not nera:
        log.info("  （9/25 以来名单上还没有 SG 单）")

    log.info("═" * 112)
    log.info("③ 30d-CPA 资格（窗口 %s → %s · 线 %.0f/%.0f）", d30, today, acc, hard)
    for k in sorted(n30, key=lambda x: sp30.get(x, 0.0) / n30[x]):
        c30 = sp30.get(k, 0.0) / n30[k]
        log.info("  %-44s 30d 花 RM%-8.0f %d单 CPA RM%-7.0f %s · %s",
                 disp.get(k, k)[:44], sp30.get(k, 0.0), n30[k], c30,
                 "✅达标" if c30 <= acc else ("🤔边缘" if c30 <= hard else "❌超硬线"),
                 ("在投: " + live_in[k]) if k in live_in else "OFF")

    log.info("═" * 112)
    log.info("④ 在投盘面（开跑 %s 起 · 按 campaign 汇总）", ERA)
    total_b = 0
    for cid, c in sorted(camps.items(), key=lambda kv: kv[1].get("name") or ""):
        b = int(c.get("daily_budget") or 0) or sum(
            int(a.get("daily_budget") or 0) for a in adsets if a.get("campaign_id") == cid)
        total_b += b
        ks = camp_keys.get(cid, set())
        sp_c = sum(spe.get(k, 0.0) for k in ks)
        ld_c = sum(lde.get(k, 0.0) for k in ks)
        sale_c = sum(nera.get(k, 0) for k in ks)
        log.info("  ▸ RM%-4d %-52s era 花 RM%-8.0f %dL%s · %d单",
                 b // 100, (c.get("name") or "")[:52], sp_c, int(ld_c),
                 f" CPL RM{sp_c / ld_c:,.0f}" if ld_c else "", sale_c)
    log.info("  在投总预算 RM%d/day", total_b // 100)

    log.info("═" * 112)
    log.info("⑤ 新片 5 支判决复核（9/28 判决时名单停在 9/23）")
    for name in TEST5:
        k = cpa.ad_key(name)
        c30 = sp30.get(k, 0.0) / n30[k] if n30.get(k) else 0.0
        log.info("  %-34s 30d 花 RM%-7.0f %d单 %s · era %d单 · %s",
                 name[:34], sp30.get(k, 0.0), n30.get(k, 0),
                 (f"CPA RM{c30:,.0f} " + ("✅" if c30 <= acc else
                  ("🤔" if c30 <= hard else "❌"))) if n30.get(k) else "无单",
                 nera.get(k, 0),
                 ("在投: " + live_in[k]) if k in live_in else "OFF")

    final_summary(log, f"CPA update: sheet latest {latest}; {sum(nera.values())} era sales "
                       f"attributed; board RM{total_b // 100}/day across "
                       f"{len(camps)} campaigns. Read-only.")


if __name__ == "__main__":
    main()
