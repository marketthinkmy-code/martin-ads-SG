"""Re-shape the 8月 hook-edit test from one 1-1-10 into 1-1-4 + 1-1-3 + 1-1-3 — PAUSED.

Meta cannot move an ad between ad sets, so "restructure" means building new campaigns and
pointing new ads at the creatives that already exist. Nothing is re-uploaded: the ten videos
and their creatives were created by scripts/build_hook_edits.py and their ids are read back
out of state/entities_hookedits_shared.json, so this runs in about a minute instead of fifteen.

WHY THESE THREE GROUPS
----------------------
All three ad sets get IDENTICAL targeting and all ten ads share one body, so the grouping does
not change who sees what. Its only job is to stop near-duplicate creatives bidding against each
other inside one CBO pool. Three pairs must not share an ad set:

    07 吃饭很慢 B  /  09 吃饭很慢 A   — the same body with two different hooks (the two source
                                       files differ by ~10KB), so in one ad set they would split
                                       the same audience with the same video
    04 不买牛奶     /  06 喝牛奶长痘痘  — both milk-myth
    03 生长激素     /  10 睡眠品质差    — both "growth hormone is secreted in deep sleep"

Three conflicting pairs across three groups: each group takes exactly one of each pair. The
remaining four (01 運動 / 02 我最討厭聽到 / 05 孩子 5-15 岁 / 08 鼻子敏感) fill the gaps.

Groups are named A/B/C rather than given theme names because they are NOT theme families —
calling them 迷思 / 体质 / 睡眠 would imply a split that the constraint-driven layout does not
actually follow.

BUDGET
------
RM50/day × 3 = RM150/day, deliberately identical to what the single 1-1-10 campaign carried, so
the restructure costs nothing extra. Note the trade-off this shape has: one pool of 10 ads on
RM150 concentrates faster than three pools of 3-4 ads on RM50, because each ad set now needs its
own conversions to leave the learning phase. That is the operator's call, not a defect.

The old 1-1-10 campaign (120257637038600093) is left PAUSED and untouched. It still holds ten ads
with the SAME names as the ones built here, which would confuse any future name-matching script,
so it should be deleted in Ads Manager once these three look right.

Everything is created PAUSED.
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
SHARED_PATH = STATE_DIR / "entities_hookedits_shared.json"
PREFIX = "[SG] 儿童长高方程式"
DAILY_MYR = 50
CLONE_ADSET_ID = "120256891851660093"          # Parents 3–17 + Engaged (1-1-4) — best CPL in acct
OLD_CAMPAIGN_ID = "120257637038600093"         # the 1-1-10 this supersedes

DETAIL_KEYS = ["interests", "behaviors", "life_events", "family_statuses", "industries",
               "income", "education_statuses", "work_positions", "work_employers",
               "relationship_statuses", "user_adclusters", "moms"]

# Ad names must match the ones build_hook_edits.py used, so the same hook keeps the same name.
NAMES = {
    "he01_sport":  "Hook Edit 01：運動就能長高？！No！",
    "he02_hate":   "Hook Edit 02：我最討厭聽到",
    "he03_gh":     "Hook Edit 03：生长激素",
    "he04_nomilk": "Hook Edit 04：不买牛奶给孩子喝",
    "he05_age515": "Hook Edit 05：孩子 5-15 岁",
    "he06_acne":   "Hook Edit 06：喝牛奶长痘痘",
    "he07_slow_b": "Hook Edit 07：吃饭很慢 B",
    "he08_sinus":  "Hook Edit 08：鼻子敏感 Sinus",
    "he09_slow_a": "Hook Edit 09：吃饭很慢 A",
    "he10_sleep":  "Hook Edit 10：睡眠品质差",
}

GROUPS: List[Dict[str, Any]] = [
    {"label": "Hook Edits A | 1-1-4", "adset_name": "Parents 3–17 + Engaged | Hook Edits A",
     "state_key": "entities_hook_edits_a",
     "keys": ["he01_sport", "he03_gh", "he04_nomilk", "he07_slow_b"]},
    {"label": "Hook Edits B | 1-1-3", "adset_name": "Parents 3–17 + Engaged | Hook Edits B",
     "state_key": "entities_hook_edits_b",
     "keys": ["he02_hate", "he06_acne", "he09_slow_a"]},
    {"label": "Hook Edits C | 1-1-3", "adset_name": "Parents 3–17 + Engaged | Hook Edits C",
     "state_key": "entities_hook_edits_c",
     "keys": ["he05_age515", "he08_sinus", "he10_sleep"]},
]


def clone_from_adset(g, adset_id: str, s) -> Dict[str, Any]:
    """Clone targeting from ONE specific ad set by ID — two live ad sets share its name."""
    src = g._request("GET", adset_id, params={"fields": "name,targeting"})
    t = src.get("targeting") or {}
    adv_raw = (t.get("targeting_automation") or {}).get("advantage_audience")
    adv = 1 if adv_raw is None else int(adv_raw)
    age_min, age_max = int(t.get("age_min") or 25), int(t.get("age_max") or 65)
    if adv == 1 and age_min > 25:
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
    s.meta.budget.level = "CAMPAIGN"
    s.meta.budget.daily_amount_myr = DAILY_MYR

    if not SHARED_PATH.exists():
        raise SystemExit(f"!! {SHARED_PATH} missing — run build_hook_edits.py first; this script "
                         f"only re-points existing creatives and never uploads video")
    creatives: Dict[str, Any] = json.loads(SHARED_PATH.read_text()).get("creatives", {})
    missing = [k for grp in GROUPS for k in grp["keys"] if k not in creatives]
    if missing:
        raise SystemExit(f"!! no cached creative for {missing} — refusing to build a partial set")
    covered = sorted(k for grp in GROUPS for k in grp["keys"])
    if covered != sorted(NAMES):
        raise SystemExit(f"!! groups cover {covered}, expected all 10 of {sorted(NAMES)}")
    log.info("reusing %d cached creatives — no video upload", len(covered))

    cloned = clone_from_adset(g, CLONE_ADSET_ID, s)
    spec = cloned["spec"]
    detail = sum(len(grp.get(k) or []) for grp in (spec.get("flexible_spec") or [])
                 for k in DETAIL_KEYS)
    log.info("targeting ← ad set %s %r (age %s-%s · adv=%s · %d detail entries)",
             CLONE_ADSET_ID, cloned["name"], spec["age_min"], spec["age_max"],
             (spec.get("targeting_automation") or {}).get("advantage_audience"), detail)

    summary: List[str] = []
    for grp in GROUPS:
        log.info("═" * 88)
        log.info("── %s  (%d ads)", grp["label"], len(grp["keys"]))

        st_path = STATE_DIR / f"{grp['state_key']}.json"
        st = json.loads(st_path.read_text()) if st_path.exists() else {}
        # Only pass a targeting spec when the ad set does not exist yet; build() ignores it
        # otherwise, and passing it on a reuse would imply an edit that is not happening.
        ent = build(g, s, units=[], captions={}, dry_run=False, label=grp["label"],
                    state_key=grp["state_key"], adset_name=grp["adset_name"],
                    targeting_override=None if st.get("adset_id") else spec)
        campaign_id, adset_id = ent["campaign_id"], ent["adset_id"]

        st = json.loads(st_path.read_text()) if st_path.exists() else {}
        built = set(st.get("built_ad_keys", []))
        ad_ids: List[str] = list(st.get("ad_ids", []))
        for key in grp["keys"]:
            if key in built:
                log.info("   skip %s (already built)", NAMES[key])
                continue
            ad = g.create_ad(acct, name=NAMES[key], adset_id=adset_id,
                             creative={"creative_id": creatives[key]["creative_id"]},
                             status="PAUSED", conversion_domain=conv)
            ad_ids.append(ad["id"])
            built.add(key)
            st.update({"campaign_id": campaign_id, "adset_id": adset_id,
                       "ad_ids": ad_ids, "built_ad_keys": sorted(built)})
            st_path.write_text(json.dumps(st, ensure_ascii=False, indent=2))
            log.info("   + ad %s ⟵ %s", ad["id"], NAMES[key])

        summary.append(f"  {grp['label']:22} campaign={campaign_id} adset={adset_id} "
                       f"ads={len(ad_ids)} RM{DAILY_MYR}/day")

    log.info("═" * 88)
    for line in summary:
        log.info(line)
    log.info("  old 1-1-10 campaign %s left PAUSED — delete it in Ads Manager; it still holds "
             "10 ads with these same names", OLD_CAMPAIGN_ID)
    final_summary(
        log, f"Hook edits re-shaped into 1-1-4 + 1-1-3 + 1-1-3, all PAUSED, RM{DAILY_MYR}/day each "
             f"(RM{DAILY_MYR*3}/day total — same as the single 1-1-10 it replaces). No video was "
             f"re-uploaded; all ten ads point at the creatives built earlier. Conflicting pairs "
             f"(07/09 same body, 04/06 milk, 03/10 sleep) are split across the three ad sets. "
             f"Delete the old 1-1-10 campaign {OLD_CAMPAIGN_ID} once these look right.")


if __name__ == "__main__":
    main()
