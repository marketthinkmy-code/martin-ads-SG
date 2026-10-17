"""老片重开 2 — 6 more (17 Oct operator: 对，照建，现在跑). Based on 老片重开 (17 Oct operator: 对，RM50，照建，现在跑): 9 dormant SG sellers relaunched on HK.

Two ABO campaigns, one ad set per creative, RM50 each, ACTIVE now. Each ad copies the exact
name and page post of its newest source ad (read live, never typed), so the sales sheet keeps
folding onto the same creative. Audiences: Family and Relationships (HK template) and
Food and Drink + Milk (the live HK Video 5 ad set). Idempotent via
state/entities_relaunch_1017.json; 75 = throttle.
"""
from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from adbot.clients.graph import GraphError, TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "entities_relaunch2_1017.json"
HK_ACCT = "act_1179668409969241"
DAILY_MINOR = 5000
CAMPAIGNS: List[Dict[str, Any]] = [
    {"key": "fr", "tpl": "120250013469590335", "adset": "Interest: Family and Relationships",
     "name": "[SG] 儿童长高方程式 | Family and Relationships | 老片重开 2 | 1-5-5",
     "src": {"story": "120238647357240093", "gh": "120250024004770335", "img4m": "120256016497810093",
             "h11": "120250294305930093", "h10": "120242608781520093"}},
    {"key": "milk", "tpl": "120250236478750335", "adset": "Interest: Food and Drink + Milk",
     "name": "[SG] 儿童长高方程式 | Food and Drink + Milk | 老片重开 2 | 1-1-1",
     "src": {"h5picky": "120240932989800093"}},
]


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    m = s.meta
    conv = m.conversion_domain_bare or None
    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
    for k in ("src", "creatives", "campaigns", "adsets", "ads"):
        st.setdefault(k, {})

    def persist() -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    # 1. read every source ad first; abort before building anything if one is unreadable
    for c in CAMPAIGNS:
        for key, ad_id in c["src"].items():
            if st["src"].get(key):
                continue
            try:
                a = g.get_object(ad_id, "name,creative{effective_object_story_id}")
            except GraphError as exc:
                log.error("❌ 源广告 %s (%s) 读不到：%s —— 停止，未建任何东西。", ad_id, key, str(exc)[:100])
                sys.exit(1)
            post = (a.get("creative") or {}).get("effective_object_story_id")
            if not post:
                log.error("❌ 源广告 %s %r 没有帖子 id —— 停止。", ad_id, a.get("name"))
                sys.exit(1)
            st["src"][key] = {"name": a.get("name"), "post": post, "from": ad_id}
            log.info("源 %-10s %s %r · post %s", key, ad_id, a.get("name"), post)
    persist()

    pix = g.get_object("120250013469590335", "promoted_object,optimization_goal,billing_event,bid_strategy")
    rows = []
    for c in CAMPAIGNS:
        ck = c["key"]
        tpl = g.get_object(c["tpl"], "name,targeting")
        t = copy.deepcopy(tpl.get("targeting") or {})
        if not t.get("flexible_spec"):
            log.error("❌ 模板 %s 没有兴趣配方 —— 停止。", c["tpl"])
            sys.exit(1)
        ig = t.get("instagram_positions")
        if ig and "explore_home" in ig and "explore" not in ig:
            t["instagram_positions"] = list(ig) + ["explore"]
        cid = st["campaigns"].get(ck)
        if not cid:
            fields = {"name": c["name"], "objective": m.objective, "buying_type": "AUCTION", "status": "ACTIVE",
                      "special_ad_categories": m.special_ad_categories, "is_adset_budget_sharing_enabled": False}
            if m.regional_regulated_categories:
                fields["regional_regulated_categories"] = m.regional_regulated_categories
            cid = g.create_campaign(HK_ACCT, **fields)["id"]
            st["campaigns"][ck] = cid
            persist()
            log.info("+ campaign %s %r ABO ACTIVE · 受众模板 %s %r", cid, c["name"], c["tpl"], tpl.get("name"))
            time.sleep(1.0)
        for key in c["src"]:
            src = st["src"][key]
            if not st["creatives"].get(key):
                f: Dict[str, Any] = {"name": src["name"], "object_story_id": src["post"]}
                if m.url_tags:
                    f["url_tags"] = m.url_tags
                st["creatives"][key] = g.create_adcreative(HK_ACCT, **f)["id"]
                persist()
                time.sleep(0.8)
            if not st["adsets"].get(key):
                f = {"name": c["adset"], "campaign_id": cid, "daily_budget": DAILY_MINOR, "status": "ACTIVE",
                     "optimization_goal": pix.get("optimization_goal"),
                     "billing_event": pix.get("billing_event") or "IMPRESSIONS",
                     "promoted_object": pix.get("promoted_object") or {}, "targeting": t}
                if pix.get("bid_strategy"):
                    f["bid_strategy"] = pix["bid_strategy"]
                if m.regional_regulated_categories:
                    f["regional_regulated_categories"] = m.regional_regulated_categories
                if m.regional_regulation_identities:
                    f["regional_regulation_identities"] = m.regional_regulation_identities
                st["adsets"][key] = g.create_adset(HK_ACCT, **f)["id"]
                persist()
                time.sleep(1.0)
            if not st["ads"].get(key):
                ad = g.create_ad(HK_ACCT, name=src["name"], adset_id=st["adsets"][key],
                                 creative={"creative_id": st["creatives"][key]}, status="ACTIVE", conversion_domain=conv)
                st["ads"][key] = ad["id"]
                persist()
                time.sleep(0.8)
            eff = g.get_object(st["ads"][key], "effective_status").get("effective_status")
            log.info("    ▸ %s · adset %s RM%d · ad %s %r · %s", ck, st["adsets"][key], DAILY_MINOR // 100,
                     st["ads"][key], src["name"], eff)
            rows.append(eff)
    final_summary(log, f"老片重开 2 built ACTIVE on HK: campaigns {st['campaigns']} · {len(rows)} ads · RM{DAILY_MINOR // 100} each")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — state saved, re-dispatch in ~30 min.", exc)
        sys.exit(75)
