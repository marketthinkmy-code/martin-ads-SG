"""Act on the 2026-08-13 CPA read: close 5 bleeders, reopen 3 sleeping winners, scale the survivors.

The account's problem is not volume, it is where the money sits. Over 60 days five good creatives
produced 16 sales on RM9.6k (CPA ~600) while six expensive ones produced 17 sales on RM31.4k
(CPA ~1,850) — near-identical output for 3.3× the spend.

CLOSE (CPA30 above the RM1300 hard stop) — pauses every ACTIVE copy:
    孩子15岁以上 2534 · video 13 三年前他長了10公分 2428 · 我不会买牛奶 1834
    准备早餐面包 1459 · 面包牛奶一点都不健康 1383
  林書豪 is deliberately NOT here: its 60d CPA of 1896 looks like a close, but 30d is 878 and
  falling, so closing it would kill something on its way back.

REOPEN (sold recently, zero ACTIVE copies) — activates the cheapest paused copy:
    video 12 15歲以上試了五六種方法 (CPA 135) · 4个月长3cm (193) · 女孩来了初经 (426)

SCALE — after the closes, raise the budget of any campaign still holding a scale winner
(新马版主打牛奶迷思 CPA30 189 · 什麼樣的孩子 192 · dec hook 13 672) by +50%, capped at RM225.
Three of the five 1-1-5 winners are scale winners and two are on the close list, so pausing those
two inside a CBO hands their share to the survivors — the budget raise compounds that rather than
just adding spend.

Guards, because a wrong pause here is expensive:
  · anything matching a REOPEN or SCALE core is never paused, whatever else it matches;
  · a close core must match the ad name via cpa.ad_key, not a loose substring;
  · reopening only activates a paused parent when every SIBLING ad is already paused — otherwise
    un-pausing the campaign would quietly restart a whole pool. That case is reported, not forced;
  · budget raises skip any campaign that still has a closed-list ad delivering.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Dict, List

from adbot import cpa
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

CLOSE = [
    ("孩子15岁以上",          "孩子15岁以上"),
    ("video 13 三年前长10公分", "三年前他長了10公分"),
    ("我不会买牛奶",           "我不会买牛奶"),
    ("准备早餐面包",           "准备早餐面包"),
    ("面包牛奶不健康",         "面包牛奶一点都不健康"),
]
REOPEN = [
    ("video 12 · CPA135", "15歲以上試了五六種方法"),
    ("4个月长3cm · CPA193", "4个月长3cm"),
    ("女孩来了初经 · CPA426", "女孩来了初经"),
]
SCALE = [
    ("新马版牛奶迷思", "新马版主打牛奶迷思"),
    ("什麼樣的孩子",   "基本上不會再長高"),
    ("dec hook 13",   "花了几千块买增高"),
]

BUMP = 1.5
CAP_CENTS = 22500          # RM225/day
PROTECT = [c for _, c in REOPEN] + [c for _, c in SCALE]


def key(s: str) -> str:
    return cpa.ad_key(s or "")


def matches(name: str, core: str) -> bool:
    return key(core) in key(name)


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path

    ads = g._get_all(f"{acct}/ads", {
        "fields": "id,name,status,effective_status,adset{id,name,status,daily_budget},"
                  "campaign{id,name,status,daily_budget}", "limit": 500})
    log.info("pulled %d ads", len(ads))
    summary: List[str] = []

    def protected(name: str) -> bool:
        return any(matches(name, c) for c in PROTECT)

    # ── 1. CLOSE ────────────────────────────────────────────────────────────────
    closed_ids = set()
    for label, core in CLOSE:
        hits = [a for a in ads if matches(a.get("name"), core)]
        live = [a for a in hits if a.get("effective_status") == "ACTIVE"]
        skipped = [a for a in live if protected(a.get("name"))]
        live = [a for a in live if not protected(a.get("name"))]
        log.info("═" * 88)
        log.info("CLOSE %-22s %d copy/copies · %d live", label, len(hits), len(live))
        for a in skipped:
            log.warning("   ⚠ %s %r also matches a keep-list core — NOT paused",
                        a["id"], (a.get("name") or "")[:52])
        n = 0
        for a in live:
            g.update_status(a["id"], "PAUSED")
            closed_ids.add(a["id"])
            n += 1
            log.info("   ⏸ %s  %s", a["id"], (a.get("name") or "")[:58])
        summary.append(f"  CLOSE {label:22} paused {n} live copy/copies"
                       + (f" ({len(skipped)} protected)" if skipped else ""))

    # ── 2. REOPEN ───────────────────────────────────────────────────────────────
    for label, core in REOPEN:
        hits = [a for a in ads if matches(a.get("name"), core)]
        if not hits:
            log.warning("REOPEN %-22s no ad found (core=%r)", label, core)
            summary.append(f"  REOPEN {label:20} ✗ no ad by that name")
            continue
        if any(a.get("effective_status") == "ACTIVE" for a in hits):
            log.info("REOPEN %-22s already has a live copy — skipped", label)
            summary.append(f"  REOPEN {label:20} already live — skipped")
            continue
        pick = hits[0]
        cam, ads_et = pick.get("campaign") or {}, pick.get("adset") or {}
        log.info("═" * 88)
        log.info("REOPEN %-22s ad %s · adset %s(%s) · campaign %s(%s)", label, pick["id"],
                 ads_et.get("name", "")[:20], ads_et.get("status"),
                 cam.get("name", "")[:24], cam.get("status"))

        # Only un-pause a parent when nothing else in it would start delivering as a side effect.
        blockers = [a for a in ads
                    if (a.get("adset") or {}).get("id") == ads_et.get("id")
                    and a["id"] != pick["id"] and a.get("status") == "ACTIVE"]
        parents_ok = True
        for ent, kind in ((cam, "campaign"), (ads_et, "ad set")):
            if ent.get("status") == "ACTIVE":
                continue
            if blockers:
                parents_ok = False
                log.warning("   ⚠ %s is PAUSED but %d sibling ad(s) are ACTIVE — not touching it, "
                            "or they would start too: %s", kind, len(blockers),
                            ", ".join((b.get("name") or "")[:26] for b in blockers[:3]))
                continue
            g.update_status(ent["id"], "ACTIVE")
            log.info("   ▶ activated %s %s", kind, ent["id"])

        g.update_status(pick["id"], "ACTIVE")
        log.info("   ▶ activated ad %s", pick["id"])
        summary.append(f"  REOPEN {label:20} ad {pick['id']} ACTIVE"
                       + ("" if parents_ok else " ⚠ parent still PAUSED — activate it by hand"))

    # ── 3. SCALE ────────────────────────────────────────────────────────────────
    scale_campaigns: Dict[str, Dict[str, Any]] = {}
    for _, core in SCALE:
        for a in ads:
            if matches(a.get("name"), core) and a.get("effective_status") == "ACTIVE":
                c = a.get("campaign") or {}
                if c.get("id"):
                    scale_campaigns[c["id"]] = c

    log.info("═" * 88)
    log.info("SCALE candidates: %d campaign(s) holding a live scale winner", len(scale_campaigns))
    for cid, c in scale_campaigns.items():
        members = [a for a in ads if (a.get("campaign") or {}).get("id") == cid]
        still_bad = [a for a in members
                     if a["id"] not in closed_ids and a.get("effective_status") == "ACTIVE"
                     and any(matches(a.get("name"), core) for _, core in CLOSE)]
        name = (c.get("name") or "")[:34]
        if still_bad:
            log.warning("   ⏭ %s — still delivering a close-list ad, not raising", name)
            summary.append(f"  SCALE {name:26} skipped (bleeder still live)")
            continue
        cur = int(c["daily_budget"]) if c.get("daily_budget") else None
        if cur is None:
            log.info("   · %s — no CBO budget (ABO), skipped", name)
            summary.append(f"  SCALE {name:26} skipped (ABO, budget on ad set)")
            continue
        new = min(int(cur * BUMP), CAP_CENTS)
        if new <= cur:
            log.info("   · %s — already at RM%.0f (cap RM%.0f)", name, cur / 100, CAP_CENTS / 100)
            summary.append(f"  SCALE {name:26} already ≥ cap RM{CAP_CENTS/100:.0f}")
            continue
        g._request("POST", cid, data={"daily_budget": str(new)})
        log.info("   ⬆ %s  RM%.0f → RM%.0f/day", name, cur / 100, new / 100)
        summary.append(f"  SCALE {name:26} RM{cur/100:.0f} → RM{new/100:.0f}/day")

    log.info("═" * 88)
    for line in summary:
        log.info(line)
    final_summary(
        log, "Applied the 8/13 read: bleeders above the RM1300 hard stop are paused, the three "
             "sleeping winners (cheapest CPA135) are live again, and campaigns still holding a "
             "scale winner are up 50% (cap RM225/day). Because two of the five 1-1-5 winners were "
             "on the close list, their share now flows to the three that convert. Re-run the CPA "
             "workflow in ~3 days — the new 别再逼孩子喝牛奶 carousel is on 1 sale, far too few to "
             "scale on yet.")


if __name__ == "__main__":
    main()
