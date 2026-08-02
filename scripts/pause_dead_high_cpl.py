"""Pause the 2 dead high-CPL SG ads (operator-approved 2026-08-02) — LIVE writes.

Both are high-CPL creatives that, over 30 days of real spend, produced ZERO provably-SG
sales — no reason to keep any copy delivering. Matched by a DISTINCTIVE core phrase inside
the ad name (NFKC/width/punctuation-robust via cpa.ad_key; cores are unique and are NOT reused
in any winner stack — these are losers, not winners, so no collision with a paid creative):

  · Extra Video 1 - 鼻子敏感            core 鼻子敏感        (30d ~RM566, 0 SG sales, 18d)
  · MAY Video Hook 1: 10 个孩子会有 8 个  core 10个孩子会有8个  (30d ~RM444, 0 SG sales, 18d)

For every SG ad whose name contains a target core we print its full chain (ad status ·
ad-set eff-status · campaign · 30d spend). We then PAUSE a copy only when its own status is
ACTIVE — flipping just that ad's switch off, never its parent (leaving sibling ads untouched).
Copies already PAUSED are reported and left alone (idempotent). Prints a full audit trail.

Note 鼻子敏感 (this loser) is DISTINCT from Video 1 孩子如果有鼻窦炎 (鼻窦炎) — different chars,
different creative; the core key won't collide.
"""
from __future__ import annotations

import datetime as dt

from adbot import cpa
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

ad_key = cpa.ad_key

TARGETS = [
    {"label": "Extra Video 1 鼻子敏感",   "core": "鼻子敏感"},
    {"label": "MAY Video Hook 1 10个孩子会有8个", "core": "10个孩子会有8个"},
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
    d30 = (today - dt.timedelta(days=30)).isoformat()
    until = today.isoformat()

    camps = g._get_all(f"{acct}/campaigns", {"fields": "id,name,effective_status", "limit": 300})
    camp_by_id = {c["id"]: c for c in camps}
    ads = g._get_all(f"{acct}/ads", {
        "fields": "id,name,status,effective_status,campaign_id,adset{id,name,effective_status}",
        "limit": 500})
    sp30 = {r.get("ad_id"): _f(r.get("spend")) for r in g.account_insights(
        acct, level="ad", fields="ad_id,spend", time_range={"since": d30, "until": until})}

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

        paused = already = 0
        for a in matches:
            adset = a.get("adset") or {}
            camp = camp_by_id.get(a.get("campaign_id"), {})
            chain = (f"ad[{a['id']}] '{(a.get('name') or '∅')[:36]}' status={a.get('status')}/"
                     f"eff={a.get('effective_status')} · adset '{(adset.get('name') or '∅')[:30]}' "
                     f"eff={adset.get('effective_status')} · camp '{(camp.get('name') or '∅')[:36]}' "
                     f"· 30d RM{sp30.get(a['id'], 0.0):.0f}")
            if a.get("status") == "ACTIVE":
                g.update_status(a["id"], "PAUSED")
                paused += 1
                log.info("   ⏸ PAUSED  %s", chain)
            else:
                already += 1
                log.info("   ✓ already paused — left alone  %s", chain)

        bits = []
        if paused:
            bits.append(f"⏸ paused {paused}")
        if already:
            bits.append(f"already-paused {already}")
        summary.append(f"  {t['label']}: {', '.join(bits) or 'no action'}")

    log.info("═" * 90)
    for line in summary:
        log.info(line)
    final_summary(log, "Pause dead high-CPL ads done — flipped only ACTIVE copies of the two "
                       "zero-SG-sale losers (鼻子敏感 · 10个孩子会有8个) to PAUSED. Parents/siblings "
                       "untouched. Any 'NOT FOUND' means the name changed — re-check by hand.")


if __name__ == "__main__":
    main()
