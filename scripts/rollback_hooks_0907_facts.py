"""Roll the Hooks 0907 fact fix back: operator said 不用，以后才改. LIVE.

The 10,000-位孩子 swap had already completed when the operator's hold arrived, so this
rebinds all 12 ads to their ORIGINAL creatives (the 7,000-家庭 copy stays live for now).
The corrected creatives are not deleted — they are kept in state as corrected_creative_id,
so "以后才改" is a single rebind pass away. Verified from stored bindings; idempotent.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "entities_hooks_0907.json"


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)

    st: Dict[str, Any] = json.loads(STATE_PATH.read_text())
    creatives: Dict[str, Any] = st["creatives"]
    campaigns: Dict[str, Any] = st["campaigns"]

    rolled: List[str] = []
    for key, rec in creatives.items():
        original = rec.get("replaced_creative_id")
        if not original:
            log.info("── %s: nothing to roll back (creative %s)", key, rec.get("creative_id"))
            continue
        corrected = rec["creative_id"]
        for ckey, camp in campaigns.items():
            ad_id = camp["units"][key]["ad_id"]
            g._request("POST", ad_id,
                       data={"creative": json.dumps({"creative_id": original})})
            bound = g._request("GET", ad_id, params={"fields": "creative{id},effective_status"})
            ok = str((bound.get("creative") or {}).get("id")) == str(original)
            log.info("   %s %s ad %s → creative %s · eff %s", "·" if ok else "✗", ckey,
                     ad_id, (bound.get("creative") or {}).get("id"),
                     bound.get("effective_status"))
            if not ok:
                raise SystemExit(f"!! {key}/{ckey}: rollback did not verify on ad {ad_id}.")
        rec.update({"creative_id": original, "corrected_creative_id": corrected})
        rec.pop("replaced_creative_id", None)
        rec.pop("fact_fixed", None)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))
        rolled.append(key)
        log.info("── %s: back on original %s (corrected %s kept for later)", key,
                 original, corrected)

    done = ", ".join(rolled) if rolled else "none — already on originals"
    final_summary(
        log, f"Rolled back {len(rolled)}/4 videos ({done}): all 12 ads are on their original "
             f"creatives again (7,000-家庭 copy). The corrected 10,000-位孩子 creatives stay "
             f"stored as corrected_creative_id — switching later is one rebind pass.")


if __name__ == "__main__":
    main()
