"""Ad-set probe (read-only, 8 Oct): what is really inside the given ad sets?

Operator pushed back on the audit's "空 ad set" flag: 他们现在都在跑着不是吗？而且都是
有成交记录的广告，不是吗？ The audit only counted ads whose effective_status was
ACTIVE / IN_PROCESS / PENDING_REVIEW, so a set full of PAUSED ads reads as "empty".
This probe answers both halves of the question without any filter:
  · every ad in the set, any status (incl. paused / archived / with issues)
  · ad-set-level spend + leads 本周 (10/1→) / 30d / lifetime — independent of ad enumeration
  · per-ad spend 本周 / 30d / lifetime
  · sheet sales: by exact campaign+ad-set UTM match, and by ad name per market
  · the sibling ad sets of the same campaign (where the running ads actually are)
ADBOT_ADSET_IDS = comma-separated ad set ids. No writes.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from collections import defaultdict
from typing import Dict, List

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

WEEK = dt.date(2026, 10, 1)
ALL_STATUSES = ["ACTIVE", "PAUSED", "DELETED", "ARCHIVED", "PENDING_REVIEW", "DISAPPROVED",
                "PREAPPROVED", "PENDING_BILLING_INFO", "CAMPAIGN_PAUSED", "ADSET_PAUSED",
                "IN_PROCESS", "WITH_ISSUES"]


def _mkt(campaign: str) -> str:
    c = cpa.norm(campaign)
    if "[sg]" in c or "martin-sg" in c or "martin sg" in c:
        return "SG"
    if "[my]" in c or "martin-my" in c or "martin my" in c:
        return "MY"
    return "other"


def main() -> None:
    log = get_logger()
    ids = [x.strip() for x in os.environ.get("ADBOT_ADSET_IDS", "").split(",") if x.strip()]
    if not ids:
        final_summary(log, "ADBOT_ADSET_IDS empty — nothing to do")
        return
    s = load_settings()
    g = graph_client(s)
    token = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d30, d60 = today - dt.timedelta(days=30), today - dt.timedelta(days=60)

    values = SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab)
    sales, _c, _h = cpa.parse_sales(values, s.cpa.price_myr)

    def ins(path: str, level: str, **window):
        rows = g._get_all(f"{path}/insights",
                          {"level": level, "limit": 500, "fields": "ad_id,ad_name,spend,actions", **window})
        out: Dict[str, List[float]] = defaultdict(lambda: [0.0, 0.0])
        for r in rows:
            try:
                v = float(r.get("spend") or 0)
            except (TypeError, ValueError):
                v = 0.0
            key = r.get("ad_id") if level == "ad" else "_"
            out[key][0] += v
            out[key][1] += extract_results(r.get("actions"), token)
        return out

    def tr(since: dt.date) -> dict:
        return {"time_range": json.dumps({"since": since.isoformat(), "until": today.isoformat()})}

    for sid in ids:
        log.info("═" * 110)
        a_set = g.get_object(sid, "name,status,effective_status,campaign_id,daily_budget,created_time,"
                                  "updated_time,account_id")
        camp = g.get_object(str(a_set.get("campaign_id")), "name,status,effective_status,daily_budget")
        cname, aname = camp.get("name") or "", a_set.get("name") or ""
        log.info("▌ad set %s %r · status %s / eff %s · 预算 RM%d · 建 %s · 改 %s · act_%s", sid, aname,
                 a_set.get("status"), a_set.get("effective_status"), int(a_set.get("daily_budget") or 0) // 100,
                 (a_set.get("created_time") or "")[:10], (a_set.get("updated_time") or "")[:10], a_set.get("account_id"))
        log.info("  campaign %s %r · %s/%s · campaign 预算 %s", camp.get("id"), cname[:80], camp.get("status"),
                 camp.get("effective_status"), f"RM{int(camp.get('daily_budget') or 0) // 100}" if camp.get("daily_budget") else "ABO")

        # ad-set-level spend, independent of which ads we manage to list
        w = ins(sid, "adset", **tr(WEEK)).get("_", [0.0, 0.0])
        m = ins(sid, "adset", **tr(d30)).get("_", [0.0, 0.0])
        life = ins(sid, "adset", date_preset="maximum").get("_", [0.0, 0.0])
        log.info("  ad set 层花费：本周(10/1→) RM%.2f %dL · 30d RM%.2f %dL · 全史 RM%.2f %dL",
                 w[0], int(w[1]), m[0], int(m[1]), life[0], int(life[1]))

        # every ad, any status
        ads = g._get_all(f"{sid}/ads", {"fields": "id,name,status,effective_status,created_time,updated_time,issues_info",
                                        "effective_status": json.dumps(ALL_STATUSES), "limit": 200})
        aw, am, al = ins(sid, "ad", **tr(WEEK)), ins(sid, "ad", **tr(d30)), ins(sid, "ad", date_preset="maximum")
        running = [a for a in ads if a.get("effective_status") in ("ACTIVE", "IN_PROCESS", "PENDING_REVIEW")]
        log.info("  广告共 %d 支（任何状态）· 其中在投 %d 支", len(ads), len(running))
        for a in sorted(ads, key=lambda x: -al.get(x["id"], [0.0, 0.0])[0]):
            k = cpa.ad_key(a.get("name") or "")
            by_m: Dict[str, List[str]] = defaultdict(list)
            for x in sales:
                if x.date and cpa.ad_key(x.ad) == k:
                    by_m[_mkt(x.campaign)].append(x.date.isoformat())
            sale_txt = " · ".join(f"{mk} {len(ds)}单(30d {sum(1 for d in ds if d >= d30.isoformat())}/60d "
                                  f"{sum(1 for d in ds if d >= d60.isoformat())}) 最近 {max(ds)}"
                                  for mk, ds in sorted(by_m.items())) or "名单上无此广告名的单"
            issues = "; ".join(str(i.get("error_summary") or i.get("error_message") or "")[:60]
                               for i in a.get("issues_info") or []) if a.get("issues_info") else ""
            log.info("    %s %-40s status %s / eff %s · 建 %s%s", "▶️" if a in running else "⏸", (a.get("name") or "")[:40],
                     a.get("status"), a.get("effective_status"), (a.get("created_time") or "")[:10],
                     f" · ⚠️ {issues}" if issues else "")
            log.info("       id %s · 本周 RM%.2f %dL · 30d RM%.2f %dL · 全史 RM%.2f %dL · 成交：%s", a["id"],
                     *aw.get(a["id"], [0.0, 0.0]), *am.get(a["id"], [0.0, 0.0]), *al.get(a["id"], [0.0, 0.0]), sale_txt)

        # sheet sales attributed to this exact campaign + ad set (UTM), regardless of ad name
        ck, ak = cpa.ad_key(cname), cpa.ad_key(aname)
        exact = sorted(x.date.isoformat() for x in sales if x.date and cpa.ad_key(x.campaign) == ck
                       and cpa.ad_key(getattr(x, "adset", "") or "") == ak)
        log.info("  名单上 UTM = 这个 campaign + 这个 ad set 的单：%d%s", len(exact),
                 f" · 最近 {exact[-1]} · 30d {sum(1 for d in exact if d >= d30.isoformat())}" if exact else "")

        # siblings: where the campaign's running ads actually are
        sibs = g._get_all(f"{camp.get('id')}/adsets", {"fields": "id,name,status,effective_status,daily_budget", "limit": 100})
        for sb in sibs:
            if sb["id"] == sid:
                continue
            sads = g._get_all(f"{sb['id']}/ads", {"fields": "id,name,effective_status", "limit": 100})
            on = [x for x in sads if x.get("effective_status") in ("ACTIVE", "IN_PROCESS", "PENDING_REVIEW")]
            sw = ins(sb["id"], "adset", **tr(WEEK)).get("_", [0.0, 0.0])
            log.info("  同 campaign 另一 ad set %s %r · %s/%s · RM%d · 广告 %d 支在投/%d 支 · 本周 RM%.2f %dL%s",
                     sb["id"], (sb.get("name") or "")[:34], sb.get("status"), sb.get("effective_status"),
                     int(sb.get("daily_budget") or 0) // 100, len(on), len(sads), sw[0], int(sw[1]),
                     (" · 在投：" + " / ".join((x.get("name") or "")[:26] for x in on[:4])) if on else "")
    final_summary(log, f"probe done · {len(ids)} ad sets")


if __name__ == "__main__":
    main()
