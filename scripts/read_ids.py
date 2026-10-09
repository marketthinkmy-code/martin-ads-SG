"""Read-only: dump campaigns / ad sets / ads by id (operator 对账用), plus the account's currency.

ADBOT_READ_IDS = comma-separated ids. Each id is tried as ad set, then campaign, then ad.
No insights calls (cheap, never hits the insights throttle). No writes.
"""
from __future__ import annotations

import json
import os

from adbot.clients.graph import GraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

TRY = [
    ("adset", "id,name,status,effective_status,daily_budget,lifetime_budget,bid_strategy,optimization_goal,"
              "campaign{id,name,status,daily_budget},account_id,created_time,updated_time"),
    ("campaign", "id,name,status,effective_status,daily_budget,lifetime_budget,objective,account_id,created_time,updated_time"),
    ("ad", "id,name,status,effective_status,adset{id,name,daily_budget},campaign{id,name},account_id,created_time,updated_time"),
]


def main() -> None:
    log = get_logger()
    g = graph_client(load_settings())
    ids = [x.strip() for x in os.environ.get("ADBOT_READ_IDS", "").split(",") if x.strip()]
    accounts = {}
    for eid in ids:
        obj, kind = None, None
        for kind, fields in TRY:
            try:
                obj = g.get_object(eid, fields)
                break
            except GraphError:
                obj = None
        if not obj:
            log.error("❌ %s 读不到（不是 campaign / ad set / ad，或没有权限）", eid)
            continue
        acct = obj.get("account_id")
        if acct and acct not in accounts:
            try:
                accounts[acct] = g.get_object(f"act_{acct}", "name,currency,timezone_name")
            except GraphError as exc:
                accounts[acct] = {"error": str(exc)[:80]}
        a = accounts.get(acct) or {}
        log.info("▌%s %s · 账户 act_%s %r · 币种 %s · 时区 %s", kind, eid, acct, a.get("name"), a.get("currency"), a.get("timezone_name"))
        log.info("%s", json.dumps(obj, ensure_ascii=False, indent=2))
    final_summary(log, f"read {len(ids)} ids · read-only")


if __name__ == "__main__":
    main()
