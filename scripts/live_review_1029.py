"""Keep or close? Every live ad on SG old + HK, judged on sales (read-only, 29 Oct).

Operator: 目前的广告有什么值得留、关的吗？ Per live ad: own sales (UTM campaign + ad set + ad) in 60 days
and all time, spend / registrations in 60 days and all time (all time = 30-day chunks since the ad
was created), own CPA and its band (cpa.target 740 / healthy 860 / max acceptable 1,040 / hard
stop 1,300), spend since Thursday; the creative across accounts (rule 4): SG sales of the ad name
(paid sheet, any campaign) and MY sales + MY 60-day spend / registrations of the same ad name. No writes.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict

from adbot import cpa
from adbot.clients.graph import GraphError
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

    def ins(ad_id, since, until):
        r = (g._get_all(f"{ad_id}/insights", {"fields": "spend,actions",
                                              "time_range": json.dumps({"since": since.isoformat(), "until": until.isoformat()})})
             or [{}])[0]
        return _f(r.get("spend")), extract_results(r.get("actions"), tok)

    rows = []
    for label, acct in ACCTS:
        for c in g._get_all(f"{acct}/campaigns", {"fields": "id,name,effective_status", "limit": 300}):
            if c.get("effective_status") != "ACTIVE":
                continue
            for a in g._get_all(f"{c['id']}/ads", {"fields": "id,name,effective_status,created_time,adset{name}", "limit": 200}):
                if a.get("effective_status") in DEAD:
                    continue
                name, st = a.get("name") or "", (a.get("adset") or {}).get("name") or ""
                k = (cpa.ad_key(c.get("name") or ""), cpa.ad_key(st), cpa.ad_key(name))
                created = dt.date.fromisoformat((a.get("created_time") or today.isoformat())[:10])
                life_sp = life_reg = 0.0
                start = created
                while start <= today:                       # all time in 30-day chunks
                    end = min(start + dt.timedelta(days=29), today)
                    sp, rg = ins(a["id"], start, end)
                    life_sp, life_reg = life_sp + sp, life_reg + rg
                    start = end + dt.timedelta(days=1)
                sp60, rg60 = ins(a["id"], max(d60, created), today)
                spw, rgw = ins(a["id"], thu, today)
                rows.append({"acct": label, "id": a["id"], "name": name, "campaign": c.get("name") or "", "adset": st,
                             "created": created, "life_sp": life_sp, "life_reg": life_reg, "sp60": sp60, "rg60": rg60,
                             "spw": spw, "rgw": rgw, "own_all": own_all.get(k, 0), "own60": own60.get(k, 0),
                             "sg_name": sg_name.get(cpa.ad_key(name), 0), "my_name": my_name.get(cpa.ad_key(name), 0)})

    my60 = {}
    for nm in sorted({r["name"] for r in rows}):
        try:
            got = g._get_all(f"{MY}/insights", {"level": "account", "fields": "spend,actions",
                                                 "time_range": json.dumps({"since": d60.isoformat(), "until": today.isoformat()}),
                                                 "filtering": json.dumps([{"field": "ad.name", "operator": "EQUAL", "value": nm}])})
            r = (got or [{}])[0]
            my60[nm] = (_f(r.get("spend")), extract_results(r.get("actions"), tok))
        except GraphError as exc:
            my60[nm] = None
            log.info("MY %r 读不到：%s", nm, str(exc)[:80])

    cfg = s.cpa
    for r in sorted(rows, key=lambda r: (r["own_all"] == 0, -(r["own_all"]), r["acct"])):
        cpa_life = r["life_sp"] / r["own_all"] if r["own_all"] else None
        m = my60.get(r["name"])
        log.info("%s ad %s %r · campaign %r · ad set %r · 建于 %s", r["acct"], r["id"], r["name"][:40], r["campaign"][:60],
                 r["adset"][:30], r["created"])
        log.info("    自己的成交 全期 %d / 60 天 %d · 全期花 RM%.2f 报名 %d · CPA %s（%s）· CPL %s · 60 天花 RM%.2f 报名 %d · 本周花 RM%.2f 报名 %d",
                 r["own_all"], r["own60"], r["life_sp"], r["life_reg"], f"RM{cpa_life:.0f}" if cpa_life is not None else "—",
                 band(cpa_life, cfg), f"RM{r['life_sp'] / r['life_reg']:.0f}" if r["life_reg"] else "—", r["sp60"], r["rg60"],
                 r["spw"], r["rgw"])
        log.info("    同名片（规矩 4）：SG 成交表 %d 笔 · MY 成交表 %d 笔 · MY 60 天 %s", r["sg_name"], r["my_name"],
                 f"花 RM{m[0]:.2f} 报名 {m[1]:.0f}" if m else "读不到")
    n0 = [r for r in rows if not r["own_all"]]
    final_summary(log, f"在跑 {len(rows)} 支 · 有自己成交 {len(rows) - len(n0)} · 零自己成交 {len(n0)} · "
                       f"零成交的全期花 RM{sum(r['life_sp'] for r in n0):.2f} 报名 {sum(r['life_reg'] for r in n0):.0f}")


if __name__ == "__main__":
    main()
