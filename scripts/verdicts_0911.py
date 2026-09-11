"""Post-webinar verdict round (11 Sep). Read-only — recommendations, no switches touched.

Operator: "你看回我的 paid student list，计算 cpl, cpa，哪一些要关 / 要调低？"

For every LIVE ad (campaign+adset+ad all effective-ACTIVE):
  · CPL over the current run window (since the last Thursday reset — the weekly OFF was
    skipped this webinar week, so the window is a full continuous 7 days),
  · sales context from the Paid Student List by ad NAME KEY (the unit a creative decision
    is made on): provably-SG sales lifetime / last 60d / last 30d, and the name-key
    lifetime CPA (key lifetime spend across every copy ÷ SG sales).
Then the standing verdict rules:
  · no verdict before RM150 spent or 3 leads (the 9 Sep 关太快 fix),
  · CPL ≤ 65 healthy · 65–100 learning allowance · > 100 kill line,
  · a name with recent (60d) SG sales and CPA ≤ acceptable is turned DOWN, not off,
  · spend ≥ 150 with 0 leads = infinite CPL → off (same sales-rescue exception).

PII discipline: no names/phones/emails in logs — dates, UTM and money only.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any, Dict, List

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _myr(minor) -> float:
    return _f(minor) / 100.0


def _sgsale(x) -> bool:  # provably-SG — the account's standing attribution rule
    return ("[sg]" in x.campaign) or ("martin-sg" in x.campaign) or ("martin sg" in x.campaign)


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    token = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    last_thu = today - dt.timedelta(days=(today.weekday() - 3) % 7)
    if last_thu == today:
        last_thu = today - dt.timedelta(days=7)
    d30, d60 = today - dt.timedelta(days=30), today - dt.timedelta(days=60)
    acc_max, hard = s.cpa.max_acceptable_myr, s.cpa.hard_stop_myr

    # ── Paid Student List → per name-key SG sales (life / 60d / 30d) ───────────
    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    sg_life: Dict[str, int] = defaultdict(int)
    sg_60: Dict[str, int] = defaultdict(int)
    sg_30: Dict[str, int] = defaultdict(int)
    sg_last: Dict[str, dt.date] = {}
    for x in sales:
        k = cpa.ad_key(x.ad)
        if not k or not _sgsale(x):
            continue
        sg_life[k] += 1
        if x.date:
            if x.date >= d60:
                sg_60[k] += 1
            if x.date >= d30:
                sg_30[k] += 1
            if k not in sg_last or x.date > sg_last[k]:
                sg_last[k] = x.date
    log.info("Paid Student List: %d rows · %d provably-SG sales on %d distinct ad-name keys",
             len(sales), sum(sg_life.values()), len(sg_life))

    # ── live structure (campaign+adset+ad all ACTIVE) ──────────────────────────
    campaigns = {c["id"]: c for c in g._get_all(
        f"{acct}/campaigns", {"fields": "id,name,effective_status,daily_budget", "limit": 200})}
    adsets = {a["id"]: a for a in g._get_all(
        f"{acct}/adsets", {"fields": "id,name,campaign_id,effective_status,daily_budget", "limit": 500})}
    ads = g._get_all(f"{acct}/ads", {"fields": "id,name,adset_id,effective_status", "limit": 1000})
    live = []
    for a in ads:
        if a.get("effective_status") != "ACTIVE":
            continue
        aset = adsets.get(a.get("adset_id")) or {}
        camp = campaigns.get(aset.get("campaign_id")) or {}
        if aset.get("effective_status") == "ACTIVE" and camp.get("effective_status") == "ACTIVE":
            live.append((camp, aset, a))
    log.info("Live ads right now: %d", len(live))

    # ── insights per ad: week-to-date (since Thu reset), 14d fallback, lifetime ─
    # The Thu reset was YESTERDAY, so most live ads can't clear the RM150/3-leads gate
    # on week-to-date alone; the 14d window judges the same creative's current run.
    win_rows = g.account_insights(acct, level="ad", fields="ad_id,ad_name,spend,actions",
                                  time_range={"since": last_thu.isoformat(),
                                              "until": today.isoformat()})
    win_by_ad = {r.get("ad_id"): r for r in win_rows}
    d14_rows = g.account_insights(acct, level="ad", fields="ad_id,ad_name,spend,actions",
                                  time_range={"since": (today - dt.timedelta(days=14)).isoformat(),
                                              "until": today.isoformat()})
    d14_by_ad = {r.get("ad_id"): r for r in d14_rows}
    life_rows = g.account_insights(acct, level="ad", fields="ad_id,ad_name,spend",
                                   date_preset="maximum")
    key_spend_life: Dict[str, float] = defaultdict(float)
    for r in life_rows:
        key_spend_life[cpa.ad_key(r.get("ad_name") or "")] += _f(r.get("spend"))

    w_spend_all = sum(_f(r.get("spend")) for r in win_rows)
    w_leads_all = sum(extract_results(r.get("actions"), token) for r in win_rows)
    blended = w_spend_all / w_leads_all if w_leads_all else 0.0
    log.info("窗口 %s → %s（上周四 reset 起，本周三没关）: 全户 spend RM%s · %d leads · blended CPL RM%s",
             last_thu, today, f"{w_spend_all:,.0f}", int(w_leads_all),
             f"{blended:,.0f}" if w_leads_all else "∞")

    # ── per-live-ad verdicts ───────────────────────────────────────────────────
    log.info("═" * 118)
    log.info("每条 live ad：预算 · 窗口 spend/leads/CPL · SG 成交(life/60d) · key CPA · 判决")
    log.info("═" * 118)
    buckets: Dict[str, List[str]] = {"close": [], "down": [], "keep": [], "wait": []}
    for camp, aset, a in sorted(live, key=lambda t: (t[0].get("name") or "", t[1].get("name") or "")):
        k = cpa.ad_key(a.get("name") or "")
        w = win_by_ad.get(a["id"]) or {}
        w_spend = _f(w.get("spend"))
        w_leads = extract_results(w.get("actions"), token)
        w_cpl = w_spend / w_leads if w_leads else 0.0
        f14 = d14_by_ad.get(a["id"]) or {}
        f_spend = _f(f14.get("spend"))
        f_leads = extract_results(f14.get("actions"), token)
        f_cpl = f_spend / f_leads if f_leads else 0.0
        n_life, n_60, n_30 = sg_life.get(k, 0), sg_60.get(k, 0), sg_30.get(k, 0)
        kspend = key_spend_life.get(k, 0.0)
        kcpa = kspend / n_life if n_life else 0.0
        budget = _myr(aset.get("daily_budget")) or _myr(camp.get("daily_budget"))

        # judge on week-to-date if it clears the gate, else on the 14d window
        if w_spend >= s.kpi.cpl_min_spend_myr or w_leads >= 3:
            spend, leads, cpl, wtag = w_spend, w_leads, w_cpl, "本周"
            has_verdict = True
        elif f_spend >= s.kpi.cpl_min_spend_myr or f_leads >= 3:
            spend, leads, cpl, wtag = f_spend, f_leads, f_cpl, "14d"
            has_verdict = True
        else:
            spend, leads, cpl, wtag = f_spend, f_leads, f_cpl, "14d"
            has_verdict = False
        if not has_verdict:
            verdict, b = (f"⏳ 再等（14d 也才 spend RM{spend:,.0f} · {int(leads)} leads，"
                          f"未到 RM150/3-leads 门槛）", "wait")
        elif leads == 0:
            if n_60 > 0 and (kcpa <= acc_max or kcpa == 0):
                verdict, b = f"🟠 调低到 RM50（{wtag} 0 leads 但 60d 内有 SG 成交）", "down"
            else:
                verdict, b = f"🔴 关（{wtag} RM{spend:,.0f} 花完 0 leads）", "close"
        elif cpl > s.kpi.cpl_threshold_myr:
            if n_60 > 0 and kcpa <= acc_max:
                verdict, b = (f"🟠 调低到 RM50（{wtag} CPL RM{cpl:,.0f} 贵，"
                              f"但 CPA RM{kcpa:,.0f} 还能接受）", "down")
            else:
                verdict, b = f"🔴 关（{wtag} CPL RM{cpl:,.0f} > 100 kill 线，无近期成交底）", "close"
        elif cpl > 65.0:
            if n_60 > 0:
                verdict, b = f"✅ 保持（{wtag} CPL RM{cpl:,.0f} 偏贵但 60d 有成交）", "keep"
            elif budget > 50:
                verdict, b = f"🟡 调低到 RM50（{wtag} CPL RM{cpl:,.0f} 在 65–100 学习带，无成交底）", "down"
            else:
                verdict, b = f"🟡 保持观察（{wtag} CPL RM{cpl:,.0f}，已是 RM50）", "keep"
        else:
            extra = " · 有成交底，加码候选" if n_60 > 0 else ""
            verdict, b = f"✅ 保持（{wtag} CPL RM{cpl:,.0f} ≤ 65{extra}）", "keep"
        if n_life > 0 and kcpa > hard:
            verdict += f" ⚠️ key CPA RM{kcpa:,.0f} 超硬线 {hard:,.0f}"

        cname = (camp.get("name") or "")[:44]
        aname = (a.get("name") or "")[:44]
        wcpl_txt = f"RM{w_cpl:,.0f}" if w_leads else "∞"
        fcpl_txt = f"RM{f_cpl:,.0f}" if f_leads else "∞"
        cpa_txt = f"RM{kcpa:,.0f}" if n_life else "—"
        log.info("▸ %s", cname)
        log.info("    ad %-44s  RM%-3.0f/day · 本周 RM%-5.0f %dL %-6s · 14d RM%-6.0f %2dL %-6s · SG %d/%d · CPA %s",
                 aname, budget, w_spend, int(w_leads), wcpl_txt,
                 f_spend, int(f_leads), fcpl_txt, n_life, n_60, cpa_txt)
        log.info("    %s", verdict)
        buckets[b].append(f"{aname}  ({cname[:30]}…)" if len(cname) > 30 else f"{aname}  ({cname})")

    log.info("═" * 118)
    log.info("汇总 — 🔴 要关 %d 条 · 🟠🟡 要调低 %d 条 · ✅ 保持 %d 条 · ⏳ 数据不够 %d 条",
             len(buckets["close"]), len(buckets["down"]), len(buckets["keep"]), len(buckets["wait"]))
    for label, key in (("🔴 关", "close"), ("🟠🟡 调低", "down"), ("✅ 保持", "keep"), ("⏳ 再等", "wait")):
        for line in buckets[key]:
            log.info("   %s  %s", label, line)
    final_summary(
        log, f"Window {last_thu}→{today}: account RM{w_spend_all:,.0f} / {int(w_leads_all)} leads "
             f"(blended CPL RM{blended:,.0f}). Verdicts: {len(buckets['close'])} close, "
             f"{len(buckets['down'])} turn down, {len(buckets['keep'])} keep, "
             f"{len(buckets['wait'])} insufficient data. Read-only — nothing was switched; "
             f"newest sheet rows may lag data entry.")


if __name__ == "__main__":
    main()
