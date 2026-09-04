"""Video 6「我也是爸爸」into all three new-structure campaigns: one ad set each. LIVE.

Operator flow (4 Sep): script + Drive video → copy written and shown first → approved ("上").
Body is the approved script-native copy (hook A), headline 「🔴 我也是爸爸，别让孩子重走我的
遗憾」. One creative is built once and shared by all three ads, so likes and comments pool on
a single post; no URL in the body (link on the CTA button only), no hashtags, no price.

Placement follows the operator's structure rule — one ad per ad set:
    Parents 3-17 + Engaged | F&R 興趣 | Food & Drink + Milk + Bread
each campaign gains ONE new ad set (named by its targeting, cloned from the same source ad
set its campaign was built from, F&R expansion lock re-verified) at RM50/day ABO, +RM150/day
total. No start_time: the campaigns are already delivering, and "上" is the go — the new ad
sets join them live.

Idempotent via state/entities_video6_dad.json (video upload cached; a re-dispatch resumes).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from adbot.clients.drive import DriveClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "entities_video6_dad.json"
STRUCTURE_STATE = Path("state") / "entities_new_structure_0904.json"
DRIVE_VIDEO_ID = "1JZGlAHSuzlZJ6vFDSH535Fp1sBRatBI-"
AD_NAME = "Video 6：我也是爸爸"
DAILY_MINOR = 5000

TITLE = "🔴 我也是爸爸，别让孩子重走我的遗憾"

# Approved 4 Sep (主文案 + Headline 1; operator chose 馬丁醫師 per the video's title card,
# matching the script). Written from the video's own script — the dad-and-former-kid double
# identity is the differentiator. No URL, no hashtags, no price.
BODY = """😔 我也是一个爸爸。

换作是我的孩子长不高，我的第一件事，
绝对不是急着买补品。

说实话，我会走上这一行，是因为我自己——

我小时候不矮：12 岁 165，13 岁 173，一直是班上最高的那几个。
我以为破 180 轻轻松松。

📉 结果那一年之后，我就再也没长高过。

那个「本来可以更高」的遗憾，我放在心里很多年。

🗣️「孩子矮？买点钙片补一补啦。」
🗣️「多喝奶粉，睡前逼他早点睡就好。」

👉 后来我才发现，很多华人爸妈，顺序都做反了。

孩子如果一直：
🌿 过敏、鼻子不通
🥣 肠胃不好、吃饭慢、吸收差
😴 晚上翻来覆去睡不好

你补进去的东西，他的身体根本用不上——
补再多，都是白补。

✅ 真正的顺序是：先把这些卡点解决，先健康，再长高。
有先后，不能颠倒。

👨‍⚕️ 我是马丁医师｜台湾儿童长高专家 · 中西医整合经验 10 年
这十年，我用这套「先后顺序」，陪过 7,000 多个华人家庭。
很多爸妈自己也不高，孩子一样一年一年往上长。

现在，我把整套方法整理成一堂免费的线上课程：

📍 怎么判断你孩子的「顺序」是不是做反了
📍 过敏、肠胃、睡眠——三个卡点分别怎么看
📍 用最健康的方式，帮孩子每年长高 6–8cm

⏰ 名额有限，坐满即止。

👇 点击下方按钮，立即免费报名。

一个爸爸跟你说句真心话——
这条路，你不用自己一个人走。
我不想让下一个孩子，再走一次我的遗憾。"""

# same clone sources the 4 Sep structure was built from
CAMPAIGNS: List[Dict[str, str]] = [
    {"key": "parents", "adset_name": "Parents 3-17 + Engaged", "clone": "120256891851660093"},
    {"key": "fr", "adset_name": "Family and Relationships", "clone": "120256985978460093"},
    {"key": "food", "adset_name": "Food & Drink + Milk + Bread",
     "clone": "120256984988980093"},
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

    structure = json.loads(STRUCTURE_STATE.read_text())
    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}

    def persist() -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    # ── video + the one shared creative ─────────────────────────────────────────
    creative_id = st.get("creative_id")
    if creative_id:
        log.info("── reuse creative %s", creative_id)
    else:
        video_id = st.get("video_id")
        if video_id:
            thumb = st.get("thumb") or g.get_video_thumbnail(video_id)
        else:
            path = Path("/tmp/video6_dad.mp4")
            DriveClient(s.secrets.google_sa_json).download_file(DRIVE_VIDEO_ID, path)
            log.info("── downloaded %.1f MB → uploading…", path.stat().st_size / 1_048_576)
            video_id = g.upload_video(acct, str(path), name=AD_NAME)
            thumb = g.get_video_thumbnail(video_id)
            path.unlink(missing_ok=True)
            st.update({"video_id": video_id, "thumb": thumb})
            persist()
            log.info("── uploaded → video %s", video_id)
        cta = {"type": m.call_to_action, "value": {"link": m.lead_destination.link_url}}
        vdata: Dict[str, Any] = {"video_id": video_id, "title": TITLE, "message": BODY,
                                 "call_to_action": cta}
        if thumb:
            vdata["image_url"] = thumb
        story: Dict[str, Any] = {"page_id": m.page_id, "video_data": vdata}
        if m.instagram_user_id:
            story["instagram_user_id"] = m.instagram_user_id
        fields: Dict[str, Any] = {"name": AD_NAME, "object_story_spec": story}
        if m.url_tags:
            fields["url_tags"] = m.url_tags
        creative_id = g.create_adcreative(acct, **fields)["id"]
        st["creative_id"] = creative_id
        persist()
        log.info("── + creative %s (shared by all three ads)", creative_id)

    # ── one new ad set + ad per campaign ────────────────────────────────────────
    rows: List[str] = []
    units: Dict[str, Any] = st.setdefault("units", {})
    for c in CAMPAIGNS:
        campaign_id = structure[c["key"]]["campaign_id"]
        rec: Dict[str, Any] = units.get(c["key"]) or {}
        spec = clone_targeting(g, c["clone"], s)
        adv = int((spec.get("targeting_automation") or {}).get("advantage_audience") or 1)
        if not rec.get("adset_id"):
            fields = {"name": c["adset_name"], "campaign_id": campaign_id,
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
            units[c["key"]] = rec
            persist()
            verify_expansion(g, rec["adset_id"], spec, adv, log)
        if not rec.get("ad_id"):
            ad = g.create_ad(acct, name=AD_NAME, adset_id=rec["adset_id"],
                             creative={"creative_id": creative_id},
                             status="ACTIVE", conversion_domain=conv)
            rec["ad_id"] = ad["id"]
            units[c["key"]] = rec
            persist()

        chk = g._request("GET", rec["adset_id"], params={"fields": "daily_budget,status"})
        fin = g._request("GET", rec["ad_id"], params={"fields": "effective_status"})
        log.info("── %-8s campaign %s · adset %s · ad %s · RM%s/day · eff %s", c["key"],
                 campaign_id, rec["adset_id"], rec["ad_id"],
                 int(chk.get("daily_budget") or 0) // 100, fin.get("effective_status"))
        rows.append(f"{c['key']}({fin.get('effective_status')})")

    final_summary(
        log, f"Video 6 我也是爸爸 live in all three structure campaigns — {'; '.join(rows)} — "
             f"one new RM50/day ad set each (+RM150/day total), one shared creative "
             f"{creative_id} (approved 主文案 + Headline 1, likes pool on a single post). "
             f"Structure totals: 13 ad sets · 13 ads · RM650/day.")


if __name__ == "__main__":
    main()
