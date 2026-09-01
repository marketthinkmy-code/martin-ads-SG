"""Reopen Hook 9's own chain, at RM100/day. Nothing else. LIVE.

Operator (1 Sep), after reviewing the 誤關 numbers ad by ad: "Hook 9 开回去就好, RM100/day".
Hook 9 is the one whose record is unambiguous — RM727 lifetime spend, 3 provably-SG sales,
CPA RM242 vs the RM740 target — and it was re-closed at ad level after the 30 Aug reopen.

Scope, exactly:
  · the pinned ad 120240921209560093 (Hook 9 in the old Interest: Family and Relationships
    campaign — the chain its 26 Aug sale's own UTM points at, same chain as the 30 Aug run);
  · its budget level set to RM100/day — on the campaign if the campaign carries the budget
    (CBO), else on the ad set (this chain ran ABO RM30/day). If the 2025-era entity rejects
    the budget edit (legacy "website URL" validation), the chain is STILL woken at its old
    budget and the failure is reported loudly — 开回去 is the core ask;
  · before waking, any ad-level-ACTIVE sibling that the wake would release is paused first
    (scoped: the ad set's own ads; campaign-wide only if the campaign itself is off);
  · verified from stored values; actions appended to state/reopen_sold_chains_log.json.

Re-kill safety: the 26 Aug sale sits inside the nightly monitor's 60-day CPA-rescue window.
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

AD_ID = "120240921209560093"      # Hook 9 · Interest: Family and Relationships · sold 26 Aug
DAILY_MINOR = 10000               # RM100/day
DELIVERING = ("ACTIVE", "IN_PROCESS", "PENDING_REVIEW")
LOG_PATH = Path("state") / "reopen_sold_chains_log.json"


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    audit: List[Dict[str, Any]] = []

    ad = g._request("GET", AD_ID, params={
        "fields": "name,status,effective_status,"
                  "adset{id,name,status,daily_budget},campaign{id,name,status,daily_budget}"})
    adset, camp = ad.get("adset") or {}, ad.get("campaign") or {}
    log.info("── %r · ad=%s eff=%s · adset %s %s (RM%s) · campaign %s %s (RM%s)",
             ad.get("name"), ad.get("status"), ad.get("effective_status"),
             adset.get("id"), adset.get("status"),
             (int(adset["daily_budget"]) // 100) if adset.get("daily_budget") else "—",
             camp.get("id"), camp.get("status"),
             (int(camp["daily_budget"]) // 100) if camp.get("daily_budget") else "—")

    # ── budget → RM100/day on whichever level carries it ────────────────────────
    budget_holder = camp if camp.get("daily_budget") else adset
    budget_note = f"RM{DAILY_MINOR // 100}/day"
    if str(budget_holder.get("daily_budget")) == str(DAILY_MINOR):
        log.info("   budget already %s", budget_note)
    else:
        try:
            g._request("POST", budget_holder["id"], data={"daily_budget": DAILY_MINOR})
            after = g._request("GET", budget_holder["id"], params={"fields": "daily_budget"})
            stored = int(after.get("daily_budget") or 0)
            budget_note = f"RM{stored // 100}/day (stored)"
            log.info("   budget %s → %s on %s", budget_holder.get("daily_budget"),
                     after.get("daily_budget"), budget_holder["id"])
            audit.append({"action": "set_budget", "entity": budget_holder["id"],
                          "daily_budget": after.get("daily_budget")})
        except GraphError as e:
            budget_note = (f"UNCHANGED RM{int(budget_holder.get('daily_budget') or 0) // 100}"
                           f"/day — legacy entity rejected the edit ({e})")
            log.info("   !! budget edit rejected: %s — waking at the old budget anyway", e)

    # ── freeze what the wake would release ──────────────────────────────────────
    camp_live = camp.get("status") == "ACTIVE"
    adset_live = adset.get("status") == "ACTIVE"
    camp_ads = g._get_all(f"{camp['id']}/ads",
                          {"fields": "id,name,status,adset{id,status}", "limit": 200})
    for a in camp_ads:
        if a["id"] == AD_ID or a.get("status") != "ACTIVE":
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
            raise SystemExit(f"!! sibling {a['id']} rejects edits ({e}) and would deliver — "
                             f"nothing was woken; open this one in Ads Manager by hand.")

    # ── wake ad → ad set → campaign, only levels that are off ───────────────────
    if ad.get("status") != "ACTIVE":
        g._request("POST", AD_ID, data={"status": "ACTIVE"})
    if not adset_live:
        g._request("POST", adset["id"], data={"status": "ACTIVE"})
    if not camp_live:
        g._request("POST", camp["id"], data={"status": "ACTIVE"})

    fin = g._request("GET", AD_ID, params={"fields": "status,effective_status"})
    ok = (fin.get("effective_status") or "") in DELIVERING
    audit.append({"action": "reopen_chain", "ad": AD_ID, "adset": adset.get("id"),
                  "campaign": camp.get("id"), "effective": fin.get("effective_status"),
                  "budget": budget_note})
    prior = json.loads(LOG_PATH.read_text()) if LOG_PATH.exists() else []
    prior.append({"ts": now_iso(), "actions": audit})
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(prior, ensure_ascii=False, indent=2))

    if not ok:
        raise SystemExit(f"!! Hook 9 still not deliverable (effective "
                         f"{fin.get('effective_status')}) — check in Ads Manager.")
    final_summary(
        log, f"Hook 9 is back on at {budget_note}: ad {AD_ID} effective "
             f"{fin.get('effective_status')} in its own sold chain. Nothing else was opened; "
             f"released siblings (if any) were paused first. Its 26 Aug sale keeps it inside "
             f"the nightly monitor's CPA-rescue window.")


if __name__ == "__main__":
    main()
