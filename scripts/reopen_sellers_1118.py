"""Reopen the 60-day sellers plus the 3 webinar-day ads at Thu 19 Nov 00:00 SGT (operator 18 Nov).

Operator 18 Nov: 「等下 00:00 开完我今天 3:00pm 左右关的广告」 then 「我刚刚 update 了 paid student list，
有成交记录的，都可以一起开，确保有开到哦！有时候 campaign 开了，ad set / ad 没有开到。」

ADBOT_MODE=check (default, read-only): read the Paid Student List, find every ad on SG老户 + HK whose OWN
sale (UTM campaign + ad set + ad all match the ad's three names) is within the last 60 days, and print
each with its campaign / ad set / ad status, daily budget, 60-day spend, CPA and ROAS. Also prints the
other ad-level-ACTIVE ads in the same campaigns (those would wake with the campaign). A name that
matches more than one ad is listed as ambiguous and NOT picked.

ADBOT_MODE=go: for ADBOT_AD_IDS (the frozen list), per campaign first pause every other ad-level-ACTIVE
ad that is not on the list (so no unproven sibling wakes up), then set ad, ad set and campaign ACTIVE,
then read every listed ad back and print its effective_status. Idempotent. Budgets untouched.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from collections import defaultdict

from adbot import cpa
from adbot.clients.sheets import SheetsClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

ACCTS = [("SG老户", "act_1024930575770087"), ("HK", "act_1179668409969241")]
FIELDS = ("id,name,status,effective_status,adset{id,name,status,effective_status,daily_budget},"
          "campaign{id,name,status,effective_status,daily_budget}")


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def key3(c, s, a):
    return cpa.ad_key(c), cpa.ad_key(s), cpa.ad_key(a)


def all_ads(g, acct):
    return g._get_all(f"{acct}/ads", {"fields": FIELDS, "limit": 500})


def check(log, s, g):
    now = dt.datetime.utcnow() + dt.timedelta(hours=8)
    today = now.date()
    d60 = today - dt.timedelta(days=60)
    sh = SheetsClient(s.secrets.google_sa_json)
    sales, _c, _h = cpa.parse_sales(sh.read_tab(s.cpa.spreadsheet_id, s.cpa.sales_tab), s.cpa.price_myr)
    own60 = defaultdict(list)
    newest = max((x.date for x in sales if x.date), default=None)
    for x in sales:
        if x.date and x.date > d60:
            own60[key3(x.campaign, x.adset, x.ad)].append(x.date)
    log.info("读数 %s SGT · 成交表最新一笔日期 %s · 60 天窗口 %s 之后 · 60 天内有 UTM 的成交键 %d 个",
             now.strftime("%Y-%m-%d %H:%M"), newest, d60, len(own60))
    by_key = defaultdict(list)
    camp_ads = defaultdict(list)
    for label, acct in ACCTS:
        for a in all_ads(g, acct):
            c, st = a.get("campaign") or {}, a.get("adset") or {}
            a["_acct"] = label
            by_key[key3(c.get("name") or "", st.get("name") or "", a.get("name") or "")].append(a)
            camp_ads[c.get("id")].append(a)
    picked, ambiguous, unmatched = [], [], []
    for k, ds in sorted(own60.items(), key=lambda kv: -len(kv[1])):
        hits = by_key.get(k, [])
        if len(hits) == 1:
            picked.append((hits[0], sorted(ds)))
        elif len(hits) > 1:
            ambiguous.append((k, hits, sorted(ds)))
        else:
            unmatched.append((k, sorted(ds)))
    sp60 = {}
    for label, acct in ACCTS:
        ids = [a["id"] for a, _ in picked if a["_acct"] == label]
        for i in range(0, len(ids), 50):
            for r in g._get_all(f"{acct}/insights", {"level": "ad", "limit": 500, "fields": "ad_id,spend",
                                                     "time_range": json.dumps({"since": d60.isoformat(), "until": today.isoformat()}),
                                                     "filtering": json.dumps([{"field": "ad.id", "operator": "IN", "value": ids[i:i + 50]}])}):
                sp60[r["ad_id"]] = _f(r.get("spend"))
    log.info("═" * 100)
    log.info("A. 60 天内有自己成交、名字只对上一支广告的（会开）：%d 支", len(picked))
    for a, ds in picked:
        c, st = a.get("campaign") or {}, a.get("adset") or {}
        sp = sp60.get(a["id"], 0.0)
        bud = (f"campaign RM{_f(c.get('daily_budget')) / 100:.0f}" if c.get("daily_budget")
               else f"ad set RM{_f(st.get('daily_budget')) / 100:.0f}")
        log.info("   %s · campaign %s %r [%s] › ad set %s %r [%s] › ad %s %r [%s/%s] · 预算 %s · 60 天成交 %d（%s）"
                 " · 60 天花 RM%.2f · CPA %s · ROAS %.2f",
                 a["_acct"], c.get("id"), (c.get("name") or "")[:60], c.get("status"), st.get("id"),
                 (st.get("name") or "")[:40], st.get("status"), a["id"], (a.get("name") or "")[:50], a.get("status"),
                 a.get("effective_status"), bud, len(ds), ",".join(str(d) for d in ds),
                 sp, f"RM{sp / len(ds):.2f}", len(ds) * s.cpa.price_myr / sp if sp else 0.0)
    log.info("B. 名字对上不止一支广告（同名副本，不开，要 operator 决定）：%d 个", len(ambiguous))
    for k, hits, ds in ambiguous:
        log.info("   %s · 成交 %d（%s）→ %s", " › ".join(k), len(ds), ",".join(str(d) for d in ds),
                 [(h["_acct"], h["id"], h.get("effective_status")) for h in hits])
    log.info("C. 成交 UTM 在 SG老户 / HK 找不到对应广告（MY 或无 UTM 等，不开）：%d 个", len(unmatched))
    for k, ds in unmatched:
        log.info("   %s · 成交 %d（%s）", " › ".join(k), len(ds), ",".join(str(d) for d in ds))
    ids = {a["id"] for a, _ in picked}
    log.info("D. 这些 campaign 里其他 ad 层是 ACTIVE 的广告（go 时会先关掉，免得跟着醒）：")
    for cid in {(a.get("campaign") or {}).get("id") for a, _ in picked}:
        sib = [x for x in camp_ads.get(cid, []) if x["id"] not in ids and x.get("status") == "ACTIVE"]
        if sib:
            log.info("   campaign %s：%s", cid, [(x["id"], (x.get("name") or "")[:30]) for x in sib])
    final_summary(log, f"会开 {len(picked)} 支：{','.join(a['id'] for a, _ in picked)} · 同名不开 {len(ambiguous)} · 对不上 {len(unmatched)}")


def go(log, g, ad_ids):
    camps = {}
    for aid in ad_ids:
        a = g.get_object(aid, FIELDS)
        c = a.get("campaign") or {}
        camps.setdefault(c.get("id"), []).append(a)
    wanted = set(ad_ids)
    for cid, ads in camps.items():
        acct = g.get_object(cid, "account_id").get("account_id")
        sibs = g._get_all(f"{cid}/ads", {"fields": "id,name,status", "limit": 500})
        for x in sibs:
            if x["id"] not in wanted and x.get("status") == "ACTIVE":
                g._request("POST", x["id"], data={"status": "PAUSED"})
                log.info("  ⏸ 同 campaign 其他广告先关（ad 层）%s %r", x["id"], (x.get("name") or "")[:40])
        for a in ads:
            st = a.get("adset") or {}
            for eid, lvl, cur in ((a["id"], "ad", a.get("status")), (st.get("id"), "ad set", st.get("status"))):
                if cur != "ACTIVE":
                    g._request("POST", eid, data={"status": "ACTIVE"})
                    log.info("  ▶️ %s %s %s → ACTIVE", lvl, eid, cur)
        c = ads[0].get("campaign") or {}
        if c.get("status") != "ACTIVE":
            g._request("POST", cid, data={"status": "ACTIVE"})
            log.info("  ▶️ campaign %s %r %s → ACTIVE (act_%s)", cid, (c.get("name") or "")[:50], c.get("status"), acct)
    log.info("─" * 60)
    ok, bad = [], []
    for aid in ad_ids:
        a = g.get_object(aid, FIELDS)
        c, st = a.get("campaign") or {}, a.get("adset") or {}
        chain = f"campaign {c.get('status')}/{c.get('effective_status')} · ad set {st.get('status')}/{st.get('effective_status')} · ad {a.get('status')}/{a.get('effective_status')}"
        log.info("  读回 %s %r · %s", aid, (a.get("name") or "")[:40], chain)
        (ok if a.get("effective_status") in ("ACTIVE", "IN_PROCESS", "PENDING_REVIEW") else bad).append(aid)
    final_summary(log, f"开好 {len(ok)}/{len(ad_ids)} · 没开到 {bad or '没有'}")


def main():
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    if (os.environ.get("ADBOT_MODE") or "check") == "find":
        # operator-given UTM triples "campaign|ad set|ad;;..." → matching ads on SG老户 + HK, chain status,
        # 60-day spend, last delivery day and Meta leads in the 7 days up to it (rule 3).
        from adbot.monitor_cpl import extract_results, result_action_type
        tok = result_action_type(s.meta.conversion_event)
        today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
        d60 = today - dt.timedelta(days=60)
        want = [t.split("|") for t in (os.environ.get("ADBOT_AD_IDS") or "").split(";;") if t.count("|") == 2]
        ads = []
        for label, acct in ACCTS:
            for a in all_ads(g, acct):
                a["_acct"] = label
                ads.append(a)
        for c0, s0, a0 in want:
            k = key3(c0, s0, a0)
            hits = [a for a in ads if key3((a.get("campaign") or {}).get("name") or "", (a.get("adset") or {}).get("name") or "",
                                            a.get("name") or "") == k]
            log.info("UTM %s › %s › %s → %d 支", c0, s0, a0, len(hits))
            for a in hits:
                c, st = a.get("campaign") or {}, a.get("adset") or {}
                days = g._get_all(f"{a['id']}/insights", {"fields": "spend,actions", "time_increment": 1,
                                                          "time_range": json.dumps({"since": d60.isoformat(), "until": today.isoformat()})})
                sp = sum(_f(r.get("spend")) for r in days)
                live_days = sorted(r["date_start"] for r in days if _f(r.get("spend")) > 0)
                last = dt.date.fromisoformat(live_days[-1]) if live_days else None
                p7 = sum(extract_results(r.get("actions"), tok) for r in days
                         if last and dt.date.fromisoformat(r["date_start"]) > last - dt.timedelta(days=7))
                bud = (f"campaign RM{_f(c.get('daily_budget')) / 100:.0f}" if c.get("daily_budget")
                       else f"ad set RM{_f(st.get('daily_budget')) / 100:.0f}")
                log.info("   %s · campaign %s [%s] › ad set %s [%s] › ad %s [%s/%s] · 预算 %s · 60 天花 RM%.2f · 最后有花钱 %s"
                         " · 那之前 7 天 Meta 报名 %d", a["_acct"], c.get("id"), c.get("status"), st.get("id"), st.get("status"),
                         a["id"], a.get("status"), a.get("effective_status"), bud, sp, last, p7)
        final_summary(log, "find done")
        return
    if (os.environ.get("ADBOT_MODE") or "check") == "pre7":
        # rule 3: leads in the 7 days before each ad was stopped. ADBOT_AD_IDS = "adid:YYYY-MM-DD(stop day)"
        from adbot.monitor_cpl import extract_results, result_action_type
        tok = result_action_type(s.meta.conversion_event)
        for pair in (os.environ.get("ADBOT_AD_IDS") or "").split(","):
            if ":" not in pair:
                continue
            aid, day = pair.strip().split(":")
            stop = dt.date.fromisoformat(day)
            r = (g._get_all(f"{aid}/insights", {"fields": "spend,actions", "time_range": json.dumps(
                {"since": (stop - dt.timedelta(days=7)).isoformat(), "until": (stop - dt.timedelta(days=1)).isoformat()})}) or [{}])[0]
            log.info("  停前 7 天 %s（%s ~ %s）· 花 RM%.2f · Meta 报名 %d", aid, stop - dt.timedelta(days=7),
                     stop - dt.timedelta(days=1), _f(r.get("spend")), extract_results(r.get("actions"), tok))
        final_summary(log, "pre7 done")
        return
    if (os.environ.get("ADBOT_MODE") or "check") == "go":
        ids = [x.strip() for x in (os.environ.get("ADBOT_AD_IDS") or "").split(",") if x.strip()]
        if not ids:
            final_summary(log, "ADBOT_AD_IDS empty — nothing to do")
            return
        go(log, g, ids)
    else:
        check(log, s, g)


if __name__ == "__main__":
    main()
