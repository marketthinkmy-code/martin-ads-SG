"""Pre-build checks for 老片重开 3 (read-only, 20 Oct; operator: 全建，RM50，今天开跑).

  rule 3: for the two old videos, every SG-market ad's last delivery day and the leads in its
          last 7 delivering days
  rule 4: lifetime spend / leads for all 5 videos on MY, HK, SG old
  source: SG old + HK ad sets named Health and Wellness / Luxury that carried the old videos,
          with spend, leads and full targeting, so the build copies the audience that sold
No writes; MY read only.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from collections import defaultdict

from adbot import cpa
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

ACCTS = [("SG老", "act_1024930575770087"), ("HK", "act_1179668409969241"), ("MY", "act_1011719073600566")]
OLD = ["Video: 孩子15岁以上还有机会长高吗？", "Video: 什麼樣的孩子基本上不會再長高"]
NEW = ["Video 5：Kaya 面包配 Milo", "Hook 5：孩子挑食"]
AUDS = ("health and wellness", "luxury")


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def aud_key(name):
    n = cpa.norm(name or "")
    n = re.sub(r"interest\s*:\s*", "", n)
    n = re.sub(r"rm\s*\d+", "", n)
    n = n.replace("&", " and ")
    return re.sub(r"[\s|·:：\-–—_/+()（）\[\]]+", " ", n).strip()


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    tok = result_action_type(s.meta.conversion_event)
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    keys = {cpa.ad_key(n): n for n in OLD + NEW}

    # rule 4 + ad inventory
    ads = defaultdict(list)  # key -> [(acct_label, ad_id, adset_id, adset_name, spend, leads)]
    for label, acct in ACCTS:
        for r in g._get_all(f"{acct}/insights", {"level": "ad", "limit": 500, "date_preset": "maximum",
                                                  "fields": "campaign_name,adset_id,adset_name,ad_id,ad_name,spend,actions"}):
            k = cpa.ad_key(r.get("ad_name") or "")
            if k in keys:
                ads[k].append((label, r["ad_id"], r.get("adset_id"), r.get("adset_name") or "", _f(r.get("spend")),
                               extract_results(r.get("actions"), tok), r.get("campaign_name") or ""))
    log.info("═" * 110)
    log.info("规矩 4：三个账户累计（全部时间）")
    for k, nm in keys.items():
        log.info("▌%s", nm)
        for label, _ in ACCTS:
            sp = sum(x[4] for x in ads[k] if x[0] == label); ld = sum(x[5] for x in ads[k] if x[0] == label)
            log.info("    %-4s 花 RM%.2f · %d 报名 · 每个报名 %s", label, sp, int(ld), f"RM{sp / ld:.0f}" if ld else "—")

    # rule 3
    log.info("═" * 110)
    log.info("规矩 3：两支旧片每支 SG 市场广告的最后投放日，和最后 7 个投放日的报名")
    for nm in OLD:
        k = cpa.ad_key(nm)
        ids = [x[1] for x in ads[k] if x[0] != "MY" and x[4] > 0]
        log.info("▌%s · SG 市场有花费的广告 %d 支", nm, len(ids))
        daily = defaultdict(list)
        acct_of = {x[1]: x[0] for x in ads[k]}
        for label, acct in ACCTS[:2]:
            mine = [i for i in ids if acct_of[i] == label]
            if not mine:
                continue
            for i in range(13):  # 13 × 30 days
                hi = today - dt.timedelta(days=30 * i); lo = hi - dt.timedelta(days=29)
                for r in g._get_all(f"{acct}/insights", {"level": "ad", "limit": 500, "time_increment": 1,
                                                          "time_range": json.dumps({"since": lo.isoformat(), "until": hi.isoformat()}),
                                                          "filtering": json.dumps([{"field": "ad.id", "operator": "IN", "value": mine}]),
                                                          "fields": "ad_id,spend,actions"}):
                    if _f(r.get("spend")) > 0:
                        daily[r["ad_id"]].append((r["date_start"], _f(r.get("spend")), extract_results(r.get("actions"), tok)))
        for x in sorted(ads[k], key=lambda x: -x[4]):
            if x[0] == "MY" or x[4] <= 0:
                continue
            d = sorted(daily.get(x[1], []))
            last7 = d[-7:]
            log.info("    %-4s ad %s · ad set %s %r · campaign %r", x[0], x[1], x[2], x[3][:40], x[6][:60])
            log.info("         累计 RM%.0f / %d 报名 · 最后投放日 %s · 最后 7 个投放日 花 RM%.0f · %d 报名",
                     x[4], int(x[5]), d[-1][0] if d else "—", sum(v[1] for v in last7), int(sum(v[2] for v in last7)))

    # source ad sets
    log.info("═" * 110)
    log.info("来源 ad set：名字是 Health and Wellness / Luxury、跑过这两支旧片的")
    seen = set()
    for k in [cpa.ad_key(n) for n in OLD]:
        for x in sorted(ads[k], key=lambda x: -x[4]):
            if x[0] == "MY" or aud_key(x[3]) not in AUDS or x[2] in seen:
                continue
            seen.add(x[2])
            a = g.get_object(x[2], "name,created_time,effective_status,daily_budget,optimization_goal,promoted_object,targeting")
            log.info("▌%s ad set %s %r · 建 %s · %s · 这支片在里面 RM%.0f / %d 报名", x[0], x[2], a.get("name"),
                     (a.get("created_time") or "")[:10], a.get("effective_status"), x[4], int(x[5]))
            log.info("    targeting %s", json.dumps(a.get("targeting") or {}, ensure_ascii=False))
    final_summary(log, "precheck 老片重开 3 · read-only")


if __name__ == "__main__":
    main()
