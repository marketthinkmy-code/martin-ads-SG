"""Build the "Scale-Winners Broad A+" SG campaign: 1 broad Advantage+ CBO + 1 ad set +
the proven-winner ads — all PAUSED.

Point ADBOT_CONFIG at config/scale-winners.yaml. Two phases:

  1. build_1_1_10.build(units=[]) creates the campaign + ad set PAUSED with the full SG
     compliance setup (SINGAPORE_UNIVERSAL, verified advertiser identity, broad geo/age/
     locale, Advantage+ audience, excluded custom audiences, CBO budget) and NO detailed
     targeting — so Meta finds the audience itself.
  2. Each winner is located in the SG account by ad NAME (width/punctuation-robust via
     cpa.ad_key) and a new ad is created that REUSES its existing creative_id — same video,
     same copy, same UTM ad name, so paid-sale attribution keeps matching the winner.

WINNERS = the 4 distinct proven winners by SG CPL + the account's #1 PAID converter
(孩子15岁以上, borderline CPL but the top sales creative). The report's duplicate 5th row
('MAR Video 1: 我不会买牛奶' twice) is the SAME creative as the workhorse, so it appears once.
Idempotent: creative names already recorded in state/entities_scale_winners.json are skipped,
so a second dispatch only adds newly-listed winners and never duplicates ads.

It also prints, for each winner, the OTHER campaign(s) it currently runs in ("home campaigns")
so the operator can decide whether to shift that budget here.
"""
from __future__ import annotations

import json
from pathlib import Path

from adbot import cpa
from adbot.build_1_1_10 import build
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_DIR = Path("state")

# The 4 distinct winners (by SG-real CPL, last 7-14d). Matched by ad_key, so the exact
# width/spacing/colon of the live ad name does not have to be reproduced here.
WINNERS = [
    "MAR Video Hook 3: 准备早餐面包",          # CPL 36 — cheapest registrations
    "Video：H2 面包牛奶一点都不健康",           # CPL 41 — cheap + steady
    "MAR Video 5: 林書豪 story",              # CPL 56
    "MAR Video 1: 我不会买牛奶",               # CPL 62 — the workhorse (absorbs real budget)
    "Video: 孩子15岁以上还有机会长高吗?",       # CPL 66 (borderline) — account's #1 PAID converter (life 47)
]


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    conv = s.meta.conversion_domain_bare or None

    # 1) broad CBO skeleton (PAUSED, 0 ads)
    ent = build(g, s, units=[], captions={}, dry_run=False,
                label=s.meta.build.label, state_key=s.meta.build.state_key)
    campaign_id, adset_id = ent["campaign_id"], ent["adset_id"]

    # 2) index every ad in the account by ad_key(name) -> (name, creative_id, active?),
    #    and record which campaign(s) each name currently runs in (its "home").
    ads = g._get_all(f"{acct}/ads",
                     {"fields": "id,name,effective_status,creative{id},campaign{name}", "limit": 500})
    index: dict[str, tuple[str, str, bool]] = {}
    homes: dict[str, list[tuple[str, str]]] = {}
    for ad in ads:
        cid = (ad.get("creative") or {}).get("id")
        if not cid:
            continue
        key = cpa.ad_key(ad.get("name", ""))
        active = ad.get("effective_status") == "ACTIVE"
        camp = (ad.get("campaign") or {}).get("name", "∅")
        homes.setdefault(key, []).append((camp, ad.get("effective_status", "?")))
        # prefer an ACTIVE source ad; otherwise keep the first seen for this name
        if key not in index or (active and not index[key][2]):
            index[key] = (ad.get("name", ""), cid, active)

    # 3) resume: skip winners already built into this campaign
    path = STATE_DIR / f"{s.meta.build.state_key}.json"
    st = json.loads(path.read_text()) if path.exists() else {}
    built = set(st.get("built_content_ids", []))
    ad_ids = list(st.get("ad_ids", []))

    summary, missing = [], []
    for want in WINNERS:
        key = cpa.ad_key(want)
        if key in built:
            log.info("  skip %s (already built)", want)
            summary.append(f"  SKIP  {want}")
            continue
        hit = index.get(key)
        if not hit:
            log.warning("  ! winner not found in account: %s", want)
            missing.append(want)
            continue
        src_name, creative_id, _active = hit
        ad = g.create_ad(acct, name=src_name, adset_id=adset_id,
                         creative={"creative_id": creative_id}, status="PAUSED",
                         conversion_domain=conv)
        ad_ids.append(ad["id"])
        built.add(key)
        st.update({"campaign_id": campaign_id, "adset_id": adset_id,
                   "ad_ids": ad_ids, "built_content_ids": sorted(built)})
        path.write_text(json.dumps(st, ensure_ascii=False, indent=2))
        log.info("  + ad %s  ⟵ creative %s  (%s)", ad["id"], creative_id, src_name)
        summary.append(f"  +ad  {ad['id']}  ⟵ creative {creative_id}  ({src_name})")

    log.info("═" * 84)
    log.info("campaign_id: %s", campaign_id)
    log.info("adset_id:    %s", adset_id)
    for line in summary:
        log.info(line)
    if missing:
        log.warning("MISSING (add manually / re-check name): %s", ", ".join(missing))

    # where does each winner currently live? (exclude this new campaign so we show only the
    # OLD homes whose budget the operator might shift here)
    log.info("─" * 84)
    log.info("📍 Winners' current home campaign(s) — budget to consider shifting here:")
    for want in WINNERS:
        others = [(c, stt) for c, stt in homes.get(cpa.ad_key(want), [])
                  if "Scale-Winners" not in c]
        loc = "  ·  ".join(f"{c} [{stt}]" for c, stt in others) or "— (only in Scale-Winners now)"
        log.info("   %-32s → %s", want, loc)
    final_summary(
        log,
        f"Scale-Winners Broad A+ built PAUSED: 1 CBO (RM{s.meta.budget.daily_amount_myr:.0f}/day) "
        f"+ 1 broad ad set + {len(ad_ids)} winner ad(s). "
        f"Activate + set placements (FB Feed/Reels + IG Feed) in Ads Manager after review.")


if __name__ == "__main__":
    main()
