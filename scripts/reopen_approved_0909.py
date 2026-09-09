"""9 Sep approved reopens: Hook 9's sold chain + the two Hooks 0907 campaigns. LIVE.

Operator approved the full prescription ("都聽你的") after the CPL-panic diagnosis:
  1. Hook 9's chain back on — the one misclosed name whose economics are unambiguous
     (RM1,205 spend · 3 provably-SG sales · CPA RM402 vs the RM960 acceptable line).
  2. Hooks 0907 Parents + F&R campaigns back on — their eight pods were killed at RM52-64
     each with zero leads (~450 impressions at RM120 CPM: no verdict), while the SAME four
     hooks in the Food campaign are producing RM36-50 leads. +RM400/day.
  3. The other four misclosed names (CPA over the hard stop) STAY OFF — untouched.
  4. The verdict rule is codified separately in config + monitor (RM150-or-3-leads gate,
     RM100 auto-pause line).

Safety: Hook 9's wake uses the scoped release check (only ads the wake would actually
release get frozen; a legacy edit refusal on a releasable sibling aborts). The two 0907
campaigns contain exactly their four approved pods each — everything inside is meant to run,
so no muting is needed there. Verified from stored values; audit appended to
state/reopen_sold_chains_log.json; idempotent.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from adbot.clients.graph import GraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings
from adbot.state import now_iso

DELIVERING = ("ACTIVE", "IN_PROCESS", "PENDING_REVIEW")
LOG_PATH = Path("state") / "reopen_sold_chains_log.json"

HOOK9 = {"ad": "120240921209560093", "adset": "120240921209550093",
         "campaign": "120239099098710093", "label": "Hook 9 @ Interest F&R"}
CAMPAIGNS_0907 = [
    {"id": "120258189792440093", "label": "Hooks 0907 | Parents 3-17 + Engaged"},
    {"id": "120258189800520093", "label": "Hooks 0907 | F&R 興趣"},
]


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    audit: List[Dict[str, Any]] = []
    results: List[str] = []

    # ── 1) Hook 9's chain, scoped release check ─────────────────────────────────
    ad = g._request("GET", HOOK9["ad"], params={
        "fields": "status,effective_status,adset{id,status},campaign{id,status}"})
    adset, camp = ad.get("adset") or {}, ad.get("campaign") or {}
    if (ad.get("effective_status") or "") in DELIVERING:
        log.info("── %s already delivering", HOOK9["label"])
        results.append(f"{HOOK9['label']}: already live")
    else:
        camp_live = camp.get("status") == "ACTIVE"
        adset_live = adset.get("status") == "ACTIVE"
        camp_ads = g._get_all(f"{HOOK9['campaign']}/ads",
                              {"fields": "id,name,status,adset{id,status}", "limit": 200})
        blocked = None
        for a in camp_ads:
            if a["id"] == HOOK9["ad"] or a.get("status") != "ACTIVE":
                continue
            sib_adset = a.get("adset") or {}
            same = str(sib_adset.get("id")) == str(adset.get("id"))
            released = (same and not (camp_live and adset_live)) or \
                       (not same and not camp_live and sib_adset.get("status") == "ACTIVE")
            if not released:
                continue
            try:
                g._request("POST", a["id"], data={"status": "PAUSED"})
                log.info("   · sibling %s %s → PAUSED", a["id"], (a.get("name") or "")[:34])
                audit.append({"action": "pause_sibling", "ad": a["id"], "name": a.get("name")})
            except GraphError as e:
                blocked = (a, e)
                break
        if blocked is not None:
            a, e = blocked
            log.info("✗ %s: sibling %s rejects edits (%s) and would deliver — left untouched",
                     HOOK9["label"], a["id"], e)
            results.append(f"{HOOK9['label']}: SKIPPED (legacy sibling)")
        else:
            if ad.get("status") != "ACTIVE":
                g._request("POST", HOOK9["ad"], data={"status": "ACTIVE"})
            if not adset_live:
                g._request("POST", adset["id"], data={"status": "ACTIVE"})
            if not camp_live:
                g._request("POST", HOOK9["campaign"], data={"status": "ACTIVE"})
            fin = g._request("GET", HOOK9["ad"], params={"fields": "effective_status"})
            ok = (fin.get("effective_status") or "") in DELIVERING
            log.info("── %s: effective %s %s", HOOK9["label"], fin.get("effective_status"),
                     "✓" if ok else "✗")
            results.append(f"{HOOK9['label']}: {fin.get('effective_status')}")
            audit.append({"action": "reopen_chain", "chain": HOOK9["label"],
                          "ad": HOOK9["ad"], "effective": fin.get("effective_status")})

    # ── 2) the two Hooks 0907 campaigns — everything inside is approved to run ──
    for c in CAMPAIGNS_0907:
        cur = g._request("GET", c["id"], params={"fields": "name,status"})
        if cur.get("status") != "ACTIVE":
            g._request("POST", c["id"], data={"status": "ACTIVE"})
        ads = g._get_all(f"{c['id']}/ads", {"fields": "id,name,effective_status", "limit": 50})
        live = [a for a in ads if (a.get("effective_status") or "") in DELIVERING]
        log.info("── %s: campaign ACTIVE · %d/%d pods delivering", c["label"], len(live),
                 len(ads))
        for a in ads:
            log.info("   · %s %s", (a.get("name") or "")[:34], a.get("effective_status"))
        results.append(f"{c['label']}: {len(live)}/{len(ads)} pods live")
        audit.append({"action": "reopen_campaign", "campaign": c["id"],
                      "pods_live": len(live), "pods": len(ads)})

    prior = json.loads(LOG_PATH.read_text()) if LOG_PATH.exists() else []
    prior.append({"ts": now_iso(), "actions": audit})
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(prior, ensure_ascii=False, indent=2))

    final_summary(
        log, f"Approved reopens done: {'; '.join(results)}. The other four misclosed names "
             f"stay off as the operator left them. New verdict gates (RM150-or-3-leads, "
             f"RM100 auto-pause line) ship in the same push, so tonight's monitor cannot "
             f"re-kill these before they earn a real verdict.")


if __name__ == "__main__":
    main()
