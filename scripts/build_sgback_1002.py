"""Rebuild the 5×1-3-3 replica board on the OLD SG account (operator, 2 Oct).

Operator: 我发现今天 MY 的广告终于便宜了，帮我开一模一样的在 SG 的 ads manager，
我对 HK 的失望了 — the MY board IS the 5-campaign replica of the hand-built
structure, so this ports that exact structure back to act_1024930575770087.

Per campaign: CBO (PAUSED) · LOWEST_COST_WITHOUT_CAP · OUTCOME_SALES ·
SINGAPORE_UNIVERSAL + identities · 3 identical ad sets (targeting + promoted_object
cloned VERBATIM from the HK counterpart ad set — geo is already SG, the two exclusion
audiences are the SG-native originals) · 1 ad each reusing the existing page posts
(creatives cached per post). Budgets mirror the replica doc: EW 80 / FAMILY 80 /
HOUSEWIFE 60 / MILK 80 / H&W 80 = RM380/day, all idle until the operator flips.
Idempotent via state/entities_sgback_1002.json; rate limit exits 75, re-dispatch resumes.
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

STATE_PATH = Path("state") / "entities_sgback_1002.json"
P = "341825319024143_"

CAMPAIGNS: List[Dict[str, Any]] = [
    {"key": "ew", "name": "[SG] 儿童长高方程式 | ENGAGED WOMEN | 1-3-3 new ads",
     "budget": 8000, "tpl": "120250066977460335",
     "ads": [("Hook 3：倒掉牛奶", P + "122197861250485585"),
             ("Hook 4：保健品叫你丢掉", P + "122197861274485585"),
             ("Hook 1：今晚回家检查三件事", P + "122197861208485585")]},
    {"key": "family", "name": "[SG] 儿童长高方程式 | FAMILY | 1-3-3 new ads",
     "budget": 8000, "tpl": "120250067332510335",
     "ads": [("Hook 7：算给你看", P + "122197861214485585"),
             ("Hook 1：今晚回家检查三件事", P + "122197861208485585"),
             ("Video 3：基因不是保证书", P + "122197328774485585")]},
    {"key": "housewife", "name": "[SG] 儿童长高方程式 | HOUSEWIFE | 1-3-3 new ads",
     "budget": 6000, "tpl": "120250067213050335",
     "ads": [("Video 1：去年半个头，今年一粒头", P + "122197328510485585"),
             ("Video 2：新马家长最怕这个东西！", P + "122197328492485585"),
             ("Hook 8：我劝你，先别买", P + "122197328822485585")]},
    {"key": "milk", "name": "[SG] 儿童长高方程式 | MILK | 1-3-3 new ads",
     "budget": 8000, "tpl": "120250067491610335",
     "ads": [("MAR Video Hook 3: 准备早餐面包", P + "122140406480485585"),
             ("MAR Video 1：我不会买牛奶", P + "122140405604485585"),
             ("MAR Single image 1：牛奶+面包", P + "122184069494485585")]},
    {"key": "hw", "name": "[SG] 儿童长高方程式 | HEALTH & WELLNESS | 1-3-3 new ads",
     "budget": 8000, "tpl": "120250067708850335",
     "ads": [("Video: 什麼樣的孩子基本上不會再長高", P + "122192843480485585"),
             ("Hook 6：没有人会告诉你", P + "122197861238485585"),
             ("Video 4：每天记录身高，却看不懂成长信号", P + "122197328660485585")]},
]


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    m = s.meta
    acct = m.account_path                       # the OLD SG account — config primary
    conv = m.conversion_domain_bare or None
    log.info("目标账户（老 SG）: %s", acct)

    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}

    def persist() -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    creatives = st.setdefault("creatives", {})

    def creative_for(name: str, post: str) -> str:
        if creatives.get(post):
            return creatives[post]
        fields: Dict[str, Any] = {"name": name, "object_story_id": post}
        if m.url_tags:
            fields["url_tags"] = m.url_tags
        cid = g.create_adcreative(acct, **fields)["id"]
        creatives[post] = cid
        persist()
        log.info("   + creative %s ← 老帖 %s", cid, post)
        time.sleep(0.8)
        return cid

    camps = st.setdefault("campaigns", {})
    adsets = st.setdefault("adsets", {})
    ads_st = st.setdefault("ads", {})
    rows = []
    for c in CAMPAIGNS:
        log.info("═" * 100)
        tpl = g.get_object(c["tpl"], "name,targeting,promoted_object,optimization_goal,"
                                     "billing_event")
        t = tpl.get("targeting") or {}
        log.info("▌%s · 模板 HK adset %s（geo %s · %d-%d · 排除 %d）", c["key"], c["tpl"],
                 (t.get("geo_locations") or {}).get("countries"),
                 t.get("age_min") or 0, t.get("age_max") or 0,
                 len(t.get("excluded_custom_audiences") or []))
        if camps.get(c["key"]):
            try:
                eff = g.get_object(camps[c["key"]], "effective_status").get("effective_status")
            except GraphError:
                eff = "DELETED"
            if eff in ("DELETED", "ARCHIVED"):
                camps.pop(c["key"], None)
        if not camps.get(c["key"]):
            fields = {"name": c["name"], "objective": m.objective,
                      "buying_type": "AUCTION", "status": "PAUSED",
                      "special_ad_categories": m.special_ad_categories,
                      "daily_budget": c["budget"],
                      "bid_strategy": "LOWEST_COST_WITHOUT_CAP"}
            if m.regional_regulated_categories:
                fields["regional_regulated_categories"] = m.regional_regulated_categories
            camps[c["key"]] = g.create_campaign(acct, **fields)["id"]
            persist()
            log.info("+ campaign %s %r CBO RM%d/day (PAUSED)", camps[c["key"]],
                     c["name"], c["budget"] // 100)
            time.sleep(1.0)
        for i, (ad_name, post) in enumerate(c["ads"], 1):
            akey = f"{c['key']}_{i}"
            if not adsets.get(akey):
                fields = {"name": tpl.get("name"), "campaign_id": camps[c["key"]],
                          "optimization_goal": tpl.get("optimization_goal"),
                          "billing_event": tpl.get("billing_event") or "IMPRESSIONS",
                          "promoted_object": tpl.get("promoted_object") or {},
                          "targeting": t, "status": "ACTIVE"}
                if m.regional_regulated_categories:
                    fields["regional_regulated_categories"] = m.regional_regulated_categories
                if m.regional_regulation_identities:
                    fields["regional_regulation_identities"] = m.regional_regulation_identities
                adsets[akey] = g.create_adset(acct, **fields)["id"]
                persist()
                log.info("  + adset %s %r", adsets[akey], tpl.get("name"))
                time.sleep(1.0)
            if not ads_st.get(akey):
                ad = g.create_ad(acct, name=ad_name, adset_id=adsets[akey],
                                 creative={"creative_id": creative_for(ad_name, post)},
                                 status="ACTIVE", conversion_domain=conv)
                ads_st[akey] = ad["id"]
                persist()
                time.sleep(1.0)
            eff = g.get_object(ads_st[akey], "effective_status").get("effective_status")
            log.info("    ▸ %s %r eff %s", ads_st[akey], ad_name, eff)
            rows.append(f"{akey}:{eff}")

    final_summary(log, f"SG-back board built PAUSED on {acct}: 5 campaigns CBO RM380/day "
                       f"total · 15 ad sets · 15 ads via post reuse · {len(rows)} ads "
                       f"verified. Operator flips campaigns to start; RM70 rules cover "
                       f"this account as primary.")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min; run is idempotent.", exc)
        sys.exit(75)
