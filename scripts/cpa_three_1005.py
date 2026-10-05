"""成交核对 (read-only, 5 Oct): the three September ads, CPA before revival.

Operator: 先把这 3 支对 Paid Student List 算成交 CPA 再决定. For each of
    Video 7：我13岁身高173 / Video 13：三年前他長了10公分 /
    Video：孩子15岁以上还有机会长高吗
report 30d and 60d windows — SG sales from the sheet (folded ad name), spend
folded across the old SG + HK accounts — plus every sale date and the verdict
lines (✅ ≤960 · 🤔 ≤1200 · ❌ beyond). Lifetime SG sales shown for context.
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
from adbot.settings import load_settings

HK_ACCT = "act_1179668409969241"
TARGETS = {
    cpa.ad_key("Video 7：我13岁身高173"): "Video 7：我13岁身高173",
    cpa.ad_key("Video 13：三年前他長了10公分"): "Video 13：三年前他長了10公分",
    cpa.ad_key("Video: 孩子15岁以上还有机会长高吗？"): "Video：孩子15岁以上还有机会长高吗",
}


def _sg(campaign: str) -> bool:
    c = cpa.norm(campaign)
    return ("[sg]" in c) or ("martin-sg" in c) or ("martin sg" in c)


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d30, d60 = today - dt.timedelta(days=30), today - dt.timedelta(days=60)
    acc, hard = s.cpa.max_acceptable_myr, s.cpa.hard_stop_myr

    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id,
                                                             s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    n30: Dict[str, int] = defaultdict(int)
    n60: Dict[str, int] = defaultdict(int)
    nall: Dict[str, int] = defaultdict(int)
    dates: Dict[str, list] = defaultdict(list)
    for x in sales:
        if not x.date or not _sg(x.campaign):
            continue
        k = cpa.ad_key(x.ad)
        if k not in TARGETS:
            continue
        nall[k] += 1
        dates[k].append(x.date.isoformat())
        if x.date >= d30:
            n30[k] += 1
        if x.date >= d60:
            n60[k] += 1

    def fold(since):
        sp: Dict[str, float] = defaultdict(float)
        for acct in (s.meta.account_path, HK_ACCT):
            for r in g._get_all(f"{acct}/insights",
                                {"level": "ad", "limit": 500,
                                 "fields": "ad_name,spend",
                                 "time_range": json.dumps(
                                     {"since": since.isoformat(),
                                      "until": today.isoformat()})}):
                k = cpa.ad_key(r.get("ad_name") or "")
                if k in TARGETS:
                    try:
                        sp[k] += float(r.get("spend") or 0)
                    except (TypeError, ValueError):
                        pass
        return sp

    sp30, sp60 = fold(d30), fold(d60)

    log.info("窗口：30d = %s 起 · 60d = %s 起 · 判线 ✅≤%.0f 🤔≤%.0f ❌>%.0f · 价 RM%.0f",
             d30, d60, acc, hard, hard, s.cpa.price_myr)
    log.info("═" * 100)
    for k, name in TARGETS.items():
        s30, s60 = sp30.get(k, 0.0), sp60.get(k, 0.0)
        line30 = (f"CPA RM{s30 / n30[k]:,.0f}" if n30[k]
                  else ("无单" + (f"（花 RM{s30:.0f}）" if s30 else "·无花费")))
        line60 = (f"CPA RM{s60 / n60[k]:,.0f}" if n60[k]
                  else ("无单" + (f"（花 RM{s60:.0f}）" if s60 else "·无花费")))
        v30 = ("✅" if n30[k] and s30 / n30[k] <= acc else
               "🤔" if n30[k] and s30 / n30[k] <= hard else
               "❌" if (n30[k] or s30) else "—")
        v60 = ("✅" if n60[k] and s60 / n60[k] <= acc else
               "🤔" if n60[k] and s60 / n60[k] <= hard else
               "❌" if (n60[k] or s60) else "—")
        log.info("▸ %s", name)
        log.info("    30d: %d 单 · 花 RM%-8.2f %s %s", n30[k], s30, line30, v30)
        log.info("    60d: %d 单 · 花 RM%-8.2f %s %s", n60[k], s60, line60, v60)
        log.info("    全史 SG 单 %d：%s", nall[k],
                 ", ".join(sorted(dates[k])) if dates[k] else "（名单上没有这支的 SG 单）")
    final_summary(log, "三支成交核对完成 — 决定权在 operator。")


if __name__ == "__main__":
    main()
