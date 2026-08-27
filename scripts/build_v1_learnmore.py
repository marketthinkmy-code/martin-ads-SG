"""Rebuild Video 1 流鼻涕 as a fresh creative: same video, same proven copy, CTA → Learn More.

Operator (27 Aug): "帮我新建一个 Video 1: 流鼻涕 咳嗽 allergy 每晚睡不好。不要用 existing
post，因为那个链接 whatsapp 了，我要带去 learn more。"

Every historical Video 1 ad rides the SAME page post (341825319024143_122172905456485585),
whose call-to-action is WHATSAPP_MESSAGE — existing posts are immutable, so no duplicate of
those ads can ever point anywhere else. This builds a NEW creative from parts:
  · the same video (read live from the pinned WhatsApp-post creative — no re-upload),
  · the same proven body + headline, verbatim (only the destination was wrong, and the text
    carries no URL — the link lives on the CTA button only, per the standing rule),
  · call_to_action LEARN_MORE → the config lead-destination page (the operator's exact ask),
    with the account's UTM url_tags so the new ad's leads track like every other build.

The ad is created PAUSED in the Winners Revival ad set — the one place Video 1 already sits
(paused, still WhatsApp-post-bound); the new ad is its clean replacement, one switch away.
The old ad is not touched. Name is the exact historical name, so sales attribution and the
"流鼻涕" cpl_hold protection carry over. Idempotent via state/entities_v1_learnmore.json;
verified by re-reading the stored CTA type and the ad's creative binding.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "entities_v1_learnmore.json"

SOURCE_CREATIVE = "28159107980439761"    # Winners Revival Video 1 — WhatsApp-post creative
TARGET_ADSET = "120257785731120093"      # Winners Revival ad set holding the paused Video 1
AD_NAME = "Video 1: 流鼻涕 咳嗽 allergy 每晚睡不好"
CTA_TYPE = "LEARN_MORE"                  # operator's explicit ask — not the config default


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    conv = s.meta.conversion_domain_bare or None

    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}

    # source parts, read live: video + proven copy off the WhatsApp-post creative
    src = g._request("GET", SOURCE_CREATIVE, params={
        "fields": "video_id,body,title,call_to_action_type,object_story_id"})
    video_id, body, title = src.get("video_id"), src.get("body"), src.get("title")
    if not (video_id and body and title):
        raise SystemExit(f"!! source creative {SOURCE_CREATIVE} is missing video/body/title "
                         f"({video_id!r}/{bool(body)}/{title!r}) — nothing was built.")
    log.info("── source: video %s · old CTA %s · post %s", video_id,
             src.get("call_to_action_type"), src.get("object_story_id"))

    adset = g._request("GET", TARGET_ADSET, params={"fields": "name,status,campaign_id"})
    log.info("── target ad set %s %r (status %s)", TARGET_ADSET, adset.get("name"),
             adset.get("status"))

    creative_id = st.get("creative_id")
    if creative_id:
        log.info("── reuse creative %s", creative_id)
    else:
        thumb = g.get_video_thumbnail(video_id)
        cta = {"type": CTA_TYPE, "value": {"link": s.meta.lead_destination.link_url}}
        vdata: Dict[str, Any] = {"video_id": video_id, "title": title, "message": body,
                                 "call_to_action": cta}
        if thumb:
            vdata["image_url"] = thumb
        story: Dict[str, Any] = {"page_id": s.meta.page_id, "video_data": vdata}
        if s.meta.instagram_user_id:
            story["instagram_user_id"] = s.meta.instagram_user_id
        fields: Dict[str, Any] = {"name": f"{AD_NAME} · Learn More", "object_story_spec": story}
        if s.meta.url_tags:
            fields["url_tags"] = s.meta.url_tags
        creative_id = g.create_adcreative(acct, **fields)["id"]
        st.update({"creative_id": creative_id, "video_id": video_id,
                   "source_creative": SOURCE_CREATIVE})
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))
        log.info("── + creative %s (video %s reused, CTA %s)", creative_id, video_id, CTA_TYPE)

    ad_id = st.get("ad_id")
    if ad_id:
        log.info("── reuse ad %s", ad_id)
    else:
        ad = g.create_ad(acct, name=AD_NAME, adset_id=TARGET_ADSET,
                         creative={"creative_id": creative_id},
                         status="PAUSED", conversion_domain=conv)
        ad_id = ad["id"]
        st.update({"ad_id": ad_id, "adset_id": TARGET_ADSET})
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))
        log.info("── + ad %s (PAUSED)", ad_id)

    # verify: binding + the stored CTA — sent is not stored
    bound = g._request("GET", ad_id, params={"fields": "creative{id},status,effective_status"})
    spec = g._request("GET", creative_id, params={"fields": "object_story_spec"})
    stored_cta = ((((spec.get("object_story_spec") or {}).get("video_data")) or {})
                  .get("call_to_action") or {}).get("type")
    ok = (str((bound.get("creative") or {}).get("id")) == str(creative_id)
          and stored_cta == CTA_TYPE)
    log.info("── ad %s → creative %s · stored CTA %s · %s/%s (%s)", ad_id,
             (bound.get("creative") or {}).get("id"), stored_cta, bound.get("status"),
             bound.get("effective_status"), "ok" if ok else "MISMATCH")
    if not ok:
        raise SystemExit("!! verify failed — check the ad in Ads Manager before activating.")

    final_summary(
        log, f"Video 1 rebuilt clean: new ad {ad_id} PAUSED in the Winners Revival ad set, "
             f"new creative {creative_id} reusing the same video {video_id} and the proven "
             f"body/headline verbatim — only the button changed: {CTA_TYPE} → "
             f"{s.meta.lead_destination.link_url}. The old WhatsApp-post ad was not touched. "
             f"Review the preview, then switch the new ad on (and leave the old one off).")


if __name__ == "__main__":
    main()
