"""Execute the operator-approved 0919 window verdicts. MUTATING, operator-ordered.

Operator (19 Sep): "执行 全部照你说的做" on the Fri→now analysis:
    CLOSE  🌟 Hook 9 孩子没以前活泼   — RM154 window spend, 0 leads (≥ RM142.50 line)
    SCALE  Video 12 15歲以上五六種方法 — CPL RM40, lifetime CPA RM606 → RM60/day (+20%)
    SCALE  Carousel 别再逼孩子喝牛奶   — CPL RM41 → RM60/day (its budget sits on the campaign)
    (Hook 4 stays RM80 untouched; Hook 8 was already auto-killed by the monitor.)

Close = pause every ACTIVE ad folding to the name + its ad set once emptied; campaigns
untouched. Scale = set the chain's budget entity (ABO ad set, else CBO campaign) to
RM60/day. Idempotent; audit in state/execute_window_0919_log.json.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from adbot import cpa
from adbot.clients.graph import TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

LOG_PATH = Path("state") / "execute_window_0919_log.json"
SCALE_MINOR = 6000                      # RM60/day, the approved +20%

CLOSE_NAMES = ["Hook 9：你有没有发现孩子没有以前那么活泼了？变得越来越安静？自卑？"]
SCALE_NAMES = ["Video 12：15歲以上試了五六種方法沒長高", "Carousel：别再逼孩子喝牛奶了"]


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    audit: List[Dict[str, Any]] = []

    ads = g._get_all(f"{acct}/ads",
                     {"fields": "id,name,status,effective_status,adset_id", "limit": 500})
    adsets = {a["id"]: a for a in g._get_all(
        f"{acct}/adsets", {"fields": "id,daily_budget,campaign_id", "limit": 500})}
    camps = {c["id"]: c for c in g._get_all(
        f"{acct}/campaigns", {"fields": "id,daily_budget", "limit": 200})}

    def key(name: str) -> str:
        return cpa.ad_key(name or "")

    log.info("═" * 100)
    for name in CLOSE_NAMES:
        k = key(name)
        targets = [a for a in ads if key(a.get("name")) == k
                   and a.get("effective_status") == "ACTIVE"]
        if not targets:
            log.info("▸ %r: 已经没有在投的 copy（monitor 或先前动作已处理）— skip", name[:30])
            continue
        for a in targets:
            g.update_status(a["id"], "PAUSED")
            a["status"] = "PAUSED"
            audit.append({"act": "pause_ad", "id": a["id"], "name": a.get("name")})
            log.info("▸ PAUSED ad %s %r", a["id"], (a.get("name") or "")[:44])
            sid = a.get("adset_id")
            others = [x for x in ads if x.get("adset_id") == sid and x["id"] != a["id"]
                      and x.get("status") == "ACTIVE"]
            if sid and not others:
                g.update_status(sid, "PAUSED")
                audit.append({"act": "pause_adset", "id": sid})
                log.info("  └ PAUSED adset %s", sid)
            time.sleep(1.0)

    log.info("═" * 100)
    for name in SCALE_NAMES:
        k = key(name)
        live = [a for a in ads if key(a.get("name")) == k
                and a.get("effective_status") == "ACTIVE"]
        if not live:
            log.info("▸ %r: 没有在投的 copy — 不 scale，回报操作员", name[:30])
            continue
        touched = set()
        for a in live:
            aset = adsets.get(a.get("adset_id")) or {}
            if int(aset.get("daily_budget") or 0) > 0:
                ent, cur = aset["id"], int(aset["daily_budget"])
                etype = "adset"
            else:
                cid = aset.get("campaign_id") or ""
                camp = camps.get(cid) or {}
                ent, cur = cid, int(camp.get("daily_budget") or 0)
                etype = "campaign"
            if not ent or ent in touched:
                continue
            touched.add(ent)
            if cur == SCALE_MINOR:
                log.info("▸ %r %s %s 已经是 RM60 — skip", name[:30], etype, ent)
                continue
            g.update_daily_budget(ent, SCALE_MINOR)
            audit.append({"act": "budget", "type": etype, "id": ent,
                          "old_cents": cur, "new_cents": SCALE_MINOR})
            log.info("▸ SCALE %r: %s %s RM%d → RM60/day", name[:30], etype, ent, cur // 100)
            time.sleep(1.0)

    # verify the three chains' end state
    log.info("═" * 100)
    for name in CLOSE_NAMES + SCALE_NAMES:
        k = key(name)
        rows = []
        for a in ads:
            if key(a.get("name")) != k:
                continue
            fresh = g.get_object(a["id"], "effective_status").get("effective_status")
            if fresh in ("DELETED", "ARCHIVED"):
                continue
            rows.append(fresh)
        log.info("▸ %-34s copies eff: %s", name[:34], ", ".join(sorted(set(rows))) or "∅")

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(
        {"run": dt.datetime.utcnow().isoformat() + "Z", "mutations": audit},
        ensure_ascii=False, indent=2) + "\n")
    final_summary(log, f"0919 window verdicts executed: Hook 9 closed, V12 + Carousel at "
                       f"RM60/day. {len(audit)} mutations; audit persisted.")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min; run is idempotent.", exc)
        sys.exit(75)
