"""What does an SG sale actually bring in? (read-only, 29 Oct)

The CPA bands in config were set on RM2,399 (3 Sep); the operator now quotes RM2,591. Lists the
Purchase amount of every paid-sheet row since ADBOT_SINCE (default 2026-07-01) by market and month,
as the sheet has it (blank amount shown as blank, not defaulted). No personal columns. No writes.
"""
from __future__ import annotations

import datetime as dt
import os
from collections import Counter

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings


def main():
    log = get_logger()
    s = load_settings()
    since = dt.date.fromisoformat(os.environ.get("ADBOT_SINCE") or "2026-07-01")
    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    _sales, cols, header = cpa.parse_sales(values, s.cpa.price_myr)
    h = values.index(header)
    c = Counter()
    for row in values[h + 1:]:
        cell = lambda k: row[cols[k]] if 0 <= cols.get(k, -1) < len(row) else ""
        d = cpa.parse_date(cell("date"))
        if not d or d < since:
            continue
        camp = cpa.norm(cell("campaign"))
        mkt = "SG" if "[sg]" in camp else "MY" if "[my]" in camp else "无UTM"
        c[(mkt, d.strftime("%Y-%m"), cell("amount").strip())] += 1
    log.info("Purchase amount 列 = %r", header[cols["amount"]] if cols.get("amount", -1) >= 0 else None)
    for (mkt, mon, amt), n in sorted(c.items()):
        log.info("  %-5s %s · 金额 %-14r · %d 笔", mkt, mon, amt, n)
    final_summary(log, "sale amounts · read-only")


if __name__ == "__main__":
    main()
