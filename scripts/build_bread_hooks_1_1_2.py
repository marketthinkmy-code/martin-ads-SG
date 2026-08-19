"""Build the 麵包早餐 hook test: 1 CBO + 1 ad set + 2 hook videos, SCHEDULED for 20 Aug 00:00.

Campaign: [SG] 儿童长高方程式 | Bread Hooks 8月 | 1-1-2

WHAT IS BEING TESTED
--------------------
Both files are the same body — Video 8 麵包牛奶, spliced in from 0:15 — carrying two different
spoken openings. So the hook is the only variable, and the ad copy is held constant to keep it
that way. The body below is the account's proven evergreen text, copied verbatim from creative
2497538107356049 (MAR Video 1, the best-performing video ad in the account); only the HEADLINE is
written per hook. Writing two fresh bodies would confound the very comparison this campaign
exists to make.

The body's qualifier list already names 吃饭很慢 and 消化 concerns, which is what both hooks open
on, so each hook lands on a body that continues its own argument.

WHICH FILE IS WHICH HOOK
------------------------
Not the order the links were sent in. The Drive filenames carry the answer and they run opposite
to the link order:

    1MNqgJkqmoDqKaf-H1zY5sErGCnsUhEZo   Martin July SGMY H1#.mp4   → Hook 1  早餐就錯了！
    1SH7_jgusVmerSTB6G5GH9MTTDQEVU1JW   Martin July SGMY H2#.mp4   → Hook 2  你還在把麵包當早餐？

Pairing by link order would have put each hook's headline on the other hook's video — invisible
in the API, and it would have quietly inverted whatever the test concluded. The script re-checks
each file's title on download and refuses to continue if the H1/H2 marker disagrees with the hook
it is about to be paired with.

SCHEDULE
--------
start_time is 2026-08-20T00:00:00+08:00 and the entities are ACTIVATED, because a schedule that
still needs a human to press play at midnight is not a schedule. Meta will not deliver a single
impression before that timestamp; the campaign simply begins on its own. Until then it can be
paused in Ads Manager like anything else.

TARGETING
---------
Cloned from ad set 120256891851660093 — "Parents 3–17 + Engaged", the account's best-converting
ad set. Cloned by ID rather than by name, because two live ad sets share that name and a name
match would pick either one.

AD NAMING
---------
scripts/apply_0813_actions.py matches ad names by cpa.ad_key containment, so a name that contains
an existing close/scale core gets swept up by a later run of that script. 早餐 appears in the live
ad 准备早餐面包, so neither name here may contain that sequence — hence 早餐就錯了 and 麵包當早餐,
neither of which contains 准备早餐面包 or 早餐面包.

Idempotent: video ids, creative ids and entity ids persist to state/, so a re-dispatch never
re-uploads a 200MB file or duplicates the campaign.
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
STATE_KEY = "entities_bread_hooks_1_1_2"
SHARED_PATH = STATE_DIR / "entities_bread_hooks_shared.json"
PREFIX = "[SG] 儿童长高方程式"
LABEL = "Bread Hooks 8月 | 1-1-2"
ADSET_NAME = "Parents 3–17 + Engaged | Bread Hooks"
DAILY_MYR = 100                       # matches the account's other Parents 兴趣定向 1-1-2 builds
START_TIME = "2026-08-20T00:00:00+08:00"

CLONE_ADSET_ID = "120256891851660093"          # Parents 3–17 + Engaged — best CPL in the account
DRIVE_FOLDER_ID = "1jwTDSNaG5pgnYChflIIA72euphFUcK-U"   # the folder both files live in

DETAIL_KEYS = ["interests", "behaviors", "life_events", "family_statuses", "industries",
               "income", "education_statuses", "work_positions", "work_employers",
               "relationship_statuses", "user_adclusters", "moms"]

HOOKS: List[Dict[str, str]] = [
    {"key": "bh1", "drive_id": "1MNqgJkqmoDqKaf-H1zY5sErGCnsUhEZo", "marker": "H1",
     "ad_name": "Bread Hook 1：早餐就錯了",
     "title": "🍞 早餐就错了！难怪孩子长不高"},
    {"key": "bh2", "drive_id": "1SH7_jgusVmerSTB6G5GH9MTTDQEVU1JW", "marker": "H2",
     "ad_name": "Bread Hook 2：麵包當早餐",
     "title": "🥛 面包配牛奶，正在拖住孩子的身高"},
]

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
    fields: Dict[str, Any] = {"name": name, "object_story_spec": story}
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

    # Filenames come from listing the parent folder — DriveClient has no per-file metadata call,
    # and a check that quietly skips itself when it cannot find a name is worse than no check.
    # If the listing fails, that is fatal: the whole point is that the two files are
    # indistinguishable apart from their names.
    names: Dict[str, str] = {f["id"]: (f.get("name") or "")
                             for f in drive.list_children(DRIVE_FOLDER_ID)}
    for h in HOOKS:
        title = names.get(h["drive_id"])
        if not title:
            raise SystemExit(
                f"!! Drive id {h['drive_id']} ({h['key']}) is not in folder {DRIVE_FOLDER_ID} — "
                f"cannot confirm which hook this video is, so nothing is built.")
        # The two files differ only by an H1/H2 marker, and the links were sent in the opposite
        # order to that marker. Pairing the wrong video with the wrong headline is invisible
        # afterwards and would invert whatever this test concludes.
        if h["marker"] not in title:
            raise SystemExit(
                f"!! {h['key']} expects a {h['marker']} file but Drive id {h['drive_id']} is "
                f"named {title!r} — refusing to pair a hook with the wrong video.")
        log.info("── %-4s %-6s %-34s %s", h["key"], h["marker"], title[:34], h["drive_id"])

    # 1) upload each video ONCE, build its creative ──────────────────────────────────
    shared: Dict[str, Any] = json.loads(SHARED_PATH.read_text()) if SHARED_PATH.exists() else {}
    videos: Dict[str, Any] = shared.get("videos", {})
    creatives: Dict[str, Any] = shared.get("creatives", {})
    for h in HOOKS:
        if h["key"] in creatives:
            log.info("reuse %s → creative %s (cached)", h["key"], creatives[h["key"]]["creative_id"])
            continue
        vc = videos.get(h["key"])
        if vc and vc.get("video_id"):
            video_id = vc["video_id"]
            thumb = vc.get("thumb") or g.get_video_thumbnail(video_id)
            log.info("reuse uploaded %s → video %s", h["key"], video_id)
        else:
            path = Path(f"/tmp/{h['key']}.mp4")
            drive.download_file(h["drive_id"], path)
            log.info("   downloaded %.1f MB → uploading…", path.stat().st_size / 1_048_576)
            video_id = g.upload_video(acct, str(path), name=h["ad_name"])
            thumb = g.get_video_thumbnail(video_id)
            path.unlink(missing_ok=True)          # 2 x ~200MB would otherwise sit on the runner
        videos[h["key"]] = {"video_id": video_id, "thumb": thumb}
        cid = make_creative(g, acct, s, h["ad_name"], video_id, thumb, h["title"])
        creatives[h["key"]] = {"video_id": video_id, "creative_id": cid}
        shared.update({"videos": videos, "creatives": creatives})
        SHARED_PATH.parent.mkdir(parents=True, exist_ok=True)
        SHARED_PATH.write_text(json.dumps(shared, ensure_ascii=False, indent=2))
        log.info("   ✔ %s → video %s · creative %s", h["key"], video_id, cid)

    # 2) campaign + ad set ───────────────────────────────────────────────────────────
    st_path = STATE_DIR / f"{STATE_KEY}.json"
    st: Dict[str, Any] = json.loads(st_path.read_text()) if st_path.exists() else {}
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
                state_key=STATE_KEY, adset_name=ADSET_NAME, targeting_override=spec,
                start_time=START_TIME)
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

    # 4) activate, so the schedule can actually fire ─────────────────────────────────
    # Children first, then the ad set, then the campaign: an ACTIVE campaign over a PAUSED ad set
    # delivers nothing, whereas the reverse order can leave a live parent above half-built
    # children. start_time gates delivery either way — nothing serves before 20 Aug 00:00 — but
    # the ordering costs nothing and removes the question.
    log.info("═" * 88)
    for ad_id in ad_ids:
        g._request("POST", ad_id, data={"status": "ACTIVE"})
    g._request("POST", adset_id, data={"status": "ACTIVE"})
    g._request("POST", campaign_id, data={"status": "ACTIVE"})

    # Meta has silently stored different values than were sent on this account before, and a
    # start_time it quietly dropped would mean the campaign runs TONIGHT rather than at midnight.
    # So the schedule is read back rather than assumed.
    chk = g._request("GET", adset_id, params={"fields": "status,start_time,effective_status"})
    log.info("ad set stored: status=%s effective=%s start_time=%s",
             chk.get("status"), chk.get("effective_status"), chk.get("start_time"))
    camp = g._request("GET", campaign_id, params={"fields": "status,effective_status,daily_budget"})
    log.info("campaign stored: status=%s effective=%s daily_budget=%s",
             camp.get("status"), camp.get("effective_status"), camp.get("daily_budget"))

    scheduled_ok = bool(chk.get("start_time"))
    log.info("campaign=%s  adset=%s  ads=%d", campaign_id, adset_id, len(ad_ids))
    for h in HOOKS:
        log.info("   %-26s %s", h["ad_name"], h["title"])

    warn = ""
    if not scheduled_ok:
        warn = (" ‼ Meta did not store a start_time, which means this campaign is live NOW rather "
                "than at midnight — pause it in Ads Manager immediately if that is not wanted.")
    final_summary(
        log, f"1-1-2 bread-hook test is ACTIVE and scheduled to begin "
             f"{chk.get('start_time') or START_TIME}: 2 hooks on the same 麵包牛奶 body, one ad set "
             f"(Parents 3–17 + Engaged, the account's best-converting targeting), CBO "
             f"RM{DAILY_MYR}/day. Nothing delivers before that timestamp. Body is the proven "
             f"evergreen copy held constant so the HOOK is the only variable; only the headline "
             f"differs. Videos were matched to hooks by the H1/H2 marker in their Drive filenames, "
             f"which runs opposite to the order the links were sent in.{warn}")


if __name__ == "__main__":
    main()
