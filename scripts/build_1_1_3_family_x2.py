"""Build 2 creative-test campaigns (1-1-3 × 2) on Interest: Family and Relationships — PAUSED.

Operator-approved 2026-07-30. The 6 newly-built videos are split into two CBO campaigns
(RM100/day each), both on interest targeting cloned LIVE from the SG "Interest: Family and
Relationships" ad set:

  A. [SG] … | Family & Relationships A | 1-1-3   → Video 16 · Video 7 · Video 15
  B. [SG] … | Family & Relationships B | 1-1-3   → Video 14 · Video 11 · Video 13

Creatives are REUSED by their existing creative_id (no re-upload) — read from the shared state
files the earlier Parents builds wrote. Idempotent: each campaign's entities live in its own
state file, ads track which videos were built. Everything PAUSED (config
activate_after_build:false) — activate in Ads Manager after review (RM100/day × 2 = RM200/day).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from adbot.build_1_1_10 import build
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_DIR = Path("state")
PREFIX = "[SG] 儿童长高方程式"
DAILY_MYR = 100
CLONE_SOURCE = "Interest: Family and Relationships"
ADSET_NAME = "Interest: Family and Relationships"

SG_GEO = {"countries": ["SG"]}
SG_EXCL = [{"id": "120226672882380093"}, {"id": "120246547080720093"}]
DETAIL_KEYS = ["interests", "behaviors", "life_events", "family_statuses", "industries",
               "income", "education_statuses", "work_positions", "work_employers",
               "relationship_statuses", "user_adclusters", "moms"]

SHARED_FILES = ["entities_v11v13_shared.json", "entities_v7v16_shared.json"]
AD_NAME = {
    "video7":  "Video 7：15 岁还没抽高，是不是已经太迟？",
    "video11": "Video 11：孩子來MC了",
    "video13": "Video 13：三年前他長了10公分",
    "video14": "Video 14：身高停在小學",
    "video15": "Video 15：不到160慌了",
    "video16": "Video 16：身高永遠停在15歲",
}
CAMPAIGNS = [
    {"suffix": "A", "state_key": "entities_1_1_3_fam_a", "videos": ["video16", "video7", "video15"]},
    {"suffix": "B", "state_key": "entities_1_1_3_fam_b", "videos": ["video14", "video11", "video13"]},
]


def _richness(t: dict) -> int:
    if not isinstance(t, dict):
        return 0
    cnt = lambda spec: sum(len(spec.get(k) or []) for k in DETAIL_KEYS)
    return cnt(t) + sum(cnt(grp) for grp in (t.get("flexible_spec") or []))


def clone_targeting(adsets: List[dict], name: str) -> Tuple[Optional[dict], Optional[str]]:
    key = name.strip().lower()
    matches = [a for a in adsets if (a.get("name") or "").strip().lower() == key] \
        or [a for a in adsets if key in (a.get("name") or "").strip().lower()]
    if not matches:
        return None, None
    best = max(matches, key=lambda a: _richness(a.get("targeting") or {}))
    t = best.get("targeting") or {}
    adv_raw = (t.get("targeting_automation") or {}).get("advantage_audience")
    adv = 1 if adv_raw is None else int(adv_raw)
    age_min, age_max = int(t.get("age_min") or 25), int(t.get("age_max") or 65)
    if adv == 1 and age_min > 25:
        age_min = 25
    spec: Dict[str, Any] = {
        "geo_locations": SG_GEO, "age_min": age_min, "age_max": age_max,
        "targeting_automation": {"advantage_audience": adv},
        "excluded_custom_audiences": SG_EXCL, "locales": [1004],
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
    return spec, best.get("name")


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    conv = s.meta.conversion_domain_bare or None

    s.naming.prefix = PREFIX
    s.meta.budget.level = "CAMPAIGN"
    s.meta.budget.daily_amount_myr = DAILY_MYR

    # creative_ids for the 6 videos, read from the shared state files the video builds wrote
    creo: Dict[str, str] = {}
    for f in SHARED_FILES:
        p = STATE_DIR / f
        if p.exists():
            for k, c in (json.loads(p.read_text()).get("creatives") or {}).items():
                if c.get("creative_id"):
                    creo[k] = c["creative_id"]
    log.info("loaded %d cached creatives: %s", len(creo), sorted(creo))
    need = {v for c in CAMPAIGNS for v in c["videos"]}
    missing = [v for v in need if v not in creo]
    if missing:
        raise SystemExit(f"!! missing cached creative_id for {missing} — cannot build; check state files.")

    # clone Interest: Family and Relationships targeting once (reused by both campaigns)
    all_adsets = g._get_all(f"{acct}/adsets", {"fields": "name,effective_status,targeting", "limit": 500})
    spec0, src = clone_targeting(all_adsets, CLONE_SOURCE)
    if spec0 is None:
        raise SystemExit(f"!! no SG ad set like {CLONE_SOURCE!r} to clone — aborting.")
    log.info("cloned targeting from %r (age %s-%s · adv=%s · %d detail entries)", src,
             spec0["age_min"], spec0["age_max"], (spec0.get("targeting_automation") or {}).get("advantage_audience"),
             _richness({"flexible_spec": spec0.get("flexible_spec", [])}))

    summary: List[str] = []
    for camp in CAMPAIGNS:
        st_path = STATE_DIR / f"{camp['state_key']}.json"
        st = json.loads(st_path.read_text()) if st_path.exists() else {}
        spec = None if st.get("adset_id") else spec0
        label = f"Family & Relationships {camp['suffix']} | 1-1-3"

        ent = build(g, s, units=[], captions={}, dry_run=False,
                    label=label, state_key=camp["state_key"], adset_name=ADSET_NAME,
                    targeting_override=spec)
        campaign_id, adset_id = ent["campaign_id"], ent["adset_id"]

        st = json.loads(st_path.read_text()) if st_path.exists() else {}
        built = set(st.get("built_videos", []))
        ad_ids = list(st.get("ad_ids", []))
        for v in camp["videos"]:
            if v in built:
                continue
            ad = g.create_ad(acct, name=AD_NAME[v], adset_id=adset_id,
                             creative={"creative_id": creo[v]}, status="PAUSED", conversion_domain=conv)
            ad_ids.append(ad["id"])
            built.add(v)
            st.update({"campaign_id": campaign_id, "adset_id": adset_id,
                       "ad_ids": ad_ids, "built_videos": sorted(built)})
            st_path.write_text(json.dumps(st, ensure_ascii=False, indent=2))
            log.info("   + ad %s ⟵ %s (%s)", ad["id"], AD_NAME[v], creo[v])
        summary.append(f"  {label:34} campaign={campaign_id} adset={adset_id} ads={len(ad_ids)}")

    log.info("═" * 88)
    for line in summary:
        log.info(line)
    final_summary(
        log, f"2× 1-1-3 built PAUSED (CBO RM{DAILY_MYR}/day each = RM{DAILY_MYR*2}/day total) on "
             f"Interest: Family and Relationships. A=V16/V7/V15 · B=V14/V11/V13. Activate in Ads "
             f"Manager after review.")


if __name__ == "__main__":
    main()
