"""Build the 8月 hook-edit test: 1 CBO + 1 ad set + 10 hook videos — PAUSED.

Campaign: [SG] 儿童长高方程式 | Hook Edits 8月 | 1-1-10

WHY THIS SHAPE
--------------
These 10 files are hook edits: the same proven video bodies with a NEW opening spliced on
(two of them — 吃饭很慢 hook 1 / hook 2 — are byte-for-byte the same length, so they are
demonstrably one body with two different hooks). The only thing being tested is the hook.

So the ad copy is held CONSTANT and only the HEADLINE moves. That is not laziness, it is what
the account's own data says: the best-performing video ad in the account
(MAR Video 1: 我不会买牛奶 — RM824.93 / 16 registrations / CPL 51.56 over 7d) runs the generic
evergreen body with a hook-specific headline (「🚫 别再让孩子喝牛奶了！！🥛🐂」). The body below is
that ad's live body, copied verbatim from creative 2497538107356049 — proven text, not new text.
Writing 10 fresh long-form bodies would confound the hook test and put 10 unproven copies live
at once.

Note the body already names five of these ten hooks in its qualifier list (吃饭很慢 / 鼻子敏感 /
睡眠障碍 / 性早熟 / 一年长不到 6cm), so each hook lands on a body that already speaks to it.

⚠️ The body says 马丁药师. The 8月 image/carousel batch says 马丁医师. Both are live in the
account today. This is deliberately left as-is: it is proven text and changing it would edit the
one variable we are trying to hold still. Say the word and it is a one-line change.

TARGETING
---------
Cloned from ad set 120256891851660093 — "Parents 3–17 + Engaged" under Parents 兴趣定向 | 1-1-4,
the best-converting ad set in the account (CPL 45.12 over 7d, 31.59 over 3d). Cloned by ID, NOT
by name, because two live ad sets share that name and a name match would pick either one.

AD NAMING
---------
Names are deliberately chosen so no existing close/scale core matches them as a substring —
scripts/apply_0813_actions.py matches ad names with cpa.ad_key containment, so an ad literally
named 我不会买牛奶 would be caught by that script's close list on a future run. Hence
"不买牛奶给孩子喝" rather than "我不会买牛奶", and "孩子 5-15 岁" rather than "孩子15岁以上".

Idempotent: each video's Meta video_id + creative_id is cached in state/entities_hookedits_shared.json
and the campaign entities in state/entities_hook_edits_8m.json, so a re-dispatch reuses instead of
duplicating. Downloaded files are deleted right after upload — 10 × ~135MB would otherwise sit on
the runner for the whole run.

Everything is created PAUSED.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from adbot.build_1_1_10 import build
from adbot.clients.drive import DriveClient
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_DIR = Path("state")
PREFIX = "[SG] 儿童长高方程式"
LABEL = "Hook Edits 8月 | 1-1-10"
ADSET_NAME = "Parents 3–17 + Engaged | Hook Edits"
STATE_KEY = "entities_hook_edits_8m"
SHARED_PATH = STATE_DIR / "entities_hookedits_shared.json"
DAILY_MYR = 150

DRIVE_FOLDER_ID = "1fMEzFUpxGaHZeNXsaqBBKtYHl97cwNKx"   # …/2026/AUGUST
CLONE_ADSET_ID = "120256891851660093"                   # Parents 3–17 + Engaged (1-1-4) — best CPL

DETAIL_KEYS = ["interests", "behaviors", "life_events", "family_statuses", "industries",
               "income", "education_statuses", "work_positions", "work_employers",
               "relationship_statuses", "user_adclusters", "moms"]

# ── proven evergreen body, verbatim from creative 2497538107356049 (the account's best video ad).
# No landing-page URL in the text — the link lives on the ad's CTA button only (standing rule).
BODY = """👨‍🏫 想让孩子健康长高？我可以帮助你！

尤其适合给：
🛑 孩子一年长不到 6cm 的家长
🛑 孩子吃饭吃很慢的家长
🛑 孩子有脊椎侧弯的家长
🛑 孩子有鼻子敏感的家长
🛑 性早熟孩子的家长
🛑 睡眠障碍的孩子的家长

大家好，我是马丁药师 🧑🏻‍⚕️🇹🇼
来自台湾的儿童长高专家，拥有超过 10 年中西医学经验
身后是一群热衷于帮助孩子长高的父母。💪✨

🌍 我已经帮助来自台湾、马来西亚、曼谷、澳洲、
加拿大和美国等国家的6000名孩子，每年实现健康增高6cm-8cm！
这些孩子中，有很多被传统医生认为难以再长高的，
但在我的指导下，他们实现了健康增高的梦想！🌈

💡 如果你：
📌 担心孩子因父母基因遗传，难以再长高
📌 尝试了很多网上的偏方、保健品、运动，孩子还是没长高
📌 看了很多中医、西医做调理，但都不见效

放心！作为一位父亲，我深知家长的心情。🫂
❌ 我绝对不会使用药物或不自然的方法，
❌ 也不会逼迫孩子吃各种难以下咽的食物，
❌ 更不会要求他们拼命运动。

相反，我会教你一些简单、健康、科学认证的方法，
让你能够关注孩子身心灵发展的同时，帮助他们健康增高！✨

✨ 如果你想知道我如何帮助这些孩子实现增高目标，欢迎参加我的线上课程！

在这堂课中，你将获得：
✅ 健康、简单的方法，让孩子轻松长高
✅ 无需额外花费时间和精力，让增高变得简单
✅ 关注孩子的全面发展，兼顾身心灵健康

🎉 抓住这个机会，让孩子拥有一个不后悔的童年！

点击以下Button，让我帮助你的孩子拥有一个不后悔的童年！我们课程见！👋


#儿童长高方程式 #儿童长高 #长高 #马丁药师 #注意力 #成長 #學習力 #馬丁藥師 #身高 #孩子 #馬丁藥師 #霸凌 #頂嘴 #家庭教養 #家庭教育 #親子關係"""

# key · Drive id · ad name · headline (the ONLY thing that varies — it restates the video's hook)
HOOKS: List[Dict[str, str]] = [
    {"key": "he01_sport",   "drive_id": "1uQ1rjia4dLvoPaLas9tbbPwHE5LXMGTp",
     "ad_name": "Hook Edit 01：運動就能長高？！No！",
     "title": "🏀 多运动就会长高？！错了！"},
    {"key": "he02_hate",    "drive_id": "14zhgVDAF4KFamdjieooGVT97-FDnBG-l",
     "ad_name": "Hook Edit 02：我最討厭聽到",
     "title": "😤 我最讨厌听到：「再等等看啦」"},
    {"key": "he03_gh",      "drive_id": "1imskPZlvx-7Ubf40jpc_3m9zn7pnXyaP",
     "ad_name": "Hook Edit 03：生长激素",
     "title": "🌙 生长激素，都在这几个小时分泌"},
    {"key": "he04_nomilk",  "drive_id": "1OXGC59aMkjefu36e11RO6fdYBYaqaCQY",
     "ad_name": "Hook Edit 04：不买牛奶给孩子喝",
     "title": "🥛 我不会买牛奶给我孩子喝"},
    {"key": "he05_age515",  "drive_id": "1kAkmBNfLnol2ocXVJXddV8vxNL5riCWC",
     "ad_name": "Hook Edit 05：孩子 5-15 岁",
     "title": "👋 孩子 5-15 岁的爸妈，请看完"},
    {"key": "he06_acne",    "drive_id": "1dzTlkur8bkzgt4lAoDX5cxnJYaEwJrFV",
     "ad_name": "Hook Edit 06：喝牛奶长痘痘",
     "title": "🥛 还在喝牛奶、长痘痘？"},
    {"key": "he07_slow_b",  "drive_id": "1vLjCZT4U-p6Zy1Q6GxGSvJQKonX76MeR",
     "ad_name": "Hook Edit 07：吃饭很慢 B",
     "title": "⏱️ 吃饭很慢的孩子，多半卡在这里"},
    {"key": "he08_sinus",   "drive_id": "1EV_7mNqFhUptFCrkRiPkX2Uh_pkSs7wv",
     "ad_name": "Hook Edit 08：鼻子敏感 Sinus",
     "title": "🤧 鼻子塞的孩子，为什么长不高？"},
    {"key": "he09_slow_a",  "drive_id": "1R8_3nxHWyJw6NKXHgt81a2c-KSPOUzX6",
     "ad_name": "Hook Edit 09：吃饭很慢 A",
     "title": "🍚 一顿饭吃一小时？先别骂他"},
    {"key": "he10_sleep",   "drive_id": "10qvimR_-JCZ6y03NudfwcstB7DUjjiAA",
     "ad_name": "Hook Edit 10：睡眠品质差",
     "title": "😴 睡满 8 小时，还是长不高？"},
]


def clone_from_adset(g, adset_id: str, s) -> Dict[str, Any]:
    """Clone interest/behaviour targeting from ONE specific ad set, forced to this market's geo.

    By ID rather than by name: two live ad sets are both called "Parents 3–17 + Engaged", and a
    name lookup would silently pick whichever happened to look richer.
    """
    src = g._request("GET", adset_id, params={"fields": "name,targeting"})
    t = src.get("targeting") or {}
    adv_raw = (t.get("targeting_automation") or {}).get("advantage_audience")
    adv = 1 if adv_raw is None else int(adv_raw)
    age_min, age_max = int(t.get("age_min") or 25), int(t.get("age_max") or 65)
    if adv == 1 and age_min > 25:      # Meta rejects a higher hard floor when Advantage+ is on
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
    return {"spec": spec, "name": src.get("name")}


def make_creative(g, acct, s, name: str, video_id: str, thumb, title: str) -> str:
    cta = {"type": s.meta.call_to_action, "value": {"link": s.meta.lead_destination.link_url}}
    vdata = {"video_id": video_id, "title": title, "message": BODY, "call_to_action": cta}
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

    drive = DriveClient(s.secrets.google_sa_json)

    # Listing first does double duty: it proves the service account can actually see the folder
    # (a permissions failure surfaces here, before anything is created), and it tells us if the
    # operator has since dropped more hooks in that this script does not know about.
    listed = [f for f in drive.list_children(DRIVE_FOLDER_ID) if not drive.is_folder(f)]
    known = {h["drive_id"] for h in HOOKS}
    log.info("Drive AUGUST folder: %d file(s); this script knows %d", len(listed), len(HOOKS))
    for f in listed:
        mark = "·" if f["id"] in known else "‼ NEW — not in HOOKS, not built"
        log.info("   %s %-44s %s", mark, (f.get("name") or "")[:44], f["id"])
    missing = known - {f["id"] for f in listed}
    if missing:
        raise SystemExit(f"!! {len(missing)} hardcoded Drive id(s) not in the folder: {sorted(missing)}")

    # 1) upload each video ONCE, build its creative ──────────────────────────────────
    shared = json.loads(SHARED_PATH.read_text()) if SHARED_PATH.exists() else {}
    videos_cache: Dict[str, Any] = shared.get("videos", {})
    creatives: Dict[str, Any] = shared.get("creatives", {})
    for h in HOOKS:
        if h["key"] in creatives:
            log.info("reuse %s → creative %s (cached)", h["key"], creatives[h["key"]]["creative_id"])
            continue
        vc = videos_cache.get(h["key"])
        if vc and vc.get("video_id"):
            video_id, thumb = vc["video_id"], vc.get("thumb") or g.get_video_thumbnail(vc["video_id"])
            log.info("reuse uploaded %s → video %s", h["key"], video_id)
        else:
            path = Path(f"/tmp/{h['key']}.mov")
            drive.download_file(h["drive_id"], path)
            mb = path.stat().st_size / 1_048_576
            log.info("downloaded %s (%.1f MB) → uploading…", h["key"], mb)
            video_id = g.upload_video(acct, str(path), name=h["ad_name"])
            thumb = g.get_video_thumbnail(video_id)
            path.unlink(missing_ok=True)          # 10 × ~135MB would otherwise pile up on the runner
        videos_cache[h["key"]] = {"video_id": video_id, "thumb": thumb}
        cid = make_creative(g, acct, s, h["ad_name"], video_id, thumb, h["title"])
        creatives[h["key"]] = {"video_id": video_id, "creative_id": cid}
        shared.update({"videos": videos_cache, "creatives": creatives})
        SHARED_PATH.parent.mkdir(parents=True, exist_ok=True)
        SHARED_PATH.write_text(json.dumps(shared, ensure_ascii=False, indent=2))
        log.info("  ✔ %s → video %s · creative %s", h["key"], video_id, cid)

    # 2) campaign + ad set (reuse if state already has them) ─────────────────────────
    st_path = STATE_DIR / f"{STATE_KEY}.json"
    st = json.loads(st_path.read_text()) if st_path.exists() else {}
    spec = None
    if not st.get("adset_id"):
        cloned = clone_from_adset(g, CLONE_ADSET_ID, s)
        spec = cloned["spec"]
        detail = sum(len(grp.get(k) or []) for grp in (spec.get("flexible_spec") or [])
                     for k in DETAIL_KEYS)
        log.info("── targeting ← ad set %s %r (age %s-%s · adv=%s · %d detail entries)",
                 CLONE_ADSET_ID, cloned["name"], spec["age_min"], spec["age_max"],
                 (spec.get("targeting_automation") or {}).get("advantage_audience"), detail)
    else:
        log.info("── reuse campaign %s / adset %s", st.get("campaign_id"), st.get("adset_id"))

    ent = build(g, s, units=[], captions={}, dry_run=False, label=LABEL,
                state_key=STATE_KEY, adset_name=ADSET_NAME, targeting_override=spec)
    campaign_id, adset_id = ent["campaign_id"], ent["adset_id"]

    # 3) one ad per hook ─────────────────────────────────────────────────────────────
    st = json.loads(st_path.read_text()) if st_path.exists() else {}
    built = set(st.get("built_ad_keys", []))
    ad_ids: List[str] = list(st.get("ad_ids", []))
    for h in HOOKS:
        if h["key"] in built:
            log.info("   skip ad %s (already built)", h["ad_name"])
            continue
        ad = g.create_ad(acct, name=h["ad_name"], adset_id=adset_id,
                         creative={"creative_id": creatives[h["key"]]["creative_id"]},
                         status="PAUSED", conversion_domain=conv)
        ad_ids.append(ad["id"])
        built.add(h["key"])
        st.update({"campaign_id": campaign_id, "adset_id": adset_id,
                   "ad_ids": ad_ids, "built_ad_keys": sorted(built)})
        st_path.write_text(json.dumps(st, ensure_ascii=False, indent=2))
        log.info("   + ad %s ⟵ %s", ad["id"], h["ad_name"])

    log.info("═" * 88)
    log.info("campaign=%s  adset=%s  ads=%d", campaign_id, adset_id, len(ad_ids))
    for h in HOOKS:
        log.info("   %-28s %s", h["ad_name"][:28], h["title"])
    final_summary(
        log, f"Hook-edit test built PAUSED: {len(ad_ids)} hook videos in ONE ad set "
             f"(CBO RM{DAILY_MYR}/day), targeting cloned from the account's best-converting ad set "
             f"(Parents 3–17 + Engaged, CPL 45). Body is held constant — the proven evergreen copy "
             f"from the account's top video ad — so the HOOK is the only variable. Review previews, "
             f"then activate; CBO will concentrate on the 2-3 hooks that hold attention.")


if __name__ == "__main__":
    main()
