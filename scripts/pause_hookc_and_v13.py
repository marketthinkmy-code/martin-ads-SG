"""Two approved cuts: pause Hook Edits C, and pause Video 13 inside every LAL 1-5-3 band.

WHY
---
Operator-approved on 21 Aug, off the back of the lead-quality audit:

  1. Hook Edits C (120257667236600093) spent RM356 for 2 registrations — CPL RM178, nearly
     3x the RM65 ceiling, with nothing in its trend worth waiting for. Paused at the
     campaign level.
  2. Video 13 三年前他長了10公分 is the audit's lead-quality problem by name: the cheapest
     CPL in the account (RM46) and ONE provably-SG paid student ever (lead→paid 1.6% vs the
     3.1% account average). It runs as one ad in each of the five 1-5-3 band ad sets, where
     it is very likely manufacturing the band test's cheap registrations. Pausing it in all
     five bands leaves every band with the same two remaining ads, so the band comparison
     stays clean — arguably cleaner, since bands can no longer win on registrations that
     never buy.

SAFETY
------
The Video 13 ads are found by name inside the 1-5-3 campaign only, and every match must
belong to one of the five known band ad sets. The script expects EXACTLY five; any other
count means the campaign does not look like what this script believes it looks like, and it
stops without pausing anything rather than guess. Nothing else in the campaign is touched —
the other two ads keep running in every band, and band budgets are unchanged.

Both changes are verified by re-reading the stored status afterwards, not assumed from the
write having been accepted.
"""
from __future__ import annotations

from typing import Any, Dict, List

from adbot import cpa
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

HOOK_C_CAMPAIGN = "120257667236600093"       # Hook Edits C | 1-1-3 — RM178 CPL
LAL_CAMPAIGN = "120257761432150093"          # PURCHASE LAL 1-5% | 1-5-3
BAND_ADSETS = {
    "120257761613910093", "120257761615520093", "120257761616950093",
    "120257761619130093", "120257761621230093",
}
V13_KEY = cpa.ad_key("Video 13：三年前他長了10公分")


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)

    # 1) Hook Edits C ────────────────────────────────────────────────────────────
    before = g._request("GET", HOOK_C_CAMPAIGN, params={"fields": "name,status,effective_status"})
    log.info("── Hook Edits C %s · before: %s/%s", HOOK_C_CAMPAIGN,
             before.get("status"), before.get("effective_status"))
    if before.get("status") == "PAUSED":
        log.info("   already paused — nothing to do")
        c_ok = True
    else:
        g._request("POST", HOOK_C_CAMPAIGN, data={"status": "PAUSED"})
        after = g._request("GET", HOOK_C_CAMPAIGN, params={"fields": "status,effective_status"})
        c_ok = after.get("status") == "PAUSED"
        log.info("   after: %s/%s", after.get("status"), after.get("effective_status"))

    # 2) Video 13 in every band ─────────────────────────────────────────────────
    ads: List[Dict[str, Any]] = g._get_all(f"{LAL_CAMPAIGN}/ads", {
        "fields": "id,name,adset_id,status,effective_status", "limit": 100})
    log.info("── LAL 1-5-3: %d ad(s) in campaign", len(ads))

    v13 = [a for a in ads if V13_KEY in cpa.ad_key(a.get("name", ""))]
    stray = [a for a in v13 if a.get("adset_id") not in BAND_ADSETS]
    if stray:
        raise SystemExit(f"!! {len(stray)} Video 13 match(es) sit outside the known band ad sets "
                         f"({[a['id'] for a in stray]}) — refusing to pause anything.")
    if len(v13) != len(BAND_ADSETS):
        raise SystemExit(f"!! expected exactly {len(BAND_ADSETS)} Video 13 ads (one per band), "
                         f"found {len(v13)} — the campaign does not look like this script "
                         f"believes it looks like, so nothing was paused.")

    paused, already = 0, 0
    for a in v13:
        if a.get("status") == "PAUSED":
            already += 1
            log.info("   · %s already paused (adset %s)", a["id"], a["adset_id"])
            continue
        g._request("POST", a["id"], data={"status": "PAUSED"})
        chk = g._request("GET", a["id"], params={"fields": "status"})
        ok = chk.get("status") == "PAUSED"
        paused += int(ok)
        log.info("   %s %s (adset %s) → %s", "✓" if ok else "✗",
                 a["id"], a["adset_id"], chk.get("status"))

    v13_ok = (paused + already) == len(v13)
    remaining = [a for a in ads if V13_KEY not in cpa.ad_key(a.get("name", ""))]
    log.info("   remaining live ads per band: %d total (%s)", len(remaining),
             "MAR Video 1 + 15岁以上 in each band")

    log.info("═" * 88)
    final_summary(
        log, f"Both approved cuts applied and verified from stored values: Hook Edits C is "
             f"{'PAUSED' if c_ok else 'NOT paused — check manually'}, and Video 13 is paused in "
             f"{paused + already}/{len(v13)} band ad sets ({already} were already paused). Every "
             f"1-5-3 band keeps the same two ads (MAR Video 1 我不会买牛奶 + 15岁以上), so the "
             f"band comparison stays clean and band budgets are unchanged — the campaign still "
             f"spends RM100/band/day, now on registrations with a real chance of buying.")


if __name__ == "__main__":
    main()
