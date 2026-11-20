"""Read-only: candidate creatives for a new SG test (operator 20 Nov 「6 个近期跑到不错的，有成交的，低 CPL 的旧素材 &
新视频…给我 existing post id」).

For each ad id in ADBOT_AD_IDS (SG老户 or HK): account, campaign › ad set › ad, status, existing post id
(effective_object_story_id), lifetime and 60-day spend, Meta registrations, Register-tab registrations (UTM campaign +
ad set + ad), CPL on the larger of the two, own sales (Paid row UTM or the buyer's Register registration,
cpa.sale_utms) all time / 60 days with dates, CPA, ROAS, first / last day with spend and Meta registrations in the
7 days before the last spend day (rule 3). Same-named copies on the other account are flagged. No writes.
"""
from __future__ import annotations

import datetime as dt
import os
from collections import defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

ACCTS = {"1024930575770087": "SG老户", "1179668409969241": "HK"}


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def key3(c, s, a):
    return cpa.ad_key(c), cpa.ad_key(s), cpa.ad_key(a)


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    tok = result_action_type(s.meta.conversion_event)
    price = s.cpa.price_myr
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d60 = today - dt.timedelta(days=60)
    ids = [x.strip() for x in (os.environ.get("ADBOT_AD_IDS") or "").split(",") if x.strip()]

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

    # same-name copies across both accounts
    seen = defaultdict(set)
    for acct, label in ACCTS.items():
        for a in g._get_all(f"act_{acct}/ads", {"fields": "name,campaign{name},adset{name}", "limit": 500}):
            seen[key3((a.get("campaign") or {}).get("name") or "", (a.get("adset") or {}).get("name") or "",
                      a.get("name") or "")].add(label)

    log.info("读数 %s SGT · 60 天窗口 %s 之后 · %d 支", today, d60, len(ids))
    for aid in ids:
        try:
            a = g.get_object(aid, "name,account_id,status,effective_status,campaign{name},adset{name,daily_budget},"
                                  "creative{effective_object_story_id,object_story_id,title}")
        except Exception as exc:  # noqa: BLE001
            log.info("   ad %s 读不到：%s", aid, str(exc)[:100])
            continue
        c, st, cr = a.get("campaign") or {}, a.get("adset") or {}, a.get("creative") or {}
        k = key3(c.get("name") or "", st.get("name") or "", a.get("name") or "")
        try:
            days = sorted((dt.date.fromisoformat(r["date_start"]), _f(r.get("spend")), extract_results(r.get("actions"), tok))
                          for r in g._get_all(f"{aid}/insights", {"date_preset": "maximum", "time_increment": 1,
                                                                  "fields": "spend,actions", "limit": 500})
                          if _f(r.get("spend")) > 0)
        except Exception as exc:  # noqa: BLE001
            log.info("   ad %s insights 读不到：%s", aid, str(exc)[:100])
            days = []
        first = days[0][0] if days else None
        last = days[-1][0] if days else None
        sp = sum(d[1] for d in days)
        meta = sum(d[2] for d in days)
        sp60 = sum(d[1] for d in days if d[0] > d60)
        meta60 = sum(d[2] for d in days if d[0] > d60)
        pre7 = sum(d[2] for d in days if last and last - dt.timedelta(days=7) < d[0] <= last)
        rg = [d for d in reg_dates.get(k, []) if first and d >= first]
        rg60 = sum(1 for d in rg if d > d60)
        sd = sorted(d for d in sale_dates.get(k, []) if d)
        n60 = sum(1 for d in sd if d > d60)
        lead, lead60 = max(meta, len(rg)), max(meta60, rg60)
        copies = sorted(seen.get(k, set()))
        log.info("═" * 100)
        log.info("%s · %s › %s › ad %s %r [%s/%s] · ad set RM%d", ACCTS.get(str(a.get("account_id")), a.get("account_id")),
                 c.get("name"), st.get("name"), aid, a.get("name"), a.get("status"), a.get("effective_status"),
                 int(_f(st.get("daily_budget"))) // 100)
        log.info("   post %s · 标题 %s", cr.get("effective_object_story_id") or cr.get("object_story_id"), cr.get("title") or "—")
        log.info("   全期 %s ~ %s · 花 RM%.2f · Meta 报名 %d · 报名表 %d · CPL %s", first, last, sp, meta, len(rg),
                 f"RM{sp / lead:.2f}" if lead else "—")
        log.info("   60 天 · 花 RM%.2f · 报名 %d / %d · CPL %s · 自己成交 %d · CPA %s · ROAS %.2f", sp60, meta60, rg60,
                 f"RM{sp60 / lead60:.2f}" if lead60 else "—", n60, f"RM{sp60 / n60:.2f}" if n60 else "—",
                 n60 * price / sp60 if sp60 else 0.0)
        log.info("   全期成交 %d（%s）· 停之前 7 天 Meta 报名 %d · 同名副本在 %s", len(sd), ",".join(map(str, sd)) or "—",
                 pre7, "/".join(copies) or "—")
    final_summary(log, f"{len(ids)} 支读完（只读）")


if __name__ == "__main__":
    main()
