"""Reopen Video 12：15歲以上試了五六種方法沒長高 in place, RM50 (operator, 10 Oct: 开 Video 12 RM50).

Evidence: 30d 2 sales CPA 593, 60d 3 sales CPA 652, lead→buyer 25% — the only seller besides
林書豪 / 倒掉牛奶. It sits paused in HK campaign "[SG] 儿童长高方程式 | BROAD WOMEN | CPA 好的广告"
(whole campaign paused). That campaign holds other ads whose own status is still ACTIVE, so
switching the campaign on would wake them too. Order of operations, all logged before/after:
  1. every OTHER ad in the campaign whose own status is ACTIVE → PAUSED
  2. every OTHER ad set in the campaign whose own status is ACTIVE → PAUSED
  3. BROAD WOMEN ad set: daily_budget → RM50, status → ACTIVE
  4. Video 12 ad → ACTIVE
  5. campaign → ACTIVE (last, so nothing else can deliver in between)
Record: state/reopen_video12_1010.json. Nothing is deleted.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "reopen_video12_1010.json"
CAMPAIGN = "120250046125980335"   # [SG] 儿童长高方程式 | BROAD WOMEN | CPA 好的广告 (HK)
ADSET = "120250046126040335"      # BROAD WOMEN
AD = "120250046126010335"         # Video 12：15歲以上試了五六種方法沒長高
BUDGET_MINOR = 5000               # RM50/day


def main() -> None:
    log = get_logger()
    g = graph_client(load_settings())
    st: Dict[str, Any] = {"actions": [], "at": dt.datetime.utcnow().isoformat() + "Z"}

    def set_status(eid: str, status: str, what: str) -> None:
        before = g.get_object(eid, "name,status,effective_status")
        if before.get("status") == status:
            log.info("   = %s %s %r already %s", what, eid, before.get("name"), status)
            return
        g._request("POST", eid, data={"status": status})
        after = g.get_object(eid, "status,effective_status")
        log.info("   %s %s %s %r %s → %s/%s", "▶️" if status == "ACTIVE" else "⏸", what, eid,
                 before.get("name"), before.get("status"), after.get("status"), after.get("effective_status"))
        st["actions"].append({"id": eid, "what": what, "name": before.get("name"),
                              "from": before.get("status"), "to": after.get("status")})

    camp = g.get_object(CAMPAIGN, "name,status,effective_status,daily_budget")
    ad = g.get_object(AD, "name,status,effective_status,adset_id,campaign_id")
    if ad.get("campaign_id") != CAMPAIGN or ad.get("adset_id") != ADSET:
        log.error("❌ ad %s 不在预期的 campaign/ad set（%s / %s）—— 停止。", AD, ad.get("campaign_id"), ad.get("adset_id"))
        raise SystemExit(1)
    if camp.get("daily_budget"):
        log.error("❌ campaign 是 CBO（RM%d），RM50 要设在 campaign 层，先停下来问操作员。", int(camp["daily_budget"]) // 100)
        raise SystemExit(1)
    log.info("campaign %s %r · %s/%s · ABO", CAMPAIGN, camp.get("name"), camp.get("status"), camp.get("effective_status"))

    # 1. other ads
    ads: List[Dict[str, Any]] = g._get_all(f"{CAMPAIGN}/ads", {"fields": "id,name,status,effective_status,adset_id", "limit": 200})
    for a in ads:
        flag = "目标" if a["id"] == AD else ("自身 ACTIVE，会跟着开 → 先关" if a.get("status") == "ACTIVE" else "自身已停")
        log.info("   · ad %s %r adset %s · %s/%s · %s", a["id"], (a.get("name") or "")[:34], a.get("adset_id"),
                 a.get("status"), a.get("effective_status"), flag)
    for a in ads:
        if a["id"] != AD and a.get("status") == "ACTIVE":
            set_status(a["id"], "PAUSED", "other ad")
    # 2. other ad sets
    for s in g._get_all(f"{CAMPAIGN}/adsets", {"fields": "id,name,status,daily_budget", "limit": 100}):
        log.info("   · adset %s %r · %s · RM%d", s["id"], s.get("name"), s.get("status"), int(s.get("daily_budget") or 0) // 100)
        if s["id"] != ADSET and s.get("status") == "ACTIVE":
            set_status(s["id"], "PAUSED", "other adset")
    # 3. target ad set: budget then on
    before = g.get_object(ADSET, "name,daily_budget,status")
    if int(before.get("daily_budget") or 0) != BUDGET_MINOR:
        g._request("POST", ADSET, data={"daily_budget": BUDGET_MINOR})
        after = g.get_object(ADSET, "daily_budget")
        log.info("   💰 adset %s %r RM%d → RM%d", ADSET, before.get("name"),
                 int(before.get("daily_budget") or 0) // 100, int(after.get("daily_budget") or 0) // 100)
        st["actions"].append({"id": ADSET, "what": "budget", "from": int(before.get("daily_budget") or 0) // 100,
                              "to": int(after.get("daily_budget") or 0) // 100})
    set_status(ADSET, "ACTIVE", "adset")
    # 4. the ad, 5. the campaign
    set_status(AD, "ACTIVE", "ad")
    set_status(CAMPAIGN, "ACTIVE", "campaign")

    # read back: what delivers in this campaign now
    live = [a for a in g._get_all(f"{CAMPAIGN}/ads", {"fields": "id,name,effective_status", "limit": 200})
            if a.get("effective_status") in ("ACTIVE", "IN_PROCESS", "PENDING_REVIEW")]
    log.info("回读：campaign 内在投 %d 支 → %s", len(live), [(a["id"], (a.get("name") or "")[:30], a.get("effective_status")) for a in live])
    st["live_after"] = [a["id"] for a in live]
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))
    final_summary(log, f"Video 12 reopened: campaign {CAMPAIGN} · adset {ADSET} RM{BUDGET_MINOR // 100} · ad {AD} · "
                       f"{len(st['actions'])} status/budget changes · {len(live)} ad(s) delivering")


if __name__ == "__main__":
    main()
