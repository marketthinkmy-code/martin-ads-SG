"""Window verdicts 0919 (Fri → now). READ-ONLY — analysis for the operator, changes nothing.

Operator (19 Sep, away from computer): 看 SG 从星期五到现在的广告，哪些要开 / scale / 关，
根据 CPL 和 CPA。

Per ad NAME (copies folded):
    window  = Friday 2026-09-18 00:00 MYT → today: spend, leads, CPL
    CPA     = fresh provably-SG buyers dated ≥ 2026-09-17 (webinar night onward)
              + lifetime spend/sales CPA for context
Verdicts use the standing rules: CPL target RM95 · zero-reg kill line RM142.50 window
spend · CPA bands 960/1,200 · "Budget 跟着 Buyer" (a fresh buyer outranks a bad CPL).
Also reports whether the 9/17 webinar's sales have reached the sheet at all — if none
are entered yet, the CPA half is explicitly flagged as still blind.
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

WINDOW_START = dt.date(2026, 9, 18)     # Friday, per the operator's ask
BUYER_START = dt.date(2026, 9, 17)      # webinar night — buyers count from here


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

    # ── sheet: lifetime + fresh buyers per ad key ───────────────────────────────
    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    life: Dict[str, int] = defaultdict(int)
    fresh: Dict[str, int] = defaultdict(int)          # dated >= 9/17
    fresh_disp: Dict[str, str] = {}
    n_sg = n_fresh_sg = 0
    latest_sale: dt.date | None = None
    for x in sales:
        if not _sg(x.campaign):
            continue
        n_sg += 1
        k = cpa.ad_key(x.ad)
        life[k] += 1
        if x.date and (latest_sale is None or x.date > latest_sale):
            latest_sale = x.date
        if x.date and x.date >= BUYER_START:
            n_fresh_sg += 1
            fresh[k] += 1
            fresh_disp.setdefault(k, (x.ad or "").strip()[:40])
    log.info("Paid Student List: %d provably-SG total · 最新成交日期 %s · ≥%s 的 SG 单: %d %s",
             n_sg, latest_sale, BUYER_START, n_fresh_sg,
             "⚠️ 周四场大概率还没录完" if n_fresh_sg == 0 else "")

    # ── meta: statuses, budgets, window + lifetime spend per name ──────────────
    ads = g._get_all(f"{acct}/ads",
                     {"fields": "id,name,effective_status,adset_id", "limit": 500})
    adsets = {a["id"]: a for a in g._get_all(
        f"{acct}/adsets", {"fields": "id,daily_budget,campaign_id", "limit": 500})}
    camps = {c["id"]: c for c in g._get_all(
        f"{acct}/campaigns", {"fields": "id,daily_budget", "limit": 200})}
    disp: Dict[str, str] = {}
    n_live: Dict[str, int] = defaultdict(int)
    abo_budget: Dict[str, int] = defaultdict(int)
    cbo_flag: Dict[str, Set[str]] = defaultdict(set)
    for a in ads:
        k = cpa.ad_key(a.get("name") or "")
        if not k:
            continue
        disp.setdefault(k, (a.get("name") or "").strip())
        if a.get("effective_status") == "ACTIVE":
            n_live[k] += 1
            aset = adsets.get(a.get("adset_id")) or {}
            b = int(aset.get("daily_budget") or 0)
            if b:
                abo_budget[k] += b
            elif int((camps.get(aset.get("campaign_id")) or {}).get("daily_budget") or 0):
                cbo_flag[k].add(aset.get("campaign_id") or "")

    win = {"since": WINDOW_START.isoformat(), "until": today.isoformat()}
    w_spend: Dict[str, float] = defaultdict(float)
    w_leads: Dict[str, float] = defaultdict(float)
    for r in g.account_insights(acct, level="ad", fields="ad_id,ad_name,spend,actions",
                                time_range=win):
        k = cpa.ad_key(r.get("ad_name") or "")
        try:
            w_spend[k] += float(r.get("spend") or 0)
        except (TypeError, ValueError):
            pass
        w_leads[k] += extract_results(r.get("actions"), token)

    l_spend: Dict[str, float] = defaultdict(float)
    for r in g.account_insights(acct, level="ad", fields="ad_id,ad_name,spend",
                                date_preset="maximum"):
        try:
            l_spend[cpa.ad_key(r.get("ad_name") or "")] += float(r.get("spend") or 0)
        except (TypeError, ValueError):
            continue

    kpi_cpl = s.kpi.cpl_target_myr
    kill_line = s.kpi.cpl_min_spend_myr        # 142.50 = 1.5 × target, zero-reg kill
    acc, hard = s.cpa.max_acceptable_myr, s.cpa.hard_stop_myr

    log.info("═" * 112)
    log.info("① 在投广告 · 窗口 %s → %s（CPL 窗口口径 · Buyer ≥ %s · CPA 终身口径）",
             WINDOW_START, today, BUYER_START)
    log.info("═" * 112)
    live_keys = sorted((k for k in set(w_spend) | set(n_live) if n_live.get(k)),
                       key=lambda k: -w_spend.get(k, 0.0))
    w_total = 0.0
    for k in live_keys:
        sp, ld = w_spend.get(k, 0.0), w_leads.get(k, 0.0)
        w_total += sp
        fb = fresh.get(k, 0)
        n, lsp = life.get(k, 0), l_spend.get(k, 0.0)
        life_cpa = lsp / n if n else 0.0
        cpl_txt = f"RM{sp / ld:,.0f}" if ld else ("∞" if sp else "—")
        btxt = f"RM{abo_budget[k] // 100}" if abo_budget.get(k) else ""
        if cbo_flag.get(k):
            btxt += ("+" if btxt else "") + "CBO"
        if fb > 0:
            verdict = f"🚀 SCALE 候选 —— 本场 {fb} 个 Buyer（Budget 跟着 Buyer）"
        elif sp >= kill_line and ld == 0:
            verdict = f"🔻 关（窗口花 RM{sp:,.0f} ≥ RM{kill_line:,.0f} 仍 0 lead —— 标准零转化线）"
        elif n and life_cpa > hard:
            verdict = f"🔻 关 候选（终身 CPA RM{life_cpa:,.0f} 超硬线）"
        elif ld and (sp / ld) <= kpi_cpl:
            verdict = "✅ 健康（CPL 达标）—— 等 Buyer 数据定 scale"
        elif ld:
            verdict = f"⚠️ CPL 超标（>RM{kpi_cpl:.0f}）—— 无 Buyer 撑腰就别加"
        else:
            verdict = "⏳ 花费未到判定线，观察"
        log.info("▸ %-38s 预算 %-8s 窗口花 RM%-6.0f %2dL CPL %-7s · Buyer≥917 %d · 终身 %d单/CPA %s",
                 disp.get(k, k)[:38], btxt, sp, int(ld), cpl_txt, fb, n,
                 f"RM{life_cpa:,.0f}" if n else "—")
        log.info("    → %s", verdict)

    # ── paused names that took a FRESH buyer (webinar-onward) ───────────────────
    log.info("═" * 112)
    log.info("② 没在投、但 %s 后有成交进 sheet 的名字（开回候选 · CPA 口径）", BUYER_START)
    hits = 0
    for k, fb in sorted(fresh.items(), key=lambda kv: -kv[1]):
        if n_live.get(k):
            continue
        n, lsp = life.get(k, 0), l_spend.get(k, 0.0)
        life_cpa = lsp / n if n else 0.0
        tag = ("💡 开 候选" if (n and life_cpa <= acc) else
               ("🤔 边缘（CPA 960-1200）" if (n and life_cpa <= hard) else
                "⚠️ 有单但终身 CPA 超硬线 — 你定"))
        log.info("▸ %-40s 本场 Buyer %d · 终身 %d单 · CPA %s → %s",
                 (fresh_disp.get(k) or disp.get(k, k))[:40], fb, n,
                 f"RM{life_cpa:,.0f}" if n else "—", tag)
        hits += 1
    if not hits:
        log.info("（没有 —— %s 后进 sheet 的 SG 单%s）", BUYER_START,
                 "为 0，周四场名单还没录" if n_fresh_sg == 0 else "都落在在投的名字上")

    final_summary(log, f"Window verdicts Fri→{today}: {len(live_keys)} live names, window "
                       f"spend ≈ RM{w_total:,.0f}; fresh SG buyers since {BUYER_START}: "
                       f"{n_fresh_sg}. READ-ONLY — nothing changed.")


if __name__ == "__main__":
    main()
