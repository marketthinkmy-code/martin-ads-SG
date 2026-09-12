"""Probe the 1-5-5 campaign's five chains — statuses + review issues. Read-only.

Operator (12 Sep): "我没有看到 Hook 7 那个 ad set" — the state says it was created, so this
dumps, for every unit in state/entities_shopper_health_155.json: the ad set's status and
the ad's status/effective_status, creative binding, and issues_info (Meta's rejection or
delivery-issue reasons), plus a listing of ALL ad sets Meta returns under the campaign —
to tell apart "UI filter is hiding it" from "Meta removed or rejected it".
"""
from __future__ import annotations

import json
from pathlib import Path

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "entities_shopper_health_155.json"


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    st = json.loads(STATE_PATH.read_text())
    camp = st["campaign_id"]

    info = g.get_object(camp, "name,status,effective_status")
    log.info("campaign %s %r · status %s / eff %s", camp, info.get("name"),
             info.get("status"), info.get("effective_status"))

    log.info("═" * 96)
    log.info("Meta 实际返回的 campaign 下所有 ad set：")
    for a in g._get_all(f"{camp}/adsets",
                        {"fields": "id,name,status,effective_status,daily_budget", "limit": 50}):
        log.info("  adset %s %r · %s/%s · RM%d/day", a["id"], a.get("name"),
                 a.get("status"), a.get("effective_status"),
                 int(a.get("daily_budget") or 0) // 100)

    log.info("═" * 96)
    for key, u in (st.get("units") or {}).items():
        log.info("▸ %s", key)
        try:
            aset = g.get_object(u["adset_id"], "name,status,effective_status")
            log.info("   adset %s · %s/%s", u["adset_id"], aset.get("status"),
                     aset.get("effective_status"))
        except Exception as exc:  # noqa: BLE001
            log.info("   adset %s 读取失败: %s", u["adset_id"], exc)
        try:
            ad = g.get_object(u["ad_id"],
                              "name,status,effective_status,creative{id},issues_info")
            log.info("   ad %s %r · %s/%s · creative %s", u["ad_id"], ad.get("name"),
                     ad.get("status"), ad.get("effective_status"),
                     (ad.get("creative") or {}).get("id"))
            for issue in ad.get("issues_info") or []:
                log.info("   ⚠️ issue: %s — %s", issue.get("error_summary"),
                         issue.get("error_message"))
        except Exception as exc:  # noqa: BLE001
            log.info("   ad %s 读取失败: %s", u["ad_id"], exc)

    final_summary(log, "1-5-5 unit probe done — statuses and issues above. Read-only.")


if __name__ == "__main__":
    main()
