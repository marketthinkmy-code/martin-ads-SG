"""CPA verdict round 0917 (webinar night). READ-ONLY — proposes, changes nothing.

Operator (17 Sep): 看现在开的广告 + 最新 Paid Student List → 每个广告的 CPA → 哪个要开 /
要 scale / 要关，以 CPA 为准。(The link pasted was the STOCK BLOOM purchase list — wrong
brand; this runs against the Martin Paid Student List the account has always used.)

Per ad NAME (copies folded, the account's name-level convention):
    lifetime spend (Meta, date_preset=maximum) ÷ lifetime provably-SG sales (sheet)
plus recency columns (60d/30d sales, cycle 9/12→today spend/leads) and live/paused status.

Verdict bands from config CpaCfg (price RM2,399):
    CPA ≤ 960 (max_acceptable)  → live: 🚀 SCALE 候选   paused: 💡 开 候选
    960 < CPA ≤ 1,200           → live: ✅ 留           paused: 🤔 边缘
    CPA > 1,200 (hard_stop)     → live: 🔻 关           paused: ❌ 别开
    无成交 & 花 ≥ RM1,000       → live: 🔻 关 候选
    无成交 & 花 < RM1,000       → live: ⏳ 样本不够，再观察
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any, Dict, List, Set

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

CYCLE_START = dt.date(2026, 9, 12)


def _sg(campaign: str) -> bool:
    c = cpa.norm(campaign)
    return ("[sg]" in c) or ("martin-sg" in c) or ("martin sg" in c)


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    token = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d60, d30 = today - dt.timedelta(days=60), today - dt.timedelta(days=30)

    # ── sheet: provably-SG sales per ad key ─────────────────────────────────────
    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    life: Dict[str, int] = defaultdict(int)
    s60: Dict[str, int] = defaultdict(int)
    s30: Dict[str, int] = defaultdict(int)
    scyc: Dict[str, int] = defaultdict(int)
    last_sale: Dict[str, dt.date] = {}
    n_sg = 0
    for x in sales:
        if not _sg(x.campaign):
            continue
        n_sg += 1
        k = cpa.ad_key(x.ad)
        life[k] += 1
        if x.date:
            if x.date >= d60:
                s60[k] += 1
            if x.date >= d30:
                s30[k] += 1
            if x.date >= CYCLE_START:
                scyc[k] += 1
            if k not in last_sale or x.date > last_sale[k]:
                last_sale[k] = x.date
    log.info("Paid Student List: %d rows parsed · %d provably-SG · %d distinct ad keys with sales",
             len(sales), n_sg, len(life))

    # ── meta: ads, statuses, budgets, lifetime + cycle spend ───────────────────
    ads = g._get_all(f"{acct}/ads",
                     {"fields": "id,name,effective_status,adset_id,campaign_id", "limit": 500})
    adsets = {a["id"]: a for a in g._get_all(
        f"{acct}/adsets", {"fields": "id,daily_budget,campaign_id", "limit": 500})}
    camps = {c["id"]: c for c in g._get_all(
        f"{acct}/campaigns", {"fields": "id,daily_budget", "limit": 200})}

    disp: Dict[str, str] = {}
    n_live: Dict[str, int] = defaultdict(int)
    n_total: Dict[str, int] = defaultdict(int)
    abo_budget: Dict[str, int] = defaultdict(int)      # cents, ACTIVE ABO chains
    cbo_flag: Dict[str, Set[str]] = defaultdict(set)   # CBO campaign ids the key rides in
    for a in ads:
        k = cpa.ad_key(a.get("name") or "")
        if not k:
            continue
        disp.setdefault(k, (a.get("name") or "").strip())
        n_total[k] += 1
        if a.get("effective_status") == "ACTIVE":
            n_live[k] += 1
            aset = adsets.get(a.get("adset_id")) or {}
            b = int(aset.get("daily_budget") or 0)
            if b:
                abo_budget[k] += b
            else:
                cid = aset.get("campaign_id") or a.get("campaign_id") or ""
                if int((camps.get(cid) or {}).get("daily_budget") or 0):
                    cbo_flag[k].add(cid)

    spend_life: Dict[str, float] = defaultdict(float)
    for r in g.account_insights(acct, level="ad", fields="ad_id,ad_name,spend",
                                date_preset="maximum"):
        try:
            spend_life[cpa.ad_key(r.get("ad_name") or "")] += float(r.get("spend") or 0)
        except (TypeError, ValueError):
            continue
    win = {"since": CYCLE_START.isoformat(), "until": today.isoformat()}
    spend_cyc: Dict[str, float] = defaultdict(float)
    leads_cyc: Dict[str, float] = defaultdict(float)
    for r in g.account_insights(acct, level="ad", fields="ad_id,ad_name,spend,actions",
                                time_range=win):
        k = cpa.ad_key(r.get("ad_name") or "")
        try:
            spend_cyc[k] += float(r.get("spend") or 0)
        except (TypeError, ValueError):
            pass
        leads_cyc[k] += extract_results(r.get("actions"), token)

    # the two historical names that already have ready-made paused chains in New Wave 0914
    nw_keys: Set[str] = {cpa.ad_key("Hook 1：今晚回家检查三件事"), cpa.ad_key("Hook 2：旧鞋当尺")}

    acc, hard = s.cpa.max_acceptable_myr, s.cpa.hard_stop_myr
    min_spend = s.cpa.min_spend_myr

    def fmt(k: str) -> str:
        sp, n = spend_life.get(k, 0.0), life.get(k, 0)
        cpa_v = sp / n if n else 0.0
        cyc = f"cyc RM{spend_cyc.get(k, 0):,.0f}/{int(leads_cyc.get(k, 0))}L/{scyc.get(k, 0)}单"
        ls = last_sale.get(k)
        return (f"花 RM{sp:>9,.0f} · {n:>2}单 (60d {s60.get(k, 0)} · 30d {s30.get(k, 0)}) · "
                f"CPA {'RM' + format(cpa_v, ',.0f') if n else '   —  '} · {cyc}"
                f"{' · 最后成交 ' + ls.isoformat() if ls else ''}")

    every_key = set(spend_life) | set(life)
    live_keys = sorted((k for k in every_key if n_live.get(k)),
                       key=lambda k: (life.get(k, 0) == 0,
                                      (spend_life.get(k, 0) / life[k]) if life.get(k) else 1e18,
                                      -spend_life.get(k, 0)))
    log.info("═" * 112)
    log.info("① 现在开着的广告（按 CPA 从好到差 · 名字口径，copies 合并）")
    log.info("═" * 112)
    for k in live_keys:
        sp, n = spend_life.get(k, 0.0), life.get(k, 0)
        cpa_v = sp / n if n else 0.0
        btxt = f"RM{abo_budget[k] // 100}" if abo_budget.get(k) else ""
        if cbo_flag.get(k):
            btxt += ("+" if btxt else "") + f"CBO×{len(cbo_flag[k])}"
        if n and cpa_v <= acc:
            verdict = "🚀 SCALE 候选（CPA 健康）"
        elif n and cpa_v <= hard:
            verdict = "✅ 留（CPA 偏贵但可接受）"
        elif n:
            verdict = "🔻 关 候选（CPA 超硬线 RM1,200）"
        elif sp >= min_spend:
            verdict = f"🔻 关 候选（RM{sp:,.0f} 零成交）"
        else:
            verdict = "⏳ 再观察（花费不足以判 CPA）"
        log.info("▸ %-38s ×%d live · 日预算 %-10s %s", disp.get(k, k)[:38], n_live[k], btxt, fmt(k))
        log.info("    → %s", verdict)

    log.info("═" * 112)
    log.info("② 现在没开、但历史 CPA 值得开的（paused 池，60d 内有成交优先）")
    log.info("═" * 112)
    cand = [k for k in every_key
            if k and not n_live.get(k) and life.get(k, 0) > 0
            and spend_life.get(k, 0) >= 200.0          # drop UTM junk / unmatched names
            and (spend_life.get(k, 0) / life[k]) <= hard]
    cand.sort(key=lambda k: (s60.get(k, 0) == 0, spend_life.get(k, 0) / life[k]))
    for k in cand[:30]:
        sp, n = spend_life.get(k, 0.0), life[k]
        cpa_v = sp / n
        tag = "💡 开 候选" if cpa_v <= acc else "🤔 边缘（960-1200）"
        if not s60.get(k):
            tag += " · ⚠️ 60d 无成交，冷了"
        if k in nw_keys:
            tag += " · New Wave 里有现成 paused 链"
        log.info("▸ %-38s %s", disp.get(k, k)[:38], fmt(k))
        log.info("    → %s", tag)

    live_total = sum(v for v in abo_budget.values())
    log.info("═" * 112)
    final_summary(log, f"CPA verdicts 0917: {len(live_keys)} live ad names "
                       f"(ABO budgets ≈ RM{live_total // 100}/day + CBO pools) · "
                       f"{len(cand)} paused names with CPA ≤ RM{hard:,.0f} worth considering. "
                       f"READ-ONLY — no changes made; operator decides tonight.")


if __name__ == "__main__":
    main()
