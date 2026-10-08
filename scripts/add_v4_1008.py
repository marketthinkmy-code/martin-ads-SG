"""Add Video 4：看舌頭就知道了 to the three 新片5支重测 campaigns (operator-approved copy, 8 Oct).

New post in the F&R campaign (video upload + creative with the approved copy), then the
same post reused by object_story_id in the Parents 3-17 + Engaged and Food & Milk
campaigns. Ad set ids come from state/entities_sgretest_1008.json. All three campaigns
are PAUSED, so nothing delivers. Idempotent via state/entities_sgretest_v4_1008.json.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict

from adbot.clients.drive import DriveClient
from adbot.clients.graph import GraphError, TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "entities_sgretest_v4_1008.json"
BASE_STATE = Path("state") / "entities_sgretest_1008.json"
DRIVE_ID = "1PmJCB4u_rcwoP1gQ2Qtye5EnoLuor8XK"
NAME_PAT = re.compile(r"video\s*4\b|\bv4\b|舌", re.IGNORECASE)
AD_NAME = "Video 4：看舌頭就知道了"
TITLE = "🔴 看舌头，就知道孩子为什么长不高"
BODY = """👅 给我看一眼孩子的舌头，我大概就知道他为什么长不高的哦！
甚至能看出他现在的身体状况。

你可能觉得很神奇，
但这几年我就是用这个方法，
帮助了超过 10,000 位来自台湾、香港、马来西亚、泰国、澳洲、加拿大、美国的孩子。

👉 舌头藏着孩子体质的线索：
😴 睡眠够不够
🥣 吃进去的有没有吸收
🏃 运动方式对不对
📐 脊椎有没有侧弯
🌿 体质上哪一块最需要优先调整

看懂了，才知道该先从哪里下手，而不是什么都补、什么都试。

大家好，我是马丁医师 🧑🏻‍⚕️🇹🇼
来自台湾、中西医结合背景，超过 10 年经验，
用更健康、更有系统的方式，帮孩子把成长条件做好。

💡 在我的免费线上分享会，我会一步一步教你：
✅ 怎么看懂孩子的身体，找出真正该优先调整的地方
✅ 睡眠、饮食、运动，哪一个先调才有效
✅ 怎么帮孩子每年健康长高 6–8cm（有些孩子更多）

如果你也想知道：孩子现在到底卡在哪里？现在还可以怎么帮他？
⚠️ 名额有限，坐满即止！
👇 点击下方链接，立即免费报名
别再猜了，先看懂孩子的身体。"""
ORDER = ["fr", "p317", "milk"]          # fr gets the new post; the others reuse it


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    m = s.meta
    acct = m.account_path
    conv = m.conversion_domain_bare or None
    base = json.loads(BASE_STATE.read_text())
    adsets: Dict[str, str] = base["adsets"]
    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}

    def persist() -> None:
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    if not st.get("video_id"):
        drive = DriveClient(s.secrets.google_sa_json)
        info = drive._svc.files().get(fileId=DRIVE_ID, fields="name,size").execute()
        name = info.get("name") or ""
        log.info("Drive 文件 %s → %r (%.1f MB)", DRIVE_ID, name, int(info.get("size") or 0) / 1_048_576)
        if not NAME_PAT.search(name.casefold()):
            log.error("❌ 文件名对不上 Video 4（%r）——停止，未建任何东西。", name)
            sys.exit(1)
        path = Path("/tmp/v4.mp4")
        drive.download_file(DRIVE_ID, path)
        log.info("下载 %.1f MB → 上传中…", path.stat().st_size / 1_048_576)
        st["video_id"] = g.upload_video(acct, str(path), name=AD_NAME)
        st["thumb"] = g.get_video_thumbnail(st["video_id"])
        path.unlink(missing_ok=True)
        persist()
        time.sleep(1.0)

    st.setdefault("creatives", {})
    st.setdefault("ads", {})
    if not st["creatives"].get("fr"):
        cta = {"type": m.call_to_action, "value": {"link": m.lead_destination.link_url}}
        vdata: Dict[str, Any] = {"video_id": st["video_id"], "title": TITLE, "message": BODY,
                                 "call_to_action": cta}
        if st.get("thumb"):
            vdata["image_url"] = st["thumb"]
        story: Dict[str, Any] = {"page_id": m.page_id, "video_data": vdata}
        if m.instagram_user_id:
            story["instagram_user_id"] = m.instagram_user_id
        fields = {"name": AD_NAME, "object_story_spec": story}
        if m.url_tags:
            fields["url_tags"] = m.url_tags
        st["creatives"]["fr"] = g.create_adcreative(acct, **fields)["id"]
        persist()
        log.info("+ creative (new post) %s", st["creatives"]["fr"])
        time.sleep(1.0)
    if not st["ads"].get("fr"):
        st["ads"]["fr"] = g.create_ad(acct, name=AD_NAME, adset_id=adsets["fr"],
                                      creative={"creative_id": st["creatives"]["fr"]},
                                      status="ACTIVE", conversion_domain=conv)["id"]
        persist()
        log.info("+ ad %s in F&R adset %s", st["ads"]["fr"], adsets["fr"])
        time.sleep(1.0)

    if not st.get("post_id"):
        for attempt in range(4):
            pid = g.get_object(st["creatives"]["fr"], "effective_object_story_id").get("effective_object_story_id")
            if pid:
                st["post_id"] = pid
                persist()
                break
            time.sleep(5)
        if not st.get("post_id"):
            log.error("❌ 新 creative 还没有 post id，稍后重跑即可（F&R 那支已建）。")
            sys.exit(1)
    log.info("post id = %s", st["post_id"])

    rows = [f"fr:{st['ads']['fr']}"]
    for k in ORDER[1:]:
        if not st["creatives"].get(k):
            fields = {"name": AD_NAME, "object_story_id": st["post_id"]}
            if m.url_tags:
                fields["url_tags"] = m.url_tags
            st["creatives"][k] = g.create_adcreative(acct, **fields)["id"]
            persist()
            time.sleep(0.8)
        if not st["ads"].get(k):
            st["ads"][k] = g.create_ad(acct, name=AD_NAME, adset_id=adsets[k],
                                       creative={"creative_id": st["creatives"][k]},
                                       status="ACTIVE", conversion_domain=conv)["id"]
            persist()
            time.sleep(0.8)
        eff = g.get_object(st["ads"][k], "effective_status").get("effective_status")
        log.info("+ ad %s in %s adset %s · eff %s", st["ads"][k], k, adsets[k], eff)
        rows.append(f"{k}:{st['ads'][k]}")
    final_summary(log, f"Video 4 added to 3 campaigns (post {st['post_id']}): {rows}")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — state saved, re-dispatch in ~30 min.", exc)
        sys.exit(75)
