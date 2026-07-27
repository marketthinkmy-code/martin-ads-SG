"""Operator-approved SG consolidation (2026-07-27) — LIVE writes.

  ⬆️ Scale-Winners Broad A+     → RM250/day (fund the best campaign — CPL 59, most sales)
  🔴 Housewife 1-1-3            → PAUSED (over-CPL, weak paid conversion)
  🔴 Food & Drink + Milk 1-1-3  → PAUSED (cheap regs, ~no paid sales)
  🔴 Scale-CBO 2               → PAUSED (hollowed out to 1 ad, CPL 88)
  ▶️ Re-activate the Scale-Winners winner ads (bring the flagship back to full strength)

Campaigns are matched by name tokens + ACTIVE status (must be exactly 1, else SKIP — never
guess). Winner ad ids come from state/entities_scale_winners.json. Prints an audit trail.
AFTER THIS: leave the account 3-5 days — repeated budget changes reset Meta's learning, which
is what caused the CPL instability.
"""
from __future__ import annotations

import json
from pathlib import Path

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

WINNERS_STATE = Path("state/entities_scale_winners.json")


def _norm(s: str) -> str:
    return " ".join((s or "").split()).lower()


CAMPAIGN_ACTIONS = [
    {"label": "Scale-Winners → RM250",           "has": ["scale-winners"],               "set_budget": 25000},
    {"label": "Housewife 1-1-3 → PAUSED",         "has": ["housewife", "1-1-3"],          "set_status": "PAUSED"},
    {"label": "Food & Drink + Milk 1-1-3 → PAUSED", "has": ["food", "drink", "milk", "1-1-3"], "set_status": "PAUSED"},
    {"label": "Scale-CBO 2 → PAUSED",             "has": ["scale-cbo 2"],                 "set_status": "PAUSED"},
]


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path

    camps = g._get_all(f"{acct}/campaigns",
                       {"fields": "id,name,effective_status,daily_budget", "limit": 300})

    def cents(c) -> int:
        try:
            return int(c.get("daily_budget") or 0)
        except (TypeError, ValueError):
            return 0

    summary = []
    for a in CAMPAIGN_ACTIONS:
        m = [c for c in camps
             if all(t in _norm(c.get("name")) for t in a["has"])
             and c.get("effective_status") == "ACTIVE"]
        if len(m) != 1:
            log.error("⏭ SKIP %s — %d ACTIVE matches (need exactly 1)", a["label"], len(m))
            for cc in m:
                log.error("       cand [%s] RM%.0f '%s'", cc["id"], cents(cc) / 100, cc.get("name"))
            summary.append(f"  ⏭ SKIP {a['label']} ({len(m)} matches)")
            continue
        c = m[0]
        cid, nm = c["id"], c.get("name")
        if "set_budget" in a:
            g._request("POST", cid, data={"daily_budget": str(a["set_budget"])})
            summary.append(f"  ⬆️ RM{cents(c)/100:.0f}→RM{a['set_budget']/100:.0f}  {nm}  [{cid}]")
        else:
            g.update_status(cid, a["set_status"])
            summary.append(f"  🔴 → {a['set_status']}  {nm}  [{cid}]")
        log.info("✔ %s [%s]", a["label"], cid)

    # re-activate the Scale-Winners winner ads (already-active ones are harmless no-ops)
    if WINNERS_STATE.exists():
        ad_ids = json.loads(WINNERS_STATE.read_text()).get("ad_ids", [])
        ok = 0
        for aid in ad_ids:
            try:
                g.update_status(aid, "ACTIVE")
                ok += 1
                log.info("▶ set ACTIVE ad %s", aid)
            except Exception as e:  # noqa: BLE001
                log.warning("! could not activate %s: %s", aid, e)
        summary.append(f"  ▶️ Scale-Winners winner ads set ACTIVE: {ok}/{len(ad_ids)}")
    else:
        summary.append("  ⏭ winners state missing — skipped ad reactivation")

    log.info("═" * 90)
    for line in summary:
        log.info(line)
    final_summary(log, "SG consolidation applied. NOW LEAVE IT 3-5 DAYS — no more budget changes "
                       "(repeated changes reset learning and cause the CPL instability).")


if __name__ == "__main__":
    main()
