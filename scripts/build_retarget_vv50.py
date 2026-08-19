"""Retarget 30-day 50% video viewers with the KL reel — 1 CBO + 1 ad set + 1 ad, PAUSED.

Campaign: [SG] 儿童长高方程式 | Retarget 30d VV50 | 1-1-1

AUDIENCE
--------
"30days video view" (120238646457220093). Despite the name it is exactly the audience the
operator asked for — retention_days 30, event video_view_50_percent, context the MARTIN page
341825319024143 — and it is the larger and fresher of the two that match that spec (60 source
videos / ~5,000-5,800 people, versus 39 / ~2,900-3,400 for "watched 50% of video FB IG").

This is a WARM pool: everyone in it has already watched half of a Martin video. The config's
standing exclusions still apply, so people who already registered or already bought are not
paid for again.

advantage_audience is 0. On a retargeting ad set, expansion defeats the entire point — Meta
would spend the budget on strangers who merely resemble the viewers.

CREATIVE
--------
The video is uploaded fresh from Drive rather than reusing the Reel post. Reusing the post was
the better option and was tried first — object_story_id 341825319024143_1811537966511148 — but
Meta answered "The reel you selected for your ad is not available. It could be deleted or you
might not have permissions to see it." The id shape was right (Meta resolved it as a reel), so
this is a permission or ad-eligibility problem with the system-user token, not a wrong id.

The cost of uploading instead is real and worth stating: the ad starts with zero likes, comments
and shares, where the Reel already carries its organic engagement. If that social proof matters,
the same reel can be boosted by hand in Ads Manager through "Use existing post", which runs with
a human's page permissions rather than the token's.

Body copy is the account's proven evergreen text, copied verbatim from creative 2497538107356049
(MAR Video 1 — the account's best-performing video ad). Only the headline is written for this
placement, and it is written for a warm audience: these people have already seen Martin talk, so
the job is the next step, not an introduction.

Everything is created PAUSED. Idempotent: the video id, creative id and entity ids persist in
state/entities_retarget_vv50.json, so a re-dispatch never re-uploads or duplicates.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from adbot.build_1_1_10 import build
from adbot.clients.drive import DriveClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_DIR = Path("state")
STATE_KEY = "entities_retarget_vv50"
PREFIX = "[SG] 儿童长高方程式"
LABEL = "Retarget 30d VV50 | 1-1-1"
ADSET_NAME = "30d Video View 50% | Retarget"
DAILY_MYR = 50

AUDIENCE_ID = "120238646457220093"      # "30days video view" — 30d, video_view_50_percent, MARTIN
SEED_ID = "120257737609370093"          # Cust Paid List (SG) — buyers, excluded from prospecting
DRIVE_VIDEO_ID = "1AzHSg6LFT_CFYQk4kSrskX4lQ1BOI3bl"   # 2026 馬丁醫師 吉隆坡.mp4 (221MB)
AD_NAME = "Reel：2026 馬丁醫師 吉隆坡"

# Verbatim from creative 2497538107356049 — proven text, not new text. No landing-page URL in the
# body; the link lives on the CTA button only (standing rule).
BODY = """👨‍🏫 想让孩子健康长高？我可以帮助你！

尤其适合给：
🛑 孩子一年长不到 6cm 的家长
🛑 孩子吃饭吃很慢的家长
🛑 孩子有脊椎侧弯的家长
🛑 孩子有鼻子敏感的家长
🛑 性早熟孩子的家长
🛑 睡眠障碍的孩子的家长

大家好，我是马丁药师 🧑🏻‍⚕️🇹🇼
来自台湾的儿童长高专家，拥有超过 10 年中西医学经验
身后是一群热衷于帮助孩子长高的父母。💪✨

🌍 我已经帮助来自台湾、马来西亚、曼谷、澳洲、
加拿大和美国等国家的6000名孩子，每年实现健康增高6cm-8cm！
这些孩子中，有很多被传统医生认为难以再长高的，
但在我的指导下，他们实现了健康增高的梦想！🌈

💡 如果你：
📌 担心孩子因父母基因遗传，难以再长高
📌 尝试了很多网上的偏方、保健品、运动，孩子还是没长高
📌 看了很多中医、西医做调理，但都不见效

放心！作为一位父亲，我深知家长的心情。🫂
❌ 我绝对不会使用药物或不自然的方法，
❌ 也不会逼迫孩子吃各种难以下咽的食物，
❌ 更不会要求他们拼命运动。

相反，我会教你一些简单、健康、科学认证的方法，
让你能够关注孩子身心灵发展的同时，帮助他们健康增高！✨

✨ 如果你想知道我如何帮助这些孩子实现增高目标，欢迎参加我的线上课程！

在这堂课中，你将获得：
✅ 健康、简单的方法，让孩子轻松长高
✅ 无需额外花费时间和精力，让增高变得简单
✅ 关注孩子的全面发展，兼顾身心灵健康

🎉 抓住这个机会，让孩子拥有一个不后悔的童年！

点击以下Button，让我帮助你的孩子拥有一个不后悔的童年！我们课程见！👋


#儿童长高方程式 #儿童长高 #长高 #马丁药师 #注意力 #成長 #學習力 #馬丁藥師 #身高 #孩子 #馬丁藥師 #霸凌 #頂嘴 #家庭教養 #家庭教育 #親子關係"""

# Written for a warm audience: they have already watched Martin talk, so the headline offers the
# next step rather than introducing him.
TITLE = "👨‍⚕️ 完整方法，在这堂免费公开课"


def make_creative(g, acct, s, name: str, video_id: str, thumb) -> str:
    cta = {"type": s.meta.call_to_action, "value": {"link": s.meta.lead_destination.link_url}}
    vdata = {"video_id": video_id, "title": TITLE, "message": BODY, "call_to_action": cta}
    if thumb:
        vdata["image_url"] = thumb
    story = {"page_id": s.meta.page_id, "video_data": vdata}
    if s.meta.instagram_user_id:
        story["instagram_user_id"] = s.meta.instagram_user_id
    fields: Dict[str, Any] = {"name": name, "object_story_spec": story}
    if s.meta.url_tags:
        fields["url_tags"] = s.meta.url_tags
    return g.create_adcreative(acct, **fields)["id"]


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    conv = s.meta.conversion_domain_bare or None

    s.naming.prefix = PREFIX
    s.meta.budget.level = "CAMPAIGN"
    s.meta.budget.daily_amount_myr = DAILY_MYR

    st_path = STATE_DIR / f"{STATE_KEY}.json"
    st: Dict[str, Any] = json.loads(st_path.read_text()) if st_path.exists() else {}

    def persist() -> None:
        st_path.parent.mkdir(parents=True, exist_ok=True)
        st_path.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    # 1) video + creative (uploaded once, then cached) ───────────────────────────────
    creative_id = st.get("creative_id")
    if creative_id:
        log.info("reusing creative %s (cached)", creative_id)
    else:
        video_id = st.get("video_id")
        if video_id:
            log.info("reusing uploaded video %s", video_id)
            thumb = st.get("thumb") or g.get_video_thumbnail(video_id)
        else:
            path = Path("/tmp/retarget_vv50.mp4")
            DriveClient(s.secrets.google_sa_json).download_file(DRIVE_VIDEO_ID, path)
            log.info("downloaded %.1f MB → uploading…", path.stat().st_size / 1_048_576)
            video_id = g.upload_video(acct, str(path), name=AD_NAME)
            thumb = g.get_video_thumbnail(video_id)
            path.unlink(missing_ok=True)
            st.update({"video_id": video_id, "thumb": thumb})
            persist()
            log.info("uploaded → video %s", video_id)
        creative_id = make_creative(g, acct, s, AD_NAME, video_id, thumb)
        st["creative_id"] = creative_id
        persist()
        log.info("+ creative %s", creative_id)

    # 2) campaign + ad set ───────────────────────────────────────────────────────────
    excl = list(s.meta.targeting.excluded_custom_audiences or [])
    if SEED_ID not in excl:
        excl.append(SEED_ID)
    spec: Dict[str, Any] = {
        "geo_locations": {"countries": s.meta.targeting.countries or ["SG"]},
        "age_min": 25, "age_max": 65,
        "custom_audiences": [{"id": AUDIENCE_ID}],
        "excluded_custom_audiences": [{"id": i} for i in excl],
        "locales": s.meta.targeting.locales or [1004],
        # 0 on a retargeting ad set — expansion would spend the budget on strangers who merely
        # resemble the viewers, which is the opposite of what retargeting is for.
        "targeting_automation": {"advantage_audience": 0},
    }
    log.info("targeting → audience %s · %d exclusion(s) · adv=0", AUDIENCE_ID, len(excl))

    ent = build(g, s, units=[], captions={}, dry_run=False, label=LABEL,
                state_key=STATE_KEY, adset_name=ADSET_NAME,
                targeting_override=None if st.get("adset_id") else spec)
    campaign_id, adset_id = ent["campaign_id"], ent["adset_id"]

    # 3) the ad ──────────────────────────────────────────────────────────────────────
    st = json.loads(st_path.read_text()) if st_path.exists() else {}
    ad_ids: List[str] = list(st.get("ad_ids", []))
    if st.get("built_ad"):
        log.info("ad already built — skipping")
    else:
        ad = g.create_ad(acct, name=AD_NAME, adset_id=adset_id,
                         creative={"creative_id": creative_id},
                         status="PAUSED", conversion_domain=conv)
        ad_ids.append(ad["id"])
        st.update({"campaign_id": campaign_id, "adset_id": adset_id,
                   "ad_ids": ad_ids, "built_ad": True, "creative_id": creative_id})
        persist()
        log.info("+ ad %s", ad["id"])

    log.info("═" * 88)
    log.info("campaign=%s  adset=%s  ads=%d", campaign_id, adset_id, len(ad_ids))
    final_summary(
        log, f"Retargeting build PAUSED: 1 ad on '30days video view' ({AUDIENCE_ID}) — 30-day, "
             f"50%-completion viewers of the MARTIN page, ~5,000-5,800 people — at CBO "
             f"RM{DAILY_MYR}/day with Advantage+ audience OFF so the budget stays on the warm pool. "
             f"The KL reel was uploaded fresh because the published Reel is not reachable through "
             f"the system-user token, so this ad starts with no likes or comments; boost the reel "
             f"by hand in Ads Manager instead if that social proof matters. Body is the proven "
             f"evergreen copy; only the headline is new. Watch frequency — a 5k pool at "
             f"RM{DAILY_MYR}/day saturates in about a week.")


if __name__ == "__main__":
    main()
