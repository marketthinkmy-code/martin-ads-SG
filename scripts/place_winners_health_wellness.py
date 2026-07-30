"""Place Video 8（1）⭐ + Hook 7 into the LIVE Health & Wellness ad set (operator-approved
2026-07-30) — LIVE writes.

Both winners' existing SG copies all sit under PAUSED ad sets, so reactivating them in place
does not deliver. Instead we add them as NEW ACTIVE ads into the currently-converting Health &
Wellness ad set, REUSING each creative's existing creative_id (no video re-upload).

Robustness:
  · Health & Wellness target is auto-located — several same/near-named ad sets exist, so we take
    the ACTIVE one with the most 60-day SG spend (the real converter). Abort if none is live.
  · Each winner's creative_id is taken from an existing SG ad copy (prefer an ACTIVE-configured
    one). Report NOT FOUND if the creative can't be located.
  · Idempotent — if the winner's creative is already an ad in the target ad set, skip.
Prints a full audit trail.
"""
from __future__ import annotations

import datetime as dt

from adbot import cpa
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

ad_key = cpa.ad_key
HW_SUB = "healthwellness"  # ad_key("Health & Wellness") / ("Health & wellness")

TARGETS = [
    {"label": "Video 8（1）新马版牛奶迷思 (⭐)", "core": "新马版主打牛奶迷思"},
    {"label": "Hook 7 担心孩子的高度",          "core": "担心孩子的高度"},
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
    conv = s.meta.conversion_domain_bare or None
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d60, until = (today - dt.timedelta(days=60)).isoformat(), today.isoformat()

    adsets = g._get_all(f"{acct}/adsets",
                        {"fields": "id,name,effective_status,campaign_id", "limit": 500})
    camps = g._get_all(f"{acct}/campaigns", {"fields": "id,name", "limit": 300})
    camp_by_id = {c["id"]: c for c in camps}
    aset_sp60 = {r.get("adset_id"): _f(r.get("spend")) for r in g.account_insights(
        acct, level="adset", fields="adset_id,spend", time_range={"since": d60, "until": until})}

    # ── locate the live Health & Wellness ad set ────────────────────────────────
    cands = [a for a in adsets if HW_SUB in ad_key(a.get("name"))]
    log.info("Health & Wellness candidates: %d", len(cands))
    for a in sorted(cands, key=lambda a: -aset_sp60.get(a["id"], 0.0)):
        log.info("   [%s] eff=%s · 60d RM%.0f · adset '%s' · camp '%s'",
                 a["id"], a.get("effective_status"), aset_sp60.get(a["id"], 0.0),
                 (a.get("name") or "")[:34], (camp_by_id.get(a.get("campaign_id"), {}).get("name") or "")[:44])

    live = [a for a in cands if a.get("effective_status") == "ACTIVE" and aset_sp60.get(a["id"], 0.0) > 0] \
        or [a for a in cands if a.get("effective_status") == "ACTIVE"]
    if not live:
        raise SystemExit("!! no ACTIVE Health & Wellness ad set found — aborting (nothing created). "
                         "It may be paused right now; unpause it or pick another live ad set.")
    target = max(live, key=lambda a: aset_sp60.get(a["id"], 0.0))
    tid = target["id"]
    log.info("→ TARGET ad set [%s] '%s'  (camp '%s' · 60d RM%.0f)", tid,
             target.get("name"), camp_by_id.get(target.get("campaign_id"), {}).get("name"),
             aset_sp60.get(tid, 0.0))

    # ── all ads (with creative id) — find each winner's creative + existing target ads ──
    ads = g._get_all(f"{acct}/ads",
                     {"fields": "id,name,status,adset_id,creative{id}", "limit": 500})
    existing_target_keys = [ad_key(a.get("name")) for a in ads if a.get("adset_id") == tid]

    summary = []
    for t in TARGETS:
        ck = ad_key(t["core"])
        srcs = [a for a in ads if ck in ad_key(a.get("name")) and (a.get("creative") or {}).get("id")]
        if not srcs:
            log.warning("‼ %s — no existing SG ad with a creative id found; cannot reuse", t["label"])
            summary.append(f"  ❓ {t['label']}: creative NOT FOUND — skipped")
            continue
        if any(ck in k for k in existing_target_keys):
            log.info("• %s already present in target ad set — skip (idempotent)", t["label"])
            summary.append(f"  ⏩ {t['label']}: already in Health & Wellness — skipped")
            continue
        src = next((a for a in srcs if a.get("status") == "ACTIVE"), srcs[0])
        cid = src["creative"]["id"]
        name = src.get("name")
        ad = g.create_ad(acct, name=name, adset_id=tid,
                         creative={"creative_id": cid}, status="ACTIVE", conversion_domain=conv)
        log.info("▶ CREATED ad %s  '%s'  (reused creative %s) → ACTIVE in Health & Wellness",
                 ad["id"], name, cid)
        summary.append(f"  ▶️ {t['label']}: new ACTIVE ad {ad['id']} (creative {cid})")

    log.info("═" * 90)
    for line in summary:
        log.info(line)
    final_summary(log, f"Placed winners into Health & Wellness [{tid}] as ACTIVE ads (reused creatives). "
                       "CPA rescue in the monitor protects them. Watch a few days — do not churn budget.")


if __name__ == "__main__":
    main()
