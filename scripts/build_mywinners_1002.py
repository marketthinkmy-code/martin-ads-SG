"""MY WINNERS on the old SG account (operator, 2 Oct): 有成绩的记得帮我开好在 sg，我验收.

The 9/30-10/2 MY sweep left 7 keepers (CPL ≤ 70 with leads). Five are already in the
SG-back board (准备早餐面包 / 保健品 / 牛奶+面包 / 我不会买牛奶 / 算给你看); the two
missing ones get their own campaign here:
    Video 2 - 一个3～15岁正常健康的孩子   MY 窗口 RM166 · 3L · CPL 55
    JAN Video 10: 马六甲                MY 窗口 RM61 · 2L · CPL 30（内容讲马六甲，SG 验收时自行定夺）
Structure mirrors the house template: 1 campaign CBO RM80/day (PAUSED) → one ad set per
ad, targeting + promoted_object cloned from the SG-back FAMILY ad set (SG · 女 25-65 ·
Adv+ · 双排除), creatives reuse the MY page posts (page shared, engagement pools).
Idempotent via state/entities_mywinners_1002.json; rate limit exits 75.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from adbot.clients.graph import GraphError, TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "entities_mywinners_1002.json"
SGBACK_STATE = Path("state") / "entities_sgback_1002.json"
CAMPAIGN_NAME = "[SG] 儿童长高方程式 | MY WINNERS | 1-2-2"
ADSET_NAME = "MY WINNERS"
CBO_MINOR = 8000
P = "341825319024143_"

ADS: List[Dict[str, str]] = [
    {"key": "age315", "name": "Video 2 - 一个3～15岁正常健康的孩子",
     "post": P + "122103687746485585"},
    {"key": "melaka", "name": "JAN Video 10: 马六甲",
     "post": P + "122129511296485585"},
]


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    m = s.meta
    acct = m.account_path
    conv = m.conversion_domain_bare or None

    tpl_id = json.loads(SGBACK_STATE.read_text())["adsets"]["family_1"]
    tpl = g.get_object(tpl_id, "name,targeting,promoted_object,optimization_goal,"
                               "billing_event")
    t = tpl.get("targeting") or {}
    log.info("模板 = SG-back FAMILY adset %s（geo %s · %s-%s · 排除 %d）", tpl_id,
             (t.get("geo_locations") or {}).get("countries"),
             t.get("age_min"), t.get("age_max"),
             len(t.get("excluded_custom_audiences") or []))

    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}

    def persist() -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    if st.get("campaign_id"):
        try:
            eff = g.get_object(st["campaign_id"], "effective_status").get("effective_status")
        except GraphError:
            eff = "DELETED"
        if eff in ("DELETED", "ARCHIVED"):
            st = {}
    if not st.get("campaign_id"):
        fields = {"name": CAMPAIGN_NAME, "objective": m.objective,
                  "buying_type": "AUCTION", "status": "PAUSED",
                  "special_ad_categories": m.special_ad_categories,
                  "daily_budget": CBO_MINOR,
                  "bid_strategy": "LOWEST_COST_WITHOUT_CAP"}
        if m.regional_regulated_categories:
            fields["regional_regulated_categories"] = m.regional_regulated_categories
        st["campaign_id"] = g.create_campaign(acct, **fields)["id"]
        persist()
        log.info("+ campaign %s %r CBO RM%d/day (PAUSED)", st["campaign_id"],
                 CAMPAIGN_NAME, CBO_MINOR // 100)
        time.sleep(1.0)

    st.setdefault("creatives", {})
    st.setdefault("adsets", {})
    st.setdefault("ads", {})
    rows = []
    for a in ADS:
        if not st["creatives"].get(a["key"]):
            fields: Dict[str, Any] = {"name": a["name"], "object_story_id": a["post"]}
            if m.url_tags:
                fields["url_tags"] = m.url_tags
            st["creatives"][a["key"]] = g.create_adcreative(acct, **fields)["id"]
            persist()
            log.info("  + creative %s ← 老帖 %s", st["creatives"][a["key"]], a["post"])
            time.sleep(1.0)
        if not st["adsets"].get(a["key"]):
            fields = {"name": ADSET_NAME, "campaign_id": st["campaign_id"],
                      "optimization_goal": tpl.get("optimization_goal"),
                      "billing_event": tpl.get("billing_event") or "IMPRESSIONS",
                      "promoted_object": tpl.get("promoted_object") or {},
                      "targeting": t, "status": "ACTIVE"}
            if m.regional_regulated_categories:
                fields["regional_regulated_categories"] = m.regional_regulated_categories
            if m.regional_regulation_identities:
                fields["regional_regulation_identities"] = m.regional_regulation_identities
            st["adsets"][a["key"]] = g.create_adset(acct, **fields)["id"]
            persist()
            log.info("  + adset %s %r", st["adsets"][a["key"]], ADSET_NAME)
            time.sleep(1.0)
        if not st["ads"].get(a["key"]):
            ad = g.create_ad(acct, name=a["name"], adset_id=st["adsets"][a["key"]],
                             creative={"creative_id": st["creatives"][a["key"]]},
                             status="ACTIVE", conversion_domain=conv)
            st["ads"][a["key"]] = ad["id"]
            persist()
            time.sleep(1.0)
        eff = g.get_object(st["ads"][a["key"]], "effective_status").get("effective_status")
        log.info("    ▸ %s %r eff %s", st["ads"][a["key"]], a["name"], eff)
        rows.append(f"{a['key']}:{eff}")

    final_summary(log, f"MY WINNERS built PAUSED on {acct}: campaign {st['campaign_id']} "
                       f"CBO RM{CBO_MINOR // 100}/day · {'; '.join(rows)}. Operator 验收后开.")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min; run is idempotent.", exc)
        sys.exit(75)
