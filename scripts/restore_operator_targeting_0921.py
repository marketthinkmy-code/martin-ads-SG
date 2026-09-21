"""Restore the OPERATOR's manual targeting on the 新片测试 ad set. MUTATING, corrective.

Sequence of events (21 Sep): the operator hand-set the test ad set to Advantage
Audience ON / ages 25-65 in Ads Manager; my "spec enforcement" pass misread that as
Meta auto-flipping and overwrote it back to OFF / 18-65 at 05:00 UTC. The operator:
"不要改" · "我自己手动调的". This restores THEIR version — advantage_audience=1,
25-65, everything else (interests, exclusions) untouched — verifies, and that ad set's
targeting is hands-off from here on.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from adbot.clients.graph import TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

sys.path.insert(0, str(Path(__file__).parent))
from build_test155_fr_0921 import STATE_PATH  # noqa: E402


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    adset_id = json.loads(STATE_PATH.read_text())["adset_id"]

    t = g.get_object(adset_id, "targeting").get("targeting") or {}
    adv = int(((t.get("targeting_automation") or {}).get("advantage_audience")) or 0)
    log.info("before: Adv+ %s · %s-%s", "ON" if adv else "OFF", t.get("age_min"), t.get("age_max"))
    if adv == 1 and t.get("age_min") == 25:
        final_summary(log, "Already at the operator's manual setting (Adv+ ON · 25-65) — "
                           "no write needed.")
        return

    t["targeting_automation"] = {"advantage_audience": 1}
    t["age_min"], t["age_max"] = 25, 65
    g._request("POST", adset_id, data={"targeting": json.dumps(t)})
    time.sleep(3)
    t2 = g.get_object(adset_id, "targeting").get("targeting") or {}
    adv2 = int(((t2.get("targeting_automation") or {}).get("advantage_audience")) or 0)
    log.info("after:  Adv+ %s · %s-%s", "ON" if adv2 else "OFF",
             t2.get("age_min"), t2.get("age_max"))
    if adv2 != 1:
        log.error("还原失败 — 请操作员在 Ads Manager 里确认")
        sys.exit(1)
    final_summary(log, f"Operator's manual targeting restored on {adset_id}: Adv+ ON · "
                       f"25-65. This ad set's targeting is now hands-off.")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min.", exc)
        sys.exit(75)
