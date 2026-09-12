"""Cycle adjust report (doc formula). READ-ONLY — proposes, never changes budgets.

Operator: "周五跑完 adjust 給我看，我再決定" — after each webinar cycle, score every funded
chain by the doc's fixed rules and print the NEXT-cycle budget proposal:

    SCALE   this cycle has Fresh Buyer(s) and buyer CPA healthy (<= acceptable)  -> +20%
    KEEP    historical buyer, this cycle ordinary                                -> unchanged
    REDUCE  two consecutive poor cycles (but past winner evidence)               -> -30%
    OFF     four consecutive poor cycles, no fresh buyer, enough sample          -> 0

Fresh Buyer = provably-SG sale on the Paid Student List dated inside the cycle window,
matched by UTM ad-name key. Cycle history accumulates in state/cycle_history.json so the
"consecutive poor cycles" counters become real from the second cycle on.

The proposal is a table for the operator; nothing is written to Meta.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

HISTORY = Path("state") / "cycle_history.json"
CYCLE_START = dt.date(2026, 9, 12)      # the doc alignment day (this cycle's clock start)

# label · name keys (normalized substring) · current daily budget (RM)
CHAINS: List[Dict[str, Any]] = [
    {"label": "HE04 不买牛奶 (Hook Edits A · CBO)", "keys": ["hook edit 04"], "daily": 180},
    {"label": "V7 15岁还没抽高 (F&R A · CBO)", "keys": ["还没抽高", "還沒抽高"], "daily": 130},
    {"label": "V13 三年前长10cm (LAL 1-2%)", "keys": ["三年前他長了10公分"], "daily": 120},
    {"label": "15岁以上 (LAL 1%)", "keys": ["15岁以上还有机会", "15歲以上還有機會"], "daily": 100},
    {"label": "Hook2 面包当早餐 (Grid B)", "keys": ["把面包当早餐", "把麵包當早餐"], "daily": 65},
    {"label": "Hook3 准备早餐面包 (Broad)", "keys": ["准备早餐面包", "準備早餐麵包"], "daily": 50},
    {"label": "鼻窦炎 (Broad)", "keys": ["鼻窦炎", "鼻竇炎"], "daily": 35},
    {"label": "15岁以上 (Broad)", "keys": [], "daily": 35, "share": "15岁以上"},
    {"label": "15岁以上 (LAL 2-3%)", "keys": [], "daily": 30, "share": "15岁以上"},
    {"label": "V12 试了五六种方法 (Parents·REDUCE)", "keys": ["試了五六種方法", "试了五六种方法"], "daily": 15},
    {"label": "V13 (Parents·REDUCE)", "keys": [], "daily": 15, "share": "V13"},
    {"label": "V11 孩子来MC (Parents·REDUCE)", "keys": ["孩子來mc", "孩子来mc"], "daily": 15},
    {"label": "Hook2 旧鞋当尺 (TEST)", "keys": ["旧鞋当尺", "舊鞋當尺"], "daily": 15},
    {"label": "1-5-5 合并定向 ×5 (TEST)", "keys": ["林書豪", "流鼻涕"], "daily": 55,
     "note": "五条 RM11：15岁以上/早餐面包/林書豪/V1流鼻涕/Hook7"},
]
# NOTE: name keys are shared across campaigns (one creative runs as several copies), so
# spend/buyers are judged at NAME level; chains marked share= inherit their name's verdict.


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    token = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    win = {"since": CYCLE_START.isoformat(), "until": today.isoformat()}

    # sheet: fresh SG buyers in the cycle window, per name key
    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    fresh: Dict[str, int] = {}
    for x in sales:
        c = cpa.norm(x.campaign)
        if not (("[sg]" in c) or ("martin-sg" in c) or ("martin sg" in c)):
            continue
        if x.date and x.date >= CYCLE_START:
            k = cpa.ad_key(x.ad)
            fresh[k] = fresh.get(k, 0) + 1

    # meta: cycle spend + leads per ad, folded to name keys
    spend: Dict[str, float] = {}
    leads: Dict[str, float] = {}
    for r in g.account_insights(s.meta.account_path, level="ad",
                                fields="ad_id,ad_name,spend,actions", time_range=win):
        k = cpa.ad_key(r.get("ad_name") or "")
        try:
            spend[k] = spend.get(k, 0.0) + float(r.get("spend") or 0)
        except (TypeError, ValueError):
            pass
        leads[k] = leads.get(k, 0.0) + extract_results(r.get("actions"), token)

    def agg(keys: List[str]):
        probes = [cpa.ad_key(x) for x in keys if cpa.ad_key(x)]
        def hit(k: str) -> bool:
            return any(p in k for p in probes)
        sp = sum(v for k, v in spend.items() if hit(k))
        ld = sum(v for k, v in leads.items() if hit(k))
        fb = sum(v for k, v in fresh.items() if hit(k))
        return sp, ld, fb

    hist: Dict[str, Any] = json.loads(HISTORY.read_text()) if HISTORY.exists() else {}
    cyc_id = f"{CYCLE_START.isoformat()}→{today.isoformat()}"
    hrec = hist.setdefault("cycles", {}).setdefault(cyc_id, {})

    log.info("═" * 100)
    log.info("CYCLE ADJUST 提案 · 窗口 %s → %s · Budget 跟着 Buyer，不是 CPL", CYCLE_START, today)
    log.info("═" * 100)
    total_next = 0
    for ch in CHAINS:
        keys = ch["keys"] or []
        if keys:
            sp, ld, fb = agg(keys)
        else:
            sp, ld, fb = 0.0, 0.0, 0.0     # share= rows report under their name's main row
        cpl = sp / ld if ld else 0.0
        bcpa = sp / fb if fb else 0.0
        poor = (fb == 0)
        streak = int((hist.get("poor_streak") or {}).get(ch["label"], 0)) + (1 if poor else 0)
        if not poor:
            streak = 0

        if ch.get("share"):
            verdict, nxt = f"跟随「{ch['share']}」主行判决", ch["daily"]
        elif fb > 0 and (bcpa <= s.cpa.max_acceptable_myr):
            nxt = int(round(ch["daily"] * 1.2 / 5.0) * 5)
            verdict = f"SCALE +20% → RM{nxt}（{int(fb)} Fresh Buyer · buyer CPA RM{bcpa:,.0f}）"
        elif fb > 0:
            nxt = ch["daily"]
            verdict = f"KEEP（{int(fb)} Fresh Buyer 但 CPA RM{bcpa:,.0f} 偏贵）"
        elif streak >= 4:
            nxt = 0
            verdict = "OFF 候选（连续 4 场差）"
        elif streak >= 2:
            nxt = int(round(ch["daily"] * 0.7 / 5.0) * 5)
            verdict = f"REDUCE −30% → RM{nxt}（连续 {streak} 场无 Fresh Buyer）"
        else:
            nxt = ch["daily"]
            verdict = "KEEP（本场无 Fresh Buyer，第 1 场差 — doc 规则不动）"
        total_next += nxt
        hrec[ch["label"]] = {"spend": round(sp, 2), "leads": ld, "fresh": fb, "poor": poor}
        hist.setdefault("poor_streak", {})[ch["label"]] = streak
        cpl_txt = f"RM{cpl:,.0f}" if ld else ("∞" if sp else "—")
        log.info("▸ %-40s 现 RM%-4d 花 RM%-7.0f %3dL CPL %-7s Buyer %d",
                 ch["label"], ch["daily"], sp, int(ld), cpl_txt, int(fb))
        log.info("    → %s%s", verdict, ("  · " + ch["note"]) if ch.get("note") else "")

    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(hist, indent=2, ensure_ascii=False) + "\n")
    log.info("═" * 100)
    final_summary(log, f"Cycle adjust proposal ready: next-cycle daily total ≈ RM{total_next} "
                       f"(current plan RM860/day). PROPOSAL ONLY — nothing changed; the "
                       f"operator decides. History recorded for streak rules.")


if __name__ == "__main__":
    main()
