"""Revive the four starved proven sellers: 1 CBO + 1 ad set + 4 ads, PAUSED.

Campaign: [SG] 儿童长高方程式 | Winners Revival | 1-1-4

WHY THESE FOUR
--------------
The lead-quality audit (lead_quality_audit.py) ranked every creative by provably-SG paid
students, not registrations. Exactly four cleared the bar of >= 4 SG sales at a lifetime CPA
inside the RM740 target while receiving RM0 of the last 30 days' budget:

    APR VIDEO: HOOK 5                       5 SG sales · CPA 496
    MAR Single image 1：牛奶+面包             4 SG sales · CPA 504
    Video 1: 流鼻涕 咳嗽 allergy 每晚睡不好     5 SG sales · CPA 664
    Video 3：5岁到15岁的孩子                   7 SG sales · CPA 724

The 1-2 sale creatives with prettier CPAs were left out on purpose: one sale is an anecdote,
and reviving anecdotes is how the account ended up funding registration-cheap, buyer-poor
creatives in the first place.

WHICH COPY OF EACH
------------------
Each name exists as several ads carrying DIFFERENT creatives (separate posts, split
engagement). Sales in the sheet are keyed by ad NAME, so they cannot say which copy sold —
but spend can: the copy that took the overwhelming share of the name's lifetime spend is the
one whose leads produced those sales. Each creative_id below is that top-spend copy, which is
also the post carrying the most social proof.

Ad names are byte-for-byte the historical names. The paid-list join and every ops script key
on cpa.ad_key(name), so the revival inherits each creative's sales history and future sheet
rows keep attributing cleanly. Which sales came from the REVIVAL is still answerable — the
sheet's campaign UTM carries this campaign's own name.

TARGETING
---------
Cloned by id from ad set 120256891851660093 (Parents 3–17 + Engaged) — the account's
best-converting ad set, the same base used for the hook-edit and bread-hook tests. By id, not
name: two live ad sets share that name. These winners originally earned their sales under
various targetings; the question this campaign asks is whether the CREATIVES still sell
today, so they all sit on the account's current best audience rather than four museum
reconstructions.

Everything is created PAUSED for review (the standing rule for new builds). CBO RM100/day —
the account's standard test size; under CBO Meta will concentrate on whichever winner still
has it. Idempotent: entity ids persist to state/, so a re-dispatch never duplicates.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from adbot.build_1_1_10 import build
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_KEY = "entities_winners_revival_1_1_4"
STATE_PATH = Path("state") / f"{STATE_KEY}.json"
PREFIX = "[SG] 儿童长高方程式"
LABEL = "Winners Revival | 1-1-4"
ADSET_NAME = "Parents 3–17 + Engaged | Winners Revival"
DAILY_MYR = 100

CLONE_ADSET_ID = "120256891851660093"      # Parents 3–17 + Engaged — best CPL in the account

DETAIL_KEYS = ["interests", "behaviors", "life_events", "family_statuses", "industries",
               "income", "education_statuses", "work_positions", "work_employers",
               "relationship_statuses", "user_adclusters", "moms"]

# key → the top-spend copy's creative (see WHICH COPY OF EACH above). Names are exact.
ADS: List[Dict[str, str]] = [
    {"key": "hook5",   "creative_id": "1869159860323394",
     "name": "APR VIDEO: HOOK 5"},
    {"key": "milksi",  "creative_id": "1273546897732001",
     "name": "MAR Single image 1：牛奶+面包"},
    {"key": "allergy", "creative_id": "1287087603180186",
     "name": "Video 1: 流鼻涕 咳嗽 allergy 每晚睡不好"},
    {"key": "v3age",   "creative_id": "25862870296679541",
     "name": "Video 3：5岁到15岁的孩子"},
]


def clone_from_adset(g, adset_id: str, s) -> Dict[str, Any]:
    """Clone interest/behaviour targeting from ONE specific ad set, forced to this market's geo.

    By ID rather than by name: two live ad sets are both called "Parents 3–17 + Engaged", and a
    name lookup would silently pick whichever happened to look richer.
    """
    src = g._request("GET", adset_id, params={"fields": "name,targeting"})
    t = src.get("targeting") or {}
    adv_raw = (t.get("targeting_automation") or {}).get("advantage_audience")
    adv = 1 if adv_raw is None else int(adv_raw)
    age_min, age_max = int(t.get("age_min") or 25), int(t.get("age_max") or 65)
    if adv == 1 and age_min > 25:      # Meta rejects a higher hard floor when Advantage+ is on
        age_min = 25
    spec: Dict[str, Any] = {
        "geo_locations": {"countries": s.meta.targeting.countries or ["SG"]},
        "age_min": age_min, "age_max": age_max,
        "targeting_automation": {"advantage_audience": adv},
        "excluded_custom_audiences": [{"id": i} for i in
                                      (s.meta.targeting.excluded_custom_audiences or [])],
        "locales": s.meta.targeting.locales or [1004],
    }
    if t.get("genders"):
        spec["genders"] = t["genders"]
    fs = t.get("flexible_spec")
    if fs:
        spec["flexible_spec"] = fs
    else:
        legacy = {k: t[k] for k in DETAIL_KEYS if t.get(k)}
        if legacy:
            spec["flexible_spec"] = [legacy]
    return {"spec": spec, "name": src.get("name")}


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    conv = s.meta.conversion_domain_bare or None

    s.naming.prefix = PREFIX
    s.meta.budget.level = "CAMPAIGN"                 # CBO — concentrate on whoever still sells
    s.meta.budget.daily_amount_myr = DAILY_MYR

    # Fail before building anything if a creative id has gone stale (deleted post, pulled
    # permissions). Half a revival campaign is worse than none.
    for a in ADS:
        c = g._request("GET", a["creative_id"], params={"fields": "id,status"})
        log.info("creative %-18s %s (%s)", a["creative_id"], a["key"], c.get("status", "?"))

    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}

    spec = None
    if not st.get("adset_id"):
        cloned = clone_from_adset(g, CLONE_ADSET_ID, s)
        spec = cloned["spec"]
        detail = sum(len(grp.get(k) or []) for grp in (spec.get("flexible_spec") or [])
                     for k in DETAIL_KEYS)
        log.info("── targeting ← ad set %s %r (age %s-%s · adv=%s · %d detail entries)",
                 CLONE_ADSET_ID, cloned["name"], spec["age_min"], spec["age_max"],
                 (spec.get("targeting_automation") or {}).get("advantage_audience"), detail)
    else:
        log.info("── reuse campaign %s / adset %s", st.get("campaign_id"), st.get("adset_id"))

    ent = build(g, s, units=[], captions={}, dry_run=False, label=LABEL,
                state_key=STATE_KEY, adset_name=ADSET_NAME, targeting_override=spec)
    campaign_id, adset_id = ent["campaign_id"], ent["adset_id"]

    st = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
    built = set(st.get("built_ad_keys", []))
    ad_ids: List[str] = list(st.get("ad_ids", []))
    for a in ADS:
        if a["key"] in built:
            log.info("   skip ad %s (already built)", a["name"])
            continue
        ad = g.create_ad(acct, name=a["name"], adset_id=adset_id,
                         creative={"creative_id": a["creative_id"]},
                         status="PAUSED", conversion_domain=conv)
        ad_ids.append(ad["id"])
        built.add(a["key"])
        st.update({"campaign_id": campaign_id, "adset_id": adset_id,
                   "ad_ids": ad_ids, "built_ad_keys": sorted(built)})
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))
        log.info("   + ad %s ⟵ %s", ad["id"], a["name"])

    log.info("═" * 88)
    log.info("campaign=%s  adset=%s  ads=%d", campaign_id, adset_id, len(ad_ids))
    final_summary(
        log, f"Winners Revival built PAUSED: the 4 creatives with >= 4 provably-SG sales at a "
             f"lifetime CPA inside the RM740 target that were getting RM0 of recent budget "
             f"(HOOK 5 · 牛奶+面包 · 流鼻涕allergy · 5岁到15岁), one ad set on the account's "
             f"best-converting targeting, CBO RM{DAILY_MYR}/day. Each ad reuses the top-spend "
             f"copy's creative, so it keeps its post engagement, and keeps its exact historical "
             f"name so the paid-list join stays continuous — revival sales remain separable via "
             f"the campaign UTM. Review previews in Ads Manager, then activate; CBO will "
             f"concentrate on whichever winner still sells today.")


if __name__ == "__main__":
    main()
