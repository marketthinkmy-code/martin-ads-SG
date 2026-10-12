"""8 号到现在 (read-only): every campaign that spent since Thu 10/8, running OR stopped.

Operator (12 Oct): 8 号到现在哦 — the readout only lists ACTIVE campaigns, so stopped
spend (SG retests, 線下見證, 倒掉牛奶, Video 12 …) was invisible. This prints, per account,
every campaign with spend since 10/8: status, spend, registrations, CPL, link clicks,
报名率, and its ads; then account and grand totals; sales since 10/7 from the sheet.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from typing import Dict, List

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

ACCOUNTS = [("SG老", "act_1024930575770087"), ("HK", "act_1179668409969241")]
SINCE = dt.date(2026, 10, 8)
WEBINAR = dt.date(2026, 10, 7)
RUNNING = ("ACTIVE", "IN_PROCESS", "PENDING_REVIEW")


def _f(x) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _sg(campaign: str) -> bool:
    c = cpa.norm(campaign)
    return ("[sg]" in c) or ("martin-sg" in c) or ("martin sg" in c)


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    token = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    tr = json.dumps({"since": SINCE.isoformat(), "until": today.isoformat()})
    today_tr = json.dumps({"since": today.isoformat(), "until": today.isoformat()})

    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)
    new = sorted((x.date.isoformat(), x.ad[:30]) for x in sales if x.date and x.date >= WEBINAR and _sg(x.campaign))
    log.info("成交表：10/7 直播起 SG 新单 %d 笔 %s", len(new), new)

    grand = [0.0, 0.0, 0.0]
    for label, acct in ACCOUNTS:
        camps = {c["id"]: c for c in g._get_all(f"{acct}/campaigns",
                 {"fields": "id,name,status,effective_status,daily_budget", "limit": 300})}
        rows = g._get_all(f"{acct}/insights", {"level": "campaign", "limit": 500, "time_range": tr,
                                               "fields": "campaign_id,campaign_name,spend,actions,inline_link_clicks"})
        today_rows = {r.get("campaign_id"): r for r in g._get_all(
            f"{acct}/insights", {"level": "campaign", "limit": 500, "time_range": today_tr,
                                 "fields": "campaign_id,spend,actions"})}
        ad_rows = defaultdict(list)
        for r in g._get_all(f"{acct}/insights", {"level": "ad", "limit": 500, "time_range": tr,
                                                 "fields": "campaign_id,ad_id,ad_name,spend,actions,inline_link_clicks"}):
            ad_rows[r.get("campaign_id")].append(r)
        ad_status = {a["id"]: a.get("effective_status") for a in g._get_all(
            f"{acct}/ads", {"fields": "id,effective_status", "limit": 800,
                            "effective_status": json.dumps(["ACTIVE", "PAUSED", "ARCHIVED", "PENDING_REVIEW", "DISAPPROVED",
                                                            "PREAPPROVED", "PENDING_BILLING_INFO", "CAMPAIGN_PAUSED",
                                                            "ADSET_PAUSED", "IN_PROCESS", "WITH_ISSUES"])})}
        tot = [0.0, 0.0, 0.0]
        log.info("═" * 110)
        log.info("【%s】%s · 10/8 起有花费的 campaign", label, acct)
        for r in sorted(rows, key=lambda x: -_f(x.get("spend"))):
            sp, ld, ck = _f(r.get("spend")), extract_results(r.get("actions"), token), _f(r.get("inline_link_clicks"))
            if sp < 1:
                continue
            c = camps.get(r.get("campaign_id"), {})
            tr_ = today_rows.get(r.get("campaign_id"), {})
            tsp, tld = _f(tr_.get("spend")), extract_results(tr_.get("actions"), token)
            on = c.get("effective_status") in RUNNING
            log.info("▌%s %-62s RM%-8.2f %2dL %-8s 报名率 %-4s 今 RM%.0f/%dL", "▶️" if on else "⏸",
                     (r.get("campaign_name") or "")[:62], sp, int(ld), f"CPL {sp / ld:,.0f}" if ld else "CPL —",
                     f"{ld / ck * 100:.0f}%" if ck else "—", tsp, int(tld))
            for a in sorted(ad_rows.get(r.get("campaign_id"), []), key=lambda x: -_f(x.get("spend"))):
                asp, ald = _f(a.get("spend")), extract_results(a.get("actions"), token)
                if asp < 1:
                    continue
                st = ad_status.get(a.get("ad_id"), "?")
                log.info("     %s %-40s RM%-7.2f %2dL %s", "▶️" if st in RUNNING else "⏸", (a.get("ad_name") or "")[:40],
                         asp, int(ald), f"CPL {asp / ald:,.0f}" if ald else "零 lead")
            tot[0] += sp; tot[1] += ld; tot[2] += ck
        log.info("  小计 %s：RM%.0f · %dL · CPL %s · 报名率 %s", label, tot[0], int(tot[1]),
                 f"{tot[0] / tot[1]:,.0f}" if tot[1] else "—", f"{tot[1] / tot[2] * 100:.0f}%" if tot[2] else "—")
        for i in range(3):
            grand[i] += tot[i]
    log.info("═" * 110)
    log.info("合计 10/8 → %s：RM%.0f · %dL · CPL %s · 新单 %d · 每单广告费 %s", today, grand[0], int(grand[1]),
             f"{grand[0] / grand[1]:,.0f}" if grand[1] else "—", len(new),
             f"RM{grand[0] / len(new):,.0f}" if new else "—")
    final_summary(log, "since-Thursday accounting done · read-only")


if __name__ == "__main__":
    main()
