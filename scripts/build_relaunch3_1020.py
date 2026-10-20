"""老片重开 3 (20 Oct operator: 全建，RM50，今天开跑): sellers back in the audiences they sold in.

Two ABO campaigns on HK, one ad set per creative, RM50 each, ACTIVE now:
  Health and Wellness 1-3-3: Video: 孩子15岁以上还有机会长高吗？ / Video: 什麼樣的孩子基本上不會再長高 /
                              Video 5：Kaya 面包配 Milo
  Luxury 1-2-2:              Video: 孩子15岁以上还有机会长高吗？ / Hook 5：孩子挑食
Targeting is copied from the SG old ad set where the old videos sold (Health & Wellness
120250914933290093, Luxury 120238644972660093). The Luxury one excluded MARTIN.csv; it gets the
same two exclusions the Health & Wellness ad set uses (15 days complete registration +
马丁 1997 Paid Student, both already used on HK). Each ad copies the name and page post of its
source ad (read live). All creatives are made before any campaign, so an unreadable post
stops the build with nothing created. Idempotent via state/entities_relaunch3_1020.json; 75 = throttle.
Campaign names carry 老片重开 → monitor RM90 zero-registration line (config kpi.cpl_min_spend_overrides).
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

STATE_PATH = Path("state") / "entities_relaunch3_1020.json"
HK_ACCT = "act_1179668409969241"
DAILY_MINOR = 5000
HW_TPL = "120250914933290093"
SRC = {  # key -> source ad (the ad the creative sold in, or the live HK ad)
    "q15": "120250914933320093",      # SG old, Health & Wellness, 176 registrations
    "nogrow": "120253308921300093",   # SG old, Health & Wellness, 38 registrations
    "v5kaya": "120250236479810335",   # HK, live Video 5
    "picky": "120250334623090335",    # HK, live Hook 5
}
CAMPAIGNS: List[Dict[str, Any]] = [
    {"key": "hw", "tpl": HW_TPL, "adset": "Interest: Health and Wellness",
     "name": "[SG] 儿童长高方程式 | Health and Wellness | 老片重开 3 | 1-3-3", "ads": ["q15", "nogrow", "v5kaya"]},
    {"key": "lux", "tpl": "120238644972660093", "adset": "Interest: Luxury",
     "name": "[SG] 儿童长高方程式 | Luxury | 老片重开 3 | 1-2-2", "ads": ["q15", "picky"]},
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

    # 1. source ads
    for key, ad_id in SRC.items():
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
        log.info("源 %-7s %s %r · post %s", key, ad_id, a.get("name"), post)
    persist()

    # 2. targeting
    excl = (g.get_object(HW_TPL, "targeting").get("targeting") or {}).get("excluded_custom_audiences") or []
    if not excl:
        log.error("❌ Health & Wellness 模板没有排除名单 —— 停止。")
        sys.exit(1)
    tgt: Dict[str, Dict[str, Any]] = {}
    for c in CAMPAIGNS:
        tpl = g.get_object(c["tpl"], "name,targeting")
        t = copy.deepcopy(tpl.get("targeting") or {})
        if not t.get("flexible_spec"):
            log.error("❌ 模板 %s 没有兴趣配方 —— 停止。", c["tpl"])
            sys.exit(1)
        t["excluded_custom_audiences"] = [{"id": x["id"]} for x in excl]
        if t.get("genders") in ([0], []):
            t.pop("genders", None)
        t.pop("custom_audiences", None)
        ig = t.get("instagram_positions")
        if ig and "explore_home" in ig and "explore" not in ig:
            t["instagram_positions"] = list(ig) + ["explore"]
        tgt[c["key"]] = t
        log.info("受众 %s ← SG老 ad set %s %r · 排除 %s", c["key"], c["tpl"], tpl.get("name"), [x.get("name") for x in excl])

    # 3. creatives first (one per source; reused across audiences)
    for key, src in st["src"].items():
        if st["creatives"].get(key):
            continue
        f: Dict[str, Any] = {"name": src["name"], "object_story_id": src["post"]}
        if m.url_tags:
            f["url_tags"] = m.url_tags
        try:
            st["creatives"][key] = g.create_adcreative(HK_ACCT, **f)["id"]
        except GraphError as exc:
            log.error("❌ creative %s %r 建不了：%s —— 停止（campaign 还没建）。", key, src["name"], str(exc)[:160])
            persist()
            sys.exit(1)
        persist()
        log.info("+ creative %s %s", key, st["creatives"][key])
        time.sleep(0.8)

    pix = g.get_object("120250013469590335", "promoted_object,optimization_goal,billing_event,bid_strategy")
    rows = []
    for c in CAMPAIGNS:
        ck = c["key"]
        cid = st["campaigns"].get(ck)
        if not cid:
            fields = {"name": c["name"], "objective": m.objective, "buying_type": "AUCTION", "status": "ACTIVE",
                      "special_ad_categories": m.special_ad_categories, "is_adset_budget_sharing_enabled": False}
            if m.regional_regulated_categories:
                fields["regional_regulated_categories"] = m.regional_regulated_categories
            cid = g.create_campaign(HK_ACCT, **fields)["id"]
            st["campaigns"][ck] = cid
            persist()
            log.info("+ campaign %s %r ABO ACTIVE", cid, c["name"])
            time.sleep(1.0)
        for key in c["ads"]:
            slot = f"{ck}:{key}"
            src = st["src"][key]
            if not st["adsets"].get(slot):
                f = {"name": c["adset"], "campaign_id": cid, "daily_budget": DAILY_MINOR, "status": "ACTIVE",
                     "optimization_goal": pix.get("optimization_goal"),
                     "billing_event": pix.get("billing_event") or "IMPRESSIONS",
                     "promoted_object": pix.get("promoted_object") or {}, "targeting": tgt[ck]}
                if pix.get("bid_strategy"):
                    f["bid_strategy"] = pix["bid_strategy"]
                if m.regional_regulated_categories:
                    f["regional_regulated_categories"] = m.regional_regulated_categories
                if m.regional_regulation_identities:
                    f["regional_regulation_identities"] = m.regional_regulation_identities
                st["adsets"][slot] = g.create_adset(HK_ACCT, **f)["id"]
                persist()
                time.sleep(1.0)
            if not st["ads"].get(slot):
                ad = g.create_ad(HK_ACCT, name=src["name"], adset_id=st["adsets"][slot],
                                 creative={"creative_id": st["creatives"][key]}, status="ACTIVE", conversion_domain=conv)
                st["ads"][slot] = ad["id"]
                persist()
                time.sleep(0.8)
    # 4. read back
    for c in CAMPAIGNS:
        cid = st["campaigns"][c["key"]]
        co = g.get_object(cid, "name,effective_status")
        log.info("▌campaign %s %r · %s", cid, co.get("name"), co.get("effective_status"))
        for key in c["ads"]:
            slot = f"{c['key']}:{key}"
            a = g.get_object(st["adsets"][slot], "name,daily_budget,effective_status")
            ad = g.get_object(st["ads"][slot], "name,effective_status")
            log.info("    ad set %s %r RM%d %s · ad %s %r %s", st["adsets"][slot], a.get("name"),
                     int(a.get("daily_budget") or 0) // 100, a.get("effective_status"),
                     st["ads"][slot], ad.get("name"), ad.get("effective_status"))
            rows.append(ad.get("effective_status"))
    final_summary(log, f"老片重开 3 built on HK: campaigns {st['campaigns']} · {len(rows)} ads · RM{DAILY_MINOR // 100} each · {rows}")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — state saved, re-dispatch in ~30 min.", exc)
        sys.exit(75)
