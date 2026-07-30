"""Reopen the 3 cheap paused SG winners (operator-approved 2026-07-30) — LIVE writes.

Targets, matched by a DISTINCTIVE core phrase inside the ad name (robust to prefix/width
differences; cores are unique enough not to collide — note 8（1） is 新马版主打牛奶迷思, NOT
the separate 麵包牛奶 creative):

  · MAR Video 8（1）：新马版主打牛奶迷思   core 新马版主打牛奶迷思   (60d CPA ~758, 6 sales — the ⭐)
  · Hook 7：担心孩子的高度…              core 担心孩子的高度        (60d CPA ~652)
  · MAR Video Hook 3：准备早餐面包        core 准备早餐面包          (60d CPA ~864)

For every SG ad whose name contains a target core we print its full chain (ad status ·
ad-set eff-status · campaign · 60d spend). We then ACTIVATE a copy only when it is PAUSED
*and* its ad set is effectively ACTIVE — i.e. reactivation will actually deliver. Copies whose
parent ad set/campaign is paused are reported but NOT touched (waking a parent would affect
other ads, and reactivating an ad under a dead parent is a silent no-op) — those get flagged so
the operator can decide (open the parent, or clone the creative into the live line). Idempotent:
already-active copies are left alone. Prints a full audit trail.
"""
from __future__ import annotations

import datetime as dt

from adbot import cpa
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

ad_key = cpa.ad_key

TARGETS = [
    {"label": "Video 8（1）新马版牛奶迷思 (⭐)", "core": "新马版主打牛奶迷思"},
    {"label": "Hook 7 担心孩子的高度",          "core": "担心孩子的高度"},
    {"label": "Hook 3 准备早餐面包",            "core": "准备早餐面包"},
]


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d60 = (today - dt.timedelta(days=60)).isoformat()
    until = today.isoformat()

    camps = g._get_all(f"{acct}/campaigns", {"fields": "id,name,effective_status", "limit": 300})
    camp_by_id = {c["id"]: c for c in camps}
    ads = g._get_all(f"{acct}/ads", {
        "fields": "id,name,status,effective_status,campaign_id,adset{id,name,effective_status}",
        "limit": 500})
    sp60 = {r.get("ad_id"): _f(r.get("spend")) for r in g.account_insights(
        acct, level="ad", fields="ad_id,spend", time_range={"since": d60, "until": until})}

    summary = []
    for t in TARGETS:
        ck = ad_key(t["core"])
        matches = [a for a in ads if ck in ad_key(a.get("name"))]
        log.info("═" * 90)
        log.info("TARGET %s   (core=%r)  — %d matching SG ad(s)", t["label"], t["core"], len(matches))
        if not matches:
            log.warning("   ‼ NOT FOUND in SG account — no ad name contains this core")
            summary.append(f"  ❓ {t['label']}: NOT FOUND in SG account")
            continue

        reopened = already = blocked = 0
        for a in matches:
            adset = a.get("adset") or {}
            aset_eff = adset.get("effective_status")
            camp = camp_by_id.get(a.get("campaign_id"), {})
            chain = (f"ad[{a['id']}] status={a.get('status')}/eff={a.get('effective_status')} · "
                     f"adset '{(adset.get('name') or '∅')[:34]}' eff={aset_eff} · "
                     f"camp '{(camp.get('name') or '∅')[:40]}' · 60d RM{sp60.get(a['id'], 0.0):.0f}")
            if a.get("status") == "PAUSED" and aset_eff == "ACTIVE":
                g.update_status(a["id"], "ACTIVE")
                reopened += 1
                log.info("   ▶ REOPENED  %s", chain)
            elif a.get("status") == "PAUSED":
                blocked += 1
                log.info("   ⏸ SKIP (parent not active — won't deliver)  %s", chain)
            else:
                already += 1
                log.info("   ✓ already ACTIVE-configured  %s", chain)

        bits = []
        if reopened:
            bits.append(f"▶ reopened {reopened}")
        if already:
            bits.append(f"already-active {already}")
        if blocked:
            bits.append(f"⏸ {blocked} blocked (parent paused)")
        summary.append(f"  {t['label']}: {', '.join(bits) or 'no action'}")

    log.info("═" * 90)
    for line in summary:
        log.info(line)
    final_summary(log, "Reopen paused winners done — reactivated only deliver-safe copies (paused ad "
                       "under a live ad set). Any 'blocked (parent paused)' or 'NOT FOUND' needs a "
                       "placement decision. CPA rescue in the monitor protects these (real sales).")


if __name__ == "__main__":
    main()
