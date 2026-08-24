"""Swap Video 5 倒數計時's copy: operator-approved script-native body replaces the evergreen.

The ad was built with the account's evergreen body as a default; the operator rejected that
("文案我不要用回一样的") and approved a body written FROM the countdown script (skill:
fb-ad-copy-martin), with headline 主文案 + Headline 1. Meta creatives are immutable, so this
creates a NEW creative reusing the already-uploaded video (no 128MB re-upload) and points the
existing PAUSED ad at it. The ad keeps its id and name, so nothing downstream changes.

The old creative id is kept in state as replaced_creative_id — swapping back is one re-run
with the ids exchanged. Verified by re-reading the ad's creative binding and the stored title.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "entities_v5_countdown.json"
AD_NAME = "Video 5：倒數計時"

TITLE = "🔴 孩子的长高时间，正在倒数"

# Approved 24 Aug (主文案 + Headline 1). Written from the video's own script — the countdown
# differentiator — not the evergreen. No URL in the body (standing rule: link on the CTA
# button only), no hashtags, no price, education framing throughout.
BODY = """⏳ 从现在，到你孩子的生长板闭合——
你猜，还剩几年？

很多爸妈以为还早。
其实，可能只剩两三年，是他真正还能长高的时间。

🗣️「顺其自然啦，大一点自己会抽高。」
🗣️「再等等看，他爸爸也是晚长的。」

结果呢？

😔 很多家长，是等到孩子十五、十六岁，
突然不长了，才开始慌。

到那个时候——
📉 花再多钱、买再贵的东西，都追不回来。

👉 因为长高，从来不是一条平平的直线。

它有一个黄金期。
青春期一启动，倒数计时就开始跑了。

等那一波抽高结束、生长板一闭合，身高就定型。
这是骨头的事，不是努力就能重来的事。

真正能帮孩子追高的，
就是中间那短短几年。

💔 这十年，最让马丁药师心疼的，永远是同一种家庭：
孩子明明还有空间，
却因为爸妈一句「再等等看」，白白错过。

✅ 反过来，愿意早一点看清楚状况的，
追回来的机会，大得多。

👨‍⚕️ 马丁药师｜台湾执照药师 · 中西医整合经验 10 年
这十年，他陪过近 7,000 个华人家庭，
用最健康的方式，帮孩子把握长高的黄金期。

现在，他把整套判断方法，
放进一堂免费的线上课程：

📍 怎么判断你的孩子，离生长板闭合还剩多少时间
📍 黄金期里，哪些事该做、哪些钱不该花
📍 怎么用最健康的方式，帮孩子每年长高 6–8cm

⏰ 名额有限，坐满即止。

👇 点击下方按钮，立即免费报名。

别再用一句「顺其自然」，
赌掉孩子最后这几年。"""


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path

    st: Dict[str, Any] = json.loads(STATE_PATH.read_text())
    ad_id, video_id = st["ad_id"], st["video_id"]
    old_creative = st["creative_id"]
    thumb = st.get("thumb")

    if st.get("copy_swapped"):
        log.info("copy already swapped (creative %s) — nothing to do", old_creative)
        final_summary(log, "Script-native copy is already live on the ad; no change made.")
        return

    # new creative around the SAME uploaded video — no re-upload
    cta = {"type": s.meta.call_to_action, "value": {"link": s.meta.lead_destination.link_url}}
    vdata: Dict[str, Any] = {"video_id": video_id, "title": TITLE, "message": BODY,
                             "call_to_action": cta}
    if thumb:
        vdata["image_url"] = thumb
    story: Dict[str, Any] = {"page_id": s.meta.page_id, "video_data": vdata}
    if s.meta.instagram_user_id:
        story["instagram_user_id"] = s.meta.instagram_user_id
    fields: Dict[str, Any] = {"name": f"{AD_NAME} · 脚本文案", "object_story_spec": story}
    if s.meta.url_tags:
        fields["url_tags"] = s.meta.url_tags
    new_creative = g.create_adcreative(acct, **fields)["id"]
    log.info("+ new creative %s (video %s reused)", new_creative, video_id)

    g._request("POST", ad_id, data={"creative": json.dumps({"creative_id": new_creative})})

    # verify the binding and the stored title — sent is not stored
    bound = g._request("GET", ad_id, params={"fields": "creative{id},status,effective_status"})
    bound_id = str((bound.get("creative") or {}).get("id"))
    spec = g._request("GET", new_creative, params={"fields": "object_story_spec"})
    stored_title = (((spec.get("object_story_spec") or {}).get("video_data")) or {}).get("title")
    ok = bound_id == str(new_creative) and stored_title == TITLE
    log.info("ad %s → creative %s (%s) · status %s/%s · title %r", ad_id, bound_id,
             "ok" if ok else "MISMATCH", bound.get("status"), bound.get("effective_status"),
             stored_title)
    if not ok:
        raise SystemExit("!! swap did not verify — the ad may still carry the old creative; "
                         "check in Ads Manager before activating.")

    st.update({"creative_id": new_creative, "replaced_creative_id": old_creative,
               "copy_swapped": True})
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))
    final_summary(
        log, f"Video 5 倒數計時 now carries the approved script-native copy (headline 「{TITLE}」) "
             f"on a new creative {new_creative}; the same uploaded video was reused, the ad keeps "
             f"its id and name, and it is still PAUSED. The evergreen-body creative "
             f"{old_creative} is retired but recorded in state for a one-run swap-back.")


if __name__ == "__main__":
    main()
