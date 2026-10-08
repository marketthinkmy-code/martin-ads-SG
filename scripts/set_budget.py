"""Set daily budgets by id (operator-ordered, reusable).

ADBOT_BUDGETS = comma-separated "entity_id:RM" pairs (campaign for CBO, ad set for ABO).
Each: read name + current daily_budget, POST the new daily_budget (minor units), read back.
"""
from __future__ import annotations

import os

from adbot.clients.graph import GraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings


def main() -> None:
    log = get_logger()
    pairs = [x.strip() for x in os.environ.get("ADBOT_BUDGETS", "").split(",") if x.strip()]
    if not pairs:
        final_summary(log, "ADBOT_BUDGETS empty — nothing to do")
        return
    g = graph_client(load_settings())
    done = []
    for pair in pairs:
        eid, rm = pair.split(":")
        minor = int(round(float(rm) * 100))
        try:
            before = g.get_object(eid, "name,daily_budget,status")
        except GraphError as exc:
            log.error("  ❌ %s unreadable: %s", eid, exc)
            continue
        g._request("POST", eid, data={"daily_budget": minor})
        after = g.get_object(eid, "daily_budget")
        log.info("  💰 %s %r RM%s → RM%s (%s)", eid, before.get("name"),
                 int(before.get("daily_budget") or 0) // 100, int(after.get("daily_budget") or 0) // 100,
                 before.get("status"))
        done.append(f"{eid}:RM{int(after.get('daily_budget') or 0) // 100}")
    final_summary(log, f"budgets set: {done}")


if __name__ == "__main__":
    main()
