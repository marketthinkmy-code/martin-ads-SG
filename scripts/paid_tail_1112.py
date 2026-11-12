"""Last rows of the paid sheet, UTM + date + amount only (read-only, 12 Nov).

Operator 12 Nov: 「昨天有 3 个成交」 but cycle review found 2 rows dated 2026-11-11 (both MY UTM). Show the
last 15 data rows of 'Paid Student List (RM1997)' — row number, raw date cell, parsed date, UTM campaign /
ad set / ad, amount — so a row without a parseable date or still being entered is visible. No name, email or
phone column is printed. No writes.
"""
from __future__ import annotations

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings


def main():
    log = get_logger()
    s = load_settings()
    vals = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    hdr_i, cols = 0, cpa.find_columns(vals[0])
    for i, row in enumerate(vals[:8]):
        c = cpa.find_columns(row)
        if c.get("campaign", -1) >= 0 and c.get("ad", -1) >= 0:
            hdr_i, cols = i, c
            break
    log.info("表头第 %d 行 · 用到的栏：%s", hdr_i + 1,
             {k: (v, vals[hdr_i][v] if 0 <= v < len(vals[hdr_i]) else None) for k, v in cols.items()})
    sales, _c, _h = cpa.parse_sales(vals, s.cpa.price_myr)

    def cell(row, k):
        j = cols.get(k, -1)
        return row[j].strip() if 0 <= j < len(row) else ""

    data = [(n + 1, r) for n, r in enumerate(vals) if n > hdr_i and any((x or "").strip() for x in r)]
    log.info("资料行 %d 行（parse_sales 读到 %d 笔）。最后 15 行：", len(data), len(sales))
    for n, r in data[-15:]:
        raw = cell(r, "date")
        d = cpa.parse_date(raw)
        log.info("  第 %d 行 · 日期 %r → %s · campaign %r · ad set %r · ad %r · 金额 %r", n, raw, d,
                 cell(r, "campaign")[:70], cell(r, "adset")[:35], cell(r, "ad")[:45], cell(r, "amount"))
    by = {}
    for x in sales:
        if x.date and x.date.isoformat() >= "2026-11-04":
            by[x.date.isoformat()] = by.get(x.date.isoformat(), 0) + 1
    final_summary(log, f"11/4 起每天笔数（读得到日期的）：{dict(sorted(by.items()))} · 资料行 {len(data)}、读到 {len(sales)} 笔")


if __name__ == "__main__":
    main()
