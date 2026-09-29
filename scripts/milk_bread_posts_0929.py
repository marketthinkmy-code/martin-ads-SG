"""面包/牛奶相关广告 · post ids + 终身数据 (read-only, 29 Sep).

Operator: 給我麵包牛奶相關的 廣告名 還有 post id 還有 花 / L / CPL。

Every ad on either account whose NAME contains 面包 / 麵包 / 麪包 / 牛奶 (folded,
case/width-insensitive), deduped by folded name. Per name: lifetime spend + leads +
CPL folded across BOTH accounts, lifetime SG sales + CPA from the Paid Student List,
and the newest copy's reusable page-post id. Read-only.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, Optional

import datetime as dt

from adbot import cpa
from adbot.clients.graph import GraphError
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

NEW_ACCT = "act_1179668409969241"
PATTERNS = ("面包", "麵包", "麪包", "牛奶")


def _sg(campaign: str) -> bool:
    c = cpa.norm(campaign)
    return ("[sg]" in c) or ("martin-sg" in c) or ("martin sg" in c)


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    token = result_action_type(s.meta.conversion_event)
    old_acct = s.meta.account_path

    ads_index = []
    names: Dict[str, str] = {}
    for acct, tag in ((old_acct, "老"), (NEW_ACCT, "新")):
        for a in g._get_all(f"{acct}/ads", {"fields": "id,name,created_time",
                                            "limit": 500}):
            nm = (a.get("name") or "").strip()
            k = cpa.ad_key(nm)
            ads_index.append((a.get("created_time") or "", tag, a["id"], k))
            if k and any(p in cpa.norm(nm) for p in PATTERNS):
                names.setdefault(k, nm)
    ads_index.sort(reverse=True)
    log.info("名字含 面包/麵包/牛奶 的广告折叠出 %d 个", len(names))

    sp: Dict[str, float] = defaultdict(float)
    ld: Dict[str, float] = defaultdict(float)
    for acct in (old_acct, NEW_ACCT):
        for r in g.account_insights(acct, level="ad", fields="ad_id,ad_name,spend,actions",
                                    date_preset="maximum"):
            k = cpa.ad_key(r.get("ad_name") or "")
            if k not in names:
                continue
            try:
                sp[k] += float(r.get("spend") or 0)
            except (TypeError, ValueError):
                pass
            ld[k] += extract_results(r.get("actions"), token)

    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id,
                                                             s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    n_sales: Dict[str, int] = defaultdict(int)
    last_sale: Dict[str, dt.date] = {}
    for x in sales:
        if not _sg(x.campaign):
            continue
        k = cpa.ad_key(x.ad)
        if k in names:
            n_sales[k] += 1
            if x.date and (k not in last_sale or x.date > last_sale[k]):
                last_sale[k] = x.date

    def find_post(key: str) -> Optional[str]:
        for _created, _tag, ad_id, k in ads_index:
            if k != key:
                continue
            try:
                cr = (g.get_object(ad_id, "creative{effective_object_story_id}")
                      .get("creative") or {})
            except GraphError:
                continue
            pid = cr.get("effective_object_story_id")
            if pid:
                return pid
        return None

    log.info("═" * 116)
    log.info("面包/牛奶 相关广告（终身口径 · 两账户合并 · 按花费排序）")
    for k in sorted(names, key=lambda x: -sp.get(x, 0.0)):
        cpl = sp[k] / ld[k] if ld.get(k) else 0.0
        ns = n_sales.get(k, 0)
        log.info("▸ %s", names[k])
        log.info("    POST ID: %s · 花 RM%-9.0f %dL%s · %d单%s%s",
                 find_post(k) or "∅ 无可复用帖", sp.get(k, 0.0), int(ld.get(k, 0)),
                 f" · CPL RM{cpl:,.0f}" if ld.get(k) else " · CPL —",
                 ns,
                 f" · CPA RM{sp.get(k, 0.0) / ns:,.0f}" if ns else "",
                 f" · 最后成交 {last_sale.get(k)}" if ns else "")
    final_summary(log, f"{len(names)} milk/bread ads listed with post ids. Read-only.")


if __name__ == "__main__":
    main()
