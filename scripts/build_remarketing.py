"""Build the SG Remarketing skeleton: 1 CBO campaign + 3 warm-audience ad sets.

Bypasses build_1_1_10 (which only creates 1 ad set) and creates all 3 ad sets
directly via GraphClient. Compliance fields (SINGAPORE_UNIVERSAL + verified
advertiser identity), targeting (SG, age 25+, Chinese locale) and the
customer-list exclusion are read from config/remarketing.yaml. Ad-set names +
optional INCLUDED custom-audience IDs come from the `remarketing.adsets` YAML
section — leaving `included_custom_audience_id` blank means the ad set is
created empty and the operator attaches the CA in Ads Manager.

Idempotent: state/entities_remarketing.json remembers the campaign_id and
which ad-set names have already been built, so re-runs never duplicate.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import yaml

from adbot import state
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import DEFAULT_CONFIG, load_settings

STATE_KEY = "entities_remarketing"


def _load_remarketing_section(config_path: Path) -> List[Dict[str, Any]]:
    """Parse the custom `remarketing.adsets` list straight from the YAML file
    (adbot's Settings model doesn't know about this section)."""
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return list((data.get("remarketing") or {}).get("adsets") or [])


def main() -> None:
    log = get_logger()
    settings = load_settings()
    graph = graph_client(settings)
    m = settings.meta

    config_path = Path(settings.config_path)
    adsets_cfg = _load_remarketing_section(config_path)
    if not adsets_cfg:
        raise SystemExit(
            f"config {config_path} has no `remarketing.adsets` list — nothing to build")

    # ---- Load / init state --------------------------------------------------
    st = state.load(STATE_KEY)
    campaign_id: str = st.get("campaign_id", "")
    built: Dict[str, str] = dict(st.get("adset_ids") or {})   # adset_name -> adset_id
    created_at = st.get("created_at") or state.now_iso()

    def _persist() -> None:
        state.save(STATE_KEY, {
            "campaign_id": campaign_id,
            "adset_ids": built,
            "created_at": created_at,
        })

    # ---- Campaign -----------------------------------------------------------
    if campaign_id:
        log.info("Reusing campaign %s", campaign_id)
    else:
        campaign_fields: Dict[str, Any] = {
            "name": settings.naming.campaign_name(m.build.label),
            "objective": m.objective,
            "buying_type": "AUCTION",
            "status": "PAUSED",
            "special_ad_categories": m.special_ad_categories,
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "daily_budget": m.budget.daily_amount_cents,   # CBO
        }
        if m.regional_regulated_categories:
            campaign_fields["regional_regulated_categories"] = m.regional_regulated_categories
        campaign_id = graph.create_campaign(m.account_path, **campaign_fields)["id"]
        log.info("Created campaign %s", campaign_id)
        _persist()

    # ---- Ad sets ------------------------------------------------------------
    base_targeting = m.targeting.to_spec()

    for cfg in adsets_cfg:
        name_suffix = cfg.get("name") or ""
        full_name = settings.naming.campaign_name(f"{m.build.label} | {name_suffix}")
        if full_name in built:
            log.info("Reusing ad set %s (%s)", built[full_name], full_name)
            continue

        targeting = dict(base_targeting)
        included = (cfg.get("included_custom_audience_id") or "").strip()
        if included:
            targeting["custom_audiences"] = [{"id": included}]

        adset_fields: Dict[str, Any] = {
            "name": full_name,
            "optimization_goal": m.optimization_goal,
            "billing_event": "IMPRESSIONS",
            "promoted_object": m.promoted_object,
            "targeting": targeting,
            "status": "PAUSED",
        }
        if m.regional_regulated_categories:
            adset_fields["regional_regulated_categories"] = m.regional_regulated_categories
        if m.regional_regulation_identities:
            adset_fields["regional_regulation_identities"] = m.regional_regulation_identities

        adset_id = graph.create_adset(m.account_path, campaign_id=campaign_id,
                                       **adset_fields)["id"]
        built[full_name] = adset_id
        _persist()
        marker = f"(CA {included})" if included else "(NO included CA — attach in Ads Manager)"
        log.info("  Created ad set %s %s %s", adset_id, full_name, marker)

    log.info("  campaign_id: %s", campaign_id)
    log.info("  adset_ids:   %s", built)
    final_summary(
        log,
        f"Remarketing skeleton created (PAUSED). 1 campaign + {len(built)} ad set(s) "
        f"at {m.budget.daily_amount_myr:.0f} MYR/day CBO. Attach the SG Custom Audiences "
        "(Video Viewers 25% 30d, LP Visitors 30d, Registered No-Shows) to their matching "
        "ad sets in Ads Manager, then add the winning ads via 'Use Existing Post'.")


if __name__ == "__main__":
    main()
