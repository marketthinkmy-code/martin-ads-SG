"""Hooks 0907: three BRAND-NEW campaigns, four videos, one ad set per ad. LIVE, runs now.

Operator's spec (7 Sep, synced line by line and approved "okk 直接跑"):
    · THREE new campaigns — Parents 3-17 + Engaged / F&R 興趣 / Food & Drink + Milk + Bread —
      named with the Hooks 0907 batch tag; the 4-Sep structure campaigns are NOT touched.
    · Each campaign holds FOUR ad sets (named by the targeting), RM50/day ABO each, one ad
      per ad set: Hook 1 今晚回家 · Hook 2 旧鞋当尺 · Hook 6 只剩两到三年 · Video 7 我13岁173.
    · 12 ad sets · 12 ads · +RM600/day, ACTIVE immediately.
    · One creative per video, shared by its three campaign copies (social proof pools).
    · Copy: the four approved script-native bodies + each video's Headline 1; 马丁医师 per the
      operator's standing call; no URL in the body, no hashtags, no price.
    · Scale stays manual per ad (RM50→80→100→150 on the operator's word) — nothing automated.

Targeting clones the same sources as the 4-Sep structure (Parents proving ground / F&R A with
expansion locked 0 and re-verified / Milk & Bread food interests). Idempotent via
state/entities_hooks_0907.json — uploads and entities are cached, a re-dispatch resumes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from adbot.clients.drive import DriveClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "entities_hooks_0907.json"
PREFIX = "[SG] 儿童长高方程式"
DAILY_MINOR = 5000

VIDEOS: List[Dict[str, str]] = [
    {"key": "hook1", "drive": "1YAeiSjwB-2eb_-zs5lJFIO15jGdFi_NC",
     "ad_name": "Hook 1：今晚回家检查三件事", "title": "🔴 今晚回家，检查这三件事"},
    {"key": "hook2", "drive": "1bxY0AK0hWJdVJKiElp1vNotEIWY-dqK4",
     "ad_name": "Hook 2：旧鞋当尺", "title": "🔴 孩子的鞋，一年没换大？"},
    {"key": "hook6", "drive": "1fBF7qq9eKLOX6OpeocvwRrwxNk2D6by9",
     "ad_name": "Hook 6：只剩两到三年", "title": "🔴 平均只剩两到三年，你知道吗"},
    {"key": "video7", "drive": "162Aes_btHX2pFo3K9TOzu7Nw5wV5qQ9J",
     "ad_name": "Video 7：我13岁身高173", "title": "🔴 我 13 岁 173，然后再也没长过"},
]

BODIES: Dict[str, str] = {
    "hook1": """🔍 今晚回家，花一分钟，检查三件事——
你就知道孩子为什么长不高。

第一：他过去一年，是不是只长了一两公分？
第二：他吃很多，但是不长肉、也不长高？
第三：他是不是经常鼻子敏感、皮肤痒、便秘，晚上睡不安稳？

⚠️ 如果三个全中——
这不是「发育比较慢」。

是他的吸收系统，在跟你求救。

🗣️「多吃一点就会长啦。」
🗣️「男生晚长，再等等。」

👉 等，等不来身高。因为问题不在吃多少，在身体有没有能力用。

我的做法，从来只有一句话：先健康，后长高。

❌ 不打针、不塞补品。
✅ 先把过敏压下去、把肠胃修好、让他睡得够深——
身体没有负担了，吃进去的营养，才真正拿去长高。

但我要老实告诉你一件事：
⏳ 孩子的生长板一旦闭合，就再也长不高了。
到时候花再多钱、买再贵的东西，都追不回来。
这不是吓你，是时间的问题。

👨‍⚕️ 我是马丁医师｜台湾儿童长高专家 · 中西医整合经验 10 年
已帮助 7,000+ 个家庭，破解孩子「长不高」的问题。

我把整套方法，放进一堂免费的线上课程：

📍 三个信号背后，孩子长不高的底层原因是什么
📍 过敏、肠胃、睡眠——先后顺序怎么排才对
📍 生长板闭合之前，你还可以为他做什么

⏰ 名额有限，坐满即止。

👇 点击下方按钮，立即免费报名。

今晚先检查那三件事——
然后来上课，别让孩子错过长高黄金期。""",
    "hook2": """👟 孩子的鞋，是不是穿了一年多，还没换大？

那你要小心了——
脚没长，往往代表：他这一整年，都没有什么在长高。

我知道你已经很努力了。

🥛 每天逼他喝牛奶
💊 买最贵的保健品
🏃 逼他跳绳跳到膝盖痛

📉 结果呢？他吃得比谁都多，身高就是不动。
你开始怀疑：是不是我们家基因就是这样？

👉 不是。

营养要变成身高，得先过「肠胃」这一关。
肠胃卡住了，你补再多，也是白补。

重点从来不是补得够不够——
是他，吸不吸得进去。

怎么知道你的孩子有没有这个问题？
今晚回家，检查三件事，一分钟就够：

📏 过去一年，是不是只长了一两公分？
🍚 吃很多，但不长肉、也不长高？
🌿 经常鼻子敏感、皮肤痒、便秘，晚上睡不安稳？

⚠️ 三个全中——这是他的吸收系统在求救。

👨‍⚕️ 我是马丁医师｜台湾儿童长高专家 · 中西医整合经验 10 年
已帮助 7,000+ 个家庭破解孩子「长不高」的问题。
我的做法只有一句话：先健康，后长高。不打针、不塞补品。

现在，我把整套方法放进一堂免费的线上课程：

📍 怎么判断孩子是「没吃够」还是「吸收不到」
📍 过敏、肠胃、睡眠的修复顺序
📍 生长板闭合之前，你还来得及做的事

⏰ 名额有限，坐满即止。

👇 点击下方按钮，立即免费报名。

一双旧鞋，就能量出孩子这一年的成长——
别等鞋换大了才发现，时间已经过去了。""",
    "hook6": """⏳ 我告诉你一个数字，可能会吓到你。

从孩子青春期启动，到生长板闭合——
平均，只剩两到三年。

🗣️「顺其自然啦，大一点自己会抽高。」
🗣️「再等等看，他爸爸也是晚长的。」

😔 结果呢？很多家长，是等到孩子十五、十六岁，
突然不长了，才开始慌。

那时候才来找——说真的，剩下的时间，已经不多了。

👉 你要知道：长高，不是一条平平的直线。

它有一个黄金期。
青春期一启动，倒数计时就开始跑了。

等那一波抽高结束、生长板一闭合，身高就定型。
这是骨头的事，不是努力就能重来的事。

真正能帮孩子追高的，就是中间那短短几年。

👨‍⚕️ 我是马丁医师｜台湾儿童长高专家 · 中西医整合经验 10 年
这十年，我陪过 7,000 多个华人家庭。
最让我心疼的，永远是同一种——
孩子明明还有空间，却因为一句「再等等看」，白白错过。

✅ 反过来，愿意早一点看清楚状况的，追回来的机会，大得多。

我把整套判断方法，放进一堂免费的线上课程：

📍 怎么判断你的孩子，还剩多少长高时间
📍 黄金期里，哪些事该做、哪些钱不该花
📍 用最健康的方式，把最后这段时间用对

⏰ 名额有限，坐满即止。

👇 点击下方按钮，立即免费报名。

别再用一句「顺其自然」，
赌掉孩子最后这几年。""",
    "video7": """我 13 岁，身高就有 173。

我以为，我随便都能破 180——

📉 结果，从那一年开始，我就再也没长高过。

我小时候不矮，在班上一直是最高的那几个。
我爸妈也急。可那个年代，没人懂查资料——

🥛 就只会叫我拼命喝牛奶、吃钙片、炖补汤，带我去看中医调体质。

试了一整轮，我的身高，永远停在 173。

173 不算矮。但我心里一直有个遗憾：
如果当年有人教我对的方法，我很可能，不只停在这里。

就是这个遗憾，让我后来一头栽进这一行——
我不想再有一个孩子，走一次我的冤枉路。

👉 后来我花了很多年才想通：
孩子长不高，不是缺哪一种补品。

是三件事没做对。我把它叫「成长金三角」：

🔍 找出他长不高的体质原因
🔓 帮他打开身体的成长空间
🍽️ 配上真正适合这里气候的吃法

左边那条路：喝牛奶、吃钙片、炖补汤、乱买保健品——钱花了，时间也没了。
右边这三步，才是真正该走的顺序。

👨‍⚕️ 我是马丁医师｜台湾儿童长高专家 · 中西医整合经验 10 年
这十年，我用这套「成长金三角」，陪过 7,000 多个华人家庭。
很多爸妈自己也不高，孩子一样一年一年稳稳往上长。

这套金三角到底怎么一步步做，
我完整讲给你听——就在一堂免费的线上课程里：

📍 第一步：怎么找出孩子长不高的体质原因
📍 第二步：怎么打开身体的成长空间
📍 第三步：三餐怎么配，营养才留得住

⏰ 名额有限，坐满即止。

👇 点击下方按钮，立即免费报名。

我不想你跟我一样，多年以后才在后悔——
「早知道，就好了。」""",
}

CAMPAIGNS: List[Dict[str, str]] = [
    {"key": "parents", "label": "Parents 3-17 + Engaged | Hooks 0907 | 1-4-4",
     "adset_name": "Parents 3-17 + Engaged", "clone": "120256891851660093"},
    {"key": "fr", "label": "F&R 興趣 | Hooks 0907 | 1-4-4",
     "adset_name": "Family and Relationships", "clone": "120256985978460093"},
    {"key": "food", "label": "Food & Drink + Milk + Bread | Hooks 0907 | 1-4-4",
     "adset_name": "Food & Drink + Milk + Bread", "clone": "120256984988980093"},
]

DETAIL_KEYS = ["interests", "behaviors", "life_events", "family_statuses", "industries",
               "income", "education_statuses", "work_positions", "work_employers",
               "relationship_statuses", "user_adclusters", "moms"]


def clone_targeting(g, adset_id: str, s) -> Dict[str, Any]:
    t = g._request("GET", adset_id, params={"fields": "targeting"}).get("targeting") or {}
    adv_raw = (t.get("targeting_automation") or {}).get("advantage_audience")
    adv = 1 if adv_raw is None else int(adv_raw)
    age_min, age_max = int(t.get("age_min") or 25), int(t.get("age_max") or 65)
    if adv == 1 and age_min > 25:
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
    return spec


def verify_expansion(g, adset_id: str, spec: Dict[str, Any], intended: int, log) -> None:
    if intended != 0:
        return
    t = g._request("GET", adset_id, params={"fields": "targeting"}).get("targeting") or {}
    adv = int((t.get("targeting_automation") or {}).get("advantage_audience") or 0)
    if adv == 0:
        return
    fix = dict(spec)
    fix["targeting_automation"] = {"advantage_audience": 0}
    g._request("POST", adset_id, data={"targeting": json.dumps(fix)})
    t2 = g._request("GET", adset_id, params={"fields": "targeting"}).get("targeting") or {}
    adv2 = int((t2.get("targeting_automation") or {}).get("advantage_audience") or 0)
    log.info("   expansion drifted (adv=%s) → rewrote → adv=%s%s", adv, adv2,
             "" if adv2 == 0 else " — STILL ON, fix by hand")


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    m = s.meta
    conv = m.conversion_domain_bare or None

    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}

    def persist() -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    # ── 1) four videos → four shared creatives ──────────────────────────────────
    creatives: Dict[str, Any] = st.setdefault("creatives", {})
    drive = None
    for v in VIDEOS:
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
            log.info("── %s: downloaded %.1f MB → uploading…", v["key"],
                     path.stat().st_size / 1_048_576)
            video_id = g.upload_video(acct, str(path), name=v["ad_name"])
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
        rec["creative_id"] = g.create_adcreative(acct, **fields)["id"]
        creatives[v["key"]] = rec
        persist()
        log.info("── %s: + creative %s (video %s)", v["key"], rec["creative_id"], video_id)

    # ── 2) three new campaigns × four (ad set + ad) ─────────────────────────────
    rows: List[str] = []
    camps: Dict[str, Any] = st.setdefault("campaigns", {})
    for c in CAMPAIGNS:
        log.info("═" * 88)
        cst: Dict[str, Any] = camps.setdefault(c["key"], {})
        if cst.get("campaign_id"):
            log.info("── reuse campaign %s", cst["campaign_id"])
        else:
            fields = {"name": f"{PREFIX} | {c['label']}", "objective": m.objective,
                      "buying_type": "AUCTION", "status": "ACTIVE",
                      "special_ad_categories": m.special_ad_categories,
                      "is_adset_budget_sharing_enabled": False}
            if m.regional_regulated_categories:
                fields["regional_regulated_categories"] = m.regional_regulated_categories
            cst["campaign_id"] = g.create_campaign(acct, **fields)["id"]
            persist()
            log.info("── + campaign %s %r", cst["campaign_id"], fields["name"])

        spec = clone_targeting(g, c["clone"], s)
        adv = int((spec.get("targeting_automation") or {}).get("advantage_audience") or 1)
        units: Dict[str, Any] = cst.setdefault("units", {})
        for v in VIDEOS:
            rec = units.get(v["key"]) or {}
            if not rec.get("adset_id"):
                fields = {"name": c["adset_name"], "campaign_id": cst["campaign_id"],
                          "optimization_goal": m.optimization_goal,
                          "billing_event": "IMPRESSIONS", "promoted_object": m.promoted_object,
                          "targeting": spec, "status": "ACTIVE",
                          "daily_budget": DAILY_MINOR,
                          "bid_strategy": "LOWEST_COST_WITHOUT_CAP"}
                if m.regional_regulated_categories:
                    fields["regional_regulated_categories"] = m.regional_regulated_categories
                if m.regional_regulation_identities:
                    fields["regional_regulation_identities"] = m.regional_regulation_identities
                rec["adset_id"] = g.create_adset(acct, **fields)["id"]
                units[v["key"]] = rec
                persist()
                verify_expansion(g, rec["adset_id"], spec, adv, log)
            if not rec.get("ad_id"):
                ad = g.create_ad(acct, name=v["ad_name"], adset_id=rec["adset_id"],
                                 creative={"creative_id": creatives[v["key"]]["creative_id"]},
                                 status="ACTIVE", conversion_domain=conv)
                rec["ad_id"] = ad["id"]
                units[v["key"]] = rec
                persist()
            fin = g._request("GET", rec["ad_id"], params={"fields": "effective_status"})
            log.info("   %-8s adset %s ad %s · RM50/day · eff %s", v["key"],
                     rec["adset_id"], rec["ad_id"], fin.get("effective_status"))
            rows.append(f"{c['key']}/{v['key']}({fin.get('effective_status')})")

    log.info("═" * 88)
    final_summary(
        log, f"Hooks 0907 live: 3 NEW campaigns · 12 ad sets (RM50/day each, named by "
             f"targeting) · 12 ads over 4 shared creatives — {'; '.join(rows)}. +RM600/day, "
             f"running immediately; the 4-Sep structure campaigns were not touched. Scale "
             f"stays manual per ad on the operator's word.")


if __name__ == "__main__":
    main()
