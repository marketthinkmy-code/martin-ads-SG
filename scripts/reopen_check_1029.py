"""Where are the ads behind the 60-day SG sales, and can they be reopened? (read-only, 29 Oct)

Operator 29 Oct 「A」: reopen the 60-day sellers that are not running. For every SG sale in the last
60 days (paid sheet, [SG] UTM campaign), find the Meta ad it came from on SG old / HK: same UTM
campaign + ad set + ad (keys folded by cpa.ad_key; a sheet campaign value cut short by the sheet
is matched as a prefix of the Meta name). Per ad: account, campaign / ad set / ad ids, names and
statuses, ad set budget, own sales (60 days / all time), spend + registrations (60 days / all time),
own CPA, last day it spent, and the last 7 delivery days' registrations (rule 3). No writes.
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

SG_ACCTS = [("SG老户", "act_1024930575770087"), ("HK", "act_1179668409969241")]
AD_F = ("id,name,effective_status,configured_status,created_time,"
        "adset{id,name,daily_budget,effective_status},campaign{id,name,effective_status,daily_budget}")


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
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    since = today - dt.timedelta(days=60)
    sales, _c, _h = cpa.parse_sales(SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab),
                                    s.cpa.price_myr)
    sg = [x for x in sales if "[sg]" in cpa.norm(x.campaign)]
    recent = [x for x in sg if x.date and x.date > since]
    want_ads = {cpa.ad_key(x.ad) for x in recent}

    ads = []
    for label, acct in SG_ACCTS:
        for a in g._get_all(f"{acct}/ads", {"fields": AD_F, "limit": 500}):
            if cpa.ad_key(a.get("name") or "") in want_ads:
                a["_acct"] = label
                ads.append(a)
    log.info("SG 老户 + HK 上同名广告 %d 支", len(ads))

    def keys(a):
        return (cpa.ad_key((a.get("campaign") or {}).get("name") or ""),
                cpa.ad_key((a.get("adset") or {}).get("name") or ""), cpa.ad_key(a.get("name") or ""))

    def same(sale_k, ad_k):
        c, st, d = sale_k
        return st == ad_k[1] and d == ad_k[2] and (c == ad_k[0] or (len(c) >= 12 and ad_k[0].startswith(c)))

    groups = defaultdict(list)                     # sale key -> recent sales
    for x in recent:
        groups[(cpa.ad_key(x.campaign), cpa.ad_key(x.adset), cpa.ad_key(x.ad))].append(x)

    tr60 = json.dumps({"since": since.isoformat(), "until": today.isoformat()})
    rows = []
    for k, xs in sorted(groups.items(), key=lambda kv: (cpa.ad_key(kv[1][0].ad), kv[0])):
        x0 = xs[0]
        hit = [a for a in ads if same(k, keys(a))]
        life_sales = sum(1 for y in sg if (cpa.ad_key(y.campaign), cpa.ad_key(y.adset), cpa.ad_key(y.ad)) == k)
        log.info("═" * 100)
        log.info("▌成交 %s · UTM campaign %r · ad set %r · ad %r · 60 天 %d 笔（日期 %s）· 全期 %d 笔",
                 x0.ad[:40], x0.campaign[:70], x0.adset[:40], x0.ad[:40], len(xs),
                 ", ".join(sorted(y.date.isoformat() for y in xs)), life_sales)
        if not hit:
            log.info("  ❌ SG 老户 / HK 上找不到同 campaign + ad set + ad 的广告")
            continue
        for a in hit:
            c, st = a.get("campaign") or {}, a.get("adset") or {}
            i60 = (g._get_all(f"{a['id']}/insights", {"time_range": tr60, "fields": "spend,actions"}) or [{}])[0]
            ilife = (g._get_all(f"{a['id']}/insights", {"date_preset": "maximum", "fields": "spend,actions"}) or [{}])[0]
            daily = g._get_all(f"{a['id']}/insights", {"date_preset": "maximum", "time_increment": 1,
                                                       "fields": "spend,actions,date_start"})
            spent_days = [d for d in daily if _f(d.get("spend")) > 0]
            last = spent_days[-1]["date_start"] if spent_days else None
            last7 = [d for d in spent_days
                     if last and dt.date.fromisoformat(d["date_start"]) > dt.date.fromisoformat(last) - dt.timedelta(days=7)]
            sp60, sp_life = _f(i60.get("spend")), _f(ilife.get("spend"))
            reg60, reg_life = extract_results(i60.get("actions"), tok), extract_results(ilife.get("actions"), tok)
            reg7 = sum(extract_results(d.get("actions"), tok) for d in last7)
            sp7 = sum(_f(d.get("spend")) for d in last7)
            log.info("  %s · campaign %s %r [%s · 预算 %s]", a["_acct"], c.get("id"), (c.get("name") or "")[:80],
                     c.get("effective_status"), c.get("daily_budget"))
            log.info("     ad set %s %r [%s · 日预算 RM%.0f] · ad %s %r [%s / %s] · 建于 %s",
                     st.get("id"), (st.get("name") or "")[:40], st.get("effective_status"), _f(st.get("daily_budget")) / 100,
                     a["id"], (a.get("name") or "")[:40], a.get("configured_status"), a.get("effective_status"),
                     (a.get("created_time") or "")[:10])
            log.info("     60 天：花 RM%.2f · 报名 %d · 成交 %d · CPA %s · CPL %s", sp60, reg60, len(xs),
                     f"RM{sp60 / len(xs):.0f}", f"RM{sp60 / reg60:.0f}" if reg60 else "—")
            log.info("     全期：花 RM%.2f · 报名 %d · 成交 %d · CPA %s · 最后花钱 %s · 最后 7 个投放日 花 RM%.2f 报名 %d",
                     sp_life, reg_life, life_sales, f"RM{sp_life / life_sales:.0f}" if life_sales else "—",
                     last, sp7, reg7)
            rows.append((x0.ad[:30], a["_acct"], a["id"], a.get("effective_status"), len(xs), sp60))
    final_summary(log, f"60 天 SG 成交 {len(recent)} 笔 · {len(groups)} 组 campaign+ad set+ad · 对上的广告 {len(rows)} 支 · "
                       + " | ".join(f"{r[0]} {r[1]} {r[2]} {r[3]}" for r in rows))


if __name__ == "__main__":
    main()
