"""成交机器 1-1-2 on the old SG account (operator, 8 Oct): revive the two ads that sold.

Sheet (refreshed 8 Oct): MAR Video 5：林書豪story 30d 2 sales CPA 301; Hook 3：倒掉牛奶
30d 2 sales CPA 552 — both currently off everywhere. One CBO RM80/day campaign (PAUSED),
one F&R-template ad set, two ads reusing the original page posts (ad names kept exactly
so the sheet keeps folding onto their lineage). Idempotent; Meta throttle exits 75.
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

STATE_PATH = Path("state") / "entities_sellers_1008.json"
CAMPAIGN_NAME = "[SG] 儿童长高方程式 | Family and Relationships | 成交机器 | 1-1-2"
ADSET_NAME = "Interest: Family and Relationships"
TPL_FR = "120250013469590335"
CBO_MINOR = 8000
P = "341825319024143_"
ADS: List[Dict[str, str]] = [
    {"key": "linshuhao", "name": "MAR Video 5：林書豪story", "post": "", "from_ad": "120250093193110335"},
    {"key": "daodiao",   "name": "Hook 3：倒掉牛奶",           "post": P + "122197861250485585", "from_ad": ""},
]


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    m = s.meta
    acct = m.account_path
    conv = m.conversion_domain_bare or None
    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}

    def persist() -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    st.setdefault("posts", {})
    for a in ADS:
        if st["posts"].get(a["key"]):
            continue
        pid = a["post"]
        if not pid:
            src = g.get_object(a["from_ad"], "name,creative{effective_object_story_id}")
            pid = (src.get("creative") or {}).get("effective_object_story_id")
            log.info("源 ad %s %r → post %s", a["from_ad"], src.get("name"), pid)
        if not pid:
            log.error("❌ %r 拿不到帖子 id，停止。", a["name"])
            sys.exit(1)
        st["posts"][a["key"]] = pid
        persist()

    tpl = g.get_object(TPL_FR, "name,targeting,promoted_object,optimization_goal,billing_event")
    t = copy.deepcopy(tpl.get("targeting") or {})
    if not t.get("flexible_spec"):
        log.error("❌ 模板没有兴趣配方，停止。")
        sys.exit(1)
    ig = t.get("instagram_positions")
    if ig and "explore_home" in ig and "explore" not in ig:
        t["instagram_positions"] = list(ig) + ["explore"]

    if st.get("campaign_id"):
        try:
            eff = g.get_object(st["campaign_id"], "effective_status").get("effective_status")
        except GraphError:
            eff = "DELETED"
        if eff in ("DELETED", "ARCHIVED"):
            st.pop("campaign_id", None)
    if not st.get("campaign_id"):
        fields: Dict[str, Any] = {"name": CAMPAIGN_NAME, "objective": m.objective,
                                  "buying_type": "AUCTION", "status": "PAUSED",
                                  "special_ad_categories": m.special_ad_categories,
                                  "daily_budget": CBO_MINOR,
                                  "bid_strategy": "LOWEST_COST_WITHOUT_CAP"}
        if m.regional_regulated_categories:
            fields["regional_regulated_categories"] = m.regional_regulated_categories
        st["campaign_id"] = g.create_campaign(acct, **fields)["id"]
        persist()
        log.info("+ campaign %s %r CBO RM%d/day (PAUSED)", st["campaign_id"], CAMPAIGN_NAME, CBO_MINOR // 100)
        time.sleep(1.0)
    if not st.get("adset_id"):
        fields = {"name": ADSET_NAME, "campaign_id": st["campaign_id"],
                  "optimization_goal": tpl.get("optimization_goal"),
                  "billing_event": tpl.get("billing_event") or "IMPRESSIONS",
                  "promoted_object": tpl.get("promoted_object") or {},
                  "targeting": t, "status": "ACTIVE"}
        if m.regional_regulated_categories:
            fields["regional_regulated_categories"] = m.regional_regulated_categories
        if m.regional_regulation_identities:
            fields["regional_regulation_identities"] = m.regional_regulation_identities
        st["adset_id"] = g.create_adset(acct, **fields)["id"]
        persist()
        log.info("+ adset %s %r", st["adset_id"], ADSET_NAME)
        time.sleep(1.0)

    st.setdefault("creatives", {})
    st.setdefault("ads", {})
    rows = []
    for a in ADS:
        k = a["key"]
        if not st["creatives"].get(k):
            fields = {"name": a["name"], "object_story_id": st["posts"][k]}
            if m.url_tags:
                fields["url_tags"] = m.url_tags
            st["creatives"][k] = g.create_adcreative(acct, **fields)["id"]
            persist()
            time.sleep(0.8)
        if not st["ads"].get(k):
            st["ads"][k] = g.create_ad(acct, name=a["name"], adset_id=st["adset_id"],
                                       creative={"creative_id": st["creatives"][k]},
                                       status="ACTIVE", conversion_domain=conv)["id"]
            persist()
            time.sleep(0.8)
        eff = g.get_object(st["ads"][k], "effective_status").get("effective_status")
        log.info("  ▸ %s %r ← post %s · eff %s", st["ads"][k], a["name"], st["posts"][k], eff)
        rows.append(f"{k}:{eff}")
    final_summary(log, f"成交机器 built PAUSED on {acct}: campaign {st['campaign_id']} CBO RM{CBO_MINOR // 100}/day · "
                       f"adset {st['adset_id']} · {'; '.join(rows)}")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — state saved, re-dispatch in ~30 min.", exc)
        sys.exit(75)
