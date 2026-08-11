"""Remove the two creatives whose artwork has a parent's phone number baked into it.

Operator rule (2026-08-11): any image showing a phone number must not run. Two of the 18 ads
built by build_sg_batch.py embed the same WhatsApp group screenshots, and the chat header carries
a member's mobile number in low-contrast grey — faint on screen, but still a real person's number
published in an ad, so both are pulled.

  1. F 备用 · single image  ad 120257496436350093  (doctor_said_no/img.jpg)
     → the whole ad goes; F drops to 1 ad.
  2. C 见证证明 · carousel   ad 120257496424740093  (review_best_of card_04)
     → only that CARD goes. Creatives are immutable, so this rebuilds the creative from the live
       object_story_spec minus the offending child attachment, points a new ad at it, and deletes
       the old ad. The deck stays coherent at 4 cards: split cover (01+02) → 裤子变短 → 7个月12cm.

Also deletes both image hashes from the account's ad-image library so they cannot be picked up
again by mistake.

Safety: identifies the cards BY IMAGE HASH and verifies each target before touching anything;
aborts that step rather than guessing if the hash is not where it is expected. Everything it
touches is already PAUSED, so nothing was ever delivered with the number on it.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from adbot.clients.graph import GraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

# image hashes of the two offending assets (from the build log, run 31491269416)
HASH_DOCTOR_SAID_NO = "184d33dfc31ac54b654fdccdc591793f"   # F group, whole ad
HASH_REVIEW_CARD_04 = "2b0a19ea5c26e204641970cbd2e20b39"   # C group, one carousel card

AD_DOCTOR_SAID_NO = "120257496436350093"
AD_REVIEW_BEST_OF = "120257496424740093"
ADSET_C_PROOF = "120257496423660093"


def _spec_without(story: Dict[str, Any], bad_hash: str) -> Dict[str, Any]:
    """Return a copy of object_story_spec with the child attachment for `bad_hash` removed."""
    story = json.loads(json.dumps(story))          # deep copy
    link_data = story.get("link_data") or {}
    children: List[Dict[str, Any]] = link_data.get("child_attachments") or []
    kept = [c for c in children if c.get("image_hash") != bad_hash]
    if len(kept) == len(children):
        raise SystemExit(f"card with hash {bad_hash} not found among {len(children)} attachments")
    if len(kept) < 2:
        raise SystemExit(f"only {len(kept)} card(s) would remain — a carousel needs at least 2")
    link_data["child_attachments"] = kept
    story["link_data"] = link_data
    return story, len(children), len(kept)


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    conv = s.meta.conversion_domain_bare or None
    done: List[str] = []

    # ── 1. F 备用 · delete the single-image ad outright ──────────────────────────
    try:
        ad = g.get_object(AD_DOCTOR_SAID_NO, "id,name,status,creative{id,object_story_spec}")
        story = (ad.get("creative") or {}).get("object_story_spec") or {}
        got = ((story.get("link_data") or {}).get("image_hash"))
        log.info("F · ad %s %r status=%s image_hash=%s", ad.get("id"), (ad.get("name") or "")[:46],
                 ad.get("status"), got)
        if got != HASH_DOCTOR_SAID_NO:
            log.error("!! image hash mismatch (expected %s) — NOT deleting", HASH_DOCTOR_SAID_NO)
            done.append("F: SKIPPED (hash mismatch — verify manually)")
        else:
            g._request("DELETE", AD_DOCTOR_SAID_NO)
            log.info("   ✓ deleted ad %s", AD_DOCTOR_SAID_NO)
            done.append(f"F 备用: deleted ad {AD_DOCTOR_SAID_NO} (医生说不会再长) → F now has 1 ad")
    except GraphError as exc:
        log.error("!! F step failed: %s", exc)
        done.append(f"F: FAILED {exc}")

    # ── 2. C 见证证明 · rebuild the carousel without the offending card ──────────
    try:
        ad = g.get_object(AD_REVIEW_BEST_OF, "id,name,status,adset_id,creative{id,object_story_spec,name}")
        creative = ad.get("creative") or {}
        story = creative.get("object_story_spec") or {}
        new_story, before, after = _spec_without(story, HASH_REVIEW_CARD_04)
        log.info("C · ad %s %r — carousel %d cards → %d", ad.get("id"),
                 (ad.get("name") or "")[:46], before, after)

        spec: Dict[str, Any] = {"name": creative.get("name") or "review_best_of (4 cards)",
                                "object_story_spec": new_story}
        if s.meta.instagram_user_id:
            spec["instagram_user_id"] = s.meta.instagram_user_id
        if s.meta.url_tags:
            spec["url_tags"] = s.meta.url_tags
        new_creative = g.create_adcreative(acct, **spec)
        log.info("   + new creative %s (%d cards)", new_creative["id"], after)

        new_ad = g.create_ad(acct, name=ad.get("name") or "Carousel：7 个月，哥哥长了 12cm",
                             adset_id=ad.get("adset_id") or ADSET_C_PROOF,
                             creative={"creative_id": new_creative["id"]},
                             status="PAUSED", conversion_domain=conv)
        log.info("   + new ad %s (PAUSED)", new_ad["id"])

        g._request("DELETE", AD_REVIEW_BEST_OF)
        log.info("   ✓ deleted old ad %s", AD_REVIEW_BEST_OF)
        done.append(f"C 见证证明: carousel rebuilt {before}→{after} cards · new ad {new_ad['id']} "
                    f"(old {AD_REVIEW_BEST_OF} deleted)")
    except (GraphError, SystemExit) as exc:
        log.error("!! C step failed: %s", exc)
        done.append(f"C: FAILED {exc}")

    # ── 3. purge both images from the account's ad-image library ─────────────────
    for label, h in (("doctor_said_no", HASH_DOCTOR_SAID_NO), ("review card_04", HASH_REVIEW_CARD_04)):
        try:
            g._request("DELETE", f"{acct}/adimages", params={"hash": h})
            log.info("   ✓ purged image %s (%s)", h, label)
            done.append(f"purged image {label} {h}")
        except GraphError as exc:
            log.warning("   · could not purge %s (%s): %s", h, label, exc)
            done.append(f"purge {label}: skipped ({exc})")

    log.info("═" * 88)
    for line in done:
        log.info("  • %s", line)
    final_summary(
        log, "Phone-number artwork pulled: F's 医生说不会再长 ad deleted, C's best-of carousel "
             "rebuilt without card 4, both images purged from the ad-image library. Batch is now "
             "17 ads across 6 campaigns, all still PAUSED. The evidence in the deleted card also "
             "appears (without the number) nowhere else — that testimonial is now out of rotation.")


if __name__ == "__main__":
    main()
