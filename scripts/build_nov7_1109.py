"""11月新片 7 支 on SG老户 (first built on HK, deleted on the operator's word), ABO 1-7-7, campaign PAUSED (operator 9 Nov: 「直接开跑，paused，我自己开」).

Operator approved 9 Nov:
  · Videos 1, 2, 3, 5, 6, 7, 8 (Video 4 not run); file = 「Martin Sep Video 0N…」 in Drive — the
    script refuses to build if a Drive file's name does not carry the matching number.
  · Copy written for SG (Simplified), 马丁医师, 10,000+ everywhere, case numbers allowed.
  · Ad names follow the operator's pattern 「Video 2：吃完就马上去厕所？」.
  · Account HK act_1179668409969241 (rule 1). One campaign, ABO, one ad set per video, RM50 each.
  · Audience = Interest: Food and Drink + Milk, targeting cloned from HK ad set 120250464911610335
    (28 all-time SG sales, 60-day CPL RM112 — scripts/adset_sales_rank_1010.py, 9 Nov), then
    apply_sg_build_defaults() (Advantage+ placements, SG home + frequently in + recent).
  · Campaign PAUSED; ad sets and ads ACTIVE underneath, so the operator's single switch on the
    campaign starts all seven. No start_time.
ADBOT_MODE=check (default): read-only preflight — Drive access + file-name check for all seven,
template ad set read, nothing written. ADBOT_MODE=go: upload, build, read every entity back.
Idempotent via state/entities_nov7_1109.json; 75 = Meta throttle (state kept, re-dispatch).
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict

from adbot.clients.drive import DriveClient
from adbot.clients.graph import TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings
from adbot.sg_build_defaults import apply_sg_build_defaults

# account → (ad account, template ad set to clone targeting / pixel from, state file)
ACCOUNTS = {
    # 9 Nov first build on HK; operator then chose 「B，建在 SG老户，HK 那个删掉」 (this cycle SG老户 CPL
    # RM141.69 vs HK RM205.89, scripts/budget_now_1029.py 11/9 15:44)
    "HK": ("act_1179668409969241", "120250464911610335", Path("state") / "entities_nov7_1109.json"),
    # SG老户 Interest: Food and Drink + Milk ad set that carried Hook 7 (10 own sales)
    "SG": ("act_1024930575770087", "120242606093210093", Path("state") / "entities_nov7_sg_1109.json"),
}
CAMPAIGN_NAME = "[SG] 儿童长高方程式 | Food and Drink + Milk | 11月新片7支 | 1-7-7"
ADSET_NAME = "Interest: Food and Drink + Milk"
DAILY_MINOR = 5000                               # RM50 per ad set (operator 「B」)

CRED = "👨‍⚕️ 马丁医师，来自台湾、同时拥有 2 个执照，中西医学结合"

V1 = f"""🥛 每天逼孩子喝牛奶、吃钙片，排队还是站最前面？
❓ 如果补钙真的这么简单，每天喝奶的孩子，应该个个都长得很高才对。

🗣️「多喝奶就会长啦」
🗣️「钙片再加一罐应该就够了」
🗣️「是不是还要补点什么？」

📉 补了一年又一年，身高还是追不上同学。

👉 马丁医师说：钙质只是成长需要的其中一种营养。
孩子能不能把长高潜力发挥出来，还要一起看——

🌿 体质适不适合
🥣 吃进去有没有吸收
😴 睡眠的时间和深度
🏃 运动的方式对不对

✅ 所以别再一直问"还要补什么？"
先问："到底是哪一个地方，卡住了孩子的成长？"

{CRED}，已经帮助超过 10,000 名来自不同国家的孩子，从孩子真正的身体状况出发，调整饮食、睡眠和运动。

免费线上分享会《儿童长高方程式》，你会学到：
📍 怎么看出孩子真正卡住的地方
📍 饮食、睡眠、运动应该先调哪一样
📍 用中西医学的思路，帮孩子每年健康长高 6–8cm

⏰ 名额有限，坐满即止
👇 点击下方链接，立即免费报名

不要只顾着补，先找出孩子卡在哪里。"""

V2 = f"""🚽 孩子是不是一吃完饭，就马上跑去厕所大号？
⚠️ 偶尔一次没关系，但长期这样，还常常肚子痛、拉稀、吃很多却不长肉……爸妈真的要留意了。

📉 想让孩子长高，不是只看他吃了多少，
更要看身体有没有好好消化、吸收。

🗣️「他吃很多啊，怎么还长这么慢？」
🍼 每天喝奶、补钙、吃营养品，
但吸收不到，吃再多也用不上。

👉 马丁医师说：孩子吃得多、补得多，不代表长得高。
你要找的不是"还要再补什么"，而是"哪里卡住了"。

🥣 消化吸收
🌿 体质状况
😴 睡眠质量
🏃 日常运动

{CRED}，已经帮助超过 10,000 名来自不同国家的孩子，从孩子真正的问题开始调整。
📈 我们追踪到的孩子，最高长高了 17 公分，平均长高 8 公分，年龄都在 5 到 17 岁。

免费线上分享会《儿童长高方程式》，你会学到：
📍 怎么从日常小细节看出孩子的吸收状况
📍 为什么"吃很多却不长"，问题可能不在营养
📍 帮孩子每年健康长高 6–8cm 的调整方向

⏰ 名额有限，坐满即止
👇 点击下方链接，立即免费报名

孩子要长高，不只是"吃了什么"，更是"吸收了什么"。"""

V3 = f"""😱「爸爸妈妈都不高，孩子一定也很矮！」
👉 先别急着帮孩子的身高下定论。

🗣️「我们家基因就这样」
🗣️「我跟他爸都不高，他能高到哪里去」

🧬 基因确实会影响身高，
但它不是孩子最后身高的唯一答案。

⏳ 孩子在 5–16 岁的黄金长高期——
😴 睡得对不对
🥣 吃得对不对
🏃 运动够不够
🌿 身体状况好不好
这些后天条件，爸妈现在还管得了。

{CRED}，已经帮助超过 10,000 个来自不同国家的家庭，从体质、饮食、睡眠和运动，找出每个孩子应该优先调整的地方。

如果你的孩子 5 到 17 岁，免费线上分享会《儿童长高方程式》会教你：
📍 怎么系统地了解孩子目前的成长状况
📍 饮食、睡眠、运动里最值得先调的是哪一项
📍 用健康的方式，帮孩子每年长高 6–8cm

⏰ 名额有限，坐满即止
👇 点击下方链接，立即免费报名

基因改不了，但成长的条件，爸妈还可以管。"""

V5 = f"""🍚 孩子吃饭扒两口就说饱，饭含在嘴里不吞，配一大杯水直接冲下去？
⚠️ 这个小动作，可能正在偷走他的身高。

😤 每天饭桌像打仗：你追着喂，他到处躲；
煮得再营养，他就只吃那几样。
🗣️「孩子胃口小，长大就好了」
📉 结果一年过去，裤子还是去年那条长度。

👉 马丁医师说：孩子不是"不爱吃"，
很多是脾胃弱、消化不动，身体自动不想吃。
逼他多吃只会更堵。
长高看的不是塞进去多少，而是吸收了多少。

{CRED}，超过十年经验，已经陪伴全球超过 10,000 位华人孩子，其中很多就是"吃饭困难户"。
📈 有个孩子调整脾胃和饮食顺序之后，两个月长了 3 到 4 公分，妈妈说他现在会自己主动添饭。

免费线上分享会《儿童长高方程式》，你会学到：
📍 怎么分辨孩子是挑食，还是脾胃弱
📍 饭桌上先吃什么、后吃什么
📍 怎么让孩子的胃口自己打开，每年健康长高 6–8cm

⏰ 名额有限，坐满即止
👇 点击下方链接，立即免费报名

改变的不只是饭量，还有孩子的身高。"""

V6 = f"""📏 爸爸妈妈，记住一个数字：一年 6 公分。
❓ 孩子过去一年长了多少？如果只长了 1、2、3 公分，这条请看完。

😟 很多家长是量了才吓一跳：去年画在墙上的线，今年只高了一点点。
🗣️「顺其自然吧」
🗣️「他爸爸当年也是高中才抽高」
但心里其实没底：万一不是晚长，是长不动了？

👉 马丁医师说：黄金期的孩子，一年应该长 6 到 8 公分。
连续一年低于这个数，就是身体在亮红灯——
😴 睡眠
🥣 脾胃吸收
🌿 体质
⏳ 发育节奏
"再等等看"，往往是最贵的决定，因为成长窗口过了就不会重来。

{CRED}，十多年来帮助超过 10,000 个孩子找回成长速度。
📈 有孩子七个月长了 12 公分，更多孩子从一年 2、3 公分，回到一年 6 到 8 公分。

免费线上分享会《儿童长高方程式》，你会学到：
📍 在家怎么算孩子的成长速度
📍 怎么判断是晚长，还是卡住
📍 卡住的孩子，要先调哪一样

⏰ 名额有限，坐满即止
👇 现在就量一下孩子的身高，再点击下方链接免费报名

别让"再等等"，等走了孩子的黄金期。"""

V7 = f"""🍼 钙片、蛋白粉、跳绳、篮球、早睡、看医生……全都试过了，
📉 孩子一年还是只长两三公分？
👉 问题可能从头到尾，都不在你试的那些方法上。

😔 柜子里一排吃到一半的补品，
周末全花在球场，晚上九点准时赶孩子上床……
努力了这么久，身高还是没动。

👉 马丁医师说：这些方法没效，不是方法错，是顺序错。
没有人先帮你判断，孩子到底卡在哪里——
😴 睡眠不够深？
🥣 脾胃吸收不了？
🌿 体质有负担？
卡点不解决，给得再多也没办法对症。

{CRED}。他做的第一件事从来不是叫家长再买什么，而是先找卡点。十几年来已经陪伴 10,000 多个孩子，很多就是"什么都试过"的孩子，重新回到一年 6 到 8 公分。

孩子 7 到 14 岁的家长，免费线上分享会《儿童长高方程式》会带你：
📍 判断孩子卡在哪里
📍 看懂之前的方法为什么没效
📍 接下来按什么顺序调，帮孩子每年健康长高 6–8cm

⏰ 名额有限，坐满即止
👇 点击下方链接，立即免费报名

别再多买一罐补品了，先把卡点找出来。"""

V8 = f"""🗣️ 我跟你说！如果你家孩子 5 到 17 岁，
今天刷到这条，真的不是巧合，先别滑走。

😅 嘴上说"身高顺其自然啦"，
看到孩子同学又抽高了，回家马上偷偷量一次？
华人爸妈都一样：嘴硬，心里急。

👉 马丁医师说：长高这件事，七成靠的不是基因，是管理——
😴 睡眠的深度
🥣 吃饭的吸收
🏃 运动的方式
⏳ 发育的节奏
这四样对了，爸妈不高的孩子也有机会；这四样错了，高个子父母的孩子也会卡住。

🧬 所以别再说"我们家基因就这样"。

{CRED}，做儿童成长管理十几年，台湾、马来西亚、新加坡、美国、加拿大，已经陪伴超过 10,000 位华人孩子。很多本来"认命"的爸妈，孩子一年健康长回 6 到 8 公分。

免费线上分享会《儿童长高方程式》，一次讲清楚：
📍 黄金期怎么抓
📍 四大关键怎么调
📍 哪些钱根本不用花

⏰ 名额有限，坐满即止
👇 点击下方链接，立即免费报名

你帮孩子做过那么多决定，这个最简单，也可能最值得。"""

VIDEOS = [
    {"n": 1, "drive_id": "1yAIft0i2AeyuYQZLcCa3-YtUlbcNcIUH", "ad_name": "Video 1：是谁说的？",
     "title": "喝牛奶补钙，就一定会长高吗？", "message": V1},
    {"n": 2, "drive_id": "1u7oPrGaV5uAzjhvxV65HtlEmz8AKsOfN", "ad_name": "Video 2：吃完就马上去厕所？",
     "title": "吃很多却不长高？先看吸收", "message": V2},
    {"n": 3, "drive_id": "15s3Kc4N9yahNtqzpoKswrhb2MHKqBW-p", "ad_name": "Video 3：完蛋了！",
     "title": "爸妈不高，孩子就注定矮吗？", "message": V3},
    {"n": 5, "drive_id": "1uXmtdeSqSt8-SzPgPzoM7IrvUP9KNbSH", "ad_name": "Video 5：饭桌生活细节场景",
     "title": "孩子吃饭慢、胃口差？先看脾胃", "message": V5},
    {"n": 6, "drive_id": "1laot0YP6o5SftX2geip_jHlsGrYAKYp0", "ad_name": "Video 6：具体数字目标",
     "title": "孩子一年长不到 6 公分？", "message": V6},
    {"n": 7, "drive_id": "1rhrfwuR9MV6I286mMS0WpI_vaGg0Zdfw", "ad_name": "Video 7：父母试过一切共情",
     "title": "什么都试过，孩子还是长不高？", "message": V7},
    {"n": 8, "drive_id": "15dghR_QMCDJjMBioq6uN-kJnTa38Cact", "ad_name": "Video 8：对话式「我跟你说！」",
     "title": "我跟你说：长高七成靠管理", "message": V8},
]
NOT_RUN_DRIVE_ID = "1tZQpgiXB5WJHyy3HxMYKmpAcybpX21qB"   # Martin Sep Video 04 — operator: 不要跑


def main() -> None:
    log = get_logger()
    s = load_settings()
    m = s.meta
    mode = (os.environ.get("ADBOT_MODE") or "check").strip().lower()
    go = mode == "go"
    g = graph_client(s)
    if mode == "delete_hk":                        # operator 9 Nov: HK 那个删掉
        hk_state = ACCOUNTS["HK"][2]
        hst = json.loads(hk_state.read_text()) if hk_state.exists() else {}
        cid = hst.get("campaign_id")
        if not cid:
            log.error("❌ state 里没有 HK campaign id（%s），什么都没删。", hk_state)
            sys.exit(1)
        before = g.get_object(cid, "name,account_id,status")
        if str(before.get("account_id")) != ACCOUNTS["HK"][0].replace("act_", "") or "11月新片7支" not in (before.get("name") or ""):
            log.error("❌ %s 不是 HK 的 11月新片7支 campaign（%s），不删。", cid, before)
            sys.exit(1)
        g.update_status(cid, "DELETED")
        after = g.get_object(cid, "status,effective_status")
        log.info("🗑 HK campaign %s %r → %s / %s（ad set 和广告跟着删除）· ad sets %s · ads %s", cid, before.get("name"),
                 after.get("status"), after.get("effective_status"), list((hst.get("adsets") or {}).values()),
                 list((hst.get("ads") or {}).values()))
        final_summary(log, f"删掉 HK campaign {cid}：{after.get('status')}")
        return
    acct_key = (os.environ.get("ADBOT_ACCOUNT") or "SG").strip().upper()
    ACCT, TEMPLATE_ADSET, STATE_PATH = ACCOUNTS[acct_key]
    log.info("账户 %s %s · 模板 ad set %s · 模式 %s", acct_key, ACCT, TEMPLATE_ADSET, mode)
    drive = DriveClient(s.secrets.google_sa_json)
    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}

    def persist() -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    # ── 1. Drive: every file readable by the service account and named 「…Video 0N…」 ──────────
    bad = []
    for v in VIDEOS:
        try:
            meta = drive._svc.files().get(fileId=v["drive_id"], fields="id,name,size,parents",
                                          supportsAllDrives=True).execute()
        except Exception as exc:  # noqa: BLE001
            bad.append(f"Video {v['n']} {v['drive_id']}: 读不到 ({str(exc)[:120]})")
            continue
        ok = re.search(rf"video\s*0?{v['n']}(?!\d)", meta.get("name", ""), re.I) is not None
        v["file"] = meta.get("name")
        log.info("  Drive · Video %d → %s · %s · %.1f MB · 档名对得上: %s", v["n"], v["drive_id"], meta.get("name"),
                 int(meta.get("size") or 0) / 1e6, "✓" if ok else "✗")
        if not ok:
            bad.append(f"Video {v['n']} 档名 {meta.get('name')!r} 不是 Video 0{v['n']}")
        parent = (meta.get("parents") or [None])[0]
        if parent and not st.get("folder_listed"):
            sibs = sorted(f["name"] for f in drive.list_children(parent) if "video" in f["name"].lower())
            log.info("  同资料夹里的影片档：%s", sibs)
            st["folder_listed"] = True
    if any(v["drive_id"] == NOT_RUN_DRIVE_ID for v in VIDEOS):
        bad.append("Video 4 不应该在名单里")
    if bad:
        log.error("❌ 停止，什么都没建：%s", " | ".join(bad))
        sys.exit(1)

    tpl = g.get_object(TEMPLATE_ADSET, "name,targeting,promoted_object,optimization_goal,billing_event,bid_strategy")
    t = apply_sg_build_defaults(copy.deepcopy(tpl.get("targeting") or {}))
    ints = [x.get("name") for fs in t.get("flexible_spec") or [] for x in fs.get("interests") or []]
    log.info("  模板 %s %s %r · %s-%s · Adv+ %s · 兴趣 %s · 地区 %s · 版位 自动", acct_key, TEMPLATE_ADSET, tpl.get("name"),
             t.get("age_min"), t.get("age_max"), (t.get("targeting_automation") or {}).get("advantage_audience"),
             "/".join(ints), t.get("geo_locations"))
    if not go:
        final_summary(log, "预检通过（只读）：7 个 Drive 档都读得到、档名对得上 Video N；模板 ad set 读到。没有建任何东西。")
        return

    # ── 2. upload + creatives ─────────────────────────────────────────────────────────────
    st.setdefault("videos", {})
    st.setdefault("creatives", {})
    cta = {"type": m.call_to_action, "value": {"link": m.lead_destination.link_url}}
    for v in VIDEOS:
        k = str(v["n"])
        if not st["videos"].get(k):
            path = drive.download_file(v["drive_id"], Path(f"/tmp/nov_v{k}.mp4"))
            log.info("  ↓ Video %s %.1f MB → 上传 " + acct_key + "…", k, path.stat().st_size / 1e6)
            vid = g.upload_video(ACCT, str(path), name=v["ad_name"])
            st["videos"][k] = {"video_id": vid, "thumb": g.get_video_thumbnail(vid)}
            persist()
            path.unlink(missing_ok=True)
        if not st["creatives"].get(k):
            vdata = {"video_id": st["videos"][k]["video_id"], "title": v["title"], "message": v["message"],
                     "call_to_action": cta}
            if st["videos"][k].get("thumb"):
                vdata["image_url"] = st["videos"][k]["thumb"]
            story = {"page_id": m.page_id, "video_data": vdata}
            if m.instagram_user_id:
                story["instagram_user_id"] = m.instagram_user_id
            fields = {"name": v["ad_name"], "object_story_spec": story}
            if m.url_tags:
                fields["url_tags"] = m.url_tags
            st["creatives"][k] = g.create_adcreative(ACCT, **fields)["id"]
            persist()
            time.sleep(0.8)
        log.info("  ✔ Video %s → video %s · creative %s", k, st["videos"][k]["video_id"], st["creatives"][k])

    # ── 3. campaign (PAUSED) + 7 ad sets + 7 ads ─────────────────────────────────────────────
    if not st.get("campaign_id"):
        fields = {"name": CAMPAIGN_NAME, "objective": m.objective, "buying_type": "AUCTION", "status": "PAUSED",
                  "special_ad_categories": m.special_ad_categories, "is_adset_budget_sharing_enabled": False}
        if m.regional_regulated_categories:
            fields["regional_regulated_categories"] = m.regional_regulated_categories
        st["campaign_id"] = g.create_campaign(ACCT, **fields)["id"]
        persist()
        log.info("+ campaign %s %r ABO PAUSED", st["campaign_id"], CAMPAIGN_NAME)
        time.sleep(1.0)
    st.setdefault("adsets", {})
    st.setdefault("ads", {})
    conv = m.conversion_domain_bare or None
    for v in VIDEOS:
        k = str(v["n"])
        if not st["adsets"].get(k):
            fields = {"name": ADSET_NAME, "campaign_id": st["campaign_id"], "daily_budget": DAILY_MINOR,
                      "status": "ACTIVE", "optimization_goal": tpl.get("optimization_goal"),
                      "billing_event": tpl.get("billing_event") or "IMPRESSIONS",
                      "promoted_object": tpl.get("promoted_object") or {}, "targeting": t}
            if tpl.get("bid_strategy"):
                fields["bid_strategy"] = tpl["bid_strategy"]
            if m.regional_regulated_categories:
                fields["regional_regulated_categories"] = m.regional_regulated_categories
            if m.regional_regulation_identities:
                fields["regional_regulation_identities"] = m.regional_regulation_identities
            st["adsets"][k] = g.create_adset(ACCT, **fields)["id"]
            persist()
            time.sleep(1.0)
        if not st["ads"].get(k):
            st["ads"][k] = g.create_ad(ACCT, name=v["ad_name"], adset_id=st["adsets"][k],
                                       creative={"creative_id": st["creatives"][k]}, status="ACTIVE",
                                       conversion_domain=conv)["id"]
            persist()
            time.sleep(0.8)

    # ── 4. read everything back ─────────────────────────────────────────────────────────────
    c = g.get_object(st["campaign_id"], "name,status,effective_status")
    log.info("═" * 100)
    log.info("campaign %s %r · %s / %s", st["campaign_id"], c.get("name"), c.get("status"), c.get("effective_status"))
    rows = []
    for v in VIDEOS:
        k = str(v["n"])
        a_s = g.get_object(st["adsets"][k], "name,status,daily_budget,targeting")
        ad = g.get_object(st["ads"][k], "name,status,effective_status,creative{id,body,title}")
        tt = a_s.get("targeting") or {}
        log.info("  Video %s · ad set %s %r RM%d %s · 地区 %s · 版位 %s · ad %s %r %s / %s · 文案开头 %r · 标题 %r",
                 k, st["adsets"][k], a_s.get("name"), int(a_s.get("daily_budget") or 0) // 100, a_s.get("status"),
                 (tt.get("geo_locations") or {}).get("location_types"),
                 "自动" if not tt.get("publisher_platforms") else tt.get("publisher_platforms"),
                 st["ads"][k], ad.get("name"), ad.get("status"), ad.get("effective_status"),
                 ((ad.get("creative") or {}).get("body") or "")[:20], (ad.get("creative") or {}).get("title"))
        rows.append(f"V{k} ad {st['ads'][k]}")
    final_summary(log, f"建好：{acct_key} campaign {st['campaign_id']} PAUSED · 7 ad set RM50 · {' | '.join(rows)}")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — state saved, re-dispatch in ~30 min.", str(exc)[:200])
        sys.exit(75)
