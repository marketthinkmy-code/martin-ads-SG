"""Top-5 60d-CPA ads + reusable post ids (read-only, 28 Sep).

Operator: 让我知道 paid student list 里 60 天内 CPA 不错的 top 5 广告，
给 ads name & existing post id，要手动建广告。

① Paid Student List → provably-SG sales dated within the last 60 days, folded by ad
  name (cpa.ad_key). ② 60d spend folded across BOTH accounts by the same key.
③ Rank by 60d CPA ascending (spend ≥ RM100 to keep the math honest; lower-spend
  qualifiers listed after). ④ For each: newest copy on either account whose creative
  carries effective_object_story_id → the post id to reuse (engagement pools).
Read-only.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Dict, Optional

from adbot import cpa
from adbot.clients.graph import GraphError
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

NEW_ACCT = "act_1179668409969241"
MIN_SPEND = 100.0


def _sg(campaign: str) -> bool:
    c = cpa.norm(campaign)
    return ("[sg]" in c) or ("martin-sg" in c) or ("martin sg" in c)


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    old_acct = s.meta.account_path
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d60 = today - dt.timedelta(days=60)
    acc = s.cpa.max_acceptable_myr

    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id,
                                                             s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    n60: Dict[str, int] = defaultdict(int)
    disp: Dict[str, str] = {}
    last_sale: Dict[str, dt.date] = {}
    latest: Optional[dt.date] = None
    for x in sales:
        if not _sg(x.campaign) or not x.date:
            continue
        if latest is None or x.date > latest:
            latest = x.date
        if x.date >= d60:
            k = cpa.ad_key(x.ad)
            if not k:
                continue
            n60[k] += 1
            disp.setdefault(k, (x.ad or "").strip())
            if k not in last_sale or x.date > last_sale[k]:
                last_sale[k] = x.date
    log.info("名单最新 SG 成交日: %s · 60d 窗口 %s → %s · 60d 有单的广告 %d 个",
             latest, d60, today, len(n60))

    sp60: Dict[str, float] = defaultdict(float)
    for acct in (old_acct, NEW_ACCT):
        for r in g.account_insights(acct, level="ad", fields="ad_id,ad_name,spend",
                                    time_range={"since": d60.isoformat(),
                                                "until": today.isoformat()}):
            try:
                sp60[cpa.ad_key(r.get("ad_name") or "")] += float(r.get("spend") or 0)
            except (TypeError, ValueError):
                continue

    ranked = sorted(((sp60.get(k, 0.0) / n, k) for k, n in n60.items()
                     if sp60.get(k, 0.0) >= MIN_SPEND))
    low = sorted(((sp60.get(k, 0.0), k) for k in n60 if sp60.get(k, 0.0) < MIN_SPEND))
    top = ranked[:5]

    ads_index = []
    for acct, tag in ((old_acct, "老"), (NEW_ACCT, "新")):
        for a in g._get_all(f"{acct}/ads", {"fields": "id,name,created_time",
                                            "limit": 500}):
            ads_index.append((a.get("created_time") or "", tag, a["id"],
                              cpa.ad_key(a.get("name") or "")))
    ads_index.sort(reverse=True)

    def find_post(key: str):
        for created, tag, ad_id, k in ads_index:
            if k != key:
                continue
            try:
                cr = (g.get_object(ad_id, "creative{effective_object_story_id}")
                      .get("creative") or {})
            except GraphError:
                continue
            pid = cr.get("effective_object_story_id")
            if pid:
                return pid, tag, ad_id, created
        return None, None, None, None

    log.info("═" * 112)
    log.info("60d CPA Top 5（SG 名单归因 · 两账户花费合并 · 达标线 RM%.0f · 花费下限 RM%.0f）",
             acc, MIN_SPEND)
    rows = []
    for i, (cpa_v, k) in enumerate(top, 1):
        pid, tag, ad_id, created = find_post(k)
        mark = "✅" if cpa_v <= acc else ("🤔" if cpa_v <= s.cpa.hard_stop_myr else "❌")
        log.info("%d) %s", i, disp.get(k, k))
        log.info("    60d: 花 RM%-9.2f %d 单 · CPA RM%-7.0f %s · 最后成交 %s",
                 sp60.get(k, 0.0), n60[k], cpa_v, mark, last_sale.get(k))
        log.info("    POST ID: %s  （取自%s账户 ad %s · %s）",
                 pid or "∅ 找不到可复用的帖", tag or "-", ad_id or "-",
                 (created or "")[:10])
        rows.append(f"#{i} {disp.get(k, k)[:24]}→{pid}")
    if not top:
        log.info("（60d 内没有花费 ≥ RM%.0f 且有单的广告）", MIN_SPEND)

    if low:
        log.info("─" * 112)
        log.info("另有 60d 有单但 60d 花费 < RM%.0f 的（多为旧点击延迟转化，CPA 数字失真，仅供参考）:",
                 MIN_SPEND)
        for sp, k in low:
            log.info("  · %-44s 60d %d 单 · 60d 花 RM%-8.2f · 最后成交 %s",
                     disp.get(k, k)[:44], n60[k], sp, last_sale.get(k))

    final_summary(log, f"Top-{len(top)} 60d-CPA ads with post ids ready; latest sheet sale "
                       f"{latest}. Read-only.")


if __name__ == "__main__":
    main()
