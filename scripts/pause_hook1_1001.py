"""Pause every ACTIVE copy of Hook 1 今晚回家检查三件事 (operator: 关 Hook 1, 1 Oct).

30d folded spend RM1,478 · 0 sales. The 10/1 morning execute paused the EW + 新片
copies; the EW and FAMILY copies are ACTIVE again — pause whatever is ACTIVE now,
ad level only. Idempotent.
"""
from __future__ import annotations

import time

from adbot import cpa
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

NEW_ACCT = "act_1179668409969241"
KEY = cpa.ad_key("Hook 1：今晚回家检查三件事")


def main() -> None:
    log = get_logger()
    g = graph_client(load_settings())
    done = []
    for a in g._get_all(f"{NEW_ACCT}/ads",
                        {"fields": "id,name,status,effective_status,campaign{name}",
                         "limit": 500}):
        if cpa.ad_key(a.get("name") or "") != KEY:
            continue
        camp = ((a.get("campaign") or {}).get("name") or "?")[:46]
        if a.get("status") == "ACTIVE":
            g._request("POST", a["id"], data={"status": "PAUSED"})
            after = g.get_object(a["id"], "status").get("status")
            log.info("⏸ %s @ %s → %s", a["id"], camp, after)
            done.append(a["id"])
            time.sleep(0.5)
        else:
            log.info("· %s @ %s 已是 %s", a["id"], camp, a.get("status"))
    final_summary(log, f"Hook 1: paused {len(done)} active copies ({', '.join(done) or '—'}).")


if __name__ == "__main__":
    main()
