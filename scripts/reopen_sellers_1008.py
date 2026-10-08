"""Reopen the two sellers in place (operator, 8 Oct: 重開舊的，保留 RM80).

    林書豪  — HK ad 120250093193110335 inside the HK FAMILY 1-3-3 campaign
    倒掉牛奶 — the SG-back ENGAGED WOMEN 1-3-3 campaign on the old SG account
For each: campaign → ACTIVE (budget untouched, stays RM80 CBO), every OTHER ad set in
that campaign → PAUSED, the seller's ad set → ACTIVE, the seller's ad → ACTIVE, any other
ad in the same ad set → PAUSED. Everything is logged with before/after statuses and
recorded in state/reopen_sellers_1008.json for undo. Idempotent.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List

from adbot import cpa
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "reopen_sellers_1008.json"
SGBACK = Path("state") / "entities_sgback_1002.json"
TARGETS = [
    {"key": "linshuhao", "label": "林書豪", "ad_id": "120250093193110335", "campaign_id": None,
     "match": "林書豪"},
    {"key": "daodiao", "label": "倒掉牛奶", "ad_id": None, "campaign_id": None, "match": "倒掉牛奶"},
]


def main() -> None:
    log = get_logger()
    g = graph_client(load_settings())
    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {"actions": []}
    sgback = json.loads(SGBACK.read_text())
    TARGETS[1]["campaign_id"] = sgback["campaigns"]["ew"] if isinstance(sgback.get("campaigns"), dict) and "ew" in sgback["campaigns"] else None

    def set_status(eid: str, status: str, what: str) -> None:
        before = g.get_object(eid, "name,status,effective_status")
        if before.get("status") == status:
            log.info("   = %s %s %r already %s", what, eid, before.get("name"), status)
            return
        g._request("POST", eid, data={"status": status})
        after = g.get_object(eid, "status,effective_status")
        log.info("   %s %s %s %r %s → %s/%s", "▶️" if status == "ACTIVE" else "⏸", what, eid,
                 before.get("name"), before.get("status"), after.get("status"), after.get("effective_status"))
        st["actions"].append({"id": eid, "what": what, "from": before.get("status"), "to": status,
                              "at": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"})
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    summary: List[str] = []
    for tgt in TARGETS:
        if tgt["ad_id"]:
            ad = g.get_object(tgt["ad_id"], "id,name,adset_id,campaign_id")
            cid, aid = ad["campaign_id"], ad["adset_id"]
        else:
            cid = tgt["campaign_id"]
            if not cid:
                # fall back: find the SG-back EW campaign by name
                acct = load_settings().meta.account_path
                cands = [c for c in g._get_all(f"{acct}/campaigns", {"fields": "id,name", "limit": 300})
                         if "engaged women" in cpa.norm(c.get("name")) and "1-3-3" in (c.get("name") or "")]
                cid = cands[0]["id"] if cands else None
            ads_in = g._get_all(f"{cid}/ads", {"fields": "id,name,adset_id,status", "limit": 100}) if cid else []
            hit = [a for a in ads_in if tgt["match"] in (a.get("name") or "")]
            if not hit:
                log.error("❌ %s：campaign %s 里找不到 %r，跳过。", tgt["label"], cid, tgt["match"])
                continue
            ad = hit[0]
            aid = ad["adset_id"]
            tgt["ad_id"] = ad["id"]
        camp = g.get_object(cid, "name,status,daily_budget")
        log.info("═══ %s · campaign %s %r · CBO RM%s（不动）", tgt["label"], cid, camp.get("name"),
                 int(camp.get("daily_budget") or 0) // 100)
        set_status(cid, "ACTIVE", "campaign")
        for a_set in g._get_all(f"{cid}/adsets", {"fields": "id,name,status", "limit": 100}):
            if a_set["id"] != aid and a_set.get("status") == "ACTIVE":
                set_status(a_set["id"], "PAUSED", "other adset")
        set_status(aid, "ACTIVE", "adset")
        for a in g._get_all(f"{aid}/ads", {"fields": "id,name,status", "limit": 100}):
            if a["id"] != tgt["ad_id"] and a.get("status") == "ACTIVE":
                set_status(a["id"], "PAUSED", "other ad")
        set_status(tgt["ad_id"], "ACTIVE", "ad")
        eff = g.get_object(tgt["ad_id"], "effective_status").get("effective_status")
        summary.append(f"{tgt['label']}:{eff}")
        log.info("   ✔ %s 现在 %s（campaign %s / adset %s / ad %s）", tgt["label"], eff, cid, aid, tgt["ad_id"])
    final_summary(log, f"reopened in place: {summary}")


if __name__ == "__main__":
    main()
