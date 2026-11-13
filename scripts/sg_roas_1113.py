"""SG project ROAS / CPA by webinar week and 30 / 60 / 90 days (read-only, 13 Nov).

Operator 13 Nov: 「我希望你的分析建议基准也有 CPA，不要只是看 CPL，我的结果还是整体项目的 ROAS，赚不赚钱。」
Spend = SG老户 + HK, all ads. Sales = Paid Student List rows whose UTM campaign is a campaign on SG老户 / HK
(CLAUDE.md Lead Quality rule 8); revenue = the row's amount (price fallback from config). Rows with no UTM are
counted apart (could be organic or untracked; never added to SG). Week = Thursday → Wednesday (the webinar day),
a sale dated on or before that Wednesday belongs to that week. Sheet rows 1331–1335 ignored (operator 12 Nov).
No names / emails / phones. No writes.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

ACCTS = ["act_1024930575770087", "act_1179668409969241"]
IGNORE = set(range(1331, 1336))


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    camps = set()
    for a in ACCTS:
        for c in g._get_all(f"{a}/campaigns", {"fields": "name", "limit": 500}):
            camps.add(cpa.ad_key(c.get("name") or ""))

    def is_sg(J):
        k = cpa.ad_key(J)
        return bool(k) and (k in camps or (len(k) >= 12 and any(p.startswith(k) for p in camps)))
    vals = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    hi, cols = 0, cpa.find_columns(vals[0])
    for i, r in enumerate(vals[:8]):
        cc = cpa.find_columns(r)
        if cc.get("campaign", -1) >= 0 and cc.get("ad", -1) >= 0:
            hi, cols = i, cc
            break

    def cell(r, k):
        j = cols.get(k, -1)
        return (r[j] if 0 <= j < len(r) else "").strip()
    sg, nout = [], []
    for n, r in enumerate(vals[hi + 1:], start=hi + 2):
        if n in IGNORE or not any((x or "").strip() for x in r):
            continue
        d = cpa.parse_date(cell(r, "date"))
        if not d or d < today - dt.timedelta(days=120):
            continue
        amt = cpa._money(cell(r, "amount"), s.cpa.price_myr)
        J = cell(r, "campaign")
        (sg if is_sg(J) else nout if not J and not cell(r, "adset") else []).append((d, amt))
    since = today - dt.timedelta(days=120)
    spend = defaultdict(float)
    for a in ACCTS:
        for r in g._get_all(f"{a}/insights", {"level": "account", "time_increment": 1, "fields": "spend",
                                              "time_range": json.dumps({"since": since.isoformat(), "until": today.isoformat()})}):
            spend[dt.date.fromisoformat(r["date_start"])] += float(r.get("spend") or 0)

    def line(lbl, a, b):
        sp = sum(v for d, v in spend.items() if a <= d <= b)
        xs = [x for x in sg if a <= x[0] <= b]
        rev = sum(x[1] for x in xs)
        no = sum(1 for x in nout if a <= x[0] <= b)
        log.info("  %s · 花 RM%.2f · SG 成交 %d 单 · 营收 RM%.2f · CPA %s · ROAS %s · 赚/亏 RM%.2f · （另有无 UTM 成交 %d 单，不算进 SG）",
                 lbl, sp, len(xs), rev, f"RM{sp / len(xs):.2f}" if xs else "—（0 单）", f"{rev / sp:.2f}" if sp else "—",
                 rev - sp, no)
    log.info("SG 整体（SG老户 + HK 全部花费 · 成交表 UTM 对上 SG 的单）· 读数 %s", today)
    for days in (30, 60, 90):
        line(f"最近 {days} 天", today - dt.timedelta(days=days - 1), today)
    log.info("按直播周（星期四 → 星期三直播）：")
    wed = today - dt.timedelta(days=(today.weekday() - 2) % 7)
    for k in range(9, -1, -1):
        b = wed - dt.timedelta(days=7 * k)
        a = b - dt.timedelta(days=6)
        line(f"{a}~{b}（{b} 直播）", a, b)
    nb = wed + dt.timedelta(days=1)
    line(f"{nb}~今天（本期，11/18 直播）", nb, today)
    final_summary(log, "SG 整体 ROAS / CPA 读完（只读）")


if __name__ == "__main__":
    main()
