"""Do the paid sheet's SG sales match live Meta names by campaign + ad set + ad? (read-only, 29 Oct)

Operator 29 Oct: 「花到 RM90 零报名，自己的 campaign，ad set，ad 还没有自己的成交，就关」. Before the
monitor keys a sale by (campaign, ad set, ad) instead of (campaign, ad), check on the last 60 days:
every SG sale, whether some ad on SG old / HK with spend in the window has the same campaign + ad
(2-part) and the same campaign + ad set + ad (3-part), keys folded by cpa.ad_key. No writes.
"""
from __future__ import annotations

import datetime as dt
import json

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

SG_ACCTS = [("SG老", "act_1024930575770087"), ("HK", "act_1179668409969241")]


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    since = today - dt.timedelta(days=60)
    tr = json.dumps({"since": since.isoformat(), "until": today.isoformat()})
    two, three = {}, {}
    for label, acct in SG_ACCTS:
        for r in g._get_all(f"{acct}/insights", {"level": "ad", "limit": 500, "time_range": tr,
                                                 "fields": "campaign_name,adset_name,ad_name,spend"}):
            c, a, d = (cpa.ad_key(r.get(k) or "") for k in ("campaign_name", "adset_name", "ad_name"))
            two.setdefault((c, d), set()).add(label)
            three.setdefault((c, a, d), set()).add(label)
    sales, _c, _h = cpa.parse_sales(SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab),
                                    s.cpa.price_myr)
    n = n2 = n3 = 0
    for x in sales:
        if not x.date or x.date <= since or "[sg]" not in cpa.norm(x.campaign):
            continue
        n += 1
        c, a, d = cpa.ad_key(x.campaign), cpa.ad_key(x.adset), cpa.ad_key(x.ad)
        m2, m3 = (c, d) in two, (c, a, d) in three
        n2 += m2
        n3 += m3
        log.info("%s · campaign %r · ad set %r · ad %r · 2层 %s · 3层 %s", x.date, x.campaign[:60], x.adset[:40],
                 x.ad[:40], "对上" if m2 else "没对上", "对上" if m3 else "没对上")
    final_summary(log, f"60 天 SG 成交 {n} 笔 · campaign+ad 对上 {n2} · campaign+ad set+ad 对上 {n3}")


if __name__ == "__main__":
    main()
