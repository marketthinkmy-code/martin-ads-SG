"""Pause every ACTIVE campaign on SG old + HK (operator 3 Nov 「B」: 现在就把 SG 全部关掉).

Campaign level only — ad sets and ads keep their own status, so turning a campaign back on
(operator reopens by hand on Thursday) brings back exactly what was running. Reads each back.
75 = Meta throttled, safe to re-run.
"""
from __future__ import annotations

import sys

from adbot.clients.graph import GraphError, TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

ACCTS = [("SG老户", "act_1024930575770087"), ("HK", "act_1179668409969241")]


def main():
    log = get_logger()
    g = graph_client(load_settings())
    done, failed = [], []
    for label, acct in ACCTS:
        # configured status, not effective_status: a campaign that is ON but shows IN_PROCESS /
        # WITH_ISSUES still delivers (the first run missed two that way)
        for c in g._get_all(f"{acct}/campaigns", {"fields": "id,name,status,effective_status", "limit": 300}):
            if c.get("status") != "ACTIVE":
                continue
            try:
                g.update_status(c["id"], "PAUSED")
                back = g.get_object(c["id"], "status").get("status")
                done.append(f"{label} {c['id']}")
                log.info("⏸ %s campaign %s %r (%s) → %s", label, c["id"], c.get("name"), c.get("effective_status"), back)
            except TransientGraphError:
                raise
            except GraphError as exc:
                failed.append(c["id"])
                log.error("❌ %s campaign %s %r 关不了：%s", label, c["id"], c.get("name"), str(exc)[:160])
    final_summary(log, f"关掉 campaign {len(done)} 个 · 失败 {len(failed)}" + (f" {failed}" if failed else ""))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min (safe to re-run).", str(exc)[:200])
        sys.exit(75)
