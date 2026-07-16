"""Build 5 audience-test campaigns — 1 campaign + 1 ad set + 3 ads each, ALL PAUSED.

Each campaign targets one of the top-converting audiences (from the Paid Student
List → real Meta Detailed-Targeting join). The ad-set targeting is CLONED LIVE
from that audience's canonical winning ad set anywhere in the account portfolio
(keeping the exact interest / behavior / family-status IDs — those are global),
then forced to SG geo + the two SG exclusion audiences and stripped of any
account-scoped custom audiences.

  • CBO RM100/day per campaign
  • delivery scheduled to start 2026-07-16 00:00 +08:00 (Asia/Singapore)
  • the SAME 3 social-proof creatives in all 5 ad sets — audience is the only variable
  • prefix '[SG] 儿童长高方程式' → campaign name '[SG] 儿童长高方程式 | <audience> | 1-1-3'

Idempotent: each audience has its own state_key, so a re-dispatch reuses the
campaign / ad set / ad IDs already recorded and is a full no-op.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from adbot.build_1_1_10 import build
from adbot.caption_source import load_from_notion
from adbot.commands import graph_client, notion_client
from adbot.creative_groups import SINGLE_IMAGE, Asset, Unit
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

PREFIX = "[SG] 儿童长高方程式"
DAILY_MYR = 100
START_TIME = "2026-07-16T00:00:00+08:00"          # 16 Jul 2026 12:00am, GMT+8

SG_GEO = {"countries": ["SG"]}
SG_EXCL = [{"id": "120226672882380093"},          # 15 days complete registration (已注册)
           {"id": "120246547080720093"}]          # 马丁 1997 Paid Student (已购买)

# 3 constant creatives — 成绩 social-proof set. meta_ids are already uploaded
# (state/media_cache.json); captions live in Notion (built once by singleimg-c).
CREATIVES: List[Tuple[str, str, str]] = [
    ("单图-成绩-家长报喜合集-繁", "73987888178a1163c623a6c90962a778", "单图-成绩-家长报喜合集-繁.png"),
    ("单图-成绩-四月对比图-繁",   "67b5d070e667ff7767983f83580c2a0d", "单图-成绩-四月对比图-繁.png"),
    ("单图-成绩-短期双孩报喜-繁", "a8bef946f1aa424b0c080f1d65c9e41a", "单图-成绩-短期双孩报喜-繁.png"),
]

# (display label, canonical winning ad-set NAME to clone the targeting from)
AUDIENCES: List[Dict[str, str]] = [
    {"label": "Parents 3–17 + Engaged",     "clone": "Advantage+ Parents + Engaged"},
    {"label": "Family and Relationships",   "clone": "Interest: Family and Relationships"},
    {"label": "Housewife",                  "clone": "Housewife"},
    {"label": "Food & Drink + Milk",        "clone": "Interest: Food and Drink + Milk"},
    {"label": "Education / Tuition",        "clone": "Education"},
]

DETAIL_KEYS = ["interests", "behaviors", "life_events", "family_statuses", "industries",
               "income", "education_statuses", "work_positions", "work_employers",
               "relationship_statuses", "user_adclusters", "moms"]


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def pull_adsets(g) -> List[dict]:
    """Every ad set (name + targeting) across every account this token can see."""
    log = get_logger()
    accts = g._get_all("me/adaccounts", {"fields": "account_id", "limit": 200})
    out: List[dict] = []
    for a in accts:
        path = f"act_{a['account_id']}"
        try:
            out += g._get_all(f"{path}/adsets",
                              {"fields": "name,effective_status,targeting", "limit": 500})
        except Exception as e:                       # noqa: BLE001
            log.warning("adsets pull failed for %s: %s", path, e)
    return out


def _richness(t: dict) -> int:
    if not isinstance(t, dict):
        return 0

    def count(spec: dict) -> int:
        return sum(len(spec.get(k) or []) for k in DETAIL_KEYS)

    n = count(t)
    for grp in (t.get("flexible_spec") or []):
        n += count(grp)
    return n


def clone_targeting(adsets: List[dict], name: str) -> Tuple[Optional[dict], Optional[str]]:
    """Rebuild a clean SG-valid targeting spec from the richest ad set called `name`.

    Keeps only detailed targeting (flexible_spec interest/behavior/… IDs — global)
    plus age / gender / advantage_audience; forces SG geo + SG exclusions; drops any
    account-scoped custom audiences. Returns (spec, source_adset_name) or (None, None).
    """
    key = name.strip().lower()
    matches = [a for a in adsets if (a.get("name") or "").strip().lower() == key]
    if not matches:  # fall back to substring
        matches = [a for a in adsets if key in (a.get("name") or "").strip().lower()]
    if not matches:
        return None, None

    best = max(matches, key=lambda a: _richness(a.get("targeting") or {}))
    t = best.get("targeting") or {}

    adv_raw = (t.get("targeting_automation") or {}).get("advantage_audience")
    adv = 1 if adv_raw is None else int(adv_raw)
    age_min = int(t.get("age_min") or 25)
    age_max = int(t.get("age_max") or 65)
    if adv == 1 and age_min > 25:   # SG API rejects a hard age_min > 25 when Advantage+ audience is on
        age_min = 25

    spec: Dict[str, Any] = {
        "geo_locations": SG_GEO,
        "age_min": age_min,
        "age_max": age_max,
        "targeting_automation": {"advantage_audience": adv},
        "excluded_custom_audiences": SG_EXCL,
        "locales": [1004],
    }
    genders = t.get("genders")
    if genders:
        spec["genders"] = genders
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

    # per-request overrides (config stays broad/RM250 for the normal builds)
    s.naming.prefix = PREFIX
    s.meta.budget.level = "CAMPAIGN"          # CBO
    s.meta.budget.daily_amount_myr = DAILY_MYR

    # 3 constant creative units — meta_id preset, so no Drive download / re-upload.
    units = [Unit(content_id=cid, kind=SINGLE_IMAGE,
                  assets=[Asset(file_id="", name=fname, mime="image/png", meta_id=mid)])
             for cid, mid, fname in CREATIVES]
    captions = load_from_notion(notion_client(s), s, units)   # strict: hard error if a caption is missing
    log.info("captions loaded for %d creatives", len(captions))

    all_adsets = pull_adsets(g)
    log.info("pulled %d ad sets across accounts", len(all_adsets))

    summary: List[str] = []
    for aud in AUDIENCES:
        spec, src = clone_targeting(all_adsets, aud["clone"])
        if spec is None:
            log.error("!! no ad set named like %r to clone — SKIPPING %s", aud["clone"], aud["label"])
            summary.append(f"  SKIPPED  {aud['label']}  (no clone source for {aud['clone']!r})")
            continue

        detail = _richness({"flexible_spec": spec.get("flexible_spec", [])})
        log.info("── %s  ← cloned from %r  (age %s-%s · genders=%s · %d detail-targeting entries)",
                 aud["label"], src, spec["age_min"], spec["age_max"],
                 spec.get("genders", "all"), detail)

        ent = build(
            g, s, units=units, captions=captions, dry_run=False,
            label=f"{aud['label']} | 1-1-3",
            state_key="entities_audtest_" + _slug(aud["label"]),
            adset_name=aud["label"],
            targeting_override=spec,
            start_time=START_TIME,
        )
        summary.append(f"  {aud['label']:26} campaign={ent['campaign_id']} "
                       f"adset={ent['adset_id']} ads={len(ent['ad_ids'])}")
        log.info("   campaign=%s  adset=%s  ads=%s", ent["campaign_id"], ent["adset_id"], ent["ad_ids"])

    log.info("═" * 78)
    log.info("5× audience-test build result (all PAUSED, CBO RM%d/day, start %s):", DAILY_MYR, START_TIME)
    for line in summary:
        log.info(line)
    final_summary(log, f"audience tests built: {len([x for x in summary if 'campaign=' in x])}/5 "
                       f"campaigns (1-1-3 each, PAUSED). Review + activate in Ads Manager.")


if __name__ == "__main__":
    main()
