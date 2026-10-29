"""Reopen the 16 ads behind the 60-day SG sales (operator 29 Oct 「A」 then 「B」: all 16).

ADBOT_MODE=check (default, read-only): for every target ad, its campaign / ad set / ad statuses and
budgets, plus every OTHER ad in the same campaign that would start delivering once the target's
ad set and campaign are ACTIVE (its own status ACTIVE and its ad set ACTIVE or being opened).
ADBOT_MODE=go: set each target ad ACTIVE, then its ad set, then its campaign; nothing else is
touched (other ads keep their own status). Reads every target back. No budget changes.
"""
from __future__ import annotations

import os
from collections import defaultdict

from adbot.clients.graph import GraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

TARGETS = [  # (#, account, ad id) — the table sent to the operator on 29 Oct
    (1, "SG老户", "120257884629490093"),   # Hook 2：你還在把麵包當早餐？ · Grid 3×3 Hook Test
    (2, "SG老户", "120258728159880093"),   # Hook 3：倒掉牛奶 · ENGAGED WOMEN
    (3, "HK", "120250066977470335"),       # Hook 3：倒掉牛奶 · ENGAGED WOMEN
    (4, "SG老户", "120258493505290093"),   # Hook 3：倒掉牛奶 · Family and Relationships 新片 5 支测试
    (5, "HK", "120250013471210335"),       # Hook 3：倒掉牛奶 · Family and Relationships 新片 5 支测试
    (6, "SG老户", "120242606093200093"),   # Hook 7 · Food and Drink + Milk 17/10/2025
    (7, "SG老户", "120257667234350093"),   # Hook Edit 04 · Hook Edits A (CBO)
    (8, "HK", "120250093193110335"),       # MAR Video 5：林書豪story · FAMILY
    (9, "SG老户", "120257934304610093"),   # MAR Video Hook 3 · Scale-Winners Broad A+
    (10, "SG老户", "120256599022280093"),  # MAR Video Hook 3 · Scale-Winners Broad A+ (other ad set)
    (11, "SG老户", "120257269401020093"),  # Video 12 · Interest: Family and Relationships 1-1-1 (CBO)
    (12, "SG老户", "120258109011660093"),  # Video 12 · Parents 3-17 + Engaged
    (13, "HK", "120250013348690335"),      # Video 12 · Parents 3-17 + Engaged
    (14, "SG老户", "120241408854940093"),  # Video 1 · Food and Drink + Milk 17/10/2025
    (15, "SG老户", "120258845193530093"),  # Video 2 · 新片5支重测 OCT 8 (CBO)
    (16, "SG老户", "120256985982080093"),  # Video 7 · Family & Relationships A (CBO)
]
AD_F = "id,name,status,effective_status,adset_id,campaign_id"
SET_F = "id,name,status,effective_status,daily_budget"
CAMP_F = "id,name,status,effective_status,daily_budget"


def _rm(v):
    try:
        return f"RM{int(v) / 100:.0f}"
    except (TypeError, ValueError):
        return "—"


def main():
    log = get_logger()
    g = graph_client(load_settings())
    go = (os.environ.get("ADBOT_MODE") or "check").strip().lower() == "go"
    ads = {aid: g.get_object(aid, AD_F) for _n, _a, aid in TARGETS}
    open_sets = {a["adset_id"] for a in ads.values()}
    by_camp = defaultdict(list)
    for n, acct, aid in TARGETS:
        by_camp[ads[aid]["campaign_id"]].append((n, acct, aid))

    extras_total = 0
    for cid, tl in by_camp.items():
        c = g.get_object(cid, CAMP_F)
        log.info("═" * 100)
        log.info("▌%s · campaign %s %r · %s/%s · campaign 预算 %s", tl[0][1], cid, c.get("name"), c.get("status"),
                 c.get("effective_status"), _rm(c.get("daily_budget")))
        sets = {s["id"]: s for s in g._get_all(f"{cid}/adsets", {"fields": SET_F, "limit": 200})}
        for n, _acct, aid in tl:
            a, s = ads[aid], sets.get(ads[aid]["adset_id"]) or {}
            log.info("  #%d 目标 ad %s %r · %s/%s · ad set %s %r · %s · 日预算 %s", n, aid, a.get("name"),
                     a.get("status"), a.get("effective_status"), s.get("id"), s.get("name"), s.get("status"),
                     _rm(s.get("daily_budget")))
        targets = {aid for _n, _a, aid in tl}
        for o in g._get_all(f"{cid}/ads", {"fields": AD_F, "limit": 500}):
            if o["id"] in targets or o.get("status") != "ACTIVE":
                continue
            s = sets.get(o.get("adset_id")) or {}
            if s.get("status") == "ACTIVE" or o.get("adset_id") in open_sets:
                extras_total += 1
                log.info("  ⚠ 会一起跑：ad %s %r · ad set %s %r (%s · 日预算 %s)", o["id"], o.get("name"),
                         s.get("id"), s.get("name"), s.get("status"), _rm(s.get("daily_budget")))

    if not go:
        final_summary(log, f"重开检查（只读）· 目标 {len(TARGETS)} 支 · {len(by_camp)} 个 campaign · 会一起跑的其他广告 {extras_total} 支")
        return

    done, failed = [], []
    for n, acct, aid in TARGETS:
        a = ads[aid]
        try:
            for eid in (aid, a["adset_id"], a["campaign_id"]):
                g.update_status(eid, "ACTIVE")
            back = g.get_object(aid, "effective_status")
            done.append(f"#{n} {acct} {aid} {back.get('effective_status')}")
            log.info("  ✅ #%d %s ad %s %r → %s", n, acct, aid, a.get("name"), back.get("effective_status"))
        except GraphError as exc:
            failed.append(f"#{n} {acct} {aid}")
            log.error("  ❌ #%d %s ad %s %r 开不了：%s", n, acct, aid, a.get("name"), str(exc)[:200])
    final_summary(log, f"重开 {len(done)} 支 · 失败 {len(failed)} · {' | '.join(done)}" + (f" · 失败 {failed}" if failed else ""))


if __name__ == "__main__":
    main()
