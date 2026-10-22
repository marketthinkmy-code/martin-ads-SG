"""Recent rows of the paid sheet, every market, with or without UTM (read-only, 22 Oct).

webinar_review counts only rows whose UTM campaign says [SG]; cpa.parse_sales also drops rows with
no UTM campaign and no UTM ad. This lists every row dated on/after ADBOT_SINCE (default 2026-10-14)
plus undated rows among the last 20, so a 21/10 SG buyer without UTM or date is not missed: date, market guess, UTM campaign / ad set / ad,
and the non-personal columns. Personal columns (name, phone, email, IC, address) are never
printed; a phone shows only its country code. No writes.
"""
from __future__ import annotations

import datetime as dt
import os
import re
from collections import Counter

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

PII = re.compile(r"name|名|phone|tel|电话|電話|手机|whatsapp|mail|邮|ic|nric|passport|address|地址|line id|wechat", re.I)


def main():
    log = get_logger()
    s = load_settings()
    since = dt.date.fromisoformat(os.environ.get("ADBOT_SINCE") or "2026-10-14")
    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    _sales, cols, header = cpa.parse_sales(values, s.cpa.price_myr)
    hidx = values.index(header)
    log.info("分页 %r · 表头在第 %d 行 · 列：%s", s.cpa.sales_tab, hidx + 1,
             " | ".join(f"{i}:{h}" for i, h in enumerate(header)))
    phone_cols = [i for i, h in enumerate(header) if re.search(r"phone|tel|电话|電話|手机|whatsapp", h or "", re.I)]
    keep = [i for i, h in enumerate(header) if h and not PII.search(h) and i not in cols.values()]
    by_day = Counter()
    for n, row in enumerate(values[hidx + 1:], start=hidx + 2):
        def cell(i):
            return row[i] if 0 <= i < len(row) else ""
        d = cpa.parse_date(cell(cols.get("date", -1)))
        tail = n > len(values) - 20
        if not any(cell(i) for i in range(len(header))):
            continue
        if (not d or d < since) and not (tail and not d):
            continue
        camp, adset, ad = cell(cols.get("campaign", -1)), cell(cols.get("adset", -1)), cell(cols.get("ad", -1))
        c = cpa.norm(camp)
        mkt = "SG" if ("[sg]" in c or "martin-sg" in c or "martin sg" in c) else "MY" if ("[my]" in c or "martin-my" in c or "martin my" in c) else "无UTM/其他"
        cc = ""
        for i in phone_cols:
            m = re.match(r"\s*\+?\s*(65|60|852|886)", cell(i).replace(" ", ""))
            if m:
                cc = "+" + m.group(1)
        by_day[(d, mkt, cc)] += 1
        extra = " · ".join(f"{header[i]}={cell(i)[:30]}" for i in keep if cell(i))
        log.info("第 %d 行 %s · %s · 电话区号 %s · campaign %r · ad set %r · ad %r · %s", n, d, mkt, cc or "—",
                 camp[:50], adset[:30], ad[:40], extra[:200])
    log.info("═" * 80)
    for (d, mkt, cc), k in sorted(by_day.items(), key=lambda kv: (str(kv[0][0]), kv[0][1], kv[0][2])):
        log.info("  %s · %-8s · 区号 %-5s · %d 笔", d, mkt, cc or "—", k)
    final_summary(log, f"recent sales rows since {since} · read-only")


if __name__ == "__main__":
    main()
