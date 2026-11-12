"""MAR Video 5：林書豪story in MY / HK / SG老户 (read-only, 12 Nov).

Operator 12 Nov: the webinar's 3 sales are paid-sheet rows 1326–1328; 1326 and 1327 carry the MY UTM
「[MY] 儿童长高方程式 | Parents 3-17 + Engaged | 老赢家回炉 | 1-4-4 | OCT 17 · MAR Video 5：林書豪story」, 1328 is
IG bio. Rule 4: look at the creative in all three accounts before any call. For every ad whose name holds
林書豪 on MY act_1011719073600566 (read only), HK, SG老户: status, campaign, lifetime / last-30-day / 11/5–11/10
spend and registrations, last day it spent, the 7 days before that (rule 3); the ad set's countries for the
MY ads; paid-sheet sales per UTM campaign for this ad name (all dates, last 60 days). No names / phones /
emails. No writes. MY is read only.
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

ACCTS = [("MY", "act_1011719073600566"), ("HK", "act_1179668409969241"), ("SG老户", "act_1024930575770087")]
KEY = cpa.ad_key("MAR Video 5：林書豪story")


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def regs(actions, tok):
    a = extract_results(actions, tok)
    cr = sum(_f(x.get("value")) for x in actions or [] if x.get("action_type") == "complete_registration")
    return a, cr


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    tok = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    vals = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(vals, s.cpa.price_myr)
    by = defaultdict(list)
    for x in sales:
        if cpa.ad_key(x.ad) == KEY:
            by[x.campaign].append(x.date)
    log.info("成交表上 ad = MAR Video 5：林書豪story 的成交（按 UTM campaign）：")
    for c, ds in sorted(by.items(), key=lambda kv: -len(kv[1])):
        d60 = [d for d in ds if d and (today - d).days <= 60]
        log.info("   %d 笔（60 天内 %d）· 最后 %s · campaign %r", len(ds), len(d60), max([d for d in ds if d], default=None),
                 c[:90])
    flt = json.dumps([{"field": "ad.name", "operator": "CONTAIN", "value": "林書豪"}])
    tot = defaultdict(lambda: [0.0, 0.0])
    for label, acct in ACCTS:
        life = g._get_all(f"{acct}/insights", {"level": "ad", "limit": 200, "date_preset": "maximum", "filtering": flt,
                                               "fields": "ad_id,ad_name,campaign_name,adset_id,spend,actions,date_stop"})
        if not life:
            log.info("%s：没有名字带 林書豪 的广告花过钱", label)
            continue
        ids = [r["ad_id"] for r in life]
        idf = json.dumps([{"field": "ad.id", "operator": "IN", "value": ids}])
        l30 = {r["ad_id"]: r for r in g._get_all(f"{acct}/insights", {"level": "ad", "limit": 200, "date_preset": "last_30d",
                                                                      "filtering": idf, "fields": "ad_id,spend,actions"})}
        cyc = {r["ad_id"]: r for r in g._get_all(f"{acct}/insights", {
            "level": "ad", "limit": 200, "filtering": idf, "fields": "ad_id,spend,actions",
            "time_range": json.dumps({"since": "2026-11-05", "until": "2026-11-10"})})}
        geo_seen = {}
        for r in sorted(life, key=lambda r: -_f(r.get("spend"))):
            aid = r["ad_id"]
            o = g.get_object(aid, "effective_status,adset{id,targeting{geo_locations}}")
            geo = ((o.get("adset") or {}).get("targeting") or {}).get("geo_locations") or {}
            sp, (rg, cr) = _f(r.get("spend")), regs(r.get("actions"), tok)
            tot[label][0] += sp
            tot[label][1] += rg
            a30, c5 = l30.get(aid, {}), cyc.get(aid, {})
            log.info("%s ad %s %r · %s · campaign %r", label, aid, r.get("ad_name", "")[:40], o.get("effective_status"),
                     (r.get("campaign_name") or "")[:80])
            log.info("    全期花 RM%.2f 报名 %.0f（complete_registration %.0f）· 30 天花 RM%.2f 报名 %.0f · 11/5–11/10 花 RM%.2f 报名 %.0f"
                     " · 最后有数据 %s · 国家 %s", sp, rg, cr, _f(a30.get("spend")), regs(a30.get("actions"), tok)[0],
                     _f(c5.get("spend")), regs(c5.get("actions"), tok)[0], r.get("date_stop"),
                     geo.get("countries") or [x.get("country") for x in geo.get("regions") or []] or geo)
    final_summary(log, " · ".join(f"{k} 全期花 RM{v[0]:.2f} 报名 {v[1]:.0f}" for k, v in tot.items())
                  + f" · 成交表上这支片 {sum(len(v) for v in by.values())} 笔")


if __name__ == "__main__":
    main()
