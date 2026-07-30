"""Build 2 winner-stack campaigns (1-1-5) on cloned interest audiences — PAUSED.

Operator-approved 2026-07-30. The SAME Top-5 SG winners (30-day) run as 5 ads in each of two
fresh CBO campaigns (RM100/day each), on interest targeting cloned LIVE from the named SG ad set:

  A. [SG] 儿童长高方程式 | Health & Wellness | 1-1-5   ← targeting cloned from "Health & Wellness"
  B. [SG] 儿童长高方程式 | Milk & Bread | 1-1-5        ← targeting cloned from "Milk & Bread"

Top-5 winner creatives are REUSED by their existing creative_id (no video re-upload) — located
in the SG account by a distinctive core phrase in the ad name:
  · 我不会买牛奶 · 孩子15岁以上 · Video 8（1）新马版牛奶迷思 · dec hook 13 增高supplement · 什麼樣的孩子不會再長高

Idempotent: campaign/adset ids live in each state file; ads track built winner cores — a
re-dispatch reuses everything and never duplicates. Everything PAUSED (config
activate_after_build:false) — activate in Ads Manager after review (RM100/day × 2 = RM200/day).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from adbot import cpa
from adbot.build_1_1_10 import build
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

ad_key = cpa.ad_key
STATE_DIR = Path("state")
PREFIX = "[SG] 儿童长高方程式"
DAILY_MYR = 100

SG_GEO = {"countries": ["SG"]}
SG_EXCL = [{"id": "120226672882380093"},          # 15 days complete registration (已注册)
           {"id": "120246547080720093"}]          # 马丁 1997 Paid Student (已购买)
DETAIL_KEYS = ["interests", "behaviors", "life_events", "family_statuses", "industries",
               "income", "education_statuses", "work_positions", "work_employers",
               "relationship_statuses", "user_adclusters", "moms"]

# Top-5 SG winners (30-day). core = distinctive phrase inside the ad name (robust match).
WINNERS = [
    {"label": "我不会买牛奶",              "core": "我不会买牛奶"},
    {"label": "孩子15岁以上",             "core": "孩子15岁以上"},
    {"label": "Video 8（1）新马版牛奶迷思", "core": "新马版主打牛奶迷思"},
    {"label": "dec hook 13 增高supplement", "core": "花了几千块买增高"},
    {"label": "什麼樣的孩子不會再長高",     "core": "基本上不會再長高"},
]

CAMPAIGNS = [
    {"clone": "Health & Wellness", "adset_name": "Health & Wellness", "state_key": "entities_1_1_5_health_wellness"},
    {"clone": "Milk & Bread",      "adset_name": "Milk & Bread",      "state_key": "entities_1_1_5_milk_bread"},
]


def _richness(t: dict) -> int:
    if not isinstance(t, dict):
        return 0
    cnt = lambda spec: sum(len(spec.get(k) or []) for k in DETAIL_KEYS)
    return cnt(t) + sum(cnt(grp) for grp in (t.get("flexible_spec") or []))


def clone_targeting(adsets: List[dict], name: str) -> Tuple[Optional[dict], Optional[str]]:
    """Clone interest/behavior targeting from the richest SG ad set matching `name` → SG spec."""
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
    s.meta.budget.level = "CAMPAIGN"                 # CBO
    s.meta.budget.daily_amount_myr = DAILY_MYR

    # 1) locate each winner's reusable creative_id (from an existing SG ad copy) ─────
    ads = g._get_all(f"{acct}/ads", {"fields": "id,name,status,creative{id}", "limit": 500})
    winner_creo: Dict[str, Dict[str, str]] = {}
    for w in WINNERS:
        ck = ad_key(w["core"])
        matches = [a for a in ads if ck in ad_key(a.get("name")) and (a.get("creative") or {}).get("id")]
        if not matches:
            log.warning("‼ winner %s — no SG ad/creative found (core=%r); it will be SKIPPED", w["label"], w["core"])
            continue
        pick = next((a for a in matches if a.get("status") == "ACTIVE"), matches[0])
        winner_creo[w["core"]] = {"creative_id": pick["creative"]["id"], "name": pick.get("name")}
        log.info("winner %-26s → creative %s  ('%s')", w["label"], pick["creative"]["id"], (pick.get("name") or "")[:40])

    # 2) pull SG ad sets once (clone source) ────────────────────────────────────────
    sg_adsets = g._get_all(f"{acct}/adsets", {"fields": "name,effective_status,targeting", "limit": 500})
    log.info("pulled %d SG ad sets for cloning", len(sg_adsets))

    summary: List[str] = []
    for camp in CAMPAIGNS:
        st_path = STATE_DIR / f"{camp['state_key']}.json"
        st = json.loads(st_path.read_text()) if st_path.exists() else {}
        spec = None
        if not st.get("adset_id"):
            spec, src = clone_targeting(sg_adsets, camp["clone"])
            if spec is None:
                log.error("!! no SG ad set like %r to clone — SKIPPING %s", camp["clone"], camp["adset_name"])
                summary.append(f"  ⏭ SKIP {camp['adset_name']} (no clone source)")
                continue
            log.info("── %s | 1-1-5 ← cloned from %r (age %s-%s · adv=%s · %d detail entries)",
                     camp["adset_name"], src, spec["age_min"], spec["age_max"],
                     (spec.get("targeting_automation") or {}).get("advantage_audience"),
                     _richness({"flexible_spec": spec.get("flexible_spec", [])}))
        else:
            log.info("── %s | 1-1-5 reuse campaign %s / adset %s", camp["adset_name"],
                     st.get("campaign_id"), st.get("adset_id"))

        ent = build(g, s, units=[], captions={}, dry_run=False,
                    label=f"{camp['adset_name']} | 1-1-5", state_key=camp["state_key"],
                    adset_name=camp["adset_name"], targeting_override=spec)
        campaign_id, adset_id = ent["campaign_id"], ent["adset_id"]

        st = json.loads(st_path.read_text()) if st_path.exists() else {}
        built = set(st.get("built_winner_cores", []))
        ad_ids = list(st.get("ad_ids", []))
        for w in WINNERS:
            creo = winner_creo.get(w["core"])
            if not creo or w["core"] in built:
                continue
            ad = g.create_ad(acct, name=creo["name"], adset_id=adset_id,
                             creative={"creative_id": creo["creative_id"]}, status="PAUSED",
                             conversion_domain=conv)
            ad_ids.append(ad["id"])
            built.add(w["core"])
            st.update({"campaign_id": campaign_id, "adset_id": adset_id,
                       "ad_ids": ad_ids, "built_winner_cores": sorted(built)})
            st_path.write_text(json.dumps(st, ensure_ascii=False, indent=2))
            log.info("   + ad %s ⟵ %s (%s)", ad["id"], w["label"], creo["creative_id"])
        summary.append(f"  {camp['adset_name']:20} campaign={campaign_id} adset={adset_id} ads={len(ad_ids)}")

    log.info("═" * 88)
    for line in summary:
        log.info(line)
    final_summary(
        log, f"2× 1-1-5 winner stacks built PAUSED (CBO RM{DAILY_MYR}/day each = RM{DAILY_MYR*2}/day total): "
             f"Top-5 SG winners on Health & Wellness + Milk & Bread targeting. Activate in Ads Manager "
             f"after review. CPA rescue in the monitor protects real-sales ads.")


if __name__ == "__main__":
    main()
