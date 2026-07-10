"""Build the SG Scale CBO skeleton: 1 campaign + 1 ad set, both PAUSED, 0 ads.

Uses adbot.build_1_1_10.build() with an empty units list so we get the full SG
compliance setup (SINGAPORE_UNIVERSAL, verified advertiser identity, geo /
locale / Advantage+ audience / excluded custom audiences, CBO budget) without
uploading any creatives. The 6 winning creatives + MANUS 测验单图 are then
added manually in Ads Manager via "Use Existing Post" (to reuse the exact
winning ad_ids' videos) or as fresh clones.

Reads the config path from the ADBOT_CONFIG env var — point it at
config/scale-cbo.yaml. Idempotent: re-runs reuse the campaign_id + adset_id
from state/entities_scale_cbo.json, so an accidental second dispatch will not
duplicate the campaign.
"""
from __future__ import annotations

from adbot.build_1_1_10 import build
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings


def main() -> None:
    log = get_logger()
    settings = load_settings()
    graph = graph_client(settings)
    entities = build(
        graph, settings,
        units=[],
        captions={},
        dry_run=False,
        label=settings.meta.build.label,
        state_key=settings.meta.build.state_key,
    )
    log.info("  campaign_id: %s", entities["campaign_id"])
    log.info("  adset_id:    %s", entities["adset_id"])
    log.info("  ad_ids:      %s (0 — add manually in Ads Manager)", entities["ad_ids"])
    final_summary(
        log,
        "Scale CBO skeleton created (PAUSED). Add 7 winning ads in Ads Manager "
        "(Use Existing Post → paste the winner ad_id) + set placements "
        "(FB Feed/Reels + IG Feed, exclude IG Stories/Reels) per adset.")


if __name__ == "__main__":
    main()
