"""Sep 新片 2 支测试 (25 Sep): NEW account · 1-1-2 · RM60/day · PAUSED.

Operator-approved spec:
    Campaign 「[SG] 儿童长高方程式 | Parents 3-17 + Engaged | Sep 新片 2 支测试 | 1-1-2」
    on act_1179668409969241 (the A/B account), ABO, created PAUSED.
    One ad set 「Parents 3-17 + Engaged」 RM60/day — targeting + promoted_object cloned
    verbatim from the ported V12 ad set on the SAME account (shared buyer exclusions
    already inside). Two ads with the approved block-layout copies:
        Sep Video 1：是谁说的（钙质迷思）   ← Drive 1yAIft0i2AeyuYQZLcCa3-YtUlbcNcIUH (A02)
        Sep Video 3：完蛋了（基因迷思）     ← Drive 15s3Kc4N9yahNtqzpoKswrhb2MHKqBW-p (A02)
    Standard rules apply (zero-reg kill, 30d CPA discipline); NO cpl_hold exemption.
Idempotent via state/entities_sep_test_0925.json; rate limit exits 75, re-dispatch resumes.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from adbot.clients.drive import DriveClient
from adbot.clients.graph import GraphError, TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

NEW_ACCT = "act_1179668409969241"
V12_ADSET_NEWACCT = "120250013348250335"     # targeting + promoted_object source
STATE_PATH = Path("state") / "entities_sep_test_0925.json"
CAMPAIGN_NAME = "[SG] 儿童长高方程式 | Parents 3-17 + Engaged | Sep 新片 2 支测试 | 1-1-2"
ADSET_NAME = "Parents 3-17 + Engaged"
DAILY_MINOR = 6000

ADS: List[Dict[str, str]] = [
    {"key": "sepv1", "drive": "1yAIft0i2AeyuYQZLcCa3-YtUlbcNcIUH",
     "ad_name": "Sep Video 1：是谁说的（钙质迷思）",
     "title": "🔴 谁说喝牛奶补钙，一定能长高？"},
    {"key": "sepv3", "drive": "15s3Kc4N9yahNtqzpoKswrhb2MHKqBW-p",
     "ad_name": "Sep Video 3：完蛋了（基因迷思）",
     "title": "🔴 爸妈不高，孩子就完蛋了？谁说的！"},
]

BODIES: Dict[str, str] = {
    "sepv1": """🥛 谁说喝牛奶、补钙一定能长高？
如果真的这么简单，
那每天喝牛奶、天天补钙的孩子，
应该个个都长得很高才对啊！

事实上，钙质只是孩子成长需要的其中一种营养。
孩子能不能把长高潜力发挥出来，
还要看他的体质，和生活习惯的搭配适不适合他。

所以我一直跟家长说，
不要再只是问："我的孩子还要补什么？"
👉 你更应该问的是：
"到底是哪一个地方，正在影响我孩子的成长？"

大家好，我是来自台湾、同时拥有 2 个执照的马丁医师 🧑🏻‍⚕️🇹🇼
拥有超过 10 年中西医整合经验，
已帮助 10,000+ 位来自不同国家的孩子健康长高！

💡 在我的免费线上分享会中，你将学习：
✅ 怎么从体质出发，找出真正影响孩子长高的地方
✅ 饮食、睡眠、运动，哪一个应该优先调整
✅ 用中西医学的系统方法，让孩子每年健康长高 6-8cm

⚠️ 名额有限，坐满即止！
点击以下 Button 立即免费报名，
别再只是一直补——先找出孩子卡住的地方更重要！我们课程见！👋""",
    "sepv3": """😱 "爸爸妈妈都不高，孩子一定也很矮！完蛋了！"
诶，是谁跟你说的？
如果你也这样想，
那你可能太早帮孩子的身高"下定论"了。

基因确实会影响身高，
👉 但这不代表孩子的身高只剩一个固定答案。
后天，还是可以争取的！

关键就在 5-17 岁的黄金长高期：
😴 睡得对不对？
🥣 吃得对不对？
🏃 运动够不够？
🌿 身体状况好不好？
这些，才是家长现在还能管理的条件。

大家好，我是来自台湾、同时拥有 2 个执照的马丁医师 🧑🏻‍⚕️🇹🇼
拥有超过 10 年中西医整合经验，
已帮助 10,000+ 位来自不同国家的孩子健康长高！
很多孩子在家长找对方向之后，身高和身体状况都有很不错的改变。

💡 在我的免费线上分享会中，你将学习：
✅ 用中西医学的角度，系统看懂孩子目前的成长状况
✅ 从饮食、睡眠、运动里，找出最值得优先调整的地方
✅ 在生长板闭合之前，把还能管理的条件做好

⚠️ 名额有限，坐满即止！
点击以下 Button 立即免费报名，
基因不能改，但孩子的成长条件你现在还能管理！我们课程见！👋""",
}


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

    src = g.get_object(V12_ADSET_NEWACCT,
                       "name,targeting,promoted_object,optimization_goal,billing_event,"
                       "bid_strategy")
    targeting = src.get("targeting") or {}
    adv = ((targeting.get("targeting_automation") or {}).get("advantage_audience"))
    exc = targeting.get("excluded_custom_audiences") or []
    log.info("定向克隆自新账户 V12 adset %s: ages %s-%s · Adv+ %s · 排除受众 %d 个",
             V12_ADSET_NEWACCT, targeting.get("age_min"), targeting.get("age_max"),
             adv, len(exc))

    # ── videos → creatives ─────────────────────────────────────────────────────
    creatives: Dict[str, Any] = st.setdefault("creatives", {})
    drive = None
    for v in ADS:
        rec: Dict[str, Any] = creatives.get(v["key"]) or {}
        if rec.get("creative_id"):
            log.info("── %s: reuse creative %s", v["key"], rec["creative_id"])
            creatives[v["key"]] = rec
            continue
        video_id = rec.get("video_id")
        if video_id:
            thumb = rec.get("thumb") or g.get_video_thumbnail(video_id)
        else:
            if drive is None:
                drive = DriveClient(s.secrets.google_sa_json)
            path = Path(f"/tmp/{v['key']}.mp4")
            drive.download_file(v["drive"], path)
            log.info("── %s: downloaded %.1f MB → uploading to %s…", v["key"],
                     path.stat().st_size / 1_048_576, NEW_ACCT)
            video_id = g.upload_video(NEW_ACCT, str(path), name=v["ad_name"])
            thumb = g.get_video_thumbnail(video_id)
            path.unlink(missing_ok=True)
            rec.update({"video_id": video_id, "thumb": thumb})
            creatives[v["key"]] = rec
            persist()
        cta = {"type": m.call_to_action, "value": {"link": m.lead_destination.link_url}}
        vdata: Dict[str, Any] = {"video_id": video_id, "title": v["title"],
                                 "message": BODIES[v["key"]], "call_to_action": cta}
        if thumb:
            vdata["image_url"] = thumb
        story: Dict[str, Any] = {"page_id": m.page_id, "video_data": vdata}
        if m.instagram_user_id:
            story["instagram_user_id"] = m.instagram_user_id
        fields: Dict[str, Any] = {"name": v["ad_name"], "object_story_spec": story}
        if m.url_tags:
            fields["url_tags"] = m.url_tags
        rec["creative_id"] = g.create_adcreative(NEW_ACCT, **fields)["id"]
        creatives[v["key"]] = rec
        persist()
        log.info("── %s: + creative %s (video %s)", v["key"], rec["creative_id"], video_id)
        time.sleep(1.0)

    # ── campaign (PAUSED) · adset · 2 ads ──────────────────────────────────────
    if st.get("campaign_id"):
        try:
            eff = g.get_object(st["campaign_id"], "effective_status").get("effective_status")
        except GraphError:
            eff = "DELETED"
        if eff in ("DELETED", "ARCHIVED"):
            st.pop("campaign_id", None)
            st.pop("adset_id", None)
            st.pop("ads", None)
    if not st.get("campaign_id"):
        fields = {"name": CAMPAIGN_NAME, "objective": m.objective,
                  "buying_type": "AUCTION", "status": "PAUSED",
                  "special_ad_categories": m.special_ad_categories,
                  "is_adset_budget_sharing_enabled": False}
        if m.regional_regulated_categories:
            fields["regional_regulated_categories"] = m.regional_regulated_categories
        st["campaign_id"] = g.create_campaign(NEW_ACCT, **fields)["id"]
        persist()
        log.info("+ campaign %s %r (PAUSED)", st["campaign_id"], CAMPAIGN_NAME)
        time.sleep(1.0)

    if not st.get("adset_id"):
        fields = {"name": ADSET_NAME, "campaign_id": st["campaign_id"],
                  "optimization_goal": src.get("optimization_goal"),
                  "billing_event": src.get("billing_event") or "IMPRESSIONS",
                  "promoted_object": src.get("promoted_object") or {},
                  "targeting": targeting, "status": "ACTIVE",
                  "daily_budget": DAILY_MINOR,
                  "bid_strategy": src.get("bid_strategy") or "LOWEST_COST_WITHOUT_CAP"}
        if m.regional_regulated_categories:
            fields["regional_regulated_categories"] = m.regional_regulated_categories
        if m.regional_regulation_identities:
            fields["regional_regulation_identities"] = m.regional_regulation_identities
        st["adset_id"] = g.create_adset(NEW_ACCT, **fields)["id"]
        persist()
        log.info("+ adset %s %r RM60/day", st["adset_id"], ADSET_NAME)
        time.sleep(1.0)

    st.setdefault("ads", {})
    rows = []
    for v in ADS:
        if not st["ads"].get(v["key"]):
            ad = g.create_ad(NEW_ACCT, name=v["ad_name"], adset_id=st["adset_id"],
                             creative={"creative_id": creatives[v["key"]]["creative_id"]},
                             status="ACTIVE", conversion_domain=conv)
            st["ads"][v["key"]] = ad["id"]
            persist()
            time.sleep(1.0)
        eff = g.get_object(st["ads"][v["key"]], "effective_status").get("effective_status")
        log.info("▸ %s ad %s %r eff %s", v["key"], st["ads"][v["key"]], v["ad_name"], eff)
        rows.append(f"{v['key']}:{eff}")

    final_summary(log, f"Sep 1-1-2 test built PAUSED on {NEW_ACCT}: campaign "
                       f"{st['campaign_id']} · adset {st['adset_id']} RM60/day · "
                       f"{'; '.join(rows)}. Operator flips the campaign to start; standard "
                       f"rules apply (no hold).")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min; run is idempotent.", exc)
        sys.exit(75)
