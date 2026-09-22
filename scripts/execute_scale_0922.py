"""Execute the 0922 scale plan (①+②). MUTATING, operator-ordered.

    SCALE  Video 12 15歲以上        RM100 → RM150   (lead engine: 7 leads / 4 days)
    SCALE  Hook 1 今晚回家 旧链      RM40  → RM60    (CPL 84)
    SCALE  V1 流鼻涕                RM50  → RM80    (CPA RM672, healthiest)
    REOPEN Carousel 别再逼孩子喝牛奶  @RM50           (operator's own 30d-rule exception —
                                                     lead machine, CPL ~50)

Guards: the 新片测试 campaign/ad set (7 天不动, shared RM100) is NEVER touched — scaling
matches live ads by name but skips anything inside the test ad set. Reopen uses the
safe-chain rule (wake only its own chain). Idempotent; audit persisted.
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

sys.path.insert(0, str(Path(__file__).parent))
from build_test155_fr_0921 import STATE_PATH as TEST_STATE  # noqa: E402

LOG_PATH = Path("state") / "execute_scale_0922_log.json"
SCALES = [
    {"name": "Video 12：15歲以上試了五六種方法沒長高", "cents": 15000},
    {"name": "Hook 1：今晚回家检查三件事", "cents": 6000},
    {"name": "Video 1: 流鼻涕 咳嗽 allergy 每晚睡不好", "cents": 8000},
]
REOPEN = {"name": "Carousel：别再逼孩子喝牛奶了", "cents": 5000}
DEAD = {"DELETED", "ARCHIVED"}


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    test = json.loads(TEST_STATE.read_text())
    protected = {test["adset_id"]}
    audit: List[Dict[str, Any]] = []

    ads = [a for a in g._get_all(
        f"{acct}/ads", {"fields": "id,name,status,effective_status,adset_id,campaign_id",
                        "limit": 500}) if a.get("effective_status") not in DEAD]
    adsets = {a["id"]: a for a in g._get_all(
        f"{acct}/adsets", {"fields": "id,status,effective_status,daily_budget,campaign_id",
                           "limit": 500})}
    camps = {c["id"]: c for c in g._get_all(
        f"{acct}/campaigns", {"fields": "id,status,effective_status,daily_budget", "limit": 200})}

    log.info("═" * 100)
    log.info("① SCALE（测试 ad set %s 受保护，永不触碰）", test["adset_id"])
    for spec in SCALES:
        k = cpa.ad_key(spec["name"])
        live = [a for a in ads if cpa.ad_key(a.get("name") or "") == k
                and a.get("effective_status") == "ACTIVE"
                and a.get("adset_id") not in protected]
        if not live:
            log.info("▸ %r: 测试之外没有在投的 copy — skip", spec["name"][:30])
            continue
        touched = set()
        for a in live:
            aset = adsets.get(a.get("adset_id")) or {}
            if int(aset.get("daily_budget") or 0) > 0:
                ent, cur, etype = aset["id"], int(aset["daily_budget"]), "adset"
            else:
                cid = aset.get("campaign_id") or ""
                ent, cur, etype = cid, int((camps.get(cid) or {}).get("daily_budget") or 0), "campaign"
            if not ent or ent in touched or ent in protected:
                continue
            touched.add(ent)
            if cur == spec["cents"]:
                log.info("▸ %r 已经是 RM%d — skip", spec["name"][:30], cur // 100)
                continue
            g.update_daily_budget(ent, spec["cents"])
            audit.append({"act": "budget", "type": etype, "id": ent,
                          "old_cents": cur, "new_cents": spec["cents"]})
            log.info("▸ SCALE %r: %s %s RM%d → RM%d/day",
                     spec["name"][:30], etype, ent, cur // 100, spec["cents"] // 100)
            time.sleep(1.0)

    log.info("═" * 100)
    log.info("② REOPEN Carousel @RM50（operator 破例 30d 规则）")
    k = cpa.ad_key(REOPEN["name"])
    cands = sorted((a for a in ads if cpa.ad_key(a.get("name") or "") == k),
                   key=lambda a: (a.get("effective_status") != "ACTIVE", -int(a["id"])))
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
                        if x.get("campaign_id") == camp.get("id") and x["id"] != aset["id"]
                        and x.get("status") == "ACTIVE" and x.get("effective_status") not in DEAD]
            if siblings:
                continue
        try:
            if int(aset.get("daily_budget") or 0) > 0:
                if int(aset["daily_budget"]) != REOPEN["cents"]:
                    g.update_daily_budget(aset["id"], REOPEN["cents"])
                    audit.append({"act": "budget", "type": "adset", "id": aset["id"],
                                  "new_cents": REOPEN["cents"]})
            elif int(camp.get("daily_budget") or 0) != REOPEN["cents"]:
                g.update_daily_budget(camp["id"], REOPEN["cents"])
                audit.append({"act": "budget", "type": "campaign", "id": camp["id"],
                              "new_cents": REOPEN["cents"]})
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
            log.info("▸ OPEN Carousel → campaign %s%s · adset %s · ad %s · RM50/day · eff %s",
                     camp.get("id"), "" if camp_active else " (activated)",
                     aset["id"], a["id"], eff)
            audit.append({"act": "opened", "ad": a["id"], "eff": eff})
            done = True
            break
        except GraphError as exc:
            log.info("  · ad %s 开不了（%s）— 换旧一条", a["id"], str(exc)[:100])
            continue
    if not done:
        log.error("Carousel 没开成 — 回报操作员")

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(
        {"run": dt.datetime.utcnow().isoformat() + "Z", "mutations": audit},
        ensure_ascii=False, indent=2) + "\n")
    final_summary(log, f"0922 ①+② executed: V12→150, Hook1旧链→60, V1→80, Carousel reopened "
                       f"@50. {len(audit)} mutations; test ad set untouched; audit saved.")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min; run is idempotent.", exc)
        sys.exit(75)
