"""Build ONE 1-1-1 creative-test campaign on Interest: Family and Relationships — PAUSED.

Campaign: [SG] 儿童长高方程式 | Family & Relationships | 1-1-1
  = 1 CBO (RM100/day) + 1 ad set (targeting cloned LIVE from the SG "Interest: Family and
    Relationships" ad set, forced to SG) + 1 NEW video ad:
      · Video 12：15歲以上試了五六種方法沒長高
        (800-家长数据揭露 + 178 个 15 岁以上孩子全部停长 → "一直在加东西，方向错了" reframe)

Copy is Simplified (SG audience-facing) and uses 马丁医师 per the operator's standing rebrand
(the raw video script still says 药师 — the caption does NOT). Single text + single headline
(Meta multi-option text = Dynamic Creative, incompatible with the operator's 1-1-N pattern).

Idempotent: the video uploads to Meta ONCE (cached by video_id in state/entities_v12_shared.json);
the campaign's entities live in state/entities_1_1_1_fam_v12.json, so a re-dispatch never
duplicates. Builds PAUSED (config activate_after_build:false) — activate in Ads Manager after
review (RM100/day).
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
CLONE_SOURCE = "Interest: Family and Relationships"
ADSET_NAME = "Interest: Family and Relationships"
STATE_KEY = "entities_1_1_1_fam_v12"
SHARED_PATH = STATE_DIR / "entities_v12_shared.json"

SG_GEO = {"countries": ["SG"]}
SG_EXCL = [{"id": "120226672882380093"},          # 15 days complete registration (已注册)
           {"id": "120246547080720093"}]          # 马丁 1997 Paid Student (已购买)
DETAIL_KEYS = ["interests", "behaviors", "life_events", "family_statuses", "industries",
               "income", "education_statuses", "work_positions", "work_employers",
               "relationship_statuses", "user_adclusters", "moms"]

# ── ad copy (Simplified — SG audience-facing; 马丁医师 per standing rebrand). ──
VIDEO12_MAIN = """📊 我调查了超过 800 位家长，
发现一件很可怕的事——

15 岁以上的孩子，试了五六种方法，
几乎全部，都没有再长高。

这 800 位家长里，有 178 位的孩子，已经 15 岁以上。
他们全都有一个共同点👇

身高，停住了。
半年没长、一年没长，
有的甚至两年，都没再动过。

你猜他们都试过什么？
🍼 保健品、花生根汤、钙片、跳绳、打篮球、看中医——
有些家长，花了超过一万块。

效果呢？
📉 几乎所有人的答案，都是同一个字：没用。

为什么？
👉 因为这些方法，都在做同一件事——
不停地往孩子身上「加东西」。
加保健品、加运动、加汤药……
却没有一个人停下来问：
为什么加了这么多，还是没长高？

真正的问题，从来不是「加得不够多」，
而是「方向，一开始就错了」。

你的孩子，可能是——
🥣 脾胃太弱，吃再多也吸收不了，等于白吃。
😴 睡眠品质差，生长激素根本没在该分泌的时候分泌。
🌿 体质在这种湿热环境下长期失衡，骨骼发育被悄悄卡住。

❗ 根本问题不解决，买再多保健品，都是白费。

我是马丁医师（台湾执照医师 · 中西医结合背景）。
这十几年，我陪着来自 🇹🇼🇲🇾🇸🇬🇭🇰🇺🇸🇨🇦 六个国家、
近 7,000 个家庭。

👨‍⚕️ 我做的第一件事，从来不是叫你买东西，
而是先帮你找到——孩子长不高的根本体质原因。
通过舌诊和体质辨识，精准判断问题到底出在哪，
然后才对症调理。不是乱补，是精准。

这也是为什么，很多孩子在我这里，
之前什么都试过、都没用，
方法对了之后，身高才终于开始有了变化。

这星期，我会开一场免费线上公开课——
📘《儿童长高方程式》

课堂上你会了解：
📍 为什么 15 岁以上的孩子，换了五六种方法还是不长
📍 脾胃、睡眠、体质——哪一个才是卡住你孩子的「根」
📍 15 岁以上的孩子，到底还剩多少空间、又该怎么抓

家里有 15 岁以上孩子的爸妈，
✅ 这堂课你一定要看完——别再用「加更多」，赌他最后的长高机会。

⏰ 名额有限，坐满即止。

👇 点击下方链接，立即免费报名《儿童长高方程式》

15 岁以上不是没机会，
只是你要先搞对方向——
再多的「加法」，都不如找对那个「根」。"""

VIDEO12_TITLE = "15岁以上还能长高吗？先找对「根」｜免费公开课"

VIDEOS = [
    {"key": "video12", "drive_id": "1VyXHppVN8AEcCBpniIWLup9is0s7mffX",
     "ad_name": "Video 12：15歲以上試了五六種方法沒長高",
     "message": VIDEO12_MAIN, "title": VIDEO12_TITLE},
]


def _richness(t: dict) -> int:
    if not isinstance(t, dict):
        return 0
    cnt = lambda spec: sum(len(spec.get(k) or []) for k in DETAIL_KEYS)
    return cnt(t) + sum(cnt(grp) for grp in (t.get("flexible_spec") or []))


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

    # 1) upload (or reuse cached) video + build single-option creative ───────────────
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

    # 2) build the campaign (reuse if state already has it) + wire the 1 ad ──────────
    st_path = STATE_DIR / f"{STATE_KEY}.json"
    st = json.loads(st_path.read_text()) if st_path.exists() else {}
    spec = None
    if not st.get("adset_id"):                        # fresh campaign → need a cloned targeting spec
        all_adsets = g._get_all(f"{acct}/adsets", {"fields": "name,effective_status,targeting", "limit": 500})
        log.info("pulled %d SG ad sets", len(all_adsets))
        spec, src = clone_targeting(all_adsets, CLONE_SOURCE)
        if spec is None:
            raise SystemExit(f"!! no SG ad set like {CLONE_SOURCE!r} to clone — aborting (built nothing)")
        adv = int((spec.get("targeting_automation") or {}).get("advantage_audience", 1))
        log.info("── %s ← cloned from %r (age %s-%s · advantage_audience=%d · %d detail entries)",
                 ADSET_NAME, src, spec["age_min"], spec["age_max"], adv,
                 _richness({"flexible_spec": spec.get("flexible_spec", [])}))
    else:
        log.info("── reuse campaign %s / adset %s", st.get("campaign_id"), st.get("adset_id"))

    ent = build(g, s, units=[], captions={}, dry_run=False,
                label=f"{ADSET_NAME} | 1-1-1", state_key=STATE_KEY,
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
        log, f"1-1-1 built PAUSED (CBO RM{DAILY_MYR}/day): Video 12 on '{ADSET_NAME}' "
             f"(cloned from {CLONE_SOURCE!r}; Advantage+ audience per source). Review copy + "
             f"placements in Ads Manager, then activate.")


if __name__ == "__main__":
    main()
