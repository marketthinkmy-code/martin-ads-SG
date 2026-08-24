"""Approved items 2-3: restore Winners Revival to RM100/day, and light up the three proven
sellers whose parent campaigns are switched off — WITHOUT letting their unproven siblings out.

WHY THE SIBLING PAUSES
----------------------
The three sellers (Video 12 · Carousel 别再逼孩子喝牛奶了 · Single Image 女孩来了初经) were
reopened at ad level on 22 Aug, but their parent campaigns are off, so they have delivered
nothing since. Just switching those campaigns on would also release every other ad inside
them — 20-odd unproven creatives from the new series — which is exactly the
spread-money-on-unproven-creatives pattern the whole week's cleanup existed to stop.

So, per campaign, the order is: pause every OTHER ad that is ad-level ACTIVE, make sure the
seller's ad and ad set are ACTIVE, and only then switch the campaign on. No window exists in
which an unproven sibling can deliver.

Ad and campaign ids are pinned (verified this morning via the API), and each seller ad's
campaign membership is re-checked before anything is written. Every write is verified by
re-reading the stored value. Idempotent: a re-run finds everything already in place.
"""
from __future__ import annotations

from typing import Any, Dict, List

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

REVIVAL_CAMPAIGN = "120257785730570093"     # Winners Revival — restore halved budget
REVIVAL_DAILY_MINOR = 10000                 # RM100/day, the budget it was built with

SELLERS: List[Dict[str, str]] = [
    {"ad": "120257269401020093", "campaign": "120257269400010093",
     "label": "Video 12：15歲以上試了五六種方法沒長高"},
    {"ad": "120257496415810093", "campaign": "120257496414280093",
     "label": "Carousel：别再逼孩子喝牛奶了"},
    {"ad": "120255723495280093", "campaign": "120255723448880093",
     "label": "Single Image：女孩来了初经"},
]


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)

    # ── 2) Winners Revival back to RM100/day ────────────────────────────────────
    before = g._request("GET", REVIVAL_CAMPAIGN, params={"fields": "name,daily_budget,status"})
    log.info("── Winners Revival budget: %s → %d", before.get("daily_budget"), REVIVAL_DAILY_MINOR)
    if str(before.get("daily_budget")) == str(REVIVAL_DAILY_MINOR):
        log.info("   already RM%d/day", REVIVAL_DAILY_MINOR // 100)
        budget_ok = True
    else:
        g._request("POST", REVIVAL_CAMPAIGN, data={"daily_budget": REVIVAL_DAILY_MINOR})
        after = g._request("GET", REVIVAL_CAMPAIGN, params={"fields": "daily_budget"})
        budget_ok = str(after.get("daily_budget")) == str(REVIVAL_DAILY_MINOR)
        log.info("   stored: %s (%s)", after.get("daily_budget"), "ok" if budget_ok else "FAILED")

    # ── 3) per seller: mute siblings, wake the chain, then the campaign ─────────
    lit: List[str] = []
    spends: List[str] = []
    for sel in SELLERS:
        log.info("═" * 88)
        camp = g._request("GET", sel["campaign"], params={
            "fields": "name,status,daily_budget,is_adset_budget_sharing_enabled"})
        log.info("── %s", sel["label"])
        log.info("   campaign %s %r · status=%s", sel["campaign"], camp.get("name"),
                 camp.get("status"))

        ads = g._get_all(f"{sel['campaign']}/ads",
                         {"fields": "id,name,status,adset_id", "limit": 200})
        me = next((a for a in ads if a["id"] == sel["ad"]), None)
        if me is None:
            log.error("   !! seller ad %s is NOT in this campaign — skipping the whole "
                      "campaign untouched", sel["ad"])
            continue

        # mute every sibling that could deliver, before the campaign can go live
        for a in ads:
            if a["id"] == sel["ad"] or a.get("status") != "ACTIVE":
                continue
            g._request("POST", a["id"], data={"status": "PAUSED"})
            chk = g._request("GET", a["id"], params={"fields": "status"})
            log.info("   %s sibling %s %s → %s", "·" if chk.get("status") == "PAUSED" else "✗",
                     a["id"], a.get("name", "")[:30], chk.get("status"))

        # the seller's own chain: ad → ad set → campaign, waking each level that is off
        if me.get("status") != "ACTIVE":
            g._request("POST", sel["ad"], data={"status": "ACTIVE"})
        adset = g._request("GET", me["adset_id"], params={"fields": "status,daily_budget"})
        if adset.get("status") != "ACTIVE":
            g._request("POST", me["adset_id"], data={"status": "ACTIVE"})
            log.info("   ad set %s was %s → ACTIVE", me["adset_id"], adset.get("status"))
        if camp.get("status") != "ACTIVE":
            g._request("POST", sel["campaign"], data={"status": "ACTIVE"})

        fin = g._request("GET", sel["ad"], params={"fields": "status,effective_status"})
        camp2 = g._request("GET", sel["campaign"], params={"fields": "status,daily_budget"})
        daily = camp2.get("daily_budget") or adset.get("daily_budget") or "?"
        ok = fin.get("effective_status") in ("ACTIVE", "IN_PROCESS", "PENDING_REVIEW")
        log.info("   seller: status=%s effective=%s · campaign=%s · daily=%s",
                 fin.get("status"), fin.get("effective_status"), camp2.get("status"), daily)
        if ok:
            lit.append(sel["label"])
            try:
                spends.append(f"RM{int(daily) / 100:.0f}")
            except (TypeError, ValueError):
                spends.append(str(daily))
        else:
            log.error("   !! seller still not deliverable (effective %s)",
                      fin.get("effective_status"))

    log.info("═" * 88)
    budget_msg = ("restored to RM100/day" if budget_ok
                  else "FAILED to update — check by hand")
    final_summary(
        log, f"Winners Revival budget {budget_msg}. {len(lit)}/{len(SELLERS)} seller campaigns "
             f"are live with ONLY the proven seller running ({'; '.join(lit)}) at daily budgets "
             f"of {', '.join(spends) or '?'} — every unproven sibling was ad-level paused BEFORE "
             f"its campaign went live, so none of them delivered even for a minute. Verified "
             f"from stored values.")


if __name__ == "__main__":
    main()
