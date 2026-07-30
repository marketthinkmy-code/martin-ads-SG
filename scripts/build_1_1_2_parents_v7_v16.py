"""Build a SECOND 1-1-2 creative-test campaign on Parents interest targeting — PAUSED.

Campaign: [SG] 儿童长高方程式 | Parents 兴趣定向 | 1-1-2  (batch B: Video 7 + Video 16)
  = 1 CBO (RM100/day) + 1 ad set (targeting cloned LIVE from the winning
    "Advantage+ Parents + Engaged" ad set, forced to SG) + 2 NEW video ads
    competing in that ONE ad set:
      · Video 7：15 岁还没抽高，是不是已经太迟？  (太迟?不一定 · 别靠猜 · 时间窗口角度)
      · Video 16：身高永遠停在15歲             (生长板闭合倒计时 · 情感冲击角度)

This is a SEPARATE campaign from the earlier Parents 兴趣定向 | 1-1-4 (Video 11/13/14/15):
own STATE_KEY + own shared-video cache, so it never touches or duplicates that one. Same
audience (cloned from the same source), different creatives — a second creative test.

Single text + single headline per ad (multi-option text/headline = a Meta "Dynamic Creative",
only allowed in a dynamic ad set of exactly ONE ad — incompatible with 1-1-2). Idempotent:
videos upload to Meta ONCE (cached in state/entities_v7v16_shared.json); entities live in
state/entities_1_1_2_parents_v7v16.json, so a re-dispatch never duplicates. Everything builds
PAUSED (config activate_after_build:false) — activate in Ads Manager after review.
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
CLONE_SOURCE = "Advantage+ Parents + Engaged"
ADSET_NAME = "Parents 兴趣定向"
STATE_KEY = "entities_1_1_2_parents_v7v16"
SHARED_PATH = STATE_DIR / "entities_v7v16_shared.json"

SG_GEO = {"countries": ["SG"]}
SG_EXCL = [{"id": "120226672882380093"},          # 15 days complete registration (已注册)
           {"id": "120246547080720093"}]          # 马丁 1997 Paid Student (已购买)
DETAIL_KEYS = ["interests", "behaviors", "life_events", "family_statuses", "industries",
               "income", "education_statuses", "work_positions", "work_employers",
               "relationship_statuses", "user_adclusters", "moms"]

# ── ad copy (Simplified — SG audience-facing). One primary text + one headline per ad. ──
VIDEO7_MAIN = """⚠️ 孩子 15 岁了，还没明显抽高——
是不是已经太迟了？

我直接告诉你：不一定。

但如果你现在还在用「等他自己长」这一招——
那才是真正危险的地方。

因为 15 岁之后，
孩子已经不是「靠自然成长就会一直长高」的阶段了。

很多家长会安慰自己：
🗣️「男生比较慢发育，迟一点就高了。」
🗣️「女生只是还没发育完，之后会追上。」

这句话，只对一半。

男生确实有机会长到比较后期，
女生初潮之后，也不是马上就停止成长。
但真正的重点是👇

孩子还有没有成长空间，
❗ 不是靠「猜」的。
要看他的发育阶段、体质、吸收能力、睡眠、运动方式，
还有骨骼的成长状态。

很多家长错就错在——
孩子都已经进入青春期后期了，
还在用「小学阶段」的方法：
🍼 继续多喝牛奶、吃保健品、随便做做运动，
然后期待他哪天突然抽高。

问题是：
🥣 如果身体吸收不好、
😴 如果睡眠时间不对、
🏃 如果运动方式不适合，
你做再多，可能都只是白忙一场。

我是马丁药师（台湾执照药师 · 中西医结合背景）。
过去我帮助过来自
🇲🇾🇸🇬🇺🇸🇨🇦🇹🇼🇭🇰 的孩子，
我发现一个共同点：
👉 不是每个孩子都没机会——
真正的问题是，很多家长太迟发现孩子「卡」在哪里。

所以这星期，我会开一场免费线上公开课，
专门教家长判断：

📍 孩子现在到底还有没有成长空间？
📍 为什么吃了补品还是没效果？
📍 什么运动适合、什么运动反而不适合？
📍 青春期的孩子，饮食、作息、体质该怎么调？

如果你的孩子现在大概 5 到 17 岁，
尤其已经开始担心身高——
✅ 别再靠猜，先搞清楚他现在到底卡在哪里。

⏰ 名额有限，坐满即止。

👇 点击下方链接，立即免费报名《儿童长高方程式》

太迟不太迟，不是用「等」的——
是先看懂，再决定怎么帮他。"""

VIDEO7_TITLE = "15岁还没抽高，是不是太迟了？｜免费公开课"

VIDEO16_MAIN = """⏳ 他不会永远都是 15 岁。
但他的身高，可能永远停在 15 岁。

这句话听起来很残酷。
但这，就是现实。

你的孩子会长大、会毕业、会工作、会组建家庭——
他的年龄，会一直往前走。

但如果你在他 15 岁的时候没做对的事，
他 20 岁、30 岁、40 岁的身高，
可能就永远停在今天这个数字上。

他会带着这个身高，
去当兵、去面试、去社交、去相亲。
💔 他会带着这个身高，活一辈子。

15 岁，是一个分水岭。

在这之前，你可以慢慢来、可以试错、可以等。
但在这之后——每一天都在倒计时。

因为孩子的生长板，正在逐渐闭合。
闭合的速度，取决于两件事：
一是年龄，二是体质状态。
年龄你改变不了，但体质，你可以调理。

如果你能在生长板完全闭合之前，
🥣 把脾胃功能调好、
😴 把睡眠品质改善、
🌿 把失衡的体质纠正过来——
他的身体，还有能力再长。

但如果你继续什么都不做，
或者继续用错的方法，
等到生长板完全闭合的那一天，
一切就都结束了。

❗ 而那一天，不会通知你。
它就这样，静静地来了。

我是马丁药师（台湾执照药师 · 中西医结合背景）。
这十几年，我陪着近 7,000 个家庭，
赶在生长板还没关上之前，
先帮孩子把体质调好，再把身高一点点追回来。

这星期，我会开一场免费线上公开课——
📘《儿童长高方程式》

课堂上你会了解：
📍 怎么判断孩子的生长板还剩多少时间
📍 脾胃、睡眠、体质——哪一个正在拖住他的成长
📍 青春期这段倒计时，到底该怎么抓

别等到那一天悄悄来了，才后悔没早点做。
✅ 现在，就是还来得及的时候。

⏰ 名额有限，坐满即止。

👇 点击下方链接，立即免费报名《儿童长高方程式》

他的年龄会一直往前走，
别让他的身高，永远停在 15 岁。"""

VIDEO16_TITLE = "别让孩子的身高，永远停在15岁｜免费公开课"

VIDEOS = [
    {"key": "video7", "drive_id": "1zpCkfT3BNxbJrJ-SbXm1GsURzsFI4nvx",
     "ad_name": "Video 7：15 岁还没抽高，是不是已经太迟？", "message": VIDEO7_MAIN, "title": VIDEO7_TITLE},
    {"key": "video16", "drive_id": "1U3m03mYstMMRQ4yRdJ-QzbxgV7mXj4UA",
     "ad_name": "Video 16：身高永遠停在15歲", "message": VIDEO16_MAIN, "title": VIDEO16_TITLE},
]


def _richness(t: dict) -> int:
    if not isinstance(t, dict):
        return 0
    cnt = lambda spec: sum(len(spec.get(k) or []) for k in DETAIL_KEYS)
    return cnt(t) + sum(cnt(grp) for grp in (t.get("flexible_spec") or []))


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
    matches = [a for a in adsets if (a.get("name") or "").strip().lower() == key] \
        or [a for a in adsets if key in (a.get("name") or "").strip().lower()]
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


def make_single_creative(g, acct, s, name, video_id, thumb, message, title) -> str:
    """Standard single text + single headline video creative — attaches to a normal ad set."""
    cta = {"type": s.meta.call_to_action, "value": {"link": s.meta.lead_destination.link_url}}
    vdata = {"video_id": video_id, "title": title, "message": message, "call_to_action": cta}
    if thumb:
        vdata["image_url"] = thumb
    story = {"page_id": s.meta.page_id, "video_data": vdata}
    if s.meta.instagram_user_id:
        story["instagram_user_id"] = s.meta.instagram_user_id
    fields = {"name": name, "object_story_spec": story}
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
    s.meta.budget.level = "CAMPAIGN"                 # CBO
    s.meta.budget.daily_amount_myr = DAILY_MYR

    # 1) upload (or reuse cached) videos + build single-option creatives ───────────
    drive = None
    shared = json.loads(SHARED_PATH.read_text()) if SHARED_PATH.exists() else {}
    videos_cache: Dict[str, Dict[str, Any]] = shared.get("videos", {})
    creatives: Dict[str, Dict[str, str]] = shared.get("creatives", {})
    for v in VIDEOS:
        if v["key"] in creatives:
            log.info("reuse %s → creative %s (cached)", v["key"], creatives[v["key"]]["creative_id"])
            continue
        vc = videos_cache.get(v["key"])
        if vc and vc.get("video_id"):
            video_id = vc["video_id"]
            thumb = vc.get("thumb") or g.get_video_thumbnail(video_id)
            log.info("reuse uploaded %s → video %s", v["key"], video_id)
        else:
            if drive is None:
                drive = DriveClient(s.secrets.google_sa_json)
            path = drive.download_file(v["drive_id"], Path(f"/tmp/{v['key']}.mp4"))
            log.info("downloaded %s (%d bytes) → uploading…", v["key"], path.stat().st_size)
            video_id = g.upload_video(acct, str(path), name=v["ad_name"])
            thumb = g.get_video_thumbnail(video_id)
        videos_cache[v["key"]] = {"video_id": video_id, "thumb": thumb}
        cid = make_single_creative(g, acct, s, v["ad_name"], video_id, thumb, v["message"], v["title"])
        creatives[v["key"]] = {"video_id": video_id, "creative_id": cid}
        shared.update({"videos": videos_cache, "creatives": creatives})
        SHARED_PATH.parent.mkdir(parents=True, exist_ok=True)
        SHARED_PATH.write_text(json.dumps(shared, ensure_ascii=False, indent=2))
        log.info("  ✔ %s → video %s · creative %s (single text/title)", v["key"], video_id, cid)

    # 2) build the campaign (reuse if state already has it) + wire the 2 ads ────────
    st_path = STATE_DIR / f"{STATE_KEY}.json"
    st = json.loads(st_path.read_text()) if st_path.exists() else {}
    spec = None
    if not st.get("adset_id"):                        # fresh campaign → need a cloned targeting spec
        all_adsets = pull_adsets(g)
        log.info("pulled %d ad sets across accounts", len(all_adsets))
        spec, src = clone_targeting(all_adsets, CLONE_SOURCE)
        if spec is None:
            raise SystemExit(f"!! no ad set like {CLONE_SOURCE!r} to clone — aborting (built nothing)")
        adv = int((spec.get("targeting_automation") or {}).get("advantage_audience", 1))
        log.info("── %s ← cloned from %r (age %s-%s · advantage_audience=%d · %d detail entries)",
                 ADSET_NAME, src, spec["age_min"], spec["age_max"], adv,
                 _richness({"flexible_spec": spec.get("flexible_spec", [])}))
    else:
        log.info("── reuse campaign %s / adset %s", st.get("campaign_id"), st.get("adset_id"))

    ent = build(g, s, units=[], captions={}, dry_run=False,
                label=f"{ADSET_NAME} | 1-1-2", state_key=STATE_KEY,
                adset_name=ADSET_NAME, targeting_override=spec)
    campaign_id, adset_id = ent["campaign_id"], ent["adset_id"]

    st = json.loads(st_path.read_text()) if st_path.exists() else {}
    built = set(st.get("built_ad_keys", []))
    ad_ids = list(st.get("ad_ids", []))
    for v in VIDEOS:
        if v["key"] in built:
            log.info("   skip ad %s (already built)", v["ad_name"])
            continue
        cid = creatives[v["key"]]["creative_id"]
        ad = g.create_ad(acct, name=v["ad_name"], adset_id=adset_id,
                         creative={"creative_id": cid}, status="PAUSED", conversion_domain=conv)
        ad_ids.append(ad["id"])
        built.add(v["key"])
        st.update({"campaign_id": campaign_id, "adset_id": adset_id,
                   "ad_ids": ad_ids, "built_ad_keys": sorted(built)})
        st_path.write_text(json.dumps(st, ensure_ascii=False, indent=2))
        log.info("   + ad %s ⟵ %s (%s)", ad["id"], v["ad_name"], cid)

    log.info("═" * 84)
    for k, c in creatives.items():
        log.info("creative %s: %s", k, c["creative_id"])
    log.info("campaign=%s  adset=%s  ads=%d", campaign_id, adset_id, len(ad_ids))
    final_summary(
        log, f"2nd 1-1-2 built PAUSED (CBO RM{DAILY_MYR}/day): Video 7 + Video 16 on a NEW "
             f"'{ADSET_NAME}' ad set (cloned from {CLONE_SOURCE!r}; Advantage+ audience ON). Separate "
             f"campaign from the 1-1-4. Review copy, set age 35+ / placements in Ads Manager, then activate.")


if __name__ == "__main__":
    main()
