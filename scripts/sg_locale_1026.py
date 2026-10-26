"""Is the Chinese-language lock shrinking SG? (read-only, 26 Oct)

Operator: Stock Bloom's AI suggests English + Chinese (all) instead of the Chinese-UI lock — should
Martin try? Martin's own evidence, no writes (MY read only):
  1. last 30 days, [SG] campaigns per account: reach, impressions, frequency, CPM; MY for contrast
  2. last 365 days, every SG ad set grouped by its language setting (Chinese locales only / other /
     none): spend, registrations, CPL, SG sales whose UTM campaign + ad set match the ad set
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

SG_ACCTS = [("SG老", "act_1024930575770087"), ("HK", "act_1179668409969241")]
MY = ("MY", "act_1011719073600566")
ZH = {20, 21, 22}  # Meta locale ids: Chinese (Simplified), Chinese (Hong Kong), Chinese (Taiwan)


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _mkt(c):
    c = cpa.norm(c)
    return "SG" if ("[sg]" in c or "martin-sg" in c or "martin sg" in c) else "MY" if ("[my]" in c or "martin-my" in c or "martin my" in c) else ""


def lang(t):
    loc = set((t or {}).get("locales") or [])
    if not loc:
        return "不锁语言"
    return "只锁中文" if loc <= ZH else "锁了其他语言组合 " + ",".join(map(str, sorted(loc)))


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    tok = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d30 = json.dumps({"since": (today - dt.timedelta(days=30)).isoformat(), "until": today.isoformat()})
    d365 = json.dumps({"since": (today - dt.timedelta(days=365)).isoformat(), "until": today.isoformat()})

    log.info("1. 最近 30 天（%s 起）触及", today - dt.timedelta(days=30))
    for label, acct, mk in [(a, b, "[SG]") for a, b in SG_ACCTS] + [(MY[0], MY[1], "[MY]")]:
        rows = list(g._get_all(f"{acct}/insights", {"level": "account", "time_range": d30,
                    "filtering": json.dumps([{"field": "campaign.name", "operator": "CONTAIN", "value": mk}]),
                    "fields": "spend,impressions,reach,frequency,cpm,actions"}))
        for r in rows:
            sp, ld = _f(r.get("spend")), extract_results(r.get("actions"), tok)
            log.info("  %-4s %s campaign · 花 RM%.2f · 曝光 %d · 触及 %d 人 · 每人 %.2f 次 · 每千次曝光 RM%.2f · %d 报名 · CPL %s",
                     label, mk, sp, int(_f(r.get("impressions"))), int(_f(r.get("reach"))), _f(r.get("frequency")),
                     _f(r.get("cpm")), int(ld), f"RM{sp / ld:.2f}" if ld else "—")
        if not rows:
            log.info("  %-4s %s campaign · 30 天没有花费", label, mk)

    sales, _c, _h = cpa.parse_sales(SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab),
                                    s.cpa.price_myr)
    cut = today - dt.timedelta(days=365)
    sold = defaultdict(int)
    for x in sales:
        if x.date and x.date >= cut and _mkt(x.campaign) == "SG":
            sold[(cpa.ad_key(x.campaign), cpa.ad_key(x.adset))] += 1

    log.info("  （成交表 SG 365 天共 %d 单，其中 UTM campaign + ad set 都有的 %d 单）",
             sum(1 for x in sales if x.date and x.date >= cut and _mkt(x.campaign) == "SG"), sum(sold.values()))
    log.info("═" * 110)
    log.info("2. 最近 365 天 SG ad set 按语言设定分组（成交 = 成交表 UTM campaign + ad set 对得上的）")
    grp = defaultdict(lambda: [0, 0.0, 0.0, 0, 0.0])  # ad sets, spend, regs, sales, reach-weighted cpm num
    examples = defaultdict(list)
    seen = defaultdict(set)  # a sale key counts once per group (same-named ad sets share a key)
    for label, acct in SG_ACCTS:
        tgt = {a["id"]: a for a in g._get_all(f"{acct}/adsets", {"fields": "id,name,targeting", "limit": 500})}
        for r in g._get_all(f"{acct}/insights", {"level": "adset", "limit": 500, "time_range": d365,
                                                  "fields": "adset_id,adset_name,campaign_name,spend,impressions,actions"}):
            if _mkt(r.get("campaign_name") or "") != "SG":
                continue
            a = tgt.get(r["adset_id"]) or {}
            k = lang(a.get("targeting"))
            sp, ld = _f(r.get("spend")), extract_results(r.get("actions"), tok)
            key = (cpa.ad_key(r.get("campaign_name") or ""), cpa.ad_key(r.get("adset_name") or ""))
            n = sold.get(key, 0)
            gr = grp[k]; gr[0] += 1; gr[1] += sp; gr[2] += ld; gr[4] += _f(r.get("impressions"))
            if key not in seen[k]:
                seen[k].add(key); gr[3] += n
            if k != "只锁中文" and sp >= 50:
                examples[k].append((sp, f"{label} {r['adset_id']} {(r.get('adset_name') or '')[:30]} | {(r.get('campaign_name') or '')[:50]} · RM{sp:.0f} · {int(ld)} 报名 · {n} 单"))
    for k, (na, sp, ld, n, im) in sorted(grp.items(), key=lambda kv: -kv[1][1]):
        log.info("  %-14s %4d 个 ad set · 花 RM%.0f · 曝光 %d · 每千次曝光 RM%.2f · %d 报名 · CPL %s · %d 单 · 每单 %s", k, na, sp, int(im),
                 sp / im * 1000 if im else 0, int(ld), f"RM{sp / ld:.2f}" if ld else "—", n, f"RM{sp / n:.0f}" if n else "—")
    for k, ex in examples.items():
        log.info("  ── %s 花费最多的 ad set：", k)
        for _, line in sorted(ex, reverse=True)[:8]:
            log.info("     %s", line)
    final_summary(log, "sg locale check · read-only")


if __name__ == "__main__":
    main()
