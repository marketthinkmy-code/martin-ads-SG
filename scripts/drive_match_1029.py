"""Match the Aug-Oct Drive videos to Meta videos and the ads that play them (read-only, 29 Oct, operator 「B」).

1. Video titles from every place Meta keeps them: each account's video library (SG old, HK, MY read
   only) and the Facebook Page's videos (page token when the system token can get one).
2. Every ad created since 2026-08-01 on the three accounts -> the video id(s) its creative plays,
   with spend / registrations since 2026-08-01 (14-day chunks) and own sales (UTM campaign + ad set + ad).
3. Per video id that has ads: title, Page description start, created date, length, which Drive file
   name it matches (folded: case, width, spaces, '#', '.mp4'; 新馬 = 新马 = SGMY), ads, spend, sales.
No writes.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
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
DRIVE = ["Martin July SGMY H1#", "Martin July SGMY H2#", "Martin July 新馬 V1#", "Martin July 新馬 V2#",
         "Martin July 新馬 V3#", "Martin July 新馬 V4#", "Martin July 新馬H3#", "Martin July 新馬 H4#",
         "Martin July 新馬 H6#", "Martin July 新馬 H7#", "Martin July 新馬 H8#",
         "Martin SGMY Video 1#", "Martin SGMY Video 2#", "Martin SGMY Video 3#", "Martin SGMY Video 4#",
         "Martin SGMY Video 5#", "Martin SGMY Video 6#", "Martin SGMY H2#", "Martin SGMY H3#"]
AD_F = ("id,name,effective_status,created_time,campaign{name},adset{name},"
        "creative{video_id,object_story_spec,asset_feed_spec}")


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").casefold().replace(".mp4", "")
    s = s.replace("新馬", "sgmy").replace("新马", "sgmy").replace("马丁", "martin").replace("馬丁", "martin")
    s = s.replace("video", "v").replace("hook", "h")
    return re.sub(r"[\s#_\-.]+", "", s)


DRIVE_KEYS = {fold(d): d for d in DRIVE}


def drive_match(title: str) -> str:
    t = fold(title)
    hits = [d for k, d in DRIVE_KEYS.items() if k and k in t]
    if hits:
        return " / ".join(hits)
    m = re.search(r"(july)?sgmy(v|h)(\d+)", t)          # e.g. "SGMYH2 面包" -> h2 (folder unknown)
    if m:
        return f"?SGMY {m.group(2).upper()}{m.group(3)} ({'July' if m.group(1) else '没写 July'})"
    return ""


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
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()

    vids = {}                                       # id -> {title, desc, created, length, src}
    for label, acct in ACCTS:
        for v in g._get_all(f"{acct}/advideos", {"fields": "id,title,created_time,length", "limit": 500}):
            vids.setdefault(v["id"], {"title": v.get("title") or "", "desc": "", "created": (v.get("created_time") or "")[:10],
                                      "length": v.get("length"), "src": label})
    page = s.meta.page_id
    ptoken = None
    try:
        ptoken = g.get_object(page, "access_token").get("access_token")
    except GraphError as exc:
        log.info("Page token 拿不到（%s）—— 用系统 token 读 Page 视频", str(exc)[:80])
    try:
        params = {"fields": "id,title,description,created_time,length", "limit": 100}
        if ptoken:
            params["access_token"] = ptoken
        n = 0
        for v in g._get_all(f"{page}/videos", params):
            n += 1
            d = vids.setdefault(v["id"], {"title": "", "desc": "", "created": "", "length": None, "src": "Page"})
            d["title"] = d["title"] or v.get("title") or ""
            d["desc"] = (v.get("description") or "")[:50].replace("\n", " ")
            d["created"] = d["created"] or (v.get("created_time") or "")[:10]
            d["length"] = d["length"] or v.get("length")
            d["src"] += "+Page" if d["src"] != "Page" else ""
        log.info("Page %s 视频 %d 支", page, n)
    except GraphError as exc:
        log.info("Page 视频读不到：%s", str(exc)[:160])

    sales, _c, _h = cpa.parse_sales(SheetsClient(s.secrets.google_sa_json).read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab),
                                    s.cpa.price_myr)
    own = defaultdict(int)
    for x in sales:
        own[(cpa.ad_key(x.campaign), cpa.ad_key(x.adset), cpa.ad_key(x.ad))] += 1

    use = defaultdict(list)                          # video id -> ad rows
    for label, acct in ACCTS:
        life = defaultdict(lambda: [0.0, 0.0])

        def pull(since: dt.date, until: dt.date) -> None:
            try:
                rows = g._get_all(f"{acct}/insights", {"level": "ad", "limit": 200, "fields": "ad_id,spend,actions",
                                                       "time_range": json.dumps({"since": since.isoformat(),
                                                                                 "until": until.isoformat()})})
            except GraphError:
                if since >= until:
                    raise
                mid = since + (until - since) // 2
                pull(since, mid)
                pull(mid + dt.timedelta(days=1), until)
                return
            for r in rows:
                life[r["ad_id"]][0] += _f(r.get("spend"))
                life[r["ad_id"]][1] += extract_results(r.get("actions"), tok)

        start = dt.date.fromisoformat(SINCE)
        while start <= today:
            end = min(start + dt.timedelta(days=13), today)
            pull(start, end)
            start = end + dt.timedelta(days=1)
        for a in g._get_all(f"{acct}/ads", {"fields": AD_F, "limit": 200,
                                            "filtering": json.dumps([{"field": "created_time", "operator": "GREATER_THAN",
                                                                      "value": SINCE}])}):
            c, st, nm = (a.get("campaign") or {}).get("name") or "", (a.get("adset") or {}).get("name") or "", a.get("name") or ""
            sp, reg = life.get(a["id"], (0.0, 0.0))
            for vid in _video_ids(a.get("creative") or {}):
                use[vid].append((label, a["id"], nm, c, st, a.get("effective_status"), sp, reg,
                                 own.get((cpa.ad_key(c), cpa.ad_key(st), cpa.ad_key(nm)), 0)))

    rows = []
    for vid, ads in use.items():
        v = vids.get(vid) or {"title": "", "desc": "", "created": "", "length": None, "src": "?"}
        match = drive_match(v["title"]) or drive_match(v["desc"])
        sp = sum(r[6] for r in ads)
        if not match and sp <= 0:
            continue
        rows.append((match, vid, v, ads, sp))
    rows.sort(key=lambda r: (r[0] == "", r[0], -r[4]))
    unmatched_spend = 0.0
    for match, vid, v, ads, sp in rows:
        reg = sum(r[7] for r in ads)
        sold = sum(r[8] for r in ads)
        if not match:
            unmatched_spend += sp
            if sp < 300:
                continue
        log.info("═" * 100)
        log.info("▌%s · video %s · 标题 %r · Page 文案 %r · 建于 %s · %ss · 来源 %s", match or "（对不上 Drive）", vid,
                 v["title"][:60], v["desc"][:40], v["created"] or "?", v["length"] or "?", v["src"])
        log.info("  %d 支广告 · 8/1 起花 RM%.2f · 报名 %d · CPL %s · 自己的成交 %d", len(ads), sp, reg,
                 f"RM{sp / reg:.0f}" if reg else "—", sold)
        for r in sorted(ads, key=lambda r: -r[6])[:6]:
            log.info("    %s ad %s %r · %s · campaign %r · ad set %r · RM%.2f · 报名 %d · 成交 %d",
                     r[0], r[1], r[2][:40], r[5], r[3][:55], r[4][:30], r[6], r[7], r[8])
    matched = [r for r in rows if r[0]]
    by_drive = defaultdict(lambda: [0, 0.0, 0])
    for match, _vid, _v, ads, sp in matched:
        by_drive[match][0] += len(ads)
        by_drive[match][1] += sp
        by_drive[match][2] += sum(r[8] for r in ads)
    final_summary(log, f"对上 Drive 的视频 {len(matched)} 个 · 对不上但有花费的 RM{unmatched_spend:.0f} · " + " | ".join(
        f"{k}: {n} 支广告 RM{sp:.0f} 成交 {so}" for k, (n, sp, so) in sorted(by_drive.items())))


if __name__ == "__main__":
    main()
