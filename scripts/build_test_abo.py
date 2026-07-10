"""Build the SG Test-ABO skeleton: 1 campaign + 1 ad set (ABO, 220 MYR/day), 0 ads.

New-material testing pipeline. Uses adbot.build_1_1_10.build() with units=[]
and meta.budget.level = "ADSET" so the daily_budget lands on the ad set (not
the campaign). Operator adds new test creatives manually in Ads Manager and
enforces the 3-day / MYR 150 elimination rule via the CPL monitor.

Idempotent: re-runs reuse the campaign_id + adset_id from
state/entities_test_abo.json, so an accidental second dispatch will not
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
    log.info("  ad_ids:      %s (0 — add new test creatives manually in Ads Manager)",
             entities["ad_ids"])
    final_summary(
        log,
        "Test-ABO skeleton created (PAUSED). Add new test creatives in Ads Manager "
        "and enforce 3-day / MYR 150 elimination rule via the CPL monitor.")


if __name__ == "__main__":
    main()
