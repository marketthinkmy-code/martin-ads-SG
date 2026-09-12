"""Shopper & Health Interests 1-4-4: ONE new campaign, 4 interest ad sets x 4 proven ads.

Operator's spec (12 Sep, restated and confirmed "① 换 Hook 7 ② A ③ 直接跑"):
    · 1 NEW ABO campaign: [SG] 儿童长高方程式 | Shopper & Health Interests | 1-4-4
    · 4 ad sets, RM50/day each (+RM200/day total), named by targeting, ACTIVE immediately:
        1. Engaged Shoppers      — behavior 6071631541183
        2. Vitamins              — interests 6803120807074 (Vitamins & nutritional
                                   supplements) + 6003331809777 (Folic acid)
        3. Health & Wellness     — interests 6003258544357 + 6003384248805
        4. Healthy Diet & Food   — interests 6003382102565 + 6003198972065 + 6003420915231
      (Option A: the Supplement set became Healthy Diet & Food — Meta's only topical
      supplement interest is the same 6803120807074, two sets would fight each other.
      Healthy diet moved out of set 3 so sets 3/4 stay disjoint.)
    · EVERY ad set carries the SAME four proven sellers (existing creatives reused, social
      proof pooled; exact historical ad names kept for sheet attribution):
        15岁以上还有机会长高吗 (25 SG sales) · Hook 3 准备早餐面包 (13) ·
        Video 5 林書豪story (11) · Hook 7 担心高度没跟上 (10 · CPA RM839)
      — 我不会买牛奶 swapped out for Hook 7 on the operator's word.
    · Copy stays as the historical posts carry it (facts update deferred, operator's rule).
    · Scale stays manual per ad; the 11 Sep daily rules govern it automatically.

Idempotent via state/entities_shopper_health_144.json — re-dispatch resumes. If a legacy
creative id is rejected on a new ad ("(#400) website URL required"), the ad falls back to a
fresh creative wrapping the same page post (effective_object_story_id) — same post, same
social proof.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from adbot.clients.graph import GraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "entities_shopper_health_144.json"
CAMPAIGN_NAME = "[SG] 儿童长高方程式 | Shopper & Health Interests | 1-4-4"
DAILY_MINOR = 5000

ADS: List[Dict[str, str]] = [   # proven sellers — creative reused from the rep ad
    {"key": "v15plus", "src_ad": "120250914933320093"},   # 15岁以上还有机会长高吗 · 25 SG
    {"key": "hook3bread", "src_ad": "120227243598650093"},  # Hook 3 准备早餐面包 · 13 SG
    {"key": "v5lin", "src_ad": "120247184595700093"},     # Video 5 林書豪story · 11 SG
    {"key": "hook7", "src_ad": "120242606093200093"},     # Hook 7 担心高度没跟上 · 10 SG
]

ADSETS: List[Dict[str, Any]] = [
    {"key": "shoppers", "name": "Engaged Shoppers",
     "flex": [{"behaviors": [{"id": "6071631541183", "name": "Engaged shoppers"}]}]},
    {"key": "vitamins", "name": "Vitamins",
     "flex": [{"interests": [
         {"id": "6803120807074", "name": "Vitamins and nutritional supplements"},
         {"id": "6003331809777", "name": "Folic acid"}]}]},
    {"key": "wellness", "name": "Health & Wellness",
     "flex": [{"interests": [
         {"id": "6003258544357", "name": "Health & wellness"},
         {"id": "6003384248805", "name": "Fitness and wellness"}]}]},
    {"key": "diet", "name": "Healthy Diet & Food",
     "flex": [{"interests": [
         {"id": "6003382102565", "name": "Healthy diet"},
         {"id": "6003198972065", "name": "Healthy food"},
         {"id": "6003420915231", "name": "Health club"}]}]},
]


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    m = s.meta
    acct = m.account_path
    conv = m.conversion_domain_bare or None
    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}

    def persist() -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, indent=2, ensure_ascii=False) + "\n")

    # ── resolve the four source creatives BEFORE creating anything ──────────────
    srcs: Dict[str, Any] = st.setdefault("sources", {})
    for a in ADS:
        rec = srcs.get(a["key"]) or {}
        if not rec.get("creative_id"):
            info = g.get_object(a["src_ad"],
                                "name,creative{id,effective_object_story_id}")
            cr = info.get("creative") or {}
            if not cr.get("id"):
                raise SystemExit(f"!! source ad {a['src_ad']} has no creative — aborting.")
            rec = {"name": info.get("name"), "creative_id": str(cr["id"]),
                   "post_id": cr.get("effective_object_story_id") or ""}
            srcs[a["key"]] = rec
            persist()
        log.info("── %-10s %r creative %s post %s", a["key"], rec["name"],
                 rec["creative_id"], rec.get("post_id") or "?")

    def creative_for(key: str) -> str:
        """The creative to bind — the fallback (post-wrap) one if it exists, else source."""
        rec = srcs[key]
        return rec.get("fallback_creative_id") or rec["creative_id"]

    def make_fallback(key: str) -> str:
        rec = srcs[key]
        if rec.get("fallback_creative_id"):
            return rec["fallback_creative_id"]
        if not rec.get("post_id"):
            raise SystemExit(f"!! {key}: legacy creative rejected and no post id to wrap.")
        fields: Dict[str, Any] = {"name": f"{rec['name']} (post reuse)",
                                  "object_story_id": rec["post_id"]}
        if m.url_tags:
            fields["url_tags"] = m.url_tags
        rec["fallback_creative_id"] = g.create_adcreative(acct, **fields)["id"]
        persist()
        log.info("   %s: legacy creative rejected → new post-wrap creative %s",
                 key, rec["fallback_creative_id"])
        return rec["fallback_creative_id"]

    # ── campaign ────────────────────────────────────────────────────────────────
    if st.get("campaign_id"):
        log.info("── reuse campaign %s", st["campaign_id"])
    else:
        fields = {"name": CAMPAIGN_NAME, "objective": m.objective, "buying_type": "AUCTION",
                  "status": "ACTIVE", "special_ad_categories": m.special_ad_categories,
                  "is_adset_budget_sharing_enabled": False}
        if m.regional_regulated_categories:
            fields["regional_regulated_categories"] = m.regional_regulated_categories
        st["campaign_id"] = g.create_campaign(acct, **fields)["id"]
        persist()
        log.info("── + campaign %s %r", st["campaign_id"], CAMPAIGN_NAME)

    base_spec = {
        "geo_locations": {"countries": m.targeting.countries or ["SG"]},
        "age_min": m.targeting.age_min, "age_max": m.targeting.age_max,
        "targeting_automation": {"advantage_audience": 1},
        "excluded_custom_audiences": [{"id": str(c)} for c in
                                      (m.targeting.excluded_custom_audiences or [])],
        "locales": m.targeting.locales or [1004],
    }

    # ── 4 ad sets × 4 ads ───────────────────────────────────────────────────────
    rows: List[str] = []
    groups: Dict[str, Any] = st.setdefault("adsets", {})
    for aset in ADSETS:
        log.info("═" * 88)
        rec: Dict[str, Any] = groups.setdefault(aset["key"], {})
        if not rec.get("adset_id"):
            spec = dict(base_spec)
            spec["flexible_spec"] = aset["flex"]
            fields = {"name": aset["name"], "campaign_id": st["campaign_id"],
                      "optimization_goal": m.optimization_goal,
                      "billing_event": "IMPRESSIONS", "promoted_object": m.promoted_object,
                      "targeting": spec, "status": "ACTIVE", "daily_budget": DAILY_MINOR,
                      "bid_strategy": "LOWEST_COST_WITHOUT_CAP"}
            if m.regional_regulated_categories:
                fields["regional_regulated_categories"] = m.regional_regulated_categories
            if m.regional_regulation_identities:
                fields["regional_regulation_identities"] = m.regional_regulation_identities
            rec["adset_id"] = g.create_adset(acct, **fields)["id"]
            persist()
        log.info("▸ %-20s adset %s · RM50/day", aset["name"], rec["adset_id"])
        ads_rec: Dict[str, Any] = rec.setdefault("ads", {})
        for a in ADS:
            if not ads_rec.get(a["key"]):
                name = srcs[a["key"]]["name"]
                try:
                    ad = g.create_ad(acct, name=name, adset_id=rec["adset_id"],
                                     creative={"creative_id": creative_for(a["key"])},
                                     status="ACTIVE", conversion_domain=conv)
                except GraphError as exc:
                    if "url" not in str(exc).lower():
                        raise
                    ad = g.create_ad(acct, name=name, adset_id=rec["adset_id"],
                                     creative={"creative_id": make_fallback(a["key"])},
                                     status="ACTIVE", conversion_domain=conv)
                ads_rec[a["key"]] = ad["id"]
                persist()
            fin = g._request("GET", ads_rec[a["key"]], params={"fields": "effective_status"})
            log.info("     %-10s ad %s · eff %s", a["key"], ads_rec[a["key"]],
                     fin.get("effective_status"))
            rows.append(f"{aset['key']}/{a['key']}({fin.get('effective_status')})")

    log.info("═" * 88)
    final_summary(
        log, f"Shopper & Health 1-4-4 live: campaign {st['campaign_id']} · 4 ad sets "
             f"(RM50/day each, named by targeting) · 16 ads over 4 proven creatives — "
             f"{'; '.join(rows)}. +RM200/day, running immediately; the 11 Sep daily rules "
             f"(CPL>95 → -30%, RM142.50 zero-reg kill) govern it automatically.")


if __name__ == "__main__":
    main()
