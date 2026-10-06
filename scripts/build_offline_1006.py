"""線下見證 two new videos → HK, 1-1-2 CBO RM50 (operator, 6 Oct).

Operator: 跑新的 campaign，1-1-2，ad set 跟回，CBO RM50 + two Drive videos
(Video 1：KL&SG 線下見面 · Video 2：長高了17cm). Account HK (the operator's latest
choice), ad set targeting cloned from the Interest: Family and Relationships template
(120250013469590335), Drive files matched by NAME (abort on ambiguity), copy per the
Martin copy system (Simplified for SG; proof numbers only as the scripts state them).
Campaign PAUSED, ad set + ads ACTIVE beneath. Idempotent; Meta throttle exits 75.
"""
from __future__ import annotations

import copy
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from adbot.clients.drive import DriveClient
from adbot.clients.graph import GraphError, TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

HK = "act_1179668409969241"
STATE_PATH = Path("state") / "entities_offline_1006.json"
CAMPAIGN_NAME = "[SG] 儿童长高方程式 | Family and Relationships | 线下见证新片 | 1-1-2"
ADSET_NAME = "Interest: Family and Relationships"
TPL_FR = "120250013469590335"
CBO_MINOR = 5000
DRIVE_IDS = ["13AgbS43PH9du1kKl77nLvcdgbxXKbIBN", "1KH_aegPvsnsMsWMIgz-28GyUrbNR7-t6"]

ADS: List[Dict[str, Any]] = [
    {"key": "v1", "ad_name": "Video 1：KL&SG 線下見面",
     "title": "🔴 新马线下见面：几个月前来上课的孩子，长高了",
     "pat": r"video\s*1\b|\bv1\b|線下|线下|offline|kl"},
    {"key": "v2", "ad_name": "Video 2：長高了17cm",
     "title": "🔴 这个孩子，长高了 17cm",
     "pat": r"video\s*2\b|\bv2\b|17"},
]

BODIES: Dict[str, str] = {
    "v1": """📏 这次在新加坡和马来西亚线下见面，
我见到了几个月前来上课的孩子——
有人长高 8 公分，有人 14 公分，
目前追踪到最高的一位，长高了 17 公分。

这些都是 3 到 19 岁的孩子，平均长高了 8 公分。

🗣️ 很多家长还告诉我：
改变的不只是身高，
孩子原本的皮肤敏感、湿疹、鼻子敏感，也跟着慢慢改善了。

👉 孩子长高，不是每天多喝一杯牛奶、
多吃一点补品和钙片就可以的。
每个孩子的情况不一样，调理方法也不一样。
很多时候不是你做得不够多，
而是你还不知道：孩子到底卡在哪里。

🥣 饮食
😴 睡眠
🏃 运动
📱 每天的生活习惯
这些要怎么配合孩子不同阶段的成长，才是分享会里我真正想让家长了解的。

大家好，我是马丁医师 🧑🏻‍⚕️🇹🇼
来自台湾、中西医结合背景，超过 10 年经验，
这些年累积了超过 10,000 位来自不同国家的孩子成长记录。

💡 在我的免费线上分享会，你将学会：
✅ 怎么找出孩子长不高真正卡在哪里
✅ 饮食、睡眠、运动，不同阶段该怎么配合
✅ 用有 SOP 的方式调理体质，帮孩子健康长高

如果你也在担心孩子比同龄人矮、一年没长几公分，
或者试了很多方法还是没效果——
⚠️ 名额有限，坐满即止！
👇 点击下方链接，立即免费报名
趁孩子还在成长阶段，先把真正影响他成长的地方找出来。""",
    "v2": """📏 长高了 17 公分。
这是我们目前追踪到，参加课程后长得最高的孩子之一。

这次再到新加坡、马来西亚办线下课，
我最开心的不是现场坐满了多少家长，
而是看到很多孩子真的长高了——
而且是用天然的方法，不吃保健品、不吃任何药。

前三名分别长高了 17、15、14 公分，
平均每个孩子长高了 8.8 公分。

🗣️ "爸爸妈妈都不矮，孩子的身高却一直追不上。"
🗣️ "一年只长一点点，急死了。"

👉 孩子长不长得高，
真的不是只看有没有喝牛奶，
也不是靠买很多补品给他吃。
真正要看的是这 3 样东西：
🥣 饮食
🏃 运动
😴 睡眠
方向做错了，你再努力，效果还是很有限。

大家好，我是马丁医师 🧑🏻‍⚕️🇹🇼
来自台湾、中西医结合背景，超过 10 年经验，
已帮助 10,000+ 位孩子健康长高！

💡 在我的免费 Zoom 分享会，我会一步一步带你了解：
✅ 孩子目前的成长状况，应该从哪里下手才对
✅ 饮食、睡眠、运动和生活习惯，每天怎么做
✅ 怎么帮孩子达到每年健康长高 6–8cm

⚠️ 名额有限，坐满即止！
👇 点击下方链接，立即免费报名
先把孩子真正的成长问题弄清楚，才知道下一步怎么做。""",
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

    drive = DriveClient(s.secrets.google_sa_json)
    if not st.get("drive_map"):
        metas = []
        for fid in DRIVE_IDS:
            info = drive._svc.files().get(fileId=fid, fields="name,size").execute()
            metas.append({"id": fid, "name": info.get("name") or "",
                          "mb": int(info.get("size") or 0) / 1_048_576})
            log.info("Drive 文件 %s → %r (%.1f MB)", fid, metas[-1]["name"], metas[-1]["mb"])
        mapping: Dict[str, str] = {}
        for a in ADS:
            hits = [x for x in metas if re.search(a["pat"], x["name"].casefold())
                    and x["id"] not in mapping.values()]
            if len(hits) != 1:
                log.error("❌ %r 对不上 Drive 文件（命中 %d）：%s — 停止，未建任何东西。",
                          a["ad_name"], len(hits), [x["name"] for x in metas])
                sys.exit(1)
            mapping[a["key"]] = hits[0]["id"]
            log.info("  ✔ %s ← %r", a["ad_name"], hits[0]["name"])
        st["drive_map"] = mapping
        persist()

    tpl = g.get_object(TPL_FR, "name,targeting,promoted_object,optimization_goal,billing_event")
    t = copy.deepcopy(tpl.get("targeting") or {})
    if not t.get("flexible_spec"):
        log.error("❌ 模板没有兴趣配方，停止。")
        sys.exit(1)
    ig = t.get("instagram_positions")
    if ig and "explore_home" in ig and "explore" not in ig:
        t["instagram_positions"] = list(ig) + ["explore"]
    log.info("模板 %s %r · %s-%s · Adv+ %s · 排除 %d", TPL_FR, tpl.get("name"),
             t.get("age_min"), t.get("age_max"),
             (t.get("targeting_automation") or {}).get("advantage_audience"),
             len(t.get("excluded_custom_audiences") or []))

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
        st["campaign_id"] = g.create_campaign(HK, **fields)["id"]
        persist()
        log.info("+ campaign %s %r CBO RM%d/day (PAUSED)", st["campaign_id"], CAMPAIGN_NAME,
                 CBO_MINOR // 100)
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
        st["adset_id"] = g.create_adset(HK, **fields)["id"]
        persist()
        log.info("+ adset %s %r", st["adset_id"], ADSET_NAME)
        time.sleep(1.0)

    st.setdefault("videos", {})
    st.setdefault("creatives", {})
    st.setdefault("ads", {})
    rows = []
    for a in ADS:
        k = a["key"]
        rec = st["videos"].get(k) or {}
        if not rec.get("video_id"):
            path = Path(f"/tmp/{k}.mp4")
            drive.download_file(st["drive_map"][k], path)
            log.info("── %s: 下载 %.1f MB → 上传中…", k, path.stat().st_size / 1_048_576)
            rec["video_id"] = g.upload_video(HK, str(path), name=a["ad_name"])
            rec["thumb"] = g.get_video_thumbnail(rec["video_id"])
            path.unlink(missing_ok=True)
            st["videos"][k] = rec
            persist()
            time.sleep(1.0)
        if not st["creatives"].get(k):
            cta = {"type": m.call_to_action, "value": {"link": m.lead_destination.link_url}}
            vdata: Dict[str, Any] = {"video_id": rec["video_id"], "title": a["title"],
                                     "message": BODIES[k], "call_to_action": cta}
            if rec.get("thumb"):
                vdata["image_url"] = rec["thumb"]
            story: Dict[str, Any] = {"page_id": m.page_id, "video_data": vdata}
            if m.instagram_user_id:
                story["instagram_user_id"] = m.instagram_user_id
            fields = {"name": a["ad_name"], "object_story_spec": story}
            if m.url_tags:
                fields["url_tags"] = m.url_tags
            st["creatives"][k] = g.create_adcreative(HK, **fields)["id"]
            persist()
            log.info("  + creative %s (video %s)", st["creatives"][k], rec["video_id"])
            time.sleep(1.0)
        if not st["ads"].get(k):
            ad = g.create_ad(HK, name=a["ad_name"], adset_id=st["adset_id"],
                             creative={"creative_id": st["creatives"][k]},
                             status="ACTIVE", conversion_domain=conv)
            st["ads"][k] = ad["id"]
            persist()
            time.sleep(1.0)
        eff = g.get_object(st["ads"][k], "effective_status").get("effective_status")
        log.info("    ▸ %s %r eff %s", st["ads"][k], a["ad_name"], eff)
        rows.append(f"{k}:{eff}")

    final_summary(log, f"線下見證 1-1-2 built PAUSED on HK: campaign {st['campaign_id']} CBO "
                       f"RM{CBO_MINOR // 100}/day · adset {st['adset_id']} · {'; '.join(rows)}")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — state saved, re-dispatch in ~30 min.", exc)
        sys.exit(75)
