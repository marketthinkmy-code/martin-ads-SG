"""Build a 1-1-3 test campaign on the SG paid-list lookalike (1%-5%) — PAUSED.

Campaign: [SG] 儿童长高方程式 | LAL 1-5% Paid | 1-1-3
  1 CBO + 1 ad set targeted at Lookalike (SG, 1% to 5%) - Cust Paid List (SG) + the operator's
  three highest-LIFETIME-conversion ads.

WHICH THREE ADS
---------------
Ranked by lifetime registrations, which is what the operator asked to lead on:
    懒人包11 睡得多不等于长得快      655  (RM21,594 · CPL 33)
    懒人包9  女孩初经来临            400  (RM12,349 · CPL 31)
    MAR Video Hook 3 准备早餐面包    351  (RM17,653 · CPL 50)

They are reused by creative_id, so each new ad points at the SAME page post as the original.
Engagement pools onto one post instead of splitting, and the creative is reproduced exactly
rather than approximated.

TWO THINGS THAT MAKE THIS A REAL TEST AND NOT A REPEAT
------------------------------------------------------
1. All three have ZERO spend in the last 60 days — they are old ads that were switched off, so
   their lifetime totals are historical. 懒人包11 and 懒人包9 are from Oct 2024 / Jan 2025.
   Creative fatigue is a live risk and is exactly what this test measures.
2. 准备早餐面包 is on the close list in scripts/apply_0813_actions.py, at a 60-day CPA of 1459
   against a 1300 hard stop. It produces cheap REGISTRATIONS and expensive SALES. It is included
   because the operator picked on lifetime conversions and it genuinely ranks third, but judge it
   on CPA from the paid-list sheet, not on the CPL this campaign will show.

TARGETING
---------
advantage_audience is 0 deliberately. Left at 1, Meta treats the lookalike as a suggestion and
expands beyond it, which would make it impossible to say whether the lookalike worked. Exclusions
carry the config's standing list PLUS the new SG seed itself, so existing buyers are not paid for
again in a prospecting campaign.

Everything is created PAUSED. The lookalike also needs a few hours to finish sizing before it can
deliver at all.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from adbot.build_1_1_10 import build
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_DIR = Path("state")
STATE_KEY = "entities_lal_1_5_paid"
PREFIX = "[SG] 儿童长高方程式"
LABEL = "LAL 1-5% Paid | 1-1-3"
ADSET_NAME = "LAL 1-5% Cust Paid List (SG)"
DAILY_MYR = 100

LOOKALIKE_ID = "120257737609450093"     # Lookalike (SG, 1% to 5%) - Cust Paid List (SG)
SEED_ID = "120257737609370093"          # the seed itself — excluded, they already bought

ADS: List[Dict[str, str]] = [
    {"key": "lazy11", "creative_id": "120213342099800093",
     "name": "懒人包11：不是让孩子睡得多就长得快 (lifetime 655)"},
    {"key": "lazy9", "creative_id": "120215302591520093",
     "name": "懒人包9：女孩初经来临 (lifetime 400)"},
    {"key": "bread", "creative_id": "562113746716671",
     "name": "MAR Video Hook 3：准备早餐面包 (lifetime 351)"},
]


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    conv = s.meta.conversion_domain_bare or None

    s.naming.prefix = PREFIX
    s.meta.budget.level = "CAMPAIGN"
    s.meta.budget.daily_amount_myr = DAILY_MYR

    excl = list(s.meta.targeting.excluded_custom_audiences or [])
    if SEED_ID not in excl:
        excl.append(SEED_ID)

    spec: Dict[str, Any] = {
        "geo_locations": {"countries": s.meta.targeting.countries or ["SG"]},
        "age_min": 25, "age_max": 65,
        "custom_audiences": [{"id": LOOKALIKE_ID}],
        "excluded_custom_audiences": [{"id": i} for i in excl],
        "locales": s.meta.targeting.locales or [1004],
        # 0, not 1: Advantage+ audience treats the lookalike as a hint and expands past it, which
        # would leave us unable to say whether the lookalike itself performed.
        "targeting_automation": {"advantage_audience": 0},
    }
    log.info("targeting → lookalike %s · %d exclusion(s) · age 25-65 · adv=0",
             LOOKALIKE_ID, len(excl))

    st_path = STATE_DIR / f"{STATE_KEY}.json"
    st = json.loads(st_path.read_text()) if st_path.exists() else {}
    ent = build(g, s, units=[], captions={}, dry_run=False, label=LABEL,
                state_key=STATE_KEY, adset_name=ADSET_NAME,
                targeting_override=None if st.get("adset_id") else spec)
    campaign_id, adset_id = ent["campaign_id"], ent["adset_id"]

    st = json.loads(st_path.read_text()) if st_path.exists() else {}
    built = set(st.get("built_ad_keys", []))
    ad_ids: List[str] = list(st.get("ad_ids", []))
    for a in ADS:
        if a["key"] in built:
            log.info("   skip %s (already built)", a["name"])
            continue
        ad = g.create_ad(acct, name=a["name"], adset_id=adset_id,
                         creative={"creative_id": a["creative_id"]},
                         status="PAUSED", conversion_domain=conv)
        ad_ids.append(ad["id"])
        built.add(a["key"])
        st.update({"campaign_id": campaign_id, "adset_id": adset_id,
                   "ad_ids": ad_ids, "built_ad_keys": sorted(built)})
        st_path.write_text(json.dumps(st, ensure_ascii=False, indent=2))
        log.info("   + ad %s ⟵ creative %s (%s)", ad["id"], a["creative_id"], a["name"][:40])

    log.info("═" * 88)
    log.info("campaign=%s  adset=%s  ads=%d", campaign_id, adset_id, len(ad_ids))
    final_summary(
        log, f"LAL test built PAUSED: {len(ad_ids)} ads on Lookalike (SG, 1%-5%) of the SG paid "
             f"list, CBO RM{DAILY_MYR}/day, Advantage+ audience OFF so the lookalike is actually "
             f"what gets tested. Ads reuse the original creatives by id, so each points at the "
             f"same page post as the ad that earned those lifetime numbers. ⚠ All three have zero "
             f"60-day spend and two date from Oct 2024 / Jan 2025 — check each preview's landing "
             f"page still resolves before activating, since a post-based creative carries its own "
             f"link. ⚠ 准备早餐面包 sits on the 8/13 close list at 60d CPA 1459 vs a 1300 hard "
             f"stop: judge it on sheet CPA, not on the CPL shown here.")


if __name__ == "__main__":
    main()
