"""Read-only: lifetime results of chosen creatives on SG老户 + HK, per ad and per weekly cycle.

Operator 19 Nov: 「美国跑到便宜、出圈的广告，可以跑在新加坡。before that，先分析给我新加坡这几个广告，
从开始跑到现在的成绩如何」 (US screenshot: Hook 1 吃完就上厕所, Video 7 14岁, Video 8 我跟你说,
Video 6 具体数字目标, Video 5 饭桌生活细节场景).

ADBOT_GROUPS = "label=k1|k2;label2=k3" (substrings matched on the folded ad name; default below).
Per ad: first / last day with spend, lifetime spend, Meta registrations, Register-tab registrations
(UTM campaign + ad set + ad), CPL on the larger of the two, link CTR, own sales (Paid row UTM or the
buyer's Register registration, cpa.sale_utms) all time and 60 days, CPA, ROAS. Then per cycle
(Thursday start) per ad, and a total per creative. No writes.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from collections import Counter, defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import _week_start_thursday, extract_results, result_action_type
from adbot.settings import load_settings

ACCTS = [("SG老户", "act_1024930575770087"), ("HK", "act_1179668409969241")]
if os.environ.get("ADBOT_INCLUDE_MY") == "1":   # rule 4: read MY too before judging a film (read-only)
    ACCTS.append(("MY", "act_1011719073600566"))
DEFAULT = ("饭桌=饭桌|飯桌;我跟你说=我跟你说|我跟你說;具体数字目标=具体数字|具體數字;"
           "吃完就上厕所=吃完就|上厕所|上廁所;14岁=14岁|14歲")


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def key3(c, s, a):
    return cpa.ad_key(c), cpa.ad_key(s), cpa.ad_key(a)


def groups():
    out = []
    for part in (os.environ.get("ADBOT_GROUPS") or DEFAULT).split(";"):
        if "=" in part:
            label, keys = part.split("=", 1)
            out.append((label.strip(), [cpa.ad_key(k) for k in keys.split("|") if k.strip()]))
    return out


def cpl(sp, n):
    return f"RM{sp / n:.2f}" if n else ("—" if sp == 0 else "0 报名")


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    tok = result_action_type(s.meta.conversion_event)
    price = s.cpa.price_myr
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d60 = today - dt.timedelta(days=60)
    grp = groups()

    sh = SheetsClient(s.secrets.google_sa_json)
    sales, _c, _h = cpa.parse_sales(sh.read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab), price)
    regs, _c2, _h2 = cpa.parse_sales(sh.read_tab(s.cpa.spreadsheet_id, s.cpa.register_tab), 0.0)
    reg_dates = defaultdict(list)
    for r in regs:
        if r.campaign and r.adset and r.ad and r.date:
            reg_dates[key3(r.campaign, r.adset, r.ad)].append(r.date)
    sale_dates = defaultdict(list)
    for x in sales:
        for k in {key3(*u) for u in cpa.sale_utms(x, regs)}:
            sale_dates[k].append(x.date)
    log.info("读数 %s SGT · 报名表 %d 行 · 成交表 %d 行 · 分组 %s", today, len(regs), len(sales),
             [lb for lb, _ in grp])

    ads = []
    for label, acct in ACCTS:
        for a in g._get_all(f"{acct}/ads", {"fields": "id,name,effective_status,created_time,"
                                                      "campaign{name},adset{name}", "limit": 500}):
            nk = cpa.ad_key(a.get("name") or "")
            hit = next((lb for lb, ks in grp if any(k and k in nk for k in ks)), None)
            if hit:
                a["_acct"], a["_acct_id"], a["_grp"] = label, acct, hit
                ads.append(a)
    log.info("名字对上的广告 %d 支", len(ads))

    daily = defaultdict(list)    # ad id -> [(date, spend, meta, impressions, link clicks)]
    for label, acct in ACCTS:
        ids = [a["id"] for a in ads if a["_acct_id"] == acct]
        for i in range(0, len(ids), 50):
            for r in g._get_all(f"{acct}/insights", {
                    "level": "ad", "limit": 500, "date_preset": "maximum", "time_increment": 1,
                    "fields": "ad_id,spend,actions,impressions,inline_link_clicks",
                    "filtering": json.dumps([{"field": "ad.id", "operator": "IN", "value": ids[i:i + 50]}])}):
                daily[r["ad_id"]].append((dt.date.fromisoformat(r["date_start"]), _f(r.get("spend")),
                                          extract_results(r.get("actions"), tok), _f(r.get("impressions")),
                                          _f(r.get("inline_link_clicks"))))

    rows, by_grp = [], defaultdict(lambda: Counter())
    for a in ads:
        days = sorted(d for d in daily.get(a["id"], []) if d[1] > 0)
        if not days:
            continue
        c, st = (a.get("campaign") or {}).get("name") or "", (a.get("adset") or {}).get("name") or ""
        k = key3(c, st, a.get("name") or "")
        first, last = days[0][0], days[-1][0]
        sp = sum(d[1] for d in days)
        meta = sum(d[2] for d in days)
        imp = sum(d[3] for d in days)
        clk = sum(d[4] for d in days)
        rg = sum(1 for d in reg_dates.get(k, []) if d >= first)
        sd = sorted(d for d in sale_dates.get(k, []) if d)
        n_all, n60 = len(sd), sum(1 for d in sd if d > d60)
        lead = max(meta, rg)
        rows.append((a, c, st, k, days, first, last, sp, meta, rg, lead, imp, clk, n_all, n60, sd))
        t = by_grp[a["_grp"]]
        t["ads"] += 1
        t["sp"] += sp
        t["meta"] += meta
        t["rg"] += rg
        t["lead"] += lead
        t["sales"] += n_all
        t["imp"] += imp
        t["clk"] += clk

    log.info("═" * 100)
    log.info("A. 每支广告，从开始跑到今天（报名取 Meta 和报名表较多的算 CPL）")
    for (a, c, st, k, days, first, last, sp, meta, rg, lead, imp, clk, n_all, n60, sd) in sorted(
            rows, key=lambda r: (r[0]["_grp"], -r[7])):
        ctr = f"{clk / imp * 100:.2f}%" if imp else "—"
        cpa_s = f"RM{sp / n_all:.2f}" if n_all else "—（零成交）"
        roas = n_all * price / sp if sp else 0.0
        log.info("   [%s] %s · %s › %s › ad %s %r [%s] · %s ~ %s（花钱 %d 天）· 花 RM%.2f · Meta 报名 %d · 报名表 %d"
                 " · CPL %s · 链接 CTR %s · 成交 %d（60 天 %d；%s）· CPA %s · ROAS %.2f",
                 a["_grp"], a["_acct"], c[:70], st[:40], a["id"], a.get("name"), a.get("effective_status"),
                 first, last, len(days), sp, meta, rg, cpl(sp, lead), ctr, n_all, n60,
                 ",".join(str(d) for d in sd) or "—", cpa_s, roas)

    log.info("═" * 100)
    log.info("B. 每支广告按周期（星期四起）")
    for (a, c, st, k, days, first, last, sp, meta, rg, lead, imp, clk, n_all, n60, sd) in sorted(
            rows, key=lambda r: (r[0]["_grp"], -r[7])):
        cyc = defaultdict(lambda: [0.0, 0, 0])
        for d in days:
            w = _week_start_thursday(d[0])
            cyc[w][0] += d[1]
            cyc[w][1] += d[2]
        for d in reg_dates.get(k, []):
            if d >= first:
                cyc[_week_start_thursday(d)][2] += 1
        parts = [f"{w:%m/%d}起 RM{v[0]:.2f} · {v[1]}/{v[2]} 报名 · CPL {cpl(v[0], max(v[1], v[2]))}"
                 for w, v in sorted(cyc.items())]
        log.info("   [%s] %s ad %s %r：%s", a["_grp"], a["_acct"], a["id"], a.get("name"), " ｜ ".join(parts))

    log.info("═" * 100)
    log.info("C. 每个素材合计（所有对上名字的广告加总）")
    for lb, _ in grp:
        t = by_grp.get(lb)
        if not t:
            log.info("   %s · SG老户 / HK 没有花过钱的广告", lb)
            continue
        log.info("   %s · %d 支 · 花 RM%.2f · Meta 报名 %d · 报名表 %d · CPL %s · 链接 CTR %s · 成交 %d · CPA %s · ROAS %.2f",
                 lb, t["ads"], t["sp"], t["meta"], t["rg"], cpl(t["sp"], t["lead"]),
                 f"{t['clk'] / t['imp'] * 100:.2f}%" if t["imp"] else "—", t["sales"],
                 f"RM{t['sp'] / t['sales']:.2f}" if t["sales"] else "—", t["sales"] * price / t["sp"] if t["sp"] else 0.0)
    final_summary(log, f"{len(rows)} 支有花钱 · 分组 {len(by_grp)}")


if __name__ == "__main__":
    main()
