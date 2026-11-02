"""Double-check: is each live ad's sale really its own, not a same-named copy's? (read-only, 2 Nov)

Operator: 确定都是自己的 campaign - ad set - ad 吗？不是副本？double confirm. For every live ad on SG old + HK
and every SG sale in the paid sheet whose UTM campaign + ad set + ad (cpa.ad_key folded) equals that
ad's names: every ad on SG old + HK with the very same three names (copies included, any status),
and for each of them spend / registrations in the 14 days up to the sale date (the buyer clicked an
ad carrying that UTM shortly before buying). Verdict per sale: only the live ad delivered -> 本广告;
another same-named ad delivered too -> 共用; the live ad did not deliver -> 不是它. No writes.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

ACCTS = [("SG老户", "act_1024930575770087"), ("HK", "act_1179668409969241")]
LIVE = ["ACTIVE", "IN_PROCESS", "PENDING_REVIEW", "WITH_ISSUES"]
WINDOW = 14


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    tok = result_action_type(s.meta.conversion_event)

    def key(c, st, a):
        return cpa.ad_key(c), cpa.ad_key(st), cpa.ad_key(a)

    all_ads = defaultdict(list)                       # 3-key -> [(acct label, acct, ad dict)]
    live = []
    for label, acct in ACCTS:
        for a in g._get_all(f"{acct}/ads", {"fields": "id,name,effective_status,created_time,campaign{name},adset{name}",
                                            "limit": 500}):
            k = key((a.get("campaign") or {}).get("name") or "", (a.get("adset") or {}).get("name") or "", a.get("name") or "")
            all_ads[k].append((label, acct, a))
            if a.get("effective_status") in LIVE:
                live.append((label, acct, a, k))
    sales, _c, _h = cpa.parse_sales(SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab),
                                    s.cpa.price_myr)
    by_key = defaultdict(list)
    for x in sales:
        by_key[key(x.campaign, x.adset, x.ad)].append(x)

    tally = defaultdict(lambda: defaultdict(int))
    for label, acct, a, k in live:
        sold = sorted(by_key.get(k, []), key=lambda x: x.date or dt.date.min)
        if not sold:
            continue
        twins = all_ads[k]
        log.info("═" * 100)
        log.info("▌%s ad %s %r · 建于 %s · 同 campaign + ad set + ad 名字的广告 %d 支：%s", label, a["id"], a.get("name"),
                 (a.get("created_time") or "")[:10], len(twins),
                 [f"{t[0]} {t[2]['id']} {t[2].get('effective_status')} 建于 {(t[2].get('created_time') or '')[:10]}" for t in twins])
        for x in sold:
            if not x.date:
                log.info("  成交（没有日期）—— 判断不了")
                tally[a["id"]]["没日期"] += 1
                continue
            since = x.date - dt.timedelta(days=WINDOW)
            delivered = []
            for t_label, t_acct, t in twins:
                rows = g._get_all(f"{t['id']}/insights", {"fields": "spend,actions",
                                                          "time_range": json.dumps({"since": since.isoformat(),
                                                                                    "until": x.date.isoformat()})})
                r = rows[0] if rows else {}
                sp, rg = _f(r.get("spend")), extract_results(r.get("actions"), tok)
                if sp > 0:
                    delivered.append((t_label, t["id"], sp, rg))
            mine = any(d[1] == a["id"] for d in delivered)
            verdict = ("本广告" if mine and len(delivered) == 1 else "共用" if mine else "不是它")
            tally[a["id"]][verdict] += 1
            log.info("  成交 %s · 成交前 %d 天有花钱的同名广告：%s → %s", x.date, WINDOW,
                     [f"{d[0]} {d[1]} RM{d[2]:.2f} 报名 {d[3]:.0f}" for d in delivered] or "没有", verdict)
    final_summary(log, " | ".join(f"{aid}: " + ", ".join(f"{k} {v}" for k, v in t.items()) for aid, t in tally.items()))


if __name__ == "__main__":
    main()
