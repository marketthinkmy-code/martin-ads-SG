"""中英文 (26 Oct operator: 「A」 · campaign 名不需要老片重开): proven SG sellers, English + Chinese.

Two ABO campaigns on HK, one ad set per creative, RM50 each, ACTIVE now:
  [SG] 儿童长高方程式 | Food and Drink + Milk | 中英文 | 1-3-3:
      Hook 7 / Video 3 / Video 1 流鼻涕 (their SG sales were mostly in Food and Drink + Milk)
  [SG] 儿童长高方程式 | Family and Relationships | 中英文 | 1-3-3:
      林書豪story / 什麼樣的孩子 / 孩子15岁以上 (operator chose Family and Relationships for all three)
Targeting = the HK template ad set's audience, through apply_sg_build_defaults() (automatic
placements; home + frequently in + recent), with locales replaced by English (All) + Chinese (All).
The two locale keys are looked up from Meta by name; a miss stops the build before anything is
made. Each ad copies the name and page post of its source ad (read live); all creatives are made
before any campaign. Rule 3 / 4 checks skipped on the operator's instruction. Idempotent via
state/entities_lang_1026.json; 75 = throttle. Campaign names carry "| 中英文 |" (monitor override).
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
from adbot.sg_build_defaults import apply_sg_build_defaults

STATE_PATH = Path("state") / "entities_lang_1026.json"
HK_ACCT = "act_1179668409969241"
DAILY_MINOR = 5000
LOCALE_NAMES = ("English (All)", "Chinese (All)")
SRC = {  # key -> newest SG-market ad of the creative (its name + post are reused)
    "hook7": "120250334555030335",    # Hook 7: 担心孩子的高度没跟得上年龄该有的高度
    "v3": "120250334546960335",       # Video 3：5岁到15岁的孩子
    "v1": "120250334556730335",       # Video 1: 流鼻涕 咳嗽 allergy 每晚睡不好
    "lin": "120250093193110335",      # MAR Video 5：林書豪story
    "nogrow": "120250374484120335",   # Video: 什麼樣的孩子基本上不會再長高
    "q15": "120250374482800335",      # Video: 孩子15岁以上还有机会长高吗？
}
CAMPAIGNS: List[Dict[str, Any]] = [
    {"key": "fdm", "tpl": "120250334622660335", "adset": "Interest: Food and Drink + Milk",
     "name": "[SG] 儿童长高方程式 | Food and Drink + Milk | 中英文 | 1-3-3", "ads": ["hook7", "v3", "v1"]},
    {"key": "fr", "tpl": "120250334621660335", "adset": "Interest: Family and Relationships",
     "name": "[SG] 儿童长高方程式 | Family and Relationships | 中英文 | 1-3-3", "ads": ["lin", "nogrow", "q15"]},
]


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    m = s.meta
    conv = m.conversion_domain_bare or None
    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
    for k in ("src", "locales", "creatives", "campaigns", "adsets", "ads"):
        st.setdefault(k, {})

    def persist() -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    # 1. language keys
    for want in LOCALE_NAMES:
        if st["locales"].get(want):
            continue
        rows = g._request("GET", "search", params={"type": "adlocale", "q": want.split(" ")[0], "limit": 50}).get("data", [])
        hit = next((r for r in rows if (r.get("name") or "").strip().lower() == want.lower()), None)
        if not hit:
            log.error("❌ 语言 %r 在 Meta 查不到（返回 %s）—— 停止，未建任何东西。", want,
                      [(r.get("name"), r.get("key")) for r in rows][:12])
            sys.exit(1)
        st["locales"][want] = hit["key"]
        log.info("语言 %r = %s", want, hit["key"])
    persist()
    locales = [st["locales"][n] for n in LOCALE_NAMES]

    # 2. source ads
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

    # 3. targeting
    tgt: Dict[str, Dict[str, Any]] = {}
    for c in CAMPAIGNS:
        tpl = g.get_object(c["tpl"], "name,targeting")
        t = copy.deepcopy(tpl.get("targeting") or {})
        if not t.get("flexible_spec"):
            log.error("❌ 模板 %s 没有兴趣配方 —— 停止。", c["tpl"])
            sys.exit(1)
        t = apply_sg_build_defaults(t)
        t["locales"] = locales
        t.pop("custom_audiences", None)
        tgt[c["key"]] = t
        log.info("受众 %s ← HK ad set %s %r · 语言 %s · 排除 %s", c["key"], c["tpl"], tpl.get("name"), locales,
                 [x.get("name") or x.get("id") for x in t.get("excluded_custom_audiences") or []])

    # 4. creatives first
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
    # 5. read back
    rows = []
    for c in CAMPAIGNS:
        cid = st["campaigns"][c["key"]]
        co = g.get_object(cid, "name,effective_status")
        log.info("▌campaign %s %r · %s", cid, co.get("name"), co.get("effective_status"))
        for key in c["ads"]:
            slot = f"{c['key']}:{key}"
            a = g.get_object(st["adsets"][slot], "name,daily_budget,effective_status,targeting{locales,geo_locations,publisher_platforms}")
            ad = g.get_object(st["ads"][slot], "name,effective_status")
            log.info("    ad set %s %r RM%d %s · 语言 %s · ad %s %r %s", st["adsets"][slot], a.get("name"),
                     int(a.get("daily_budget") or 0) // 100, a.get("effective_status"), (a.get("targeting") or {}).get("locales"),
                     st["ads"][slot], ad.get("name"), ad.get("effective_status"))
            rows.append(ad.get("effective_status"))
    final_summary(log, f"中英文 built on HK: campaigns {st['campaigns']} · {len(rows)} ads · RM{DAILY_MINOR // 100} each · {rows}")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — state saved, re-dispatch in ~30 min.", exc)
        sys.exit(75)
