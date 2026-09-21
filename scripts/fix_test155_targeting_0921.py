"""Force the 新片测试 ad set back to Adv+ OFF · 18-65. MUTATING, spec enforcement.

Build log evidence: the create call sent ages 18-65 with advantage_audience=0 and the
immediate read-back was OFF — Meta flipped the ad set to Adv+ ON / 25-65 on its own
within minutes ("Meta 偷改"). This pass rewrites the full cloned targeting with the
explicit lock, reads back, retries once if needed, and exits non-zero if Meta still
refuses so the flip is visible instead of silent.
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
from build_new_wave_0914 import clone_targeting  # noqa: E402
from build_test155_fr_0921 import FR_SOURCE, STATE_PATH  # noqa: E402


def read_state(g, adset_id: str):
    t = g.get_object(adset_id, "targeting").get("targeting") or {}
    adv = int(((t.get("targeting_automation") or {}).get("advantage_audience")) or 0)
    return adv, t.get("age_min"), t.get("age_max")


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    adset_id = json.loads(STATE_PATH.read_text())["adset_id"]

    spec = clone_targeting(g, FR_SOURCE, s)
    spec["targeting_automation"] = {"advantage_audience": 0}
    spec["age_min"], spec["age_max"] = 18, 65

    for attempt in (1, 2):
        adv, lo, hi = read_state(g, adset_id)
        log.info("attempt %d · before: Adv+ %s · %s-%s", attempt, "ON" if adv else "OFF", lo, hi)
        if adv == 0 and lo == 18:
            break
        g._request("POST", adset_id, data={"targeting": json.dumps(spec)})
        time.sleep(3)
        adv, lo, hi = read_state(g, adset_id)
        log.info("attempt %d · after:  Adv+ %s · %s-%s", attempt, "ON" if adv else "OFF", lo, hi)
        if adv == 0 and lo == 18:
            break
        time.sleep(10)

    adv, lo, hi = read_state(g, adset_id)
    if adv != 0 or lo != 18:
        log.error("Meta 拒绝锁定：仍然 Adv+ %s · %s-%s — 需要人工在 Ads Manager 里关",
                  "ON" if adv else "OFF", lo, hi)
        sys.exit(1)
    final_summary(log, f"Test ad set {adset_id} locked: Adv+ OFF · 18-65. A delayed "
                       f"re-verify should confirm Meta does not flip it again.")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min.", exc)
        sys.exit(75)
