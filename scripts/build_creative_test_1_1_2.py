"""Build 2 creative-test campaigns (1-1-2) on proven audiences — ALL PAUSED.

Campaign A: [SG] 儿童长高方程式 | Parents 3–17 + Engaged | 1-1-2
Campaign B: [SG] 儿童长高方程式 | Family and Relationships | 1-1-2

Each = 1 CBO (RM100/day) + 1 ad set (interest targeting cloned LIVE from that audience's
canonical winning ad set, forced to SG) + the SAME 2 NEW video ads:
  · Video 3：别再拿你的经验，赌孩子的身高
  · Video 4：孩子长高最大的敌人，不是遗传而是误判

Each ad is a FLEXIBLE creative (asset_feed_spec): the operator's multiple primary-text
options (main caption + 3 A/B hooks) + multiple headline options (3), which Meta rotates
/ optimizes ("add text option" + "add headline option"). If Meta rejects the flexible
payload the build falls back to a single text/headline video creative (main caption +
1st headline) so it never hard-fails — the extra options can then be added in the UI.

Videos are downloaded from Drive and uploaded to Meta ONCE; the 2 creatives are reused in
both campaigns. Idempotent: uploaded video_id + creative_id cached in
state/entities_ctest_shared.json and each campaign's entities in its own state file, so a
re-dispatch never re-uploads or duplicates.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from adbot.build_1_1_10 import build
from adbot.clients.drive import DriveClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_DIR = Path("state")
PREFIX = "[SG] 儿童长高方程式"
DAILY_MYR = 100

SG_GEO = {"countries": ["SG"]}
SG_EXCL = [{"id": "120226672882380093"},          # 15 days complete registration (已注册)
           {"id": "120246547080720093"}]          # 马丁 1997 Paid Student (已购买)
DETAIL_KEYS = ["interests", "behaviors", "life_events", "family_statuses", "industries",
               "income", "education_statuses", "work_positions", "work_employers",
               "relationship_statuses", "user_adclusters", "moms"]

# ── operator-supplied copy (verbatim). bodies[0] = main caption, [1:] = A/B hooks. ──
VIDEO3_MAIN = """🚫「我小时候也很矮，后来不也长到这么高？」

如果你也常这样安慰自己——请先停一下。

因为现在孩子的成长环境，
跟 20 年前已经完全不一样了。 📱

很多爸妈会用自己的经验，去判断孩子：
🗣️「男孩子晚一点长很正常。」
🗣️「我以前也是中学才抽高。」
🗣️「再等等看就好了。」

但问题是——
❗ 你的孩子，不是 20 年前的你。

马丁药师（台湾执照药师 · 中西医结合背景）
过去十多年来，接触过来自
🇹🇼🇲🇾🇸🇬🇭🇰🇺🇸🇨🇦 六个国家的家庭，
👨‍⚕️ 累积帮助超过上千位正在成长期的孩子。

他发现一件很有意思的事：

很多家长不是不关心，反而是「太关心」。
知道孩子爱吃什么、几点睡、最近做什么运动——
却从来没有人教过他们：
👉 到底该怎么看懂孩子真正的「成长讯号」。

😴 有些孩子只是晚发育。
⏳ 有些孩子却正在错过最重要的成长阶段。

而这两种，家长用肉眼几乎看不出来。

最可惜的是——
很多家庭等到发现不对劲的时候，时间已经过去了。 💔

但也有一个好消息：
发育期不一定是结束，
反而可能是孩子最后一次快速成长的关键机会。
✅ 前提是：你要知道自己在看什么。

这星期，马丁药师特别开放一场免费线上公开课——
📘《儿童长高方程式》

课堂上会分享三个大部分家长从没学过的观念：
📍 为什么同样的方法，别人家孩子有效，你孩子却没反应
📍 如何从日常表现，初步判断孩子的成长状态与体质
📍 不同孩子在饮食、吸收与成长需求上，到底差在哪里

你不需要买任何产品，也不需要先做任何决定。
但请先把「判断标准」学会——因为孩子的成长，只有一次。

⏰ 名额有限，先保留位置。

👇 点击下方链接，免费领取《儿童长高方程式》

很多家长最后后悔的，从来不是做错了什么，
而是当初以为还有时间，一等再等，错过了黄金期。"""

VIDEO3_HOOKS = [
    "👨‍⚕️ 10 年经验、700+ 家庭、6 个国家的谘询——\n"
    "马丁药师发现：长不高的孩子，家长常常「太关心」，却看错了地方。",
    "😴 有的孩子只是晚发育，⏳ 有的却正在错过黄金期。\n"
    "可怕的是——这两种，你用肉眼几乎分不出来。",
    "很多爸妈后悔的，从来不是做错了什么，\n"
    "而是以为「还有时间」，结果一等，就错过了。",
]
VIDEO3_TITLES = [
    "别再拿你的经验，赌孩子的身高",
    "你的孩子，不是 20 年前的你｜免费公开课",
    "免费领取《儿童长高方程式》——名额有限",
]

VIDEO4_MAIN = """⚠️ 孩子长高最大的敌人，不是遗传——
而是「误判」。

家长们，别再用自己的成长经历，
去预测孩子的未来了。

我知道你会这样说：
🗣️「不用担心啦，我以前也是班上最矮的，现在还不是长高了？」

但我想问你一个问题👇
你小时候的成长环境，真的跟孩子现在一样吗？

🏃 你小时候放学：跑跳、打球、骑脚车，晚上九点就睡。
📱 现在的孩子：补习、玩手机、十一二点还没睡。

而且三天两头——
🤧 鼻子敏感、皮肤过敏、很容易生病，
🥣 肠胃吸收也越来越差。

很多父母不知道：
孩子长不高，未必是基因问题，
❗ 更可能是身体已经出现三个警讯：

😴 睡眠品质不好
🌿 体质差
🦵 筋膜长期紧绷

如果这三个问题没改善，
补品吃再多、牛奶喝再多，效果都很有限。

最可惜的是——很多家长一直等。
等一年、等两年，
等到同学一个个抽高，自己的孩子还站在第一排，
这时候才开始紧张。 💔

我是马丁药师。这些年我发现，
很多长不高的孩子，问题往往出在「体质」：

吸收能力差、长期过敏消耗身体、
睡眠品质不好、筋膜长期紧绷——
🔍 体质不同，需要的调整方式自然不同。

所以我建立了一套「儿童体质辨识系统」，
透过孩子的 👅 舌象、日常症状、饮食后的身体反应，
帮家长找出真正影响成长的关键。

这星期，我会开一场免费线上公开课——
📘《儿童长高方程式》

课堂上你会了解：
📍 为什么同一种方法，别人孩子有效、你孩子却没效
📍 如何从生活细节，判断孩子的体质特点
📍 不同体质的孩子，饮食与日常调理重点差在哪

如果你的孩子正处于 🔟–1️⃣5️⃣ 岁的关键成长阶段，
别再盲目尝试各种方法。
✅ 先了解原因，再决定方向。

⏰ 名额有限，坐满即止。

👇 点击下方链接，立即免费报名《儿童长高方程式》

孩子的成长只有一次，别让一个「误判」，赔掉他的身高。"""

VIDEO4_HOOKS = [
    "😴 睡眠差、🌿 体质弱、🦵 筋膜紧——\n"
    "孩子长不高，往往不是缺钙，是这三个警讯被忽略了。",
    "🏃 你小时候九点睡、天天跑跳；📱 你孩子十二点还在滑手机。\n"
    "凭什么用你的成长经历，赌他的身高？",
    "👅 从孩子的舌象、日常症状、饮食反应，就能看出他为什么长不高。\n"
    "马丁药师的「儿童体质辨识系统」，帮家长找出真正的卡点。",
]
VIDEO4_TITLES = [
    "孩子长高最大的敌人，是遗传还是误判？",
    "长不高不一定缺钙——是这 3 个警讯被忽略了",
    "免费公开课《儿童长高方程式》｜名额有限",
]

VIDEOS = [
    {"key": "video3", "drive_id": "16rmsI2MjxGcCT8Br7jrXwVGDRBaQo7e3",
     "ad_name": "Video 3：别再拿你的经验，赌孩子的身高",
     "bodies": [VIDEO3_MAIN, *VIDEO3_HOOKS], "titles": VIDEO3_TITLES},
    {"key": "video4", "drive_id": "13ztt-jYHTmK7X93Is84GQ1L_8Oc6xd8f",
     "ad_name": "Video 4：孩子长高最大的敌人，不是遗传而是误判",
     "bodies": [VIDEO4_MAIN, *VIDEO4_HOOKS], "titles": VIDEO4_TITLES},
]

CAMPAIGNS = [
    {"label": "Parents 3–17 + Engaged",   "clone": "Advantage+ Parents + Engaged",
     "state_key": "entities_ctest_parents"},
    {"label": "Family and Relationships", "clone": "Interest: Family and Relationships",
     "state_key": "entities_ctest_family"},
]


# ── targeting clone (self-contained copy of the audience-test logic) ─────────────
def _richness(t: dict) -> int:
    if not isinstance(t, dict):
        return 0
    cnt = lambda spec: sum(len(spec.get(k) or []) for k in DETAIL_KEYS)
    n = cnt(t)
    for grp in (t.get("flexible_spec") or []):
        n += cnt(grp)
    return n


def pull_adsets(g) -> List[dict]:
    log = get_logger()
    out: List[dict] = []
    for a in g._get_all("me/adaccounts", {"fields": "account_id", "limit": 200}):
        path = f"act_{a['account_id']}"
        try:
            out += g._get_all(f"{path}/adsets",
                              {"fields": "name,effective_status,targeting", "limit": 500})
        except Exception as e:  # noqa: BLE001
            log.warning("adsets pull failed for %s: %s", path, e)
    return out


def clone_targeting(adsets: List[dict], name: str) -> Tuple[Optional[dict], Optional[str]]:
    key = name.strip().lower()
    matches = [a for a in adsets if (a.get("name") or "").strip().lower() == key]
    if not matches:
        matches = [a for a in adsets if key in (a.get("name") or "").strip().lower()]
    if not matches:
        return None, None
    best = max(matches, key=lambda a: _richness(a.get("targeting") or {}))
    t = best.get("targeting") or {}
    adv_raw = (t.get("targeting_automation") or {}).get("advantage_audience")
    adv = 1 if adv_raw is None else int(adv_raw)
    age_min, age_max = int(t.get("age_min") or 25), int(t.get("age_max") or 65)
    if adv == 1 and age_min > 25:
        age_min = 25
    spec: Dict[str, Any] = {
        "geo_locations": SG_GEO, "age_min": age_min, "age_max": age_max,
        "targeting_automation": {"advantage_audience": adv},
        "excluded_custom_audiences": SG_EXCL, "locales": [1004],
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
    return spec, best.get("name")


# ── flexible creative (multi text + title) with single-option fallback ──────────
def make_creative(g, acct, s, name, video_id, thumb, bodies, titles) -> Tuple[str, str]:
    log = get_logger()
    ident = {"page_id": s.meta.page_id}
    if s.meta.instagram_user_id:
        ident["instagram_user_id"] = s.meta.instagram_user_id
    try:
        video = {"video_id": video_id}
        if thumb:
            video["thumbnail_url"] = thumb
        afs = {
            "ad_formats": ["SINGLE_VIDEO"],
            "videos": [video],
            "bodies": [{"text": b} for b in bodies],
            "titles": [{"text": t} for t in titles],
            "link_urls": [{"website_url": s.meta.lead_destination.link_url}],
            "call_to_action_types": [s.meta.call_to_action],
        }
        fields = {"name": name, "object_story_spec": ident, "asset_feed_spec": afs}
        if s.meta.url_tags:
            fields["url_tags"] = s.meta.url_tags
        return g.create_adcreative(acct, **fields)["id"], f"flexible({len(bodies)}text/{len(titles)}title)"
    except Exception as e:  # noqa: BLE001
        log.warning("  ! flexible creative rejected (%s) — falling back to single text/title", e)
        cta = {"type": s.meta.call_to_action, "value": {"link": s.meta.lead_destination.link_url}}
        vdata = {"video_id": video_id, "title": titles[0], "message": bodies[0], "call_to_action": cta}
        if thumb:
            vdata["image_url"] = thumb
        story = dict(ident, video_data=vdata)
        fields = {"name": name, "object_story_spec": story}
        if s.meta.url_tags:
            fields["url_tags"] = s.meta.url_tags
        return g.create_adcreative(acct, **fields)["id"], "single(fallback)"


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    conv = s.meta.conversion_domain_bare or None

    s.naming.prefix = PREFIX
    s.meta.budget.level = "CAMPAIGN"                 # CBO
    s.meta.budget.daily_amount_myr = DAILY_MYR

    # 1) upload the 2 videos + build creatives ONCE (cached in shared state) ───────
    drive = DriveClient(s.secrets.google_sa_json)
    shared_path = STATE_DIR / "entities_ctest_shared.json"
    shared = json.loads(shared_path.read_text()) if shared_path.exists() else {}
    creatives: Dict[str, Dict[str, str]] = shared.get("creatives", {})
    for v in VIDEOS:
        if v["key"] in creatives:
            log.info("reuse %s → creative %s (cached)", v["key"], creatives[v["key"]]["creative_id"])
            continue
        path = drive.download_file(v["drive_id"], Path(f"/tmp/{v['key']}.mp4"))
        log.info("downloaded %s (%d bytes) → uploading to Meta…", v["key"], path.stat().st_size)
        video_id = g.upload_video(acct, str(path), name=v["ad_name"])
        thumb = g.get_video_thumbnail(video_id)
        cid, mode = make_creative(g, acct, s, v["ad_name"], video_id, thumb, v["bodies"], v["titles"])
        creatives[v["key"]] = {"video_id": video_id, "creative_id": cid, "mode": mode,
                               "ad_name": v["ad_name"]}
        shared["creatives"] = creatives
        shared_path.parent.mkdir(parents=True, exist_ok=True)
        shared_path.write_text(json.dumps(shared, ensure_ascii=False, indent=2))
        log.info("  ✔ %s → video %s · creative %s · %s", v["key"], video_id, cid, mode)

    # 2) clone targeting + build each campaign (skeleton) + wire the 2 ads ─────────
    all_adsets = pull_adsets(g)
    log.info("pulled %d ad sets across accounts", len(all_adsets))

    summary: List[str] = []
    for camp in CAMPAIGNS:
        spec, src = clone_targeting(all_adsets, camp["clone"])
        if spec is None:
            log.error("!! no ad set like %r to clone — SKIPPING %s", camp["clone"], camp["label"])
            summary.append(f"  SKIPPED {camp['label']} (no clone source {camp['clone']!r})")
            continue
        log.info("── %s ← cloned from %r (age %s-%s · %d detail entries)",
                 camp["label"], src, spec["age_min"], spec["age_max"],
                 _richness({"flexible_spec": spec.get("flexible_spec", [])}))

        ent = build(g, s, units=[], captions={}, dry_run=False,
                    label=f"{camp['label']} | 1-1-2", state_key=camp["state_key"],
                    adset_name=camp["label"], targeting_override=spec)
        campaign_id, adset_id = ent["campaign_id"], ent["adset_id"]

        st_path = STATE_DIR / f"{camp['state_key']}.json"
        st = json.loads(st_path.read_text()) if st_path.exists() else {}
        built = set(st.get("built_ad_keys", []))
        ad_ids = list(st.get("ad_ids", []))
        for v in VIDEOS:
            if v["key"] in built:
                log.info("   skip ad %s (already built)", v["ad_name"])
                continue
            cid = creatives[v["key"]]["creative_id"]
            ad = g.create_ad(acct, name=v["ad_name"], adset_id=adset_id,
                             creative={"creative_id": cid}, status="PAUSED",
                             conversion_domain=conv)
            ad_ids.append(ad["id"])
            built.add(v["key"])
            st.update({"campaign_id": campaign_id, "adset_id": adset_id,
                       "ad_ids": ad_ids, "built_ad_keys": sorted(built)})
            st_path.write_text(json.dumps(st, ensure_ascii=False, indent=2))
            log.info("   + ad %s ⟵ %s (%s)", ad["id"], v["ad_name"], cid)
        summary.append(f"  {camp['label']:26} campaign={campaign_id} adset={adset_id} "
                       f"ads={len(ad_ids)}")

    log.info("═" * 84)
    for k, c in creatives.items():
        log.info("creative %s: %s (%s)", k, c["creative_id"], c["mode"])
    for line in summary:
        log.info(line)
    final_summary(
        log, f"2× creative-test 1-1-2 built PAUSED (CBO RM{DAILY_MYR}/day each): Video 3 + Video 4 "
             f"on Parents 3–17 + Engaged and Family and Relationships. Activate + set placements in "
             f"Ads Manager after review.")


if __name__ == "__main__":
    main()
