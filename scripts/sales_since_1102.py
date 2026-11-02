"""Paid-sheet sales since a date, by market, with their UTM (read-only, 2 Nov; operator 「读数」).

Only date / UTM campaign / ad set / ad / amount are read (cpa.parse_sales) — no names, phones or emails.
ADBOT_SINCE (default 2026-10-29, the Thursday the 4 Nov webinar's ads opened).
"""
from __future__ import annotations

import datetime as dt
import os
from collections import Counter

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings


def market(campaign: str) -> str:
    c = cpa.norm(campaign)
    if "[sg]" in c or "martin-sg" in c or "martin sg" in c:
        return "SG"
    if "[my]" in c or "martin-my" in c or "martin my" in c:
        return "MY"
    return "没有 UTM / 其他"


def main():
    log = get_logger()
    s = load_settings()
    since = dt.date.fromisoformat(os.environ.get("ADBOT_SINCE") or "2026-10-29")
    sales, _c, _h = cpa.parse_sales(SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab),
                                    s.cpa.price_myr)
    rows = sorted((x for x in sales if x.date and x.date >= since), key=lambda x: x.date)
    undated = [x for x in sales if not x.date]
    n = Counter()
    for x in rows:
        m = market(x.campaign)
        n[m] += 1
        log.info("%s · %s · RM%.0f · campaign %r · ad set %r · ad %r", x.date, m, x.amount, x.campaign[:70], x.adset[:35], x.ad[:45])
    log.info("没有日期的行 %d 行（最后 3 行：%s）", len(undated),
             [(u.campaign[:40], u.ad[:30]) for u in undated[-3:]])
    final_summary(log, f"{since} 起成交 {len(rows)} 笔 · " + " · ".join(f"{k} {v}" for k, v in n.most_common()))


if __name__ == "__main__":
    main()
