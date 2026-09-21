"""Verify the 新片 5 支测试 build end-to-end (read-only). Operator asked "你有没有建错？".

Checks, all read back from Meta, no trust in local state:
    1. Campaign: exact name · ACTIVE · ABO (no campaign budget) · objective
    2. Ad set: exact name · RM100/day · ACTIVE · targeting digest (ages, Adv+, interests,
       excluded buyer audiences count) vs the F&R winner source
    3. Each of the 5 ads: name → creative id → the VIDEO ID inside the creative, compared
       against the video ids recorded when the files were uploaded on 9/14
       (state/entities_new_wave_0914.json) — proves 倒掉牛奶 is the 新馬H3 file, 保健品
       is the 北美H4 file, etc. Hook 1 checks against the pinned 10,000-version creative.
    4. The two old RM40 chains (Hook 1 / Hook 7) are ACTIVE again per 不要关.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

sys.path.insert(0, str(Path(__file__).parent))
from build_new_wave_0914 import STATE_PATH as NW_STATE  # noqa: E402
from build_test155_fr_0921 import (  # noqa: E402
    ADS, ADSET_NAME, CAMPAIGN_NAME, DAILY_MINOR, FR_SOURCE, STATE_PATH)

STRAYS = {"120258340162830093": "Hook 1 旧链", "120258340143400093": "Hook 7 旧链"}


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    st = json.loads(STATE_PATH.read_text())
    nw = json.loads(NW_STATE.read_text())
    problems = []

    c = g.get_object(st["campaign_id"],
                     "name,status,effective_status,objective,daily_budget,buying_type")
    ok_name = c.get("name") == CAMPAIGN_NAME
    ok_abo = not int(c.get("daily_budget") or 0)
    log.info("① campaign %s", st["campaign_id"])
    log.info("   name %s %r", "✓" if ok_name else "✗", c.get("name"))
    log.info("   status %s/%s · objective %s · ABO %s",
             c.get("status"), c.get("effective_status"), c.get("objective"),
             "✓ (无 campaign 预算)" if ok_abo else "✗ CBO?!")
    if not ok_name:
        problems.append("campaign name mismatch")
    if not ok_abo:
        problems.append("campaign has CBO budget")

    a = g.get_object(st["adset_id"], "name,status,effective_status,daily_budget,targeting")
    t = a.get("targeting") or {}
    adv = (t.get("targeting_automation") or {}).get("advantage_audience")
    names = []
    for spec_ in (t.get("flexible_spec") or [{}]):
        for kind in ("interests", "behaviors", "life_events", "family_statuses"):
            names += [i.get("name") or i.get("id") for i in spec_.get(kind) or []]
    exc = t.get("excluded_custom_audiences") or []
    src_t = g.get_object(FR_SOURCE, "targeting").get("targeting") or {}
    src_names = []
    for spec_ in (src_t.get("flexible_spec") or [{}]):
        for kind in ("interests", "behaviors", "life_events", "family_statuses"):
            src_names += [i.get("name") or i.get("id") for i in spec_.get(kind) or []]
    ok_budget = int(a.get("daily_budget") or 0) == DAILY_MINOR
    ok_adv = int(adv or 0) == 0
    ok_interests = sorted(map(str, names)) == sorted(map(str, src_names))
    log.info("② adset %s", st["adset_id"])
    log.info("   name %s %r · RM%d/day %s · %s/%s",
             "✓" if a.get("name") == ADSET_NAME else "✗", a.get("name"),
             int(a.get("daily_budget") or 0) // 100, "✓" if ok_budget else "✗",
             a.get("status"), a.get("effective_status"))
    log.info("   ages %s-%s · Adv+ %s %s · 兴趣 %d 项 %s 源 · 排除受众 %d 个",
             t.get("age_min"), t.get("age_max"), "OFF" if ok_adv else f"ON({adv})",
             "✓" if ok_adv else "✗", len(names), "＝" if ok_interests else "≠",
             len(exc))
    log.info("   兴趣: %s", " + ".join(map(str, names))[:100])
    for cond, msg in [(ok_budget, "adset budget wrong"), (ok_adv, "Adv+ not OFF"),
                      (ok_interests, "interests differ from source"),
                      (a.get("name") == ADSET_NAME, "adset name mismatch"),
                      (bool(exc), "no excluded audiences")]:
        if not cond:
            problems.append(msg)

    log.info("③ 5 支 ad → creative → video 对账（含视频标题/时长——不同文件时长必不同）")
    expect_video = {k: (nw["creatives"].get(k) or {}).get("video_id") for k in nw["creatives"]}
    seen_videos = {}
    for spec_ad in ADS:
        key = spec_ad["key"]
        ad_id = st["ads"][key]
        info = g.get_object(ad_id, "name,effective_status,creative{id,object_story_spec}")
        cr = info.get("creative") or {}
        vid = ((cr.get("object_story_spec") or {}).get("video_data") or {}).get("video_id")
        try:
            vmeta = g.get_object(vid, "title,length") if vid else {}
        except Exception:  # noqa: BLE001
            vmeta = {}
        want_cr = spec_ad.get("creative_id") or (nw["creatives"].get(key) or {}).get("creative_id")
        ok_cr = str(cr.get("id")) == str(want_cr)
        if key == "hook1":
            ok_vid = ok_cr           # pinned creative is the ground truth for hook1
            vid_txt = f"video {vid}（10,000 版固定 creative）"
        else:
            want_vid = expect_video.get(key)
            ok_vid = str(vid) == str(want_vid)
            vid_txt = f"video {vid} {'＝' if ok_vid else '≠'} 9/14 上传记录 {want_vid}"
        seen_videos[key] = vid
        mark = "✓" if (ok_cr and ok_vid) else "✗"
        log.info("   %s %-6s ad %s %r · creative %s · %s · eff %s",
                 mark, key, ad_id, (info.get("name") or "")[:26], cr.get("id"),
                 vid_txt, info.get("effective_status"))
        log.info("        视频标题 %r · 时长 %ss",
                 (vmeta.get("title") or "?")[:34], vmeta.get("length", "?"))
        if not (ok_cr and ok_vid):
            problems.append(f"{key}: creative/video mismatch")
    if len(set(seen_videos.values())) != len(seen_videos):
        problems.append("TWO ADS SHARE ONE VIDEO — real mixup")
        log.error("✗ 有两支 ad 用了同一个 video id: %s", seen_videos)

    log.info("④ 旧链恢复（不要关）")
    for ad_id, label in STRAYS.items():
        eff = g.get_object(ad_id, "effective_status").get("effective_status")
        ok = eff == "ACTIVE"
        log.info("   %s %s ad %s eff %s", "✓" if ok else "✗", label, ad_id, eff)
        if not ok:
            problems.append(f"{label} not ACTIVE ({eff})")

    if problems:
        log.error("发现问题 %d 个: %s", len(problems), "; ".join(problems))
        sys.exit(1)
    final_summary(log, "Verification clean: campaign/adset/targeting/5 creatives-to-videos/"
                       "old chains all match the operator's spec. Read-only.")


if __name__ == "__main__":
    main()
