"""Pause ads / ad sets / campaigns by id (operator-ordered, reusable).

ADBOT_ACTIVATE_IDS = comma-separated entity ids. Each one: read name/status, POST
status=ACTIVE, read back, log before → after. No deletes, no budget changes. A scheduled ad set (start_time in the future) starts by itself at that time.
"""
from __future__ import annotations

import os

from adbot.clients.graph import GraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings


def main() -> None:
    log = get_logger()
    ids = [x.strip() for x in os.environ.get("ADBOT_ACTIVATE_IDS", "").split(",") if x.strip()]
    if not ids:
        final_summary(log, "ADBOT_ACTIVATE_IDS empty — nothing to do")
        return
    g = graph_client(load_settings())
    done = []
    for eid in ids:
        try:
            before = g.get_object(eid, "name,status,effective_status")
        except GraphError as exc:
            log.error("  ❌ %s unreadable: %s", eid, exc)
            continue
        if before.get("status") == "ACTIVE":
            log.info("  = %s %r already ACTIVE (%s)", eid, before.get("name"), before.get("effective_status"))
            done.append(eid)
            continue
        g._request("POST", eid, data={"status": "ACTIVE"})
        after = g.get_object(eid, "status,effective_status")
        log.info("  ▶️ %s %r %s → %s/%s", eid, before.get("name"), before.get("status"),
                 after.get("status"), after.get("effective_status"))
        done.append(eid)
    final_summary(log, f"activated {len(done)}/{len(ids)}: {done}")


if __name__ == "__main__":
    main()
