"""Video 5 倒數計時 on the proving ground: 1 CBO + 1 ad set + 1 ad, PAUSED.

Campaign: [SG] 儿童长高方程式 | Video 5 倒數計時 | 1-1-1  ·  RM80/day CBO

One unknown per test. The video is the new part (growth-plate countdown urgency angle,
finished edit "Martin July (通用）北美V5#.mp4"), so everything else is the account's proven
machinery: targeting cloned from ad set 120256891851660093 (Parents 3–17 + Engaged — the
proving ground every hook-edit and bread-hook test sat in, so this creative's CPL is
comparable against those benchmarks), and the evergreen body copy verbatim from creative
2497538107356049. Only the headline is new, written for the countdown angle.

The ad name "Video 5：倒數計時" was checked against every name-matching script in this repo:
its key does not contain, and is not contained by, any existing close/scale/hold core
("MAR Video 5" folds to marvideo5…, which does not collide).

Everything is created PAUSED for review. Idempotent: the video id, creative id and entity ids
persist in state/entities_v5_countdown.json, so a re-dispatch never re-uploads the 128MB file
or duplicates the campaign.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from adbot.build_1_1_10 import build
from adbot.clients.drive import DriveClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_DIR = Path("state")
STATE_KEY = "entities_v5_countdown"
PREFIX = "[SG] 儿童长高方程式"
LABEL = "Video 5 倒數計時 | 1-1-1"
ADSET_NAME = "Parents 3–17 + Engaged | 倒數計時"
AD_NAME = "Video 5：倒數計時"
DAILY_MYR = 80

DRIVE_VIDEO_ID = "1hKjaZh-U-1vPOmoYSD6oXzZqrtLQ9vGw"    # Martin July (通用）北美V5#.mp4, 128MB
CLONE_ADSET_ID = "120256891851660093"                    # Parents 3–17 + Engaged — best CPL

DETAIL_KEYS = ["interests", "behaviors", "life_events", "family_statuses", "industries",
               "income", "education_statuses", "work_positions", "work_employers",
               "relationship_statuses", "user_adclusters", "moms"]

# Written for the countdown angle; the video says 7000+ 華人家庭, the body keeps its own proven
# 6000名孩子 figure — different units, no conflict, and proven text is not edited.
TITLE = "⏳ 孩子还能长高的时间，正在倒数"

# ── proven evergreen body, verbatim from creative 2497538107356049 (the account's best video ad).
# No landing-page URL in the text — the link lives on the ad's CTA button only (standing rule).
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


def clone_from_adset(g, adset_id: str, s) -> Dict[str, Any]:
    """Clone interest/behaviour targeting from ONE specific ad set, forced to this market's geo.

    By ID rather than by name: two live ad sets are both called "Parents 3–17 + Engaged", and a
    name lookup would silently pick whichever happened to look richer.
    """
    src = g._request("GET", adset_id, params={"fields": "name,targeting"})
    t = src.get("targeting") or {}
    adv_raw = (t.get("targeting_automation") or {}).get("advantage_audience")
    adv = 1 if adv_raw is None else int(adv_raw)
    age_min, age_max = int(t.get("age_min") or 25), int(t.get("age_max") or 65)
    if adv == 1 and age_min > 25:      # Meta rejects a higher hard floor when Advantage+ is on
        age_min = 25
    spec: Dict[str, Any] = {
        "geo_locations": {"countries": s.meta.targeting.countries or ["SG"]},
        "age_min": age_min, "age_max": age_max,
        "targeting_automation": {"advantage_audience": adv},
        "excluded_custom_audiences": [{"id": i} for i in
                                      (s.meta.targeting.excluded_custom_audiences or [])],
        "locales": s.meta.targeting.locales or [1004],
    }
    if t.get("genders"):
        spec["genders"] = t["genders"]
    fs = t.get("flexible_spec")
    if fs:
        spec["flexible_spec"] = fs
    else:
        legacy = {k: t[k] for k in DETAIL_KEYS if t.get(k)}
        if legacy:
            spec["flexible_spec"] = [legacy]
    return {"spec": spec, "name": src.get("name")}


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    conv = s.meta.conversion_domain_bare or None

    s.naming.prefix = PREFIX
    s.meta.budget.level = "CAMPAIGN"                 # CBO
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
            path = Path("/tmp/v5_countdown.mp4")
            DriveClient(s.secrets.google_sa_json).download_file(DRIVE_VIDEO_ID, path)
            log.info("downloaded %.1f MB → uploading…", path.stat().st_size / 1_048_576)
            video_id = g.upload_video(acct, str(path), name=AD_NAME)
            thumb = g.get_video_thumbnail(video_id)
            path.unlink(missing_ok=True)
            st.update({"video_id": video_id, "thumb": thumb})
            persist()
            log.info("uploaded → video %s", video_id)
        cta = {"type": s.meta.call_to_action, "value": {"link": s.meta.lead_destination.link_url}}
        vdata: Dict[str, Any] = {"video_id": video_id, "title": TITLE, "message": BODY,
                                 "call_to_action": cta}
        if thumb:
            vdata["image_url"] = thumb
        story: Dict[str, Any] = {"page_id": s.meta.page_id, "video_data": vdata}
        if s.meta.instagram_user_id:
            story["instagram_user_id"] = s.meta.instagram_user_id
        fields: Dict[str, Any] = {"name": AD_NAME, "object_story_spec": story}
        if s.meta.url_tags:
            fields["url_tags"] = s.meta.url_tags
        creative_id = g.create_adcreative(acct, **fields)["id"]
        st["creative_id"] = creative_id
        persist()
        log.info("+ creative %s", creative_id)

    # 2) campaign + ad set ───────────────────────────────────────────────────────────
    spec = None
    if not st.get("adset_id"):
        cloned = clone_from_adset(g, CLONE_ADSET_ID, s)
        spec = cloned["spec"]
        detail = sum(len(grp.get(k) or []) for grp in (spec.get("flexible_spec") or [])
                     for k in DETAIL_KEYS)
        log.info("── targeting ← ad set %s %r (age %s-%s · adv=%s · %d detail entries)",
                 CLONE_ADSET_ID, cloned["name"], spec["age_min"], spec["age_max"],
                 (spec.get("targeting_automation") or {}).get("advantage_audience"), detail)
    else:
        log.info("── reuse campaign %s / adset %s", st.get("campaign_id"), st.get("adset_id"))

    ent = build(g, s, units=[], captions={}, dry_run=False, label=LABEL,
                state_key=STATE_KEY, adset_name=ADSET_NAME, targeting_override=spec)
    campaign_id, adset_id = ent["campaign_id"], ent["adset_id"]

    # 3) the ad ──────────────────────────────────────────────────────────────────────
    st = json.loads(st_path.read_text()) if st_path.exists() else {}
    if st.get("built_ad"):
        log.info("ad already built — skipping")
        ad_id = st.get("ad_id")
    else:
        ad = g.create_ad(acct, name=AD_NAME, adset_id=adset_id,
                         creative={"creative_id": creative_id},
                         status="PAUSED", conversion_domain=conv)
        ad_id = ad["id"]
        st.update({"campaign_id": campaign_id, "adset_id": adset_id,
                   "ad_id": ad_id, "built_ad": True, "creative_id": creative_id})
        persist()
        log.info("+ ad %s", ad_id)

    log.info("═" * 88)
    log.info("campaign=%s  adset=%s  ad=%s", campaign_id, adset_id, ad_id)
    final_summary(
        log, f"Video 5 倒數計時 built PAUSED: 1-1-1 on Parents 3–17 + Engaged (cloned by id from "
             f"the account's best-converting ad set) at CBO RM{DAILY_MYR}/day. Proven evergreen "
             f"body held verbatim, only the headline is new — so its CPL reads directly against "
             f"the hook-edit and bread-hook benchmarks from the same audience. Judge CPL after "
             f"~RM300 spend; judge money on the 14-day window and the webinar list. Review the "
             f"preview in Ads Manager, then activate.")


if __name__ == "__main__":
    main()
