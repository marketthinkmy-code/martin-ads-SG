"""Move Video 12 into the Family and Relationships audience (operator, 10 Oct: 搬).

Its 3 SG sales came from Family and Relationships (2) and Parents 3-17 + Engaged (1), none
from BROAD WOMEN where it was reopened this afternoon. So: a third ad set in the new F&R
新片 campaign (same template, RM50, start 2026-10-11 00:00 MYT, PAUSED like its siblings)
holding Video 12 on its existing post, then the BROAD WOMEN ad set and its campaign go
PAUSED. Idempotent via state/entities_newpair_1011.json (keys fr:v12).
"""
from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict

from adbot.clients.graph import GraphError, TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "entities_newpair_1011.json"
HK_ACCT = "act_1179668409969241"
FR_CAMPAIGN = "120250236476000335"         # [SG] 儿童长高方程式 | Family and Relationships | 新片 | 1-2-2
FR_TEMPLATE = "120250013469590335"         # HK F&R template (targeting + pixel)
SRC_AD = "120250046126010335"              # Video 12 in BROAD WOMEN (its post comes from here)
OLD_ADSET = "120250046126040335"           # BROAD WOMEN
OLD_CAMPAIGN = "120250046125980335"        # [SG] 儿童长高方程式 | BROAD WOMEN | CPA 好的广告
AD_NAME = "Video 12：15歲以上試了五六種方法沒長高"
ADSET_NAME = "Interest: Family and Relationships"
START_TIME = "2026-10-11T00:00:00+0800"
DAILY_MINOR = 5000


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    m = s.meta
    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
    for k in ("creatives", "adsets", "ads"):
        st.setdefault(k, {})
    st.setdefault("video12_move", {})

    def persist() -> None:
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    def set_status(eid: str, status: str, what: str) -> None:
        before = g.get_object(eid, "name,status,effective_status")
        if before.get("status") == status:
            log.info("   = %s %s %r already %s", what, eid, before.get("name"), status)
            return
        g._request("POST", eid, data={"status": status})
        after = g.get_object(eid, "status,effective_status")
        log.info("   %s %s %s %r %s → %s/%s", "⏸" if status == "PAUSED" else "▶️", what, eid, before.get("name"),
                 before.get("status"), after.get("status"), after.get("effective_status"))
        st["video12_move"].setdefault("actions", []).append({"id": eid, "what": what, "from": before.get("status"), "to": after.get("status")})

    # 1. the post behind Video 12
    src = g.get_object(SRC_AD, "name,creative{id,effective_object_story_id}")
    post = (src.get("creative") or {}).get("effective_object_story_id")
    if not post or AD_NAME[:8] not in (src.get("name") or ""):
        log.error("❌ 源广告 %s 读不到帖子或名字不符（%r / %s）—— 停止。", SRC_AD, src.get("name"), post)
        sys.exit(1)
    log.info("Video 12 帖子 %s（来自 ad %s）", post, SRC_AD)

    # 2. creative (de-duped by Meta if identical)
    if not st["creatives"].get("v12"):
        fields: Dict[str, Any] = {"name": AD_NAME, "object_story_id": post}
        if m.url_tags:
            fields["url_tags"] = m.url_tags
        st["creatives"]["v12"] = g.create_adcreative(HK_ACCT, **fields)["id"]
        persist()
        log.info("  + creative %s", st["creatives"]["v12"])
        time.sleep(0.8)

    # 3. the ad set in the F&R 新片 campaign
    camp = g.get_object(FR_CAMPAIGN, "name,status,daily_budget")
    if camp.get("daily_budget"):
        log.error("❌ campaign %s 是 CBO，停止。", FR_CAMPAIGN)
        sys.exit(1)
    tpl = g.get_object(FR_TEMPLATE, "targeting,promoted_object,optimization_goal,billing_event,bid_strategy")
    t = copy.deepcopy(tpl.get("targeting") or {})
    ig = t.get("instagram_positions")
    if ig and "explore_home" in ig and "explore" not in ig:
        t["instagram_positions"] = list(ig) + ["explore"]
    if not st["adsets"].get("fr:v12"):
        fields = {"name": ADSET_NAME, "campaign_id": FR_CAMPAIGN, "daily_budget": DAILY_MINOR,
                  "start_time": START_TIME, "status": "PAUSED",
                  "optimization_goal": tpl.get("optimization_goal"),
                  "billing_event": tpl.get("billing_event") or "IMPRESSIONS",
                  "promoted_object": tpl.get("promoted_object") or {}, "targeting": t}
        if tpl.get("bid_strategy"):
            fields["bid_strategy"] = tpl["bid_strategy"]
        if m.regional_regulated_categories:
            fields["regional_regulated_categories"] = m.regional_regulated_categories
        if m.regional_regulation_identities:
            fields["regional_regulation_identities"] = m.regional_regulation_identities
        st["adsets"]["fr:v12"] = g.create_adset(HK_ACCT, **fields)["id"]
        persist()
        log.info("  + adset %s %r RM%d · start %s (PAUSED) in %r", st["adsets"]["fr:v12"], ADSET_NAME,
                 DAILY_MINOR // 100, START_TIME, camp.get("name"))
        time.sleep(1.0)
    if not st["ads"].get("fr:v12"):
        ad = g.create_ad(HK_ACCT, name=AD_NAME, adset_id=st["adsets"]["fr:v12"],
                         creative={"creative_id": st["creatives"]["v12"]}, status="ACTIVE",
                         conversion_domain=m.conversion_domain_bare or None)
        st["ads"]["fr:v12"] = ad["id"]
        persist()
        time.sleep(0.8)
    eff = g.get_object(st["ads"]["fr:v12"], "effective_status").get("effective_status")
    log.info("    ▸ ad %s %r eff %s", st["ads"]["fr:v12"], AD_NAME, eff)

    # 4. BROAD WOMEN off (ad set, then its campaign shell)
    set_status(OLD_ADSET, "PAUSED", "old adset")
    set_status(OLD_CAMPAIGN, "PAUSED", "old campaign")
    st["video12_move"].update({"post": post, "new_adset": st["adsets"]["fr:v12"], "new_ad": st["ads"]["fr:v12"]})
    persist()
    final_summary(log, f"Video 12 → F&R 新片: adset {st['adsets']['fr:v12']} RM50 start {START_TIME} (PAUSED) · "
                       f"ad {st['ads']['fr:v12']} ({eff}) · BROAD WOMEN {OLD_ADSET} + campaign {OLD_CAMPAIGN} PAUSED")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — state saved, re-dispatch in ~30 min.", exc)
        sys.exit(75)
