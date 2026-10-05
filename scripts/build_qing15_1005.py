"""QING 15岁+ 三支新片 → 1-3-3 PAUSED on the old SG account (operator, 5 Oct).

Three freshly cut videos (Qing) on the 15岁+/太迟了吗 theme — the theme whose old
footage (25 lifetime sales) just failed the 60d CPA check; this is its re-test with
new material. One CBO RM80/day campaign (PAUSED) → 3 ad sets (FAMILY-template
targeting, identical names, house style) → 1 video ad each, copy per the Martin
copy system (Simplified for SG, signals front-loaded, credentials mid-copy,
no price / no hashtags).

Drive file ids are matched to ads BY FILE NAME (hook 2 / hook 3 / video 3 keywords),
never by link order; an unresolvable mapping aborts before anything is created.
Idempotent via state/entities_qing15_1005.json; Meta throttle exits 75.
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

STATE_PATH = Path("state") / "entities_qing15_1005.json"
SGBACK_STATE = Path("state") / "entities_sgback_1002.json"
CAMPAIGN_NAME = "[SG] 儿童长高方程式 | 15岁+ QING | 1-3-3"
ADSET_NAME = "15岁+ QING"
CBO_MINOR = 8000
DRIVE_IDS = ["1bxTj0aAGJMFET8Cf6pyMNwKHRD8pEVN1",
             "1d3Zaydl3nDQPuzdOlgEC2tDnqC82Ynm_",
             "15fdYmnrv7NUNOfS3u2MYZSe33EhIcXsQ"]

ADS: List[Dict[str, str]] = [
    {"key": "h2", "ad_name": "OCT Hook 2：上了中學卻沒有長高",
     "title": "🔴 上了中学，身高还停在小六？",
     "kw": ["hook 2", "hook2", "中學", "中学"]},
    {"key": "h3", "ad_name": "OCT Hook 3：16歲還長高",
     "title": "🔴 16 岁，3 个月长高 2cm",
     "kw": ["hook 3", "hook3", "16"]},
    {"key": "v3", "ad_name": "OCT Video 3：15歲後就不能長高了",
     "title": "🔴 15 岁了，还来得及长高吗？",
     "kw": ["video 3", "video3", "15"]},
]

BODIES: Dict[str, str] = {
    "h2": """🏫 孩子上了中学，
身高却还停留在小学六年级？

排队的位置没变过，
校服还是去年那一套，
🗣️ "不急啦，男生以后才抽高。"

👉 但身高不会等人：
进入青春期后段，长高的黄金期正在倒数。
再用"等"来处理，窗口过了就很难再突破。

其实你现在最该做的不是乱补，
而是先看懂孩子的状况：
⏳ 他的成长空间还剩多少
🌿 体质和肠胃吸收有没有卡住
😴 睡眠和作息是不是在拖后腿

大家好，我是马丁医师 🧑🏻‍⚕️🇹🇼
来自台湾、中西医结合背景，超过 10 年经验，
已帮助 10,000+ 位孩子健康长高！

💡 在我的免费线上分享会，你将学会：
✅ 怎么判断孩子还有多少成长空间
✅ 升上中学后，还能从哪里调整追高
✅ 先调理体质和吸收，再谈长高的正确顺序

⚠️ 名额有限，坐满即止！
👇 点击下方链接，立即免费报名
别让孩子的身高，停在小学六年级。""",
    "h3": """📏 这个 16 岁的孩子，
3 个月长高了 2cm。

很多家长看到都不敢相信：
🗣️ "16 岁了不是早就定型了吗？"
🗣️ "不是说过了发育期就没救了吗？"

👉 年龄不是判断的唯一标准。
真正要看的，是孩子的生长状况和体质卡点——
有些孩子 16 岁还有空间，
有些孩子 13 岁就在浪费最后的窗口。

与其到处试方法，不如先搞清楚：
⏳ 孩子的成长空间还剩多少
🥣 营养吃进去了，身体有没有吸收
🌿 体质到底卡在哪里

大家好，我是马丁医师 🧑🏻‍⚕️🇹🇼
来自台湾、中西医结合背景，超过 10 年经验，
已帮助 10,000+ 位孩子健康长高！

💡 在我的免费线上分享会，你将学会：
✅ 如何判断孩子"还有没有机会"，不靠猜
✅ 青春期后段追高，先调哪里才有效
✅ 把肠胃吸收调好，营养才变成身高

⚠️ 名额有限，坐满即止！
👇 点击下方链接，立即免费报名
别急着下结论，先看懂孩子的身体。""",
    "v3": """🗣️ "孩子都 15 岁了，是不是来不及了？"
这是我最常被家长问的一句话。

很多父母一看到孩子 14、15 岁，
第一反应就是：
😔 "完了，现在是不是太迟了？"
😔 "是不是没什么机会再长了？"

👉 但孩子能不能再长高，
从来不是看"几岁"这一个数字，
而是看他的生长状况和体质。

我们接触过超过 10,000 名孩子，
很多父母一开始也都这么想——
结果不是没机会，是用错了方法、浪费了时间。

你现在最重要的，不是什么都去试，而是先搞清楚：
⏳ 孩子到底还有多少成长空间
🌿 目前真正卡在哪里
🥣 肠胃和吸收有没有拖后腿

大家好，我是马丁医师 🧑🏻‍⚕️🇹🇼
来自台湾、中西医结合背景，超过 10 年经验，
已帮助 10,000+ 位孩子健康长高！

💡 在我的免费线上分享会，你将学会：
✅ 怎么判断 14、15 岁后还有没有成长空间
✅ 先了解状况再调整，不再用错方法浪费时间
✅ 调理体质和肠胃吸收的正确方向

⚠️ 名额有限，坐满即止！
👇 点击下方链接，立即免费报名
别再用"几岁了"，去判断孩子还有没有机会。""",
}


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

    # ── map Drive files to ads by NAME, abort on ambiguity ──────────────────────
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
            hits = [x for x in metas
                    if any(k in x["name"].casefold() for k in a["kw"])
                    and x["id"] not in mapping.values()]
            if len(hits) != 1:
                log.error("❌ %r 无法唯一对上 Drive 文件（命中 %d 个）：%s — 停止，未建任何东西。",
                          a["ad_name"], len(hits), [x["name"] for x in metas])
                sys.exit(1)
            mapping[a["key"]] = hits[0]["id"]
            log.info("  ✔ %s ← %r", a["ad_name"], hits[0]["name"])
        st["drive_map"] = mapping
        persist()

    tpl_id = json.loads(SGBACK_STATE.read_text())["adsets"]["family_1"]
    tpl = g.get_object(tpl_id, "name,targeting,promoted_object,optimization_goal,"
                               "billing_event")
    t = tpl.get("targeting") or {}
    log.info("模板 = SG-back FAMILY adset %s（geo %s · %s-%s）", tpl_id,
             (t.get("geo_locations") or {}).get("countries"),
             t.get("age_min"), t.get("age_max"))

    if st.get("campaign_id"):
        try:
            eff = g.get_object(st["campaign_id"], "effective_status").get("effective_status")
        except GraphError:
            eff = "DELETED"
        if eff in ("DELETED", "ARCHIVED"):
            st.pop("campaign_id", None)
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

    st.setdefault("videos", {})
    st.setdefault("creatives", {})
    st.setdefault("adsets", {})
    st.setdefault("ads", {})
    rows = []
    for a in ADS:
        k = a["key"]
        rec = st["videos"].get(k) or {}
        if not rec.get("video_id"):
            path = Path(f"/tmp/{k}.mp4")
            drive.download_file(st["drive_map"][k], path)
            log.info("── %s: 下载 %.1f MB → 上传中…", k, path.stat().st_size / 1_048_576)
            rec["video_id"] = g.upload_video(acct, str(path), name=a["ad_name"])
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
            st["creatives"][k] = g.create_adcreative(acct, **fields)["id"]
            persist()
            log.info("  + creative %s (video %s)", st["creatives"][k], rec["video_id"])
            time.sleep(1.0)
        if not st["adsets"].get(k):
            fields = {"name": ADSET_NAME, "campaign_id": st["campaign_id"],
                      "optimization_goal": tpl.get("optimization_goal"),
                      "billing_event": tpl.get("billing_event") or "IMPRESSIONS",
                      "promoted_object": tpl.get("promoted_object") or {},
                      "targeting": t, "status": "ACTIVE"}
            if m.regional_regulated_categories:
                fields["regional_regulated_categories"] = m.regional_regulated_categories
            if m.regional_regulation_identities:
                fields["regional_regulation_identities"] = m.regional_regulation_identities
            st["adsets"][k] = g.create_adset(acct, **fields)["id"]
            persist()
            log.info("  + adset %s %r", st["adsets"][k], ADSET_NAME)
            time.sleep(1.0)
        if not st["ads"].get(k):
            ad = g.create_ad(acct, name=a["ad_name"], adset_id=st["adsets"][k],
                             creative={"creative_id": st["creatives"][k]},
                             status="ACTIVE", conversion_domain=conv)
            st["ads"][k] = ad["id"]
            persist()
            time.sleep(1.0)
        eff = g.get_object(st["ads"][k], "effective_status").get("effective_status")
        log.info("    ▸ %s %r eff %s", st["ads"][k], a["ad_name"], eff)
        rows.append(f"{k}:{eff}")

    final_summary(log, f"QING 15岁+ built PAUSED on {acct}: campaign {st['campaign_id']} "
                       f"CBO RM{CBO_MINOR // 100}/day · {'; '.join(rows)}. Operator 验收后开.")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — state saved, re-dispatch in ~30 min.", exc)
        sys.exit(75)
