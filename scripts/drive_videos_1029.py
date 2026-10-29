"""Which Meta ads use the Aug / Sep / Oct videos in the two Drive folders? (read-only, 29 Oct)

Operator: 8/9 月广告重新上 (Drive folders 1jwTDSNaG5pgnYChflIIA72euphFUcK-U "Martin July ..." and
1NAKPEHsUlD3ub1BDXBeaezrICuDq1JNy "Martin SGMY ..."). For every ad created since 2026-08-01 on SG old,
HK and MY (MY read only, rule 4): the video it plays (creative video id -> video title), then
grouped by video title: account, campaign, ad set, ad, status, lifetime spend / registrations /
CPL, own sales (UTM campaign + ad set + ad) and SG sales of the same ad name (paid sheet). No writes.
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
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

ACCTS = [("SG老户", "act_1024930575770087"), ("HK", "act_1179668409969241"), ("MY(只读)", "act_1011719073600566")]
SINCE = "2026-08-01"
AD_F = ("id,name,effective_status,created_time,campaign{name},adset{name},"
        "creative{video_id,object_story_spec,asset_feed_spec}")


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _video_ids(cr):
    out = []
    if cr.get("video_id"):
        out.append(cr["video_id"])
    vd = ((cr.get("object_story_spec") or {}).get("video_data") or {}).get("video_id")
    if vd:
        out.append(vd)
    for v in (cr.get("asset_feed_spec") or {}).get("videos") or []:
        if v.get("video_id"):
            out.append(v["video_id"])
    return list(dict.fromkeys(out))


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    tok = result_action_type(s.meta.conversion_event)
    sales, _c, _h = cpa.parse_sales(SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab),
                                    s.cpa.price_myr)
    own = defaultdict(int)
    by_name = defaultdict(int)
    for x in sales:
        own[(cpa.ad_key(x.campaign), cpa.ad_key(x.adset), cpa.ad_key(x.ad))] += 1
        if "[sg]" in cpa.norm(x.campaign):
            by_name[cpa.ad_key(x.ad)] += 1

    titles = {}
    groups = defaultdict(list)
    for label, acct in ACCTS:
        for v in g._get_all(f"{acct}/advideos", {"fields": "id,title", "limit": 500}):
            titles[v["id"]] = v.get("title") or ""
        life = defaultdict(lambda: [0.0, 0.0])     # ads made since SINCE: chunks cover their whole life

        def pull(since: dt.date, until: dt.date) -> None:
            try:
                rows = g._get_all(f"{acct}/insights", {"level": "ad", "limit": 200, "fields": "ad_id,spend,actions",
                                                       "time_range": json.dumps({"since": since.isoformat(),
                                                                                 "until": until.isoformat()})})
            except GraphError:
                if since >= until:
                    raise
                mid = since + (until - since) // 2      # Meta refused the range: split it in two
                pull(since, mid)
                pull(mid + dt.timedelta(days=1), until)
                return
            for r in rows:
                life[r["ad_id"]][0] += _f(r.get("spend"))
                life[r["ad_id"]][1] += extract_results(r.get("actions"), tok)

        start = dt.date.fromisoformat(SINCE)
        today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
        while start <= today:
            end = min(start + dt.timedelta(days=13), today)
            pull(start, end)
            start = end + dt.timedelta(days=1)
        n = 0
        for a in g._get_all(f"{acct}/ads", {"fields": AD_F, "limit": 200,
                                            "filtering": json.dumps([{"field": "created_time", "operator": "GREATER_THAN",
                                                                      "value": SINCE}])}):
            n += 1
            vids = _video_ids(a.get("creative") or {})
            for vid in vids:
                if vid not in titles:
                    try:
                        titles[vid] = g.get_object(vid, "title").get("title") or ""
                    except GraphError:
                        titles[vid] = ""
            t = " / ".join(sorted({titles.get(v) or f"(video {v} 无标题)" for v in vids})) or "(没有视频)"
            sp, reg = life.get(a["id"], (0.0, 0.0))
            c, st = (a.get("campaign") or {}).get("name") or "", (a.get("adset") or {}).get("name") or ""
            groups[t].append((label, a["id"], c, st, a.get("name") or "", a.get("effective_status"), sp, reg,
                              own.get((cpa.ad_key(c), cpa.ad_key(st), cpa.ad_key(a.get("name") or "")), 0),
                              by_name.get(cpa.ad_key(a.get("name") or ""), 0)))
        log.info("%s %s 起建的广告 %d 支", label, SINCE, n)

    for t in sorted(groups):
        rows = groups[t]
        tsp = sum(r[6] for r in rows)
        treg = sum(r[7] for r in rows)
        tsales = sum(r[8] for r in rows)
        log.info("═" * 100)
        log.info("▌视频 %r · %d 支广告 · 全期花 RM%.2f · 报名 %d · CPL %s · 自己的成交 %d · 广告名在 SG 成交表 %s",
                 t, len(rows), tsp, treg, f"RM{tsp / treg:.0f}" if treg else "—", tsales,
                 sorted({(r[4][:30], r[9]) for r in rows if r[9]}))
        for r in sorted(rows, key=lambda r: -r[6])[:12]:
            log.info("  %s ad %s %r · %s · campaign %r · ad set %r · RM%.2f · 报名 %d · 自己成交 %d",
                     r[0], r[1], r[4][:40], r[5], r[2][:60], r[3][:30], r[6], r[7], r[8])
    final_summary(log, f"{len(groups)} 个视频标题 · " + " | ".join(
        f"{t[:40]}: {len(r)} 支 RM{sum(x[6] for x in r):.0f} 报名 {sum(x[7] for x in r):.0f} 成交 {sum(x[8] for x in r)}"
        for t, r in sorted(groups.items())))


if __name__ == "__main__":
    main()
