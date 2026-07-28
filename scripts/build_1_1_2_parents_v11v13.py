"""Build ONE 1-1-4 creative-test campaign on Parents interest targeting — PAUSED.

Campaign: [SG] 儿童长高方程式 | Parents 兴趣定向 | 1-1-4
  = 1 CBO (RM100/day) + 1 ad set (targeting cloned LIVE from the winning
    "Advantage+ Parents + Engaged" ad set, forced to SG) + 4 NEW video ads
    competing in that ONE ad set:
      · Video 11：孩子來MC了            (初潮 = 长高倒计时 urgency angle)
      · Video 13：三年前他長了10公分     (testimonial / proof angle)
      · Video 14：身高停在小學           (青春期是"机会"不是"保证" · 3 条件角度)
      · Video 15：不到160慌了           (男孩15岁不到160 · 慌了乱补 = 治标不治本角度)

Idempotent: each re-dispatch reuses the cached earlier creatives + the existing campaign/ad
set from state, and only uploads + attaches the newly-added video ad (this run adds Video 15,
turning the 1-1-3 into a 1-1-4). The campaign is renamed to "| 1-1-4" to match.

Single text + single headline per ad (Meta treats multi-option text/headline as a
"Dynamic Creative", which only lives in a dynamic ad set holding exactly ONE ad — mutually
exclusive with the operator's 1-1-2). So each ad uses its strongest single caption + headline.

Idempotent: videos upload to Meta ONCE (cached by video_id in state/entities_v11v13_shared.json);
the campaign's entities live in state/entities_1_1_2_parents_v11v13.json, so a re-dispatch
never duplicates. Everything builds PAUSED (config activate_after_build:false) — activate in
Ads Manager after review.
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
STATE_KEY = "entities_1_1_2_parents_v11v13"
SHARED_PATH = STATE_DIR / "entities_v11v13_shared.json"

SG_GEO = {"countries": ["SG"]}
SG_EXCL = [{"id": "120226672882380093"},          # 15 days complete registration (已注册)
           {"id": "120246547080720093"}]          # 马丁 1997 Paid Student (已购买)
DETAIL_KEYS = ["interests", "behaviors", "life_events", "family_statuses", "industries",
               "income", "education_statuses", "work_positions", "work_employers",
               "relationship_statuses", "user_adclusters", "moms"]

# ── ad copy (Simplified — SG audience-facing). One primary text + one headline per ad. ──
VIDEO11_MAIN = """🩸 女儿第一次来月经那天，你是松了一口气——
还是心里突然一紧？

很多妈妈的第一反应是：
🗣️「终于来了，代表她发育正常。」
🗣️「长大了，是好事啊。」
🗣️「该长的还会再长啦。」

但很少有人告诉你一件事👇

❗ 月经一来，孩子的长高，就进入了倒计时。

女孩子初潮之后，
身高通常只剩最后一段可以冲刺的空间，
而这段黄金窗口，往往只有短短一两年。

⏳ 骨龄一旦追上年龄，生长板慢慢闭合，
之后再怎么补、再怎么努力，
能追回来的空间都非常有限。

最可惜的是——
很多妈妈是等到女儿一整年都没再长，
才开始着急去找方法。💔
可那时候，最好的时机往往已经过了。

但也有一个好消息：
👉 月经来了，不等于不能再长高。
只是从这一刻起，你要非常清楚——
孩子现在到底还剩多少空间，又该怎么把握。

我是马丁药师（台湾执照药师 · 中西医结合背景）。
这十几年，我接触过来自
🇹🇼🇲🇾🇸🇬🇭🇰🇺🇸🇨🇦 六个国家、
近 7,000 个正在长高路上的家庭。

我发现，青春期的孩子长不长得起来，
关键往往不是「还有没有机会」，
而是爸妈有没有看懂这几件事：

😴 睡眠品质好不好
🥣 吸收够不够、脾胃强不强
🌿 体质有没有在偷偷消耗（过敏、易生病）
⏳ 生长窗口还剩多少、该用什么节奏去追

这星期，我会开一场免费线上公开课——
📘《儿童长高方程式》

课堂上你会了解：
📍 女孩初潮后，到底还有多少长高空间、怎么判断
📍 青春期这段窗口，饮食与体质该怎么调
📍 为什么同样的方法，别人有效、你孩子却没反应

如果你的女儿已经来了月经，
请别再抱着「应该还会长」的心态一等再等。
✅ 先搞清楚还剩多少时间，再决定怎么帮她。

⏰ 名额有限，坐满即止。

👇 点击下方链接，立即免费报名《儿童长高方程式》

青春期只有一次，
别让「以为还有时间」，赔掉她最后的长高机会。"""

VIDEO11_TITLE = "女儿来月经后，还能再长高吗？｜免费公开课"

VIDEO13_MAIN = """📈 三年前，有个孩子长高了 10 公分。

不是靠运气，
不是狂灌补品，
也不是突然抽高的遗传奇迹。

很多爸妈看到别人家孩子长高，
第一个念头都是：
🗣️「人家遗传好啦。」
🗣️「运气好，刚好会长。」
🗣️「我们家基因就这样，没办法。」

但如果长高真的只看运气和遗传，
那为什么——
👉 同样的年纪、同样喝牛奶补钙，
有些孩子一年长 8 公分，有些却卡着几乎不动？

差别，从来不在运气。
而在于爸妈有没有找对方向。

那个长了 10 公分的孩子，
一开始也曾经卡了很久：
😴 睡不好、
🥣 吃了不吸收、
🌿 三天两头过敏生病、
🦵 筋膜紧绷、动不动喊累。

真正改变的，不是多吃了什么补品，
而是这些「拖住成长的卡点」被一个一个解开。

我是马丁药师（台湾执照药师 · 中西医结合背景）。
这十几年，我陪着近 7,000 个家庭，
帮孩子用最健康的方式，
先把体质调理好，再让身高一年年稳稳追上来。

我常跟家长说一句话：
❗ 长高不是碰运气，是可以被复制的。
前提是——你要先看懂孩子卡在哪里。

这星期，我会开一场免费线上公开课——
📘《儿童长高方程式》

课堂上你会了解：
📍 别人家孩子长得好，背后到底做对了什么
📍 如何找出正在拖住你孩子成长的「卡点」
📍 不同体质的孩子，饮食与调理方向差在哪

孩子不是长不高，
很多时候只是那几个卡点，一直没有人帮他解开。
✅ 先找到原因，再谈追高。

⏰ 名额有限，坐满即止。

👇 点击下方链接，立即免费报名《儿童长高方程式》

三年前他长了 10 公分——
你孩子的那三年，也不该只是等待。"""

VIDEO13_TITLE = "三年长高10公分，不是运气｜免费公开课"

VIDEO14_MAIN = """⚠️ 孩子已经上中学了，
身高却还停在小学的水平——你要注意了。

别再安慰自己「等青春期一到，他自然就会长」。

这些年在东南亚，我见过太多这样的孩子：
🗣️ 小学毕业 140 几公分，想说「还好，等发育就追上了」。

结果上了中学，一年、两年、三年，
身高几乎没动。📉
同学一个个在飙高，
你的孩子站在旁边，还是小学时候的样子。

你有没有想过，为什么？

👉 很多家长以为，青春期一到，孩子自然会长高。
但事实是——
青春期是长高的「机会」，不是「保证」。

孩子是进入青春期了，
但身体如果不具备长高的条件，
机会来了，也一样抓不住。

什么叫「条件」？三个关键👇

🥣 脾胃功能正常——吃进去的营养，身体真的吸收得到。
😴 睡眠品质好——进入深睡，生长激素才会大量分泌。
🌿 体质没有失衡——东南亚这种气候，孩子长期喝冰饮、吃奶制品，
　　体质很容易偏湿偏热，这会直接拖慢骨骼的生长速度。

这三个条件，缺任何一个，
青春期的长高机会，就这样被浪费掉了。💔

我是马丁药师（台湾执照药师 · 中西医结合背景）。
这十几年，我陪着近 7,000 个家庭，
先帮孩子把脾胃、睡眠、体质调理好，
再用最健康的方式，一年年把身高追上来。

这星期，我会开一场免费线上公开课——
📘《儿童长高方程式》

课堂上你会了解：
📍 为什么孩子进了青春期，身高却还是不动
📍 脾胃、睡眠、体质这三个「长高条件」，怎么判断哪个卡住了
📍 东南亚气候下，孩子的饮食与体质该怎么调

如果你的孩子已经上中学，身高却还追不上同学——
✅ 别再等了，先搞懂他到底卡在哪。

⏰ 名额有限，坐满即止。

👇 点击下方链接，立即免费报名《儿童长高方程式》

青春期的窗口就那几年，
机会来了，得先让孩子的身体接得住。"""

VIDEO14_TITLE = "孩子上中学，身高还停在小学？｜免费公开课"

VIDEO15_MAIN = """⚠️ 男孩子 15 岁了，身高还不到 160——
你是不是已经开始慌了？

慌，是正常的。
但我要告诉你——
比慌更危险的是：慌了之后，乱做。

🗣️ 有些家长一慌，就开始疯狂买保健品。
今天看到广告说增高保健品有效，买；
明天听朋友说花生根汤有效，煲。
还有些家长，甚至去咨询生长激素注射——
一个月几千块，打了半年，
经济负担太重，又停了。

结果呢？
💔 钱花了，时间也花了，
孩子的身高，还是不到 160。

你知道问题出在哪吗？
👉 你一直在「治标」，从来没有「治本」。

15 岁、身高不到 160，
这不是「缺营养」那么简单的事。
背后一定有一个根本原因，在卡住孩子的生长：

🥣 也许他的脾胃从小就弱——
　　吃了很多好东西，身体却吸收不了，等于白吃。
😴 也许他的睡眠品质长期很差——
　　打游戏到半夜、课业压力大睡不着，
　　生长激素分泌的黄金时段，被完全浪费。
🌿 也许他的体质，在东南亚这种环境下严重失衡——
　　你不知道，所以只能不停地「加东西」上去，越加越乱。

你要做的，不是「加更多」，
而是——先找到那个根本原因。

我是马丁药师（台湾执照药师 · 中西医结合背景）。
这十几年，我陪着近 7,000 个家庭，
不是叫他们拼命加补品，
而是先找出卡住孩子生长的「根」，再对症调理。

这星期，我会开一场免费线上公开课——
📘《儿童长高方程式》

课堂上你会了解：
📍 为什么保健品、汤方一直换，孩子却还是不长
📍 脾胃、睡眠、体质——哪一个才是你孩子真正的「根」
📍 15 岁以上的孩子，还有没有机会、又该怎么抓

家里有 15 岁以上孩子的爸妈，
✅ 这堂课你一定要看完——别再用「加更多」赌他最后的身高。

⏰ 名额有限，坐满即止。

👇 点击下方链接，立即免费报名《儿童长高方程式》

慌，没有用；乱做，更危险。
先找到根本原因，才是真正帮到孩子。"""

VIDEO15_TITLE = "男孩15岁还不到160，别再乱补了｜免费公开课"

VIDEOS = [
    {"key": "video11", "drive_id": "17EC5vCjPQBbs7tPIbPg8RKfXsGUkbnZx",
     "ad_name": "Video 11：孩子來MC了", "message": VIDEO11_MAIN, "title": VIDEO11_TITLE},
    {"key": "video13", "drive_id": "1VCbh8D55mDlMz78D1l9CQvusAp1gLNCC",
     "ad_name": "Video 13：三年前他長了10公分", "message": VIDEO13_MAIN, "title": VIDEO13_TITLE},
    {"key": "video14", "drive_id": "16FJbD3oCzmKLCosjRZ760r8qOpq_2Xzu",
     "ad_name": "Video 14：身高停在小學", "message": VIDEO14_MAIN, "title": VIDEO14_TITLE},
    {"key": "video15", "drive_id": "15dxn6BGkWblgZ1OtibXqFuRIeD3hoHaa",
     "ad_name": "Video 15：不到160慌了", "message": VIDEO15_MAIN, "title": VIDEO15_TITLE},
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
                label=f"{ADSET_NAME} | 1-1-4", state_key=STATE_KEY,
                adset_name=ADSET_NAME, targeting_override=spec)
    campaign_id, adset_id = ent["campaign_id"], ent["adset_id"]

    # reused campaigns keep their original name (build never renames), so bump the live
    # campaign to "| 1-1-4" now that a 4th ad joins. Setting the same name is a harmless no-op.
    new_name = s.naming.campaign_name(f"{ADSET_NAME} | 1-1-4")
    g._request("POST", campaign_id, data={"name": new_name})
    log.info("campaign %s name → %s", campaign_id, new_name)

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
        log, f"1-1-4 built PAUSED (CBO RM{DAILY_MYR}/day): Video 11 + 13 + 14 + 15 on "
             f"'{ADSET_NAME}' (cloned from {CLONE_SOURCE!r}; Advantage+ audience ON per operator). "
             f"Review Video 15 copy, set age 35+ / placements in Ads Manager, then activate.")


if __name__ == "__main__":
    main()
