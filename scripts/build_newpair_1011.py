"""Two new posts, two audience campaigns, 1-2-2 each, scheduled 11 Oct 2026 00:00 MYT.

Operator (10 Oct): Video 5：Kaya 面包配 Milo (post 122199998054485585) and
Video 6：花了几千块，孩子还是没长高？ (post 122199998384485585); 全部 schedule 11 oct 2026 00:00 跑;
structure = campaign per audience, one ad set per video (1-2-2 × 2), RM50 per ad set.
Audiences (sales-ranked, 10 Oct): Family and Relationships (19 all-time SG sales) and
Food and Drink + Milk (27 all-time, 20% lead→buyer in 90d) — the latter replaces
Parents 3-17 + Engaged (90d RM13,934 → 3 sales, 1.8%).
Account: HK (林書豪 CPL 64 there vs 101 on the old SG account for the same creative).
Everything PAUSED for 验收; ad sets carry start_time so switching them ACTIVE lets Meta
start at midnight by itself. Idempotent via state/entities_newpair_1011.json; 75 = throttle.
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

STATE_PATH = Path("state") / "entities_newpair_1011.json"
HK_ACCT = "act_1179668409969241"
PAGE = "341825319024143"
START_TIME = "2026-10-11T00:00:00+0800"      # account timezone Asia/Kuala_Lumpur
DAILY_MINOR = 5000                           # RM50 per ad set
PIXEL_TEMPLATE = "120250013469590335"        # HK F&R: promoted_object / optimisation / billing for this account
CAMPAIGNS: List[Dict[str, str]] = [
    {"key": "fr", "tpl": "120250013469590335", "tpl_acct": "HK",
     "name": "[SG] 儿童长高方程式 | Family and Relationships | 新片 | 1-2-2",
     "adset": "Interest: Family and Relationships"},
    {"key": "milk", "tpl": "120258845200600093", "tpl_acct": "SG老",
     "name": "[SG] 儿童长高方程式 | Food and Drink + Milk | 新片 | 1-2-2",
     "adset": "Interest: Food and Drink + Milk"},
]
ADS: List[Dict[str, str]] = [
    {"key": "v5", "name": "Video 5：Kaya 面包配 Milo", "post": f"{PAGE}_122199998054485585"},
    {"key": "v6", "name": "Video 6：花了几千块，孩子还是没长高？", "post": f"{PAGE}_122199998384485585"},
]


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    m = s.meta
    conv = m.conversion_domain_bare or None
    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}

    def persist() -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    # the two posts must exist and be readable before anything is built
    for a in ADS:
        try:
            p = g.get_object(a["post"], "id,created_time,message")
        except GraphError as exc:
            log.error("❌ 帖子 %s 读不到：%s —— 停止，未建任何东西。", a["post"], str(exc)[:120])
            sys.exit(1)
        log.info("帖子 %-28s %s · 发布 %s · 文案 %r", a["name"][:28], p.get("id"), (p.get("created_time") or "")[:16],
                 (p.get("message") or "")[:60].replace("\n", " "))

    pix = g.get_object(PIXEL_TEMPLATE, "promoted_object,optimization_goal,billing_event,bid_strategy")

    st.setdefault("creatives", {})
    for a in ADS:
        if st["creatives"].get(a["key"]):
            continue
        fields: Dict[str, Any] = {"name": a["name"], "object_story_id": a["post"]}
        if m.url_tags:
            fields["url_tags"] = m.url_tags
        st["creatives"][a["key"]] = g.create_adcreative(HK_ACCT, **fields)["id"]
        persist()
        log.info("  + creative %s ← %s", st["creatives"][a["key"]], a["name"])
        time.sleep(0.8)

    st.setdefault("campaigns", {})
    st.setdefault("adsets", {})
    st.setdefault("ads", {})
    rows: List[str] = []
    for c in CAMPAIGNS:
        ck = c["key"]
        tpl = g.get_object(c["tpl"], "name,targeting")
        t = copy.deepcopy(tpl.get("targeting") or {})
        if not t.get("flexible_spec"):
            log.error("❌ 模板 %s 没有兴趣配方，停止。", c["tpl"])
            sys.exit(1)
        dropped = []
        if c["tpl_acct"] != "HK":        # custom audiences belong to the source account
            for k in ("custom_audiences", "excluded_custom_audiences"):
                if t.pop(k, None):
                    dropped.append(k)
        ig = t.get("instagram_positions")
        if ig and "explore_home" in ig and "explore" not in ig:
            t["instagram_positions"] = list(ig) + ["explore"]
        ints = [x.get("name") for fs in t["flexible_spec"] for kind in
                ("interests", "behaviors", "family_statuses") for x in fs.get(kind) or []]
        log.info("═══ %s · 模板 %s %s %r · %s-%s · Adv+ %s · %s%s", ck, c["tpl_acct"], c["tpl"], tpl.get("name"),
                 t.get("age_min"), t.get("age_max"), (t.get("targeting_automation") or {}).get("advantage_audience"),
                 "/".join(ints[:6]), f" · 去掉跨账户的 {dropped}" if dropped else "")

        cid = st["campaigns"].get(ck)
        if cid:
            try:
                eff = g.get_object(cid, "effective_status").get("effective_status")
            except GraphError:
                eff = "DELETED"
            if eff in ("DELETED", "ARCHIVED"):
                cid = None
        if not cid:
            fields = {"name": c["name"], "objective": m.objective, "buying_type": "AUCTION", "status": "PAUSED",
                      "special_ad_categories": m.special_ad_categories, "is_adset_budget_sharing_enabled": False}
            if m.regional_regulated_categories:
                fields["regional_regulated_categories"] = m.regional_regulated_categories
            cid = g.create_campaign(HK_ACCT, **fields)["id"]
            st["campaigns"][ck] = cid
            persist()
            log.info("+ campaign %s %r ABO (PAUSED)", cid, c["name"])
            time.sleep(1.0)

        for a in ADS:
            sk = f"{ck}:{a['key']}"
            if not st["adsets"].get(sk):
                fields = {"name": c["adset"], "campaign_id": cid, "daily_budget": DAILY_MINOR,
                          "start_time": START_TIME, "status": "PAUSED",
                          "optimization_goal": pix.get("optimization_goal"),
                          "billing_event": pix.get("billing_event") or "IMPRESSIONS",
                          "promoted_object": pix.get("promoted_object") or {}, "targeting": t}
                if pix.get("bid_strategy"):
                    fields["bid_strategy"] = pix["bid_strategy"]
                if m.regional_regulated_categories:
                    fields["regional_regulated_categories"] = m.regional_regulated_categories
                if m.regional_regulation_identities:
                    fields["regional_regulation_identities"] = m.regional_regulation_identities
                st["adsets"][sk] = g.create_adset(HK_ACCT, **fields)["id"]
                persist()
                log.info("  + adset %s %r RM%d · start %s (PAUSED)", st["adsets"][sk], c["adset"], DAILY_MINOR // 100, START_TIME)
                time.sleep(1.0)
            if not st["ads"].get(sk):
                ad = g.create_ad(HK_ACCT, name=a["name"], adset_id=st["adsets"][sk],
                                 creative={"creative_id": st["creatives"][a["key"]]}, status="ACTIVE",
                                 conversion_domain=conv)
                st["ads"][sk] = ad["id"]
                persist()
                time.sleep(0.8)
            info = g.get_object(st["adsets"][sk], "start_time,daily_budget,status")
            eff = g.get_object(st["ads"][sk], "effective_status").get("effective_status")
            log.info("    ▸ adset %s start %s RM%d %s · ad %s %r eff %s", st["adsets"][sk], info.get("start_time"),
                     int(info.get("daily_budget") or 0) // 100, info.get("status"), st["ads"][sk], a["name"], eff)
            rows.append(f"{sk}:{eff}")
    final_summary(log, f"新片 1-2-2 ×2 built PAUSED on HK: campaigns {st['campaigns']} · adsets {st['adsets']} · "
                       f"ads {st['ads']} · start {START_TIME} · RM{DAILY_MINOR // 100} each")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — state saved, re-dispatch in ~30 min.", exc)
        sys.exit(75)
