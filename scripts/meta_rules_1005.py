"""Zero-token enforcement: Meta Automated Rules for the 0-lead kill (operator, 5 Oct).

操作员: 我要继续监控，但我不要开对话、不要烧 token. GitHub's scheduler has been
delivering ~8% of the monitor's cron slots, and the Claude guard sessions cost tokens,
so the money-critical rule moves to Meta's own rules engine (evaluated every 30 min,
no GitHub, no Claude). Per account:
    SG old + HK : 15岁以上新片 campaigns → spent ≥ RM80 in the last 7 days with 0 results → pause ad
                  every other campaign     → spent ≥ RM105 … → pause ad
    MY          : every campaign           → spent ≥ RM90 … → pause ad  (MY regime)
DRY_RUN=1 only lists the accounts' existing rules (to confirm filter shapes) and prints
the payloads. DRY_RUN=0 creates the rules (idempotent by name), reads them back and runs
Meta's rule preview so a wrong unit would show up as an absurd match list.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from adbot.clients.graph import GraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

ACCOUNTS = [("SG老", "act_1024930575770087"), ("HK", "act_1179668409969241"),
            ("MY", "act_1011719073600566")]
TOKEN = "15岁以上新片"
DRY = os.environ.get("DRY_RUN", "1") != "0"


def rule(name: str, spent_minor: int, name_filter: Dict[str, Any] | None) -> Dict[str, Any]:
    filters: List[Dict[str, Any]] = [
        {"field": "entity_type", "value": "AD", "operator": "EQUAL"},
        {"field": "time_preset", "value": "LAST_7D", "operator": "EQUAL"},
        {"field": "spent", "value": spent_minor, "operator": "GREATER_THAN"},
        {"field": "results", "value": 0, "operator": "EQUAL"},
    ]
    if name_filter:
        filters.insert(2, name_filter)
    return {"name": name,
            "schedule_spec": {"schedule_type": "SEMI_HOURLY"},
            "evaluation_spec": {"evaluation_type": "SCHEDULE", "filters": filters},
            "execution_spec": {"execution_type": "PAUSE"},
            "status": "ENABLED"}


def main() -> None:
    log = get_logger()
    g = graph_client(load_settings())
    created, previews = [], []
    for label, acct in ACCOUNTS:
        existing = g._get_all(f"{acct}/adrules_library",
                              {"fields": "id,name,status,evaluation_spec,execution_spec,schedule_spec",
                               "limit": 100})
        log.info("═══ %s %s · 现有自动规则 %d 条", label, acct, len(existing))
        for r in existing:
            log.info("  · %s %r %s · %s", r.get("id"), r.get("name"), r.get("status"),
                     json.dumps(r.get("evaluation_spec"), ensure_ascii=False)[:300])
        if label == "MY":
            wanted = [rule("adbot · 0-lead kill RM90 (7d)", 9000, None)]
        else:
            wanted = [rule(f"adbot · 0-lead kill RM80 (7d) · {TOKEN}", 8000,
                           {"field": "campaign.name", "value": [TOKEN], "operator": "CONTAIN"}),
                      rule("adbot · 0-lead kill RM105 (7d) · others", 10500,
                           {"field": "campaign.name", "value": [TOKEN], "operator": "NOT_CONTAIN"})]
        by_name = {r.get("name"): r for r in existing}
        for w in wanted:
            if DRY:
                log.info("  [dry-run] would create: %s", json.dumps(w, ensure_ascii=False))
                continue
            if w["name"] in by_name:
                rid = by_name[w["name"]]["id"]
                log.info("  = exists %s %r", rid, w["name"])
            else:
                try:
                    rid = g._request("POST", f"{acct}/adrules_library",
                                     data={k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                                           for k, v in w.items()})["id"]
                    log.info("  + created %s %r", rid, w["name"])
                    created.append(f"{label}:{rid}")
                except GraphError as exc:
                    log.error("  ❌ create failed %r: %s", w["name"], exc)
                    continue
            try:
                back = g.get_object(rid, "name,status,evaluation_spec,execution_spec,schedule_spec")
                log.info("    readback: %s", json.dumps(back, ensure_ascii=False)[:400])
                pv = g._get_all(f"{rid}/preview", {"limit": 50})
                names = [f"{p.get('name') or p.get('id')}" for p in pv]
                log.info("    preview（现在就会被它关的广告，%d 支）: %s", len(names), names[:12])
                previews.append(f"{label}/{w['name']}: {len(names)}")
            except GraphError as exc:
                log.info("    (readback/preview failed: %s)", exc)
    final_summary(log, ("DRY RUN — nothing created" if DRY else
                        f"rules created {created or 'none new'} · previews {previews}"))


if __name__ == "__main__":
    main()
