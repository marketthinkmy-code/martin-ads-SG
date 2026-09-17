"""Execute the operator-approved CPA verdicts 0917. MUTATING, operator-ordered.

Operator (18 Sep 00:4x MYT): "停掉 你建议要关的。照建议开。全部照你建议" — exactly the
recommendation set from cpa_verdicts_0917:

    CLOSE  Video 1 孩子如果有鼻窦炎  (CPA RM2,240, over the RM1,200 hard stop)
    CLOSE  Video 11 孩子來MC了       (RM1,365 lifetime, zero sales)
    OPEN   🌟 Hook 9 孩子没以前活泼   (CPA RM402)   at RM50/day
    OPEN   Video 12 15歲以上五六種方法 (CPA RM566)   at RM50/day
    OPEN   Video 1 流鼻涕咳嗽allergy  (CPA RM643)   at RM50/day
    OPEN   Carousel 别再逼孩子喝牛奶   (CPA RM819)   at RM50/day

Close = pause every ACTIVE ad folding to the name, then its ad set once no active ads
remain in it; campaigns are never touched. Open = pick the newest intact copy of the name
whose revival wakes ONLY that chain: campaign already ACTIVE (activate ad set + ad), or
campaign PAUSED with every other ad set in it individually paused (activate campaign too).
Budget RM50/day on the ad set (or the campaign when the chain is CBO). Idempotent —
re-running skips whatever already matches; audit in state/execute_cpa_0917_log.json.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from adbot import cpa
from adbot.clients.graph import GraphError, TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

LOG_PATH = Path("state") / "execute_cpa_0917_log.json"
OPEN_BUDGET_MINOR = 5000        # RM50/day, per the approved recommendation

CLOSE_NAMES = ["Video 1: 孩子如果有鼻窦炎", "Video 11：孩子來MC了"]
OPEN_NAMES = [
    "Hook 9：你有没有发现孩子没有以前那么活泼了？变得越来越安静？自卑？",
    "Video 12：15歲以上試了五六種方法沒長高",
    "Video 1: 流鼻涕 咳嗽 allergy 每晚睡不好",
    "Carousel：别再逼孩子喝牛奶了",
]
DEAD = {"DELETED", "ARCHIVED"}


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
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

    def key(name: str) -> str:
        return cpa.ad_key(name or "")

    # ── 1) closes ───────────────────────────────────────────────────────────────
    close_keys = {key(n) for n in CLOSE_NAMES}
    log.info("═" * 100)
    log.info("① 关（只动 ad + ad set，campaign 不碰）")
    for k in close_keys:
        targets = [a for a in ads if key(a.get("name")) == k
                   and a.get("effective_status") == "ACTIVE"]
        if not targets:
            log.info("▸ %s: 没有在投的 copy（可能已手动关了）— skip", k[:34])
            continue
        for a in targets:
            g.update_status(a["id"], "PAUSED")
            a["status"] = "PAUSED"          # keep the local view honest for sibling checks
            audit.append({"act": "pause_ad", "id": a["id"], "name": a.get("name")})
            log.info("▸ PAUSED ad %s %r", a["id"], (a.get("name") or "")[:44])
            sid = a.get("adset_id")
            others = [x for x in ads if x.get("adset_id") == sid and x["id"] != a["id"]
                      and x.get("status") == "ACTIVE"]
            if sid and not others:
                g.update_status(sid, "PAUSED")
                audit.append({"act": "pause_adset", "id": sid})
                log.info("  └ PAUSED adset %s (链上没有别的 active ad)", sid)
            time.sleep(1.0)

    # ── 2) opens ────────────────────────────────────────────────────────────────
    log.info("═" * 100)
    log.info("② 开 · RM50/day（新→旧找一条只会唤醒自己的链）")
    opened_rows: List[str] = []
    for name in OPEN_NAMES:
        k = key(name)
        # a copy that is already delivering wins outright (budget lands on the live
        # chain, all status writes become no-ops); otherwise newest copy first
        cands = sorted((a for a in ads if key(a.get("name")) == k),
                       key=lambda a: (a.get("effective_status") != "ACTIVE",
                                      -int(a["id"])))
        if not cands:
            log.info("▸ %r: 账户里找不到任何 copy — SKIP，回报操作员", name[:34])
            opened_rows.append(f"{name[:24]}: ❌ 找不到")
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
                    log.info("  · copy ad %s 的 campaign %s 关着且里面还有 %d 个 active ad set"
                             "（开它会连带）— 换旧一条", a["id"], camp.get("id"), len(siblings))
                    continue
            try:
                if int(aset.get("daily_budget") or 0) > 0:
                    if int(aset["daily_budget"]) != OPEN_BUDGET_MINOR:
                        g.update_daily_budget(aset["id"], OPEN_BUDGET_MINOR)
                        audit.append({"act": "budget_adset", "id": aset["id"],
                                      "cents": OPEN_BUDGET_MINOR})
                elif int(camp.get("daily_budget") or 0) > 0:
                    if int(camp["daily_budget"]) != OPEN_BUDGET_MINOR:
                        g.update_daily_budget(camp["id"], OPEN_BUDGET_MINOR)
                        audit.append({"act": "budget_campaign", "id": camp["id"],
                                      "cents": OPEN_BUDGET_MINOR})
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
                log.info("▸ OPEN %r → campaign %s%s · adset %s @RM50 · ad %s · eff %s",
                         name[:34], camp.get("id"), "" if camp_active else " (activated)",
                         aset["id"], a["id"], eff)
                opened_rows.append(f"{name[:24]}: {eff}")
                audit.append({"act": "opened", "ad": a["id"], "adset": aset["id"],
                              "campaign": camp.get("id"), "eff": eff})
                done = True
                break
            except GraphError as exc:
                log.info("  · copy ad %s 开不了（%s）— 换旧一条", a["id"],
                         str(exc)[:120])
                continue
        if not done:
            log.info("▸ %r: 所有 copy 都开不了 — 回报操作员", name[:34])
            opened_rows.append(f"{name[:24]}: ❌ 没开成")

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(
        {"run": dt.datetime.utcnow().isoformat() + "Z", "mutations": audit},
        ensure_ascii=False, indent=2) + "\n")
    log.info("═" * 100)
    final_summary(log, f"CPA 0917 executed: closed 鼻窦炎 + V11 chains; opened at RM50/day → "
                       f"{'; '.join(opened_rows)}. {len(audit)} mutations, audit persisted.")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min; run is idempotent.", exc)
        sys.exit(75)
