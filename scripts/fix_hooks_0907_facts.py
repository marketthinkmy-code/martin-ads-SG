"""Fact fix on the Hooks 0907 copies: 10,000+ 位孩子, not 7,000 个家庭. LIVE.

Operator (8 Sep): "10000位孩子 ，不是 7000个家庭 / 5-17岁孩子，不是3-15岁".

Meta creatives are immutable, so each of the four videos gets a NEW creative — same uploaded
video, same headline, body with the corrected proof line — and its three campaign ads are
rebound. The old creative ids stay in state as replaced_creative_id (one-run swap-back).
None of the four bodies contains a 3-15 age range (asserted at run time); the 5-17 rule is
recorded for future copywriting.

Every replacement is exact-string and must hit exactly once, or the run refuses — no fuzzy
edits on live copy. Verified by re-reading each ad's binding and the stored message.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "entities_hooks_0907.json"

# per-video exact replacement (old line → corrected line)
FIXES: Dict[str, Tuple[str, str]] = {
    "hook1": ("已帮助 7,000+ 个家庭，破解孩子「长不高」的问题。",
              "已帮助 10,000+ 位孩子，破解「长不高」的问题。"),
    "hook2": ("已帮助 7,000+ 个家庭破解孩子「长不高」的问题。",
              "已帮助 10,000+ 位孩子破解「长不高」的问题。"),
    "hook6": ("这十年，我陪过 7,000 多个华人家庭。",
              "这十年，我帮助过 10,000 多位孩子。"),
    "video7": ("这十年，我用这套「成长金三角」，陪过 7,000 多个华人家庭。",
               "这十年，我用这套「成长金三角」，帮助过 10,000 多位孩子。"),
}


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    m = s.meta

    st: Dict[str, Any] = json.loads(STATE_PATH.read_text())
    creatives: Dict[str, Any] = st["creatives"]
    campaigns: Dict[str, Any] = st["campaigns"]

    swapped: List[str] = []
    for key, (old_line, new_line) in FIXES.items():
        rec = creatives[key]
        if rec.get("fact_fixed"):
            log.info("── %s already fixed (creative %s)", key, rec["creative_id"])
            continue
        old_creative = rec["creative_id"]
        spec = g._request("GET", old_creative,
                          params={"fields": "object_story_spec,url_tags,name"})
        story = spec.get("object_story_spec") or {}
        vd = story.get("video_data") or {}
        body, title, video_id = vd.get("message") or "", vd.get("title"), vd.get("video_id")
        if not (body and video_id):
            raise SystemExit(f"!! {key}: creative {old_creative} missing message/video — "
                             f"nothing was changed.")
        if "3-15" in body or "3–15" in body or "3～15" in body:
            raise SystemExit(f"!! {key}: body unexpectedly contains a 3-15 age range — "
                             f"stopping so it can be reviewed, nothing was changed.")
        if body.count(old_line) != 1:
            raise SystemExit(f"!! {key}: expected the proof line exactly once, found "
                             f"{body.count(old_line)} — refusing a fuzzy edit.")
        new_body = body.replace(old_line, new_line)

        vdata: Dict[str, Any] = {"video_id": video_id, "title": title, "message": new_body,
                                 "call_to_action": vd.get("call_to_action")}
        if vd.get("image_url"):
            vdata["image_url"] = vd["image_url"]
        new_story: Dict[str, Any] = {"page_id": story.get("page_id") or m.page_id,
                                     "video_data": vdata}
        if story.get("instagram_user_id"):
            new_story["instagram_user_id"] = story["instagram_user_id"]
        fields: Dict[str, Any] = {"name": f"{spec.get('name')} · 10k孩子",
                                  "object_story_spec": new_story}
        if spec.get("url_tags"):
            fields["url_tags"] = spec["url_tags"]
        new_creative = g.create_adcreative(acct, **fields)["id"]
        log.info("── %s: creative %s → %s (video %s reused)", key, old_creative,
                 new_creative, video_id)

        # rebind this video's three ads
        for ckey, camp in campaigns.items():
            ad_id = camp["units"][key]["ad_id"]
            g._request("POST", ad_id, data={"creative": json.dumps({"creative_id": new_creative})})
            bound = g._request("GET", ad_id, params={"fields": "creative{id},effective_status"})
            ok = str((bound.get("creative") or {}).get("id")) == str(new_creative)
            log.info("   %s %s ad %s → creative %s · eff %s", "·" if ok else "✗", ckey,
                     ad_id, (bound.get("creative") or {}).get("id"),
                     bound.get("effective_status"))
            if not ok:
                raise SystemExit(f"!! {key}/{ckey}: rebind did not verify — check ad {ad_id} "
                                 f"in Ads Manager.")

        chk = g._request("GET", new_creative, params={"fields": "object_story_spec"})
        stored = (((chk.get("object_story_spec") or {}).get("video_data")) or {}).get("message") or ""
        if "10,000" not in stored:
            raise SystemExit(f"!! {key}: stored body does not carry the corrected number.")
        rec.update({"creative_id": new_creative, "replaced_creative_id": old_creative,
                    "fact_fixed": True})
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))
        swapped.append(key)

    final_summary(
        log, f"Fact fix live on {len(swapped)}/4 videos ({', '.join(swapped) or 'none — all "
             f"already fixed'}): proof line now 10,000+ 位孩子, all 12 ads rebound to the "
             f"corrected creatives (same videos, same headlines; old creatives kept in state "
             f"for swap-back). No 3-15 age range exists in these bodies; 5-17岁 is the "
             f"standing rule for future copy.")


if __name__ == "__main__":
    main()
