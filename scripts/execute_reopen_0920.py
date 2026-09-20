"""Reopen the two 30d-CPA-qualified names (20 Sep). MUTATING, operator-ordered ("开").

    OPEN  Video 1 流鼻涕咳嗽 allergy   at RM50/day   (30d CPA RM672 · 终身 6单/RM666)
    OPEN  🌟 Hook 9 孩子没以前活泼      at RM30/day   (30d CPA RM712 · 终身 3单/RM453)

No cpl_hold exemption for Hook 9 — the operator accepts the standing zero-reg kill.
Chain picking: prefer a copy already delivering, else newest copy whose revival wakes
ONLY its own chain (campaign ACTIVE → activate ad set + ad; campaign PAUSED with every
sibling ad set individually paused → activate campaign too). Budget lands on the chain's
budget entity (ABO ad set, else CBO campaign). Idempotent; audit persisted.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from adbot import cpa
from adbot.clients.graph import GraphError, TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

LOG_PATH = Path("state") / "execute_reopen_0920_log.json"
OPENS: List[Dict[str, Any]] = [
    {"name": "Video 1: 流鼻涕 咳嗽 allergy 每晚睡不好", "budget": 5000},
    {"name": "Hook 9：你有没有发现孩子没有以前那么活泼了？变得越来越安静？自卑？", "budget": 3000},
]
DEAD = {"DELETED", "ARCHIVED"}


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    conv = s.meta.conversion_domain_bare or None  # noqa: F841  (parity with builders)
    audit: List[Dict[str, Any]] = []

    ads = [a for a in g._get_all(
        f"{acct}/ads", {"fields": "id,name,status,effective_status,adset_id,campaign_id",
                        "limit": 500}) if a.get("effective_status") not in DEAD]
    adsets = {a["id"]: a for a in g._get_all(
        f"{acct}/adsets", {"fields": "id,name,status,effective_status,daily_budget,campaign_id",
                           "limit": 500})}
    camps = {c["id"]: c for c in g._get_all(
        f"{acct}/campaigns", {"fields": "id,name,status,effective_status,daily_budget",
                              "limit": 200})}

    rows: List[str] = []
    for spec in OPENS:
        name, budget = spec["name"], int(spec["budget"])
        k = cpa.ad_key(name)
        cands = sorted((a for a in ads if cpa.ad_key(a.get("name") or "") == k),
                       key=lambda a: (a.get("effective_status") != "ACTIVE", -int(a["id"])))
        if not cands:
            log.info("▸ %r: 账户里找不到任何 copy — SKIP", name[:34])
            rows.append(f"{name[:22]}: ❌ 找不到")
            continue
        done = False
        for a in cands:
            aset = adsets.get(a.get("adset_id")) or {}
            camp = camps.get(aset.get("campaign_id") or a.get("campaign_id")) or {}
            if not aset or not camp or camp.get("effective_status") in DEAD \
                    or aset.get("effective_status") in DEAD:
                continue
            camp_active = camp.get("status") == "ACTIVE"
            if not camp_active:
                siblings = [x for x in adsets.values()
                            if x.get("campaign_id") == camp.get("id")
                            and x["id"] != aset["id"] and x.get("status") == "ACTIVE"
                            and x.get("effective_status") not in DEAD]
                if siblings:
                    log.info("  · ad %s 的 campaign %s 关着且还有 %d 个 active ad set — 换旧一条",
                             a["id"], camp.get("id"), len(siblings))
                    continue
            try:
                if int(aset.get("daily_budget") or 0) > 0:
                    if int(aset["daily_budget"]) != budget:
                        g.update_daily_budget(aset["id"], budget)
                        audit.append({"act": "budget_adset", "id": aset["id"], "cents": budget})
                elif int(camp.get("daily_budget") or 0) > 0:
                    if int(camp["daily_budget"]) != budget:
                        g.update_daily_budget(camp["id"], budget)
                        audit.append({"act": "budget_campaign", "id": camp["id"], "cents": budget})
                if not camp_active:
                    g.update_status(camp["id"], "ACTIVE")
                    audit.append({"act": "activate_campaign", "id": camp["id"]})
                if aset.get("status") != "ACTIVE":
                    g.update_status(aset["id"], "ACTIVE")
                    audit.append({"act": "activate_adset", "id": aset["id"]})
                if a.get("status") != "ACTIVE":
                    g.update_status(a["id"], "ACTIVE")
                    audit.append({"act": "activate_ad", "id": a["id"]})
                time.sleep(1.0)
                eff = g.get_object(a["id"], "effective_status").get("effective_status")
                log.info("▸ OPEN %r → campaign %s%s · adset %s @RM%d · ad %s · eff %s",
                         name[:34], camp.get("id"), "" if camp_active else " (activated)",
                         aset["id"], budget // 100, a["id"], eff)
                rows.append(f"{name[:22]}: {eff} @RM{budget // 100}")
                audit.append({"act": "opened", "ad": a["id"], "adset": aset["id"],
                              "campaign": camp.get("id"), "eff": eff, "cents": budget})
                done = True
                break
            except GraphError as exc:
                log.info("  · ad %s 开不了（%s）— 换旧一条", a["id"], str(exc)[:120])
                continue
        if not done:
            log.info("▸ %r: 所有 copy 都开不了 — 回报操作员", name[:34])
            rows.append(f"{name[:22]}: ❌ 没开成")

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(
        {"run": dt.datetime.utcnow().isoformat() + "Z", "mutations": audit},
        ensure_ascii=False, indent=2) + "\n")
    final_summary(log, f"Reopen executed: {'; '.join(rows)}. {len(audit)} mutations; "
                       f"audit persisted. Hook 9 stays under the zero-reg rule (no hold).")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min; run is idempotent.", exc)
        sys.exit(75)
