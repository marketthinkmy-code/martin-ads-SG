"""The new opening structure, 4 Sep: 3 ABO campaigns, one ad set per ad, RM50/day each. LIVE.

Operator's spec (3 Sep, confirmed step by step):
    Parents 3-17 + Engaged      → Top-10 #4 Video 12 · #6 Hook 7 · #7 Video 3
    F&R 興趣                     → #2 Hook 9 · #8 APR HOOK 5 · #9 Video 1 (Learn More 版)
    Food & Drink + Milk + Bread → #1 Hook Edit 04 · #3 Hook 2 · #5 Carousel · #10 牛奶+面包
    all use existing post · schedule 4 Sep 2026 00:00 · ad set names = the targeting name
    scale rule: per-ad, manual, RM50 → 80 → 100 → 150 only on the operator's word (not built).

HOW IT'S BUILT
    · One campaign per audience, ABO (is_adset_budget_sharing_enabled false) — every ad owns
      its ad set and its RM50/day, so nothing gets starved by CBO.
    · Ad sets all carry their audience's name (the operator's convention), targeting cloned
      faithfully from the named source ad set (advantage_audience as stored; the F&R source
      is locked 0, so the pod is re-read and rewritten if Meta flips it).
    · "Existing post": every ad REUSES the creative currently bound to its proven source ad
      (same post id, same social proof). Video 1 is pinned to the Learn More rebuild
      (creative 2071081143496182) — its historical post's button opens WhatsApp and existing
      posts are immutable, which is why that rebuild exists.
    · Ads keep their exact historical names (sheet attribution is keyed to names); a leading
      🌟 on a source name is stripped — the star marks the old sold chains, not these tests.
    · Everything is created ACTIVE with start_time 2026-09-04T00:00:00+0800: Meta holds
      delivery until midnight, no separate switch-on needed.

Total: 3 campaigns · 10 ad sets · 10 ads · RM500/day from 4 Sep. Idempotent via
state/entities_new_structure_0904.json (re-dispatch resumes, never duplicates).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from adbot import cpa
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "entities_new_structure_0904.json"
START_TIME = "2026-09-04T00:00:00+0800"
DAILY_MINOR = 5000                       # RM50/day per ad set
PREFIX = "[SG] 儿童长高方程式"

CAMPAIGNS: List[Dict[str, Any]] = [
    {"key": "parents", "label": "Parents 3-17 + Engaged | 1-3-3",
     "adset_name": "Parents 3-17 + Engaged", "clone": "120256891851660093",
     "ads": [
         {"key": "video12", "src_ad": "120257269401020093"},
         {"key": "hook7", "find": "hook7担心孩子"},
         {"key": "video3", "find": "video35岁到15岁的孩子"},
     ]},
    {"key": "fr", "label": "F&R 興趣 | 1-3-3",
     "adset_name": "Family and Relationships", "clone": "120256985978460093",
     "ads": [
         {"key": "hook9", "src_ad": "120240921209560093"},
         {"key": "hook5", "find": "aprvideohook5"},
         {"key": "video1", "name": "Video 1: 流鼻涕 咳嗽 allergy 每晚睡不好",
          "creative": "2071081143496182"},
     ]},
    {"key": "food", "label": "Food & Drink + Milk + Bread | 1-4-4",
     "adset_name": "Food & Drink + Milk + Bread", "clone": "120256984988980093",
     "ads": [
         {"key": "he04", "src_ad": "120257667234350093"},
         {"key": "hook2", "src_ad": "120257884629490093"},
         {"key": "carousel_milk", "src_ad": "120257496415810093"},
         {"key": "si_milkbread", "find": "marsingleimage1牛奶面包"},
     ]},
]

DETAIL_KEYS = ["interests", "behaviors", "life_events", "family_statuses", "industries",
               "income", "education_statuses", "work_positions", "work_employers",
               "relationship_statuses", "user_adclusters", "moms"]


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def clone_targeting(g, adset_id: str, s) -> Dict[str, Any]:
    """Faithful clone of the source ad set's audience, geo forced to this market."""
    t = g._request("GET", adset_id, params={"fields": "targeting"}).get("targeting") or {}
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
    return spec


def verify_expansion(g, adset_id: str, spec: Dict[str, Any], intended: int, log) -> None:
    """Meta silently flips advantage_audience 0→1 on creation — re-read, rewrite if drifted."""
    if intended != 0:
        return
    t = g._request("GET", adset_id, params={"fields": "targeting"}).get("targeting") or {}
    adv = int((t.get("targeting_automation") or {}).get("advantage_audience") or 0)
    if adv == 0:
        return
    fix = dict(spec)
    fix["targeting_automation"] = {"advantage_audience": 0}
    g._request("POST", adset_id, data={"targeting": json.dumps(fix)})
    t2 = g._request("GET", adset_id, params={"fields": "targeting"}).get("targeting") or {}
    adv2 = int((t2.get("targeting_automation") or {}).get("advantage_audience") or 0)
    log.info("   expansion drifted (adv=%s) → rewrote → adv=%s%s", adv, adv2,
             "" if adv2 == 0 else " — STILL ON, fix by hand")


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    m = s.meta
    conv = m.conversion_domain_bare or None

    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}

    def persist() -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    # ── resolve every source creative BEFORE anything is created ────────────────
    all_ads = g._get_all(f"{acct}/ads", {"fields": "id,name,creative{id}", "limit": 500})
    spend_by_id = {r.get("ad_id"): _f(r.get("spend")) for r in g.account_insights(
        acct, level="ad", fields="ad_id,spend", date_preset="maximum")}

    def resolve(a: Dict[str, Any]) -> Optional[Dict[str, str]]:
        if a.get("creative"):                              # pinned creative (Video 1 rebuild)
            return {"name": a["name"], "creative": a["creative"]}
        if a.get("src_ad"):
            src = next((x for x in all_ads if x["id"] == a["src_ad"]), None)
            if src is None:
                return None
            name = (src.get("name") or "").removeprefix("🌟").strip()
            return {"name": name, "creative": str((src.get("creative") or {}).get("id"))}
        hits = [x for x in all_ads if a["find"] in cpa.ad_key(x.get("name") or "")]
        if not hits:
            return None
        best = max(hits, key=lambda x: spend_by_id.get(x["id"], 0.0))
        name = (best.get("name") or "").removeprefix("🌟").strip()
        return {"name": name, "creative": str((best.get("creative") or {}).get("id"))}

    resolved: Dict[str, Dict[str, str]] = {}
    for c in CAMPAIGNS:
        for a in c["ads"]:
            r = resolve(a)
            if r is None or not r.get("creative") or r["creative"] == "None":
                raise SystemExit(f"!! cannot resolve source for {a['key']} — nothing was "
                                 f"created; half a structure is worse than none.")
            resolved[a["key"]] = r
            log.info("── %-14s → %r (creative %s)", a["key"], r["name"], r["creative"])

    # ── build: campaign → per-ad (ad set + ad), everything scheduled ────────────
    rows: List[str] = []
    for c in CAMPAIGNS:
        log.info("═" * 88)
        cst: Dict[str, Any] = st.setdefault(c["key"], {})
        if cst.get("campaign_id"):
            log.info("── reuse campaign %s", cst["campaign_id"])
        else:
            fields = {"name": f"{PREFIX} | {c['label']}", "objective": m.objective,
                      "buying_type": "AUCTION", "status": "ACTIVE",
                      "special_ad_categories": m.special_ad_categories,
                      "is_adset_budget_sharing_enabled": False}
            if m.regional_regulated_categories:
                fields["regional_regulated_categories"] = m.regional_regulated_categories
            cst["campaign_id"] = g.create_campaign(acct, **fields)["id"]
            persist()
            log.info("── + campaign %s %r", cst["campaign_id"], fields["name"])

        spec = clone_targeting(g, c["clone"], s)
        adv = (spec.get("targeting_automation") or {}).get("advantage_audience")
        detail = sum(len(grp.get(k) or []) for grp in (spec.get("flexible_spec") or [])
                     for k in DETAIL_KEYS)
        log.info("   targeting ← %s (age %s-%s · adv=%s · %d detail entries)",
                 c["clone"], spec["age_min"], spec["age_max"], adv, detail)

        units: Dict[str, Any] = cst.setdefault("units", {})
        for a in c["ads"]:
            rec: Dict[str, Any] = units.get(a["key"]) or {}
            r = resolved[a["key"]]
            if not rec.get("adset_id"):
                fields = {"name": c["adset_name"], "campaign_id": cst["campaign_id"],
                          "optimization_goal": m.optimization_goal,
                          "billing_event": "IMPRESSIONS", "promoted_object": m.promoted_object,
                          "targeting": spec, "status": "ACTIVE",
                          "daily_budget": DAILY_MINOR,
                          "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                          "start_time": START_TIME}
                if m.regional_regulated_categories:
                    fields["regional_regulated_categories"] = m.regional_regulated_categories
                if m.regional_regulation_identities:
                    fields["regional_regulation_identities"] = m.regional_regulation_identities
                rec["adset_id"] = g.create_adset(acct, **fields)["id"]
                units[a["key"]] = rec
                persist()
                verify_expansion(g, rec["adset_id"], spec,
                                 int(adv) if adv is not None else 1, log)
            if not rec.get("ad_id"):
                ad = g.create_ad(acct, name=r["name"], adset_id=rec["adset_id"],
                                 creative={"creative_id": r["creative"]},
                                 status="ACTIVE", conversion_domain=conv)
                rec.update({"ad_id": ad["id"], "ad_name": r["name"],
                            "creative_id": r["creative"]})
                units[a["key"]] = rec
                persist()

            chk = g._request("GET", rec["adset_id"],
                             params={"fields": "daily_budget,start_time,status"})
            fin = g._request("GET", rec["ad_id"], params={"fields": "effective_status"})
            log.info("   %-14s adset %s ad %s · RM%s/day · start %s · eff %s", a["key"],
                     rec["adset_id"], rec["ad_id"],
                     int(chk.get("daily_budget") or 0) // 100, chk.get("start_time"),
                     fin.get("effective_status"))
            rows.append(f"{a['key']}({fin.get('effective_status')})")

    log.info("═" * 88)
    final_summary(
        log, f"New structure built and scheduled: 3 ABO campaigns · 10 ad sets (one per ad, "
             f"named by targeting) · 10 ads reusing their proven existing posts — "
             f"{'; '.join(rows)}. RM50/day each, RM500/day total, delivery starts "
             f"{START_TIME}. Video 1 runs the Learn More rebuild. Scale-ups stay manual: "
             f"RM50→80→100→150 per ad, only on the operator's word.")


if __name__ == "__main__":
    main()
