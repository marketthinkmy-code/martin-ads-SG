"""Shopper & Health 1-5-5 REBUILD: delete the mis-built grid, build the operator's form.

Operator (12 Sep, with a structure picture): "我要这样的形式，不是分开 · 删掉，重建 · 1-5-5"
    Campaign A
      - ad set A - ad 1 (RM50/day)
      - ad set A - ad 2 (RM50/day)
      ...
    = ONE campaign · the SAME combined-targeting ad set duplicated FIVE times (RM50/day
    each) · ONE ad per ad set, so every ad spends evenly (the house rule). The four
    keyword themes are ONE audience, not four separate ad sets — that was the mis-read.

Steps:
  1. DELETE the mis-built campaign 120258299111680093 (the 4-targeting x 4-ads grid).
  2. Build: [SG] 儿童长高方程式 | Shopper & Health Interests | 1-5-5 (ABO, ACTIVE)
     · 5 ad sets, all named "Engaged Shoppers + Vitamins + Health & Wellness +
       Supplements", identical combined targeting (behavior 6071631541183 OR interests
       6803120807074 / 6003331809777 / 6003258544357 / 6003384248805 / 6003382102565),
       SG 25+, Advantage+ ON, exclusions + SG regulated fields as standard, RM50/day.
     · one proven ad per set (exact historical names for attribution):
       15岁以上 · Hook 3 早餐面包 · 林書豪 · V1 流鼻涕 Learn More · Hook 7 (rebuilt on its
       original video with the operator-approved Learn More copy — old post is
       WhatsApp-banned). +RM250/day total.

Idempotent via state/entities_shopper_health_155.json.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "entities_shopper_health_155.json"
OLD_CAMPAIGN = "120258299111680093"          # the mis-built 4x4 grid — delete
CAMPAIGN_NAME = "[SG] 儿童长高方程式 | Shopper & Health Interests | 1-5-5"
ADSET_NAME = "Engaged Shoppers + Vitamins + Health & Wellness + Supplements"
DAILY_MINOR = 5000

FLEX = [{
    "behaviors": [{"id": "6071631541183", "name": "Engaged shoppers"}],
    "interests": [
        {"id": "6803120807074", "name": "Vitamins and nutritional supplements"},
        {"id": "6003331809777", "name": "Folic acid"},
        {"id": "6003258544357", "name": "Health & wellness"},
        {"id": "6003384248805", "name": "Fitness and wellness"},
        {"id": "6003382102565", "name": "Healthy diet"},
    ],
}]

ADS: List[Dict[str, str]] = [    # one per ad set; creative_id resolved from the 1-4-4 state
    {"key": "v15plus", "name": "Video: 孩子15岁以上还有机会长高吗？", "creative": "1312364757098700"},
    {"key": "hook3bread", "name": "MAR Video Hook 3: 准备早餐面包", "creative": "562113746716671"},
    {"key": "v5lin", "name": "MAR Video 5：林書豪story", "creative": "1132702978964396"},
    {"key": "v1learn", "name": "Video 1: 流鼻涕 咳嗽 allergy 每晚睡不好", "creative": "2071081143496182"},
    {"key": "hook7", "name": "Hook 7: 担心孩子的高度没跟得上年龄该有的高度", "creative": ""},  # rebuilt below
]

HOOK7_VIDEO = "1581713046358741"
HOOK7_TITLE = "🔴 孩子的身高，跟上年龄了吗？"
HOOK7_BODY = """📏 担心孩子的高度，没跟得上年龄该有的高度？

尤其适合这些家长：
🛑 孩子一年长不到 6cm
🛑 骨龄超前 / 落后
🛑 性早熟
🛑 睡不深、注意力不集中
🛑 课业压力大，越坐越"矮"

大家好，我是马丁医师 🇹🇼
台湾儿童长高专家，中西医整合经验超过 10 年。

🌍 我已经帮助台湾、新加坡、马来西亚、澳洲、加拿大等地
超过 10,000+ 位孩子健康长高——
其中很多，是被认为"很难再长高"的孩子。

💡 如果你：
👉 担心父母不高，孩子跟着长不高
👉 试过网上的偏方、保健品、运动，都没动静
👉 中医西医都看了，还是不见效

放心，作为一位父亲，我懂你的心情。
❌ 不打针、不逼孩子吞难吃的补品
✅ 只用简单、健康、有科学根据的方法——
先把身体调好，营养吸收得进去，身高自然跟上来。

✨ 我把整套方法放进一堂免费的线上课程：
✅ 5-17 岁孩子的黄金长高期，到底在什么时候
✅ 怎么科学管理身高，不错过关键节点
✅ 哪些营养和运动真正有效，让长高变简单
✅ 成长金三角：身高、注意力、睡眠一起管

⏳ 生长板一旦闭合，就再也追不回来了。
👇 点击下方按钮，立即免费报名，我们课程见！"""


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
        STATE_PATH.write_text(json.dumps(st, indent=2, ensure_ascii=False) + "\n")

    # ── 1) delete the mis-built grid campaign ───────────────────────────────────
    if not st.get("old_deleted"):
        cur = g.get_object(OLD_CAMPAIGN, "status,name")
        if cur.get("status") == "DELETED":
            log.info("── old campaign already DELETED")
        else:
            g.update_status(OLD_CAMPAIGN, "DELETED")
            after = g.get_object(OLD_CAMPAIGN, "status")
            if after.get("status") != "DELETED":
                raise SystemExit(f"!! old campaign not deleted (status {after.get('status')})")
            log.info("── deleted mis-built campaign %s (%r)", OLD_CAMPAIGN, cur.get("name"))
        st["old_deleted"] = True
        persist()

    # ── 2) Hook 7 rebuilt creative (operator-approved copy, original video) ─────
    if not st.get("hook7_creative_id"):
        thumb = g.get_video_thumbnail(HOOK7_VIDEO)
        vdata: Dict[str, Any] = {
            "video_id": HOOK7_VIDEO, "title": HOOK7_TITLE, "message": HOOK7_BODY,
            "call_to_action": {"type": m.call_to_action,
                               "value": {"link": m.lead_destination.link_url}}}
        if thumb:
            vdata["image_url"] = thumb
        story: Dict[str, Any] = {"page_id": m.page_id, "video_data": vdata}
        if m.instagram_user_id:
            story["instagram_user_id"] = m.instagram_user_id
        fields: Dict[str, Any] = {"name": "Hook 7: 担心孩子的高度没跟得上年龄该有的高度 (Learn More rebuild)",
                                  "object_story_spec": story}
        if m.url_tags:
            fields["url_tags"] = m.url_tags
        st["hook7_creative_id"] = g.create_adcreative(acct, **fields)["id"]
        persist()
        log.info("── hook7: + Learn More rebuild creative %s (video %s)",
                 st["hook7_creative_id"], HOOK7_VIDEO)

    # ── 3) campaign ─────────────────────────────────────────────────────────────
    # 12 Sep: the operator deleted the first 1-5-5 by hand while clearing the mis-build
    # ("应该被我删掉了，重建一个新的") — if the stored campaign is gone, drop the stale ids
    # and build a brand-new one instead of trying to attach ad sets to a deleted parent.
    if st.get("campaign_id"):
        alive = g.get_object(st["campaign_id"], "status").get("status")
        if alive in ("DELETED", "ARCHIVED"):
            log.info("── stored campaign %s is %s — rebuilding fresh", st["campaign_id"], alive)
            st.pop("campaign_id", None)
            st.pop("units", None)
            persist()
    if st.get("campaign_id"):
        log.info("── reuse campaign %s", st["campaign_id"])
    else:
        fields = {"name": CAMPAIGN_NAME, "objective": m.objective, "buying_type": "AUCTION",
                  "status": "ACTIVE", "special_ad_categories": m.special_ad_categories,
                  "is_adset_budget_sharing_enabled": False}
        if m.regional_regulated_categories:
            fields["regional_regulated_categories"] = m.regional_regulated_categories
        st["campaign_id"] = g.create_campaign(acct, **fields)["id"]
        persist()
        log.info("── + campaign %s %r", st["campaign_id"], CAMPAIGN_NAME)

    spec = {
        "geo_locations": {"countries": m.targeting.countries or ["SG"]},
        "age_min": m.targeting.age_min, "age_max": m.targeting.age_max,
        "targeting_automation": {"advantage_audience": 1},
        "excluded_custom_audiences": [{"id": str(c)} for c in
                                      (m.targeting.excluded_custom_audiences or [])],
        "locales": m.targeting.locales or [1004],
        "flexible_spec": FLEX,
    }

    # ── 4) five duplicate ad sets, one ad each ─────────────────────────────────
    rows: List[str] = []
    units: Dict[str, Any] = st.setdefault("units", {})
    for a in ADS:
        rec: Dict[str, Any] = units.setdefault(a["key"], {})
        if not rec.get("adset_id"):
            fields = {"name": ADSET_NAME, "campaign_id": st["campaign_id"],
                      "optimization_goal": m.optimization_goal,
                      "billing_event": "IMPRESSIONS", "promoted_object": m.promoted_object,
                      "targeting": spec, "status": "ACTIVE", "daily_budget": DAILY_MINOR,
                      "bid_strategy": "LOWEST_COST_WITHOUT_CAP"}
            if m.regional_regulated_categories:
                fields["regional_regulated_categories"] = m.regional_regulated_categories
            if m.regional_regulation_identities:
                fields["regional_regulation_identities"] = m.regional_regulation_identities
            rec["adset_id"] = g.create_adset(acct, **fields)["id"]
            persist()
        if not rec.get("ad_id"):
            creative_id = a["creative"] or st["hook7_creative_id"]
            ad = g.create_ad(acct, name=a["name"], adset_id=rec["adset_id"],
                             creative={"creative_id": creative_id},
                             status="ACTIVE", conversion_domain=conv)
            rec["ad_id"] = ad["id"]
            persist()
        fin = g._request("GET", rec["ad_id"], params={"fields": "effective_status"})
        log.info("▸ %-10s adset %s · ad %s · RM50/day · eff %s",
                 a["key"], rec["adset_id"], rec["ad_id"], fin.get("effective_status"))
        rows.append(f"{a['key']}({fin.get('effective_status')})")

    final_summary(
        log, f"1-5-5 rebuilt: old grid campaign DELETED; campaign {st['campaign_id']} · "
             f"5 identical combined-targeting ad sets (RM50/day, one ad each) — "
             f"{'; '.join(rows)}. +RM250/day, ACTIVE; the 11 Sep daily rules govern it.")


if __name__ == "__main__":
    main()
