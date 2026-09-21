"""Undo the stray-pausing of the 新片测试 build (21 Sep). MUTATING, operator-ordered.

Operator: "不要关" — the two RM40 F&R chains (Hook 1 / Hook 7) must KEEP running alongside
the 1-1-5 test. The build had already paused them; this reactivates each paused stray ad
and its ad set, verifies, and clears the strays_paused record.
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

STATE_PATH = Path("state") / "entities_test155_fr_0921.json"


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)

    st = json.loads(STATE_PATH.read_text())
    strays = st.get("strays_paused") or []
    if not strays:
        log.info("strays_paused 为空 — 没东西要恢复")
        final_summary(log, "Nothing to undo.")
        return

    rows = []
    for ad_id in strays:
        info = g.get_object(ad_id, "id,name,status,adset_id")
        aid = info.get("adset_id")
        if aid:
            g.update_status(aid, "ACTIVE")
            time.sleep(1.0)
        g.update_status(ad_id, "ACTIVE")
        time.sleep(1.0)
        eff = g.get_object(ad_id, "effective_status").get("effective_status")
        b = int((g.get_object(aid, "daily_budget").get("daily_budget") or 0)) if aid else 0
        log.info("▸ 恢复 ad %s %r · adset %s RM%d/day · eff %s",
                 ad_id, (info.get("name") or "")[:36], aid, b // 100, eff)
        rows.append(f"{(info.get('name') or ad_id)[:24]}: {eff} @RM{b // 100}")

    st["strays_paused"] = []
    st["strays_restored"] = strays
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))
    final_summary(log, f"Strays restored per operator's 不要关: {'; '.join(rows)}. "
                       f"The five test names now run in the test AND their old chains.")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min; run is idempotent.", exc)
        sys.exit(75)
