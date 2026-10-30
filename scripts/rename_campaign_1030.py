"""Drop a suffix from a campaign name so the paid sheet's UTM campaign matches again (operator 30 Oct 「A」).

SG old 120258845186730093 '…| 新片5支重测 | 1-1-5 | OCT 8': its Video 2 sale (14 Oct) carries the UTM
campaign '…| 新片5支重测 | 1-1-5', so the monitor's sale_key saw no own sale. Renames only when the current
name ends with ADBOT_SUFFIX, reads the name back, and counts the sheet's sales now matching each live ad
of the campaign by sale_key (campaign + ad set + ad).
"""
from __future__ import annotations

import os
import sys

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import sale_key
from adbot.settings import load_settings


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    cid = os.environ.get("ADBOT_CAMPAIGN_ID") or "120258845186730093"
    suffix = os.environ.get("ADBOT_SUFFIX") or " | OCT 8"
    name = g.get_object(cid, "name").get("name") or ""
    if not name.endswith(suffix):
        log.error("❌ campaign %s 名字 %r 不是以 %r 结尾 —— 没改。", cid, name, suffix)
        sys.exit(1)
    new = name[: -len(suffix)]
    g._request("POST", cid, data={"name": new})
    back = g.get_object(cid, "name").get("name")
    log.info("✏ campaign %s：%r → %r", cid, name, back)
    sales, _c, _h = cpa.parse_sales(SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab),
                                    s.cpa.price_myr)
    keys = [sale_key(x.campaign, x.adset, x.ad) for x in sales]
    for a in g._get_all(f"{cid}/ads", {"fields": "id,name,effective_status,adset{name}", "limit": 200}):
        k = sale_key(back or "", (a.get("adset") or {}).get("name") or "", a.get("name") or "")
        log.info("   ad %s %r · %s · 成交表对上 %d 笔", a["id"], a.get("name"), a.get("effective_status"), keys.count(k))
    final_summary(log, f"campaign {cid} 改名为 {back!r}")


if __name__ == "__main__":
    main()
