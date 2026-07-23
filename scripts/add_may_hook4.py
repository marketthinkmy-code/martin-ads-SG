"""Add ONE new video ad — MAY Video Hook 4: 想要加入州队 — to the two existing
creative-test ad sets (Parents + Family), making each 1-1-3. ALL PAUSED.

Single text + single headline video creative (a normal ad set can't carry multi-option
"Dynamic Creative"). The video is downloaded from Drive + uploaded to Meta ONCE, one creative
is built, and the SAME creative is used to create one ad in each ad set. Idempotent: video_id
/ creative_id / per-ad-set ad ids are cached in state/entities_may_hook4.json, so a re-dispatch
never re-uploads or duplicates.
"""
from __future__ import annotations

import json
from pathlib import Path

from adbot.clients.drive import DriveClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE = Path("state/entities_may_hook4.json")
DRIVE_ID = "1nM7JBRr-sL9xVK9qmW1qB2G___6ctQ2i"      # 新马 May Hook 4#.mp4
AD_NAME = "Hook 4：想要加入州队？"
TITLE = "爸妈都不高，孩子就注定矮吗？｜免费公开课"

# existing ad sets built earlier (both 1-1-2 → become 1-1-3)
AD_SETS = [("parents", "120256638809380093"),        # [SG] … | Parents 3–17 + Engaged | 1-1-2
           ("family", "120256639280150093")]          # [SG] … | Family and Relationships | 1-1-2

MAIN = """⚠️ 你的孩子天天抱着篮球，梦想有一天能进校队、州队，甚至国家队？
但现实是——一整年过去，身高却没长几公分。
你，是不是也开始慌了？

很多爸妈来找我，第一句话就是：
🗣️「马丁药师，我和我老公都不高，孩子是不是注定矮人一截？」

然后就开始焦虑——
🍼 昂贵的保健品一堆一堆买、牛奶拼命灌，
甚至想带孩子去打生长针。

停！❗
这些不只花冤枉钱，
还可能把孩子的脾胃搞差、让他提早发育，
反而把最后的长高空间，给锁死了。

👉 其实，基因只决定孩子身高的「范围」；
能不能逼近那个上限，靠的是发育期后天的精准调理。

这些年我发现，真正长得好的孩子，
都是先把身体的负担清掉：
🌿 把过敏解决掉
🥣 把脾胃吸收调理好
😴 让睡眠达到最深度的修复
身体没有负担了，营养才会全部冲向骨骼。

✅ 所以别急着乱补——
先看懂孩子卡在哪，再决定怎么帮他追高。
而且越早调理，越早见效。

👨‍⚕️ 马丁药师（台湾执照药师 · 中西医结合背景），
过去三年帮助全球 7000 多个孩子；
很多父母身高不到 165 公分，
孩子照样在指导下，每年自然长高 6 到 10 公分——
靠的不是吃药打针，而是「先健康，后长高」。

这星期，我特别开一堂免费线上课——
📘《儿童长高方程式》

课堂上你会明白：
📍 就算爸妈基因不高，孩子到底该怎么逆袭身高
📍 怎么看懂孩子现在卡在哪个成长阶段
📍 不吃药、不打针，怎么用最健康的方式帮孩子长高

⏰ 名额有限，坐满即止。
👇 点击下方链接，立即免费报名《儿童长高方程式》，我们线上见！

孩子的骨龄一旦闭合，花再多钱、吃再多仙丹都来不及。
别让一句「顺其自然」，耽误了他的身高，也耽误了他的篮球梦。"""


def make_creative(g, acct, s, name, video_id, thumb) -> str:
    cta = {"type": s.meta.call_to_action, "value": {"link": s.meta.lead_destination.link_url}}
    vdata = {"video_id": video_id, "title": TITLE, "message": MAIN, "call_to_action": cta}
    if thumb:
        vdata["image_url"] = thumb
    story = {"page_id": s.meta.page_id, "video_data": vdata}
    if s.meta.instagram_user_id:
        story["instagram_user_id"] = s.meta.instagram_user_id
    fields = {"name": name, "object_story_spec": story}
    if s.meta.url_tags:
        fields["url_tags"] = s.meta.url_tags
    return g.create_adcreative(acct, **fields)["id"]


def _save(st: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2))


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    conv = s.meta.conversion_domain_bare or None
    st = json.loads(STATE.read_text()) if STATE.exists() else {}

    # 1) video (download + upload once, else reuse)
    if st.get("video_id"):
        video_id = st["video_id"]
        thumb = st.get("thumb") or g.get_video_thumbnail(video_id)
        log.info("reuse video %s", video_id)
    else:
        path = DriveClient(s.secrets.google_sa_json).download_file(DRIVE_ID, Path("/tmp/may_hook4.mp4"))
        log.info("downloaded (%d bytes) → uploading to Meta…", path.stat().st_size)
        video_id = g.upload_video(acct, str(path), name=AD_NAME)
        thumb = g.get_video_thumbnail(video_id)
    st.update({"video_id": video_id, "thumb": thumb})
    _save(st)

    # 2) single-option creative (reuse if cached)
    if st.get("creative_id"):
        cid = st["creative_id"]
        log.info("reuse creative %s", cid)
    else:
        cid = make_creative(g, acct, s, AD_NAME, video_id, thumb)
        st["creative_id"] = cid
        _save(st)
        log.info("built creative %s (single text/title)", cid)

    # 3) one ad into each existing ad set
    ads = st.get("ads", {})
    for key, adset_id in AD_SETS:
        if ads.get(key):
            log.info("skip %s (ad %s already exists)", key, ads[key])
            continue
        ad = g.create_ad(acct, name=AD_NAME, adset_id=adset_id,
                         creative={"creative_id": cid}, status="PAUSED", conversion_domain=conv)
        ads[key] = ad["id"]
        st["ads"] = ads
        _save(st)
        log.info("  + ad %s ⟵ %s ad set %s", ad["id"], key, adset_id)

    final_summary(log, f"MAY Video Hook 4 added PAUSED → Parents ad {ads.get('parents')} + "
                       f"Family ad {ads.get('family')} (both ad sets now 1-1-3). "
                       f"Activate in Ads Manager after review.")


if __name__ == "__main__":
    main()
