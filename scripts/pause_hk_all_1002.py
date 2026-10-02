"""Pause EVERY active campaign on the HK account (2 Oct).

Operator said 我都关完了 (10:33 MYT) — but their Ads Manager bulk edit stuck at
"Publishing 2 of 15" and the 10:45 screenshot shows all 9 campaigns still ACTIVE
with RM509 spent today for 1 registration. This completes the operator's own
shutdown at the CAMPAIGN level (one switch stops everything underneath; fully
reversible). Ids recorded to state for a clean undo.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

NEW_ACCT = "act_1179668409969241"
STATE_PATH = Path("state") / "hk_pause_1002.json"


def main() -> None:
    log = get_logger()
    g = graph_client(load_settings())
    st = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {"paused": {}}
    for c in g._get_all(f"{NEW_ACCT}/campaigns",
                        {"fields": "id,name,status,effective_status", "limit": 200}):
        if c.get("status") != "ACTIVE":
            continue
        g._request("POST", c["id"], data={"status": "PAUSED"})
        after = g.get_object(c["id"], "status").get("status")
        st["paused"][c["id"]] = c.get("name")
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))
        log.info("⏸ campaign %s %r → %s", c["id"], (c.get("name") or "")[:60], after)
        time.sleep(0.5)
    final_summary(log, f"HK account fully paused at campaign level: "
                       f"{len(st['paused'])} campaigns recorded in {STATE_PATH}.")


if __name__ == "__main__":
    main()
