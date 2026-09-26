"""Board snapshot + forgotten-winners scan (read-only, 26 Sep).

Operator: 新账户开剩什么了？下一步怎么做？有没有成交不错但被遗忘/被关的广告可以重开？

① NEW account (act_1179668409969241): every campaign → ad set → budget → live ads, plus
  each chain's spend/leads since the 9/25 evening launch.
② OLD account: anything still delivering (expect none).
③ Reopen tiers over ALL history (sheet joined to name-folded spend, both accounts' live
  names excluded):
    Tier A 近期合格没在投 — ≥1 SG sale in 30d, 30d CPA ≤ RM960
    Tier B 终身单王被冷落 — lifetime sales ≥ 3, lifetime CPA ≤ RM960, no 30d sale
  each with lifetime/30d numbers and last-sale date. Read-only.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Dict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

NEW_ACCT = "act_1179668409969241"
LAUNCH = dt.date(2026, 9, 25)


def _sg(campaign: str) -> bool:
    c = cpa.norm(campaign)
    return ("[sg]" in c) or ("martin-sg" in c) or ("martin sg" in c)


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    old_acct = s.meta.account_path
    token = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d30 = today - dt.timedelta(days=30)
    acc = s.cpa.max_acceptable_myr

    live_names: set = set()

    def board(acct: str, title: str, with_perf: bool) -> float:
        camps = {c["id"]: c for c in g._get_all(
            f"{acct}/campaigns", {"fields": "id,name,status,effective_status,daily_budget",
                                  "limit": 200})}
        adsets = g._get_all(f"{acct}/adsets",
                            {"fields": "id,name,status,effective_status,daily_budget,"
                                       "campaign_id", "limit": 500})
        ads = g._get_all(f"{acct}/ads",
                         {"fields": "id,name,effective_status,adset_id", "limit": 500})
        perf_sp: Dict[str, float] = defaultdict(float)
        perf_ld: Dict[str, float] = defaultdict(float)
        if with_perf:
            for r in g.account_insights(acct, level="ad", fields="ad_id,spend,actions",
                                        time_range={"since": LAUNCH.isoformat(),
                                                    "until": today.isoformat()}):
                try:
                    perf_sp[r.get("ad_id")] += float(r.get("spend") or 0)
                except (TypeError, ValueError):
                    pass
                perf_ld[r.get("ad_id")] += extract_results(r.get("actions"), token)
        live_ads = [a for a in ads if a.get("effective_status") == "ACTIVE"]
        by_set: Dict[str, list] = defaultdict(list)
        for a in live_ads:
            by_set[a.get("adset_id")].append(a)
            k = cpa.ad_key(a.get("name") or "")
            if k:
                live_names.add(k)
        log.info("═" * 110)
        log.info("%s", title)
        log.info("═" * 110)
        total = 0
        for aset in adsets:
            ads_here = by_set.get(aset["id"]) or []
            if not ads_here:
                continue
            b = int(aset.get("daily_budget") or 0)
            if not b:
                b = int((camps.get(aset.get("campaign_id")) or {}).get("daily_budget") or 0)
            total += b
            camp_name = (camps.get(aset.get("campaign_id")) or {}).get("name") or "?"
            log.info("▸ RM%-4d %s › %s", b // 100, camp_name[:56], aset.get("name")[:38])
            for a in ads_here:
                sp, ld = perf_sp.get(a["id"], 0.0), perf_ld.get(a["id"], 0.0)
                extra = (f" · 开跑后 花 RM{sp:,.0f} · {int(ld)}L" +
                         (f" · CPL RM{sp / ld:,.0f}" if ld else "")) if with_perf else ""
                log.info("     %s%s", (a.get("name") or "")[:52], extra)
        if total == 0:
            log.info("（没有在投的链）")
        log.info("小计: RM%d/day", total // 100)
        return total / 100

    new_total = board(NEW_ACCT, f"① 新账户 现在开着的（开跑 {LAUNCH} 起的数据）", True)
    old_total = board(old_acct, "② 老账户 现在开着的", False)

    # ── ③ reopen tiers ──────────────────────────────────────────────────────────
    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    life_n: Dict[str, int] = defaultdict(int)
    s30: Dict[str, int] = defaultdict(int)
    last_sale: Dict[str, dt.date] = {}
    disp: Dict[str, str] = {}
    for x in sales:
        if not _sg(x.campaign):
            continue
        k = cpa.ad_key(x.ad)
        if not k:
            continue
        disp.setdefault(k, (x.ad or "").strip())
        life_n[k] += 1
        if x.date:
            if x.date >= d30:
                s30[k] += 1
            if k not in last_sale or x.date > last_sale[k]:
                last_sale[k] = x.date

    def fold(acct, **kw):
        out: Dict[str, float] = defaultdict(float)
        for r in g.account_insights(acct, level="ad", fields="ad_id,ad_name,spend", **kw):
            try:
                out[cpa.ad_key(r.get("ad_name") or "")] += float(r.get("spend") or 0)
            except (TypeError, ValueError):
                continue
        return out

    spL = fold(old_acct, date_preset="maximum")
    for k, v in fold(NEW_ACCT, date_preset="maximum").items():
        spL[k] += v
    sp30 = fold(old_acct, time_range={"since": d30.isoformat(), "until": today.isoformat()})
    for k, v in fold(NEW_ACCT, time_range={"since": d30.isoformat(),
                                           "until": today.isoformat()}).items():
        sp30[k] += v

    tier_a, tier_b = [], []
    for k, n in life_n.items():
        if k in live_names:
            continue
        lsp = spL.get(k, 0.0)
        lcpa = lsp / n if n else 0.0
        if s30.get(k, 0) >= 1:
            c30 = sp30.get(k, 0.0) / s30[k]
            if c30 <= acc:
                tier_a.append((c30, k))
        elif n >= 3 and lcpa <= acc and lsp >= 200:
            tier_b.append((lcpa, k))
    tier_a.sort()
    tier_b.sort()

    log.info("═" * 110)
    log.info("③A 近期合格但没在投（30d 有单 · 30d CPA ≤ RM%.0f）", acc)
    for c30, k in tier_a:
        log.info("▸ %-44s 30d CPA RM%-6.0f (30d %d单) · 终身 %d单/CPA RM%-6.0f · 最后成交 %s",
                 disp.get(k, k)[:44], c30, s30[k], life_n[k],
                 spL.get(k, 0.0) / life_n[k], last_sale.get(k))
    if not tier_a:
        log.info("（没有）")
    log.info("═" * 110)
    log.info("③B 终身单王被冷落（≥3 单 · 终身 CPA ≤ RM%.0f · 30d 无单）", acc)
    for lcpa, k in tier_b:
        log.info("▸ %-44s 终身 %d单 · CPA RM%-6.0f · 花 RM%-8.0f · 最后成交 %s",
                 disp.get(k, k)[:44], life_n[k], lcpa, spL.get(k, 0.0), last_sale.get(k))
    if not tier_b:
        log.info("（没有）")
    final_summary(log, f"Snapshot: new acct RM{new_total:.0f}/day, old acct RM{old_total:.0f}"
                       f"/day; reopen tiers: {len(tier_a)} recent-qualified, "
                       f"{len(tier_b)} forgotten lifetime winners. Read-only.")


if __name__ == "__main__":
    main()
