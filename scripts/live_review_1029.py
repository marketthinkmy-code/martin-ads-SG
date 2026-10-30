"""Keep or close? Every live ad on SG old + HK, judged on sales (read-only, 29 Oct).

Operator: 目前的广告有什么值得留、关的吗？ Per live ad: own sales (UTM campaign + ad set + ad) in 60 days
and all time, spend / registrations in 60 days and all time (one insights call per window, filtered to the
live ad ids, to stay under Meta's per-account call limit), own CPA and its band (cpa.target 740 / healthy 860 / max acceptable 1,040 / hard
stop 1,300), spend since Thursday; the creative across accounts (rule 4): SG sales of the ad name
(paid sheet, any campaign) and MY sales of the same
ad name (MY spend is not read: Meta refuses ad.name filters). No writes.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict

from adbot import cpa
import sys

from adbot.clients.graph import GraphError, TransientGraphError
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type, _week_start_thursday
from adbot.settings import load_settings

ACCTS = [("SG老户", "act_1024930575770087"), ("HK", "act_1179668409969241")]
MY = "act_1011719073600566"
DEAD = ("PAUSED", "ADSET_PAUSED", "CAMPAIGN_PAUSED", "ARCHIVED", "DELETED")


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def band(v, c):
    if v is None:
        return "零成交"
    if v <= c.target_myr:
        return "≤目标"
    if v <= c.healthy_max_myr:
        return "健康"
    if v <= c.max_acceptable_myr:
        return "可接受"
    if v <= c.hard_stop_myr:
        return "暂停候选"
    return "超硬停线"


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    tok = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d60 = today - dt.timedelta(days=60)
    thu = _week_start_thursday(today)

    sales, _c, _h = cpa.parse_sales(SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab),
                                    s.cpa.price_myr)
    own_all, own60 = defaultdict(int), defaultdict(int)
    sg_name, my_name = defaultdict(int), defaultdict(int)
    for x in sales:
        k = (cpa.ad_key(x.campaign), cpa.ad_key(x.adset), cpa.ad_key(x.ad))
        own_all[k] += 1
        if x.date and x.date > d60:
            own60[k] += 1
        c = cpa.norm(x.campaign)
        if "[sg]" in c or "martin-sg" in c:
            sg_name[cpa.ad_key(x.ad)] += 1
        elif "[my]" in c or "martin-my" in c:
            my_name[cpa.ad_key(x.ad)] += 1

    LIVE = ["ACTIVE", "IN_PROCESS", "PENDING_REVIEW", "WITH_ISSUES", "PREAPPROVED"]

    def by_ad(acct, ids, **when):                     # one insights call per window, filtered to the live ads
        out = {}
        for r in g._get_all(f"{acct}/insights", {"level": "ad", "limit": 200, "fields": "ad_id,spend,actions",
                                                 "filtering": json.dumps([{"field": "ad.id", "operator": "IN", "value": ids}]),
                                                 **when}):
            out[r["ad_id"]] = (_f(r.get("spend")), extract_results(r.get("actions"), tok))
        return out

    def tr(a, b):
        return {"time_range": json.dumps({"since": a.isoformat(), "until": b.isoformat()})}

    rows = []
    for label, acct in ACCTS:
        ads = [a for a in g._get_all(f"{acct}/ads", {
            "fields": "id,name,effective_status,created_time,campaign{name,effective_status},adset{name}", "limit": 200,
            "filtering": json.dumps([{"field": "effective_status", "operator": "IN", "value": LIVE}])})
            if a.get("effective_status") not in DEAD]
        ids = [a["id"] for a in ads]
        if not ids:
            continue
        life = by_ad(acct, ids, date_preset="maximum")
        s60 = by_ad(acct, ids, **tr(d60, today))
        wk = by_ad(acct, ids, **tr(thu, today))
        for a in ads:
            name, st = a.get("name") or "", (a.get("adset") or {}).get("name") or ""
            cname = (a.get("campaign") or {}).get("name") or ""
            k = (cpa.ad_key(cname), cpa.ad_key(st), cpa.ad_key(name))
            (life_sp, life_reg), (sp60, rg60), (spw, rgw) = (life.get(a["id"], (0.0, 0.0)), s60.get(a["id"], (0.0, 0.0)),
                                                              wk.get(a["id"], (0.0, 0.0)))
            rows.append({"acct": label, "id": a["id"], "name": name, "campaign": cname, "adset": st,
                         "created": (a.get("created_time") or "")[:10], "life_sp": life_sp, "life_reg": life_reg,
                         "sp60": sp60, "rg60": rg60, "spw": spw, "rgw": rgw, "own_all": own_all.get(k, 0),
                         "own60": own60.get(k, 0), "sg_name": sg_name.get(cpa.ad_key(name), 0),
                         "my_name": my_name.get(cpa.ad_key(name), 0)})

    cfg = s.cpa
    for r in sorted(rows, key=lambda r: (r["own_all"] == 0, -(r["own_all"]), r["acct"])):
        cpa_life = r["life_sp"] / r["own_all"] if r["own_all"] else None
        log.info("%s ad %s %r · campaign %r · ad set %r · 建于 %s", r["acct"], r["id"], r["name"][:40], r["campaign"][:60],
                 r["adset"][:30], r["created"])
        log.info("    自己的成交 全期 %d / 60 天 %d · 全期花 RM%.2f 报名 %d · CPA %s（%s）· CPL %s · 60 天花 RM%.2f 报名 %d · 本周花 RM%.2f 报名 %d",
                 r["own_all"], r["own60"], r["life_sp"], r["life_reg"], f"RM{cpa_life:.0f}" if cpa_life is not None else "—",
                 band(cpa_life, cfg), f"RM{r['life_sp'] / r['life_reg']:.0f}" if r["life_reg"] else "—", r["sp60"], r["rg60"],
                 r["spw"], r["rgw"])
        log.info("    同名片（规矩 4）：SG 成交表 %d 笔 · MY 成交表 %d 笔", r["sg_name"], r["my_name"])
        nxt = r["life_sp"] / (r["own_all"] + 1)        # CPA if the next sale came now (30 Oct test)
        log.info("    ▶ 判定：现在 CPA %s · 如果下一单现在来 CPA RM%.0f（%s）",
                 f"RM{cpa_life:.0f}" if cpa_life is not None else "—（零成交）", nxt, band(nxt, cfg))
    n0 = [r for r in rows if not r["own_all"]]
    final_summary(log, f"在跑 {len(rows)} 支 · 有自己成交 {len(rows) - len(n0)} · 零自己成交 {len(n0)} · "
                       f"零成交的全期花 RM{sum(r['life_sp'] for r in n0):.2f} 报名 {sum(r['life_reg'] for r in n0):.0f}")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min.", str(exc)[:200])
        sys.exit(75)
