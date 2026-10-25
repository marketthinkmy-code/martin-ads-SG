"""Why is today expensive? (read-only, 25 Oct; operator: 为什么今天那么贵)

For the given HK ads (ADBOT_AD_IDS), day by day since ADBOT_SINCE: spend, impressions, reach,
frequency, CPM, link clicks, CTR, cost per click, landing page views, registrations,
registration rate (registrations ÷ landing page views), CPL. Then today hour by hour, and the
past 7 days' registrations by hour of day (when leads usually arrive). No writes.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from collections import defaultdict

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

HK = "act_1179668409969241"


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _act(actions, kind):
    return sum(_f(a.get("value")) for a in actions or [] if a.get("action_type") == kind)


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    tok = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    since = dt.date.fromisoformat(os.environ.get("ADBOT_SINCE") or "2026-10-15")
    ids = [x.strip() for x in (os.environ.get("ADBOT_AD_IDS") or "120250236479810335,120250334623090335").split(",") if x.strip()]
    filt = json.dumps([{"field": "ad.id", "operator": "IN", "value": ids}])
    f = "ad_id,ad_name,adset_name,spend,impressions,reach,frequency,cpm,inline_link_clicks,actions"
    rows = list(g._get_all(f"{HK}/insights", {"level": "ad", "limit": 500, "time_increment": 1, "filtering": filt, "fields": f,
                                               "time_range": json.dumps({"since": since.isoformat(), "until": today.isoformat()})}))
    by_ad = defaultdict(list)
    for r in rows:
        by_ad[(r["ad_id"], r.get("ad_name"), r.get("adset_name"))].append(r)
    for (aid, name, aset), rs in by_ad.items():
        log.info("═" * 120)
        log.info("▌%s %s · ad set %s", aid, name, aset)
        log.info("  日期        星期 花费      曝光    触达   频次  CPM     点击  点击率  每点击  落地页  报名  报名率  CPL")
        for r in sorted(rs, key=lambda r: r["date_start"]):
            d = dt.date.fromisoformat(r["date_start"])
            sp, im, ck = _f(r.get("spend")), _f(r.get("impressions")), _f(r.get("inline_link_clicks"))
            lpv, reg = _act(r.get("actions"), "landing_page_view"), extract_results(r.get("actions"), tok)
            log.info("  %s %s RM%-7.2f %-7d %-6d %-5.2f RM%-6.2f %-5d %-6s RM%-5.2f %-6d %-5d %-6s %s", d, "一二三四五六日"[d.weekday()],
                     sp, int(im), int(_f(r.get("reach"))), _f(r.get("frequency")), _f(r.get("cpm")), int(ck),
                     f"{ck / im * 100:.2f}%" if im else "—", sp / ck if ck else 0, int(lpv), int(reg),
                     f"{reg / lpv * 100:.0f}%" if lpv else "—", f"RM{sp / reg:.0f}" if reg else "—")
    # hourly: today, and past 7 days' registrations by hour
    hb = "hourly_stats_aggregated_by_advertiser_time_zone"
    for label, lo, hi in (("今天", today, today), ("过去 7 天（不含今天）", today - dt.timedelta(days=7), today - dt.timedelta(days=1))):
        agg = defaultdict(lambda: [0.0, 0.0, 0.0])
        for r in g._get_all(f"{HK}/insights", {"level": "account", "limit": 500, "filtering": filt, "breakdowns": hb,
                                                "fields": "spend,inline_link_clicks,actions",
                                                "time_range": json.dumps({"since": lo.isoformat(), "until": hi.isoformat()})}):
            h = int((r.get(hb) or "00")[:2])
            a = agg[h]; a[0] += _f(r.get("spend")); a[1] += _f(r.get("inline_link_clicks")); a[2] += extract_results(r.get("actions"), tok)
        log.info("═" * 120)
        log.info("%s 每小时（两支合计，马来西亚时间）：小时 · 花费 · 点击 · 报名", label)
        tot = [0.0, 0.0, 0.0]
        for h in range(24):
            if h in agg:
                a = agg[h]; tot = [tot[i] + a[i] for i in range(3)]
                log.info("  %02d:00  RM%-7.2f %-4d %d   累计 RM%.2f · %d 报名", h, a[0], int(a[1]), int(a[2]), tot[0], int(tot[2]))
    final_summary(log, "why today · read-only")


if __name__ == "__main__":
    main()
