"""Put the two Rina-testimonial creatives back, using the redacted artwork.

Follow-up to fix_remove_phone_number_ads.py, which pulled both because the chat header leaked a
parent's mobile number. The number is now painted out (scripts/redact_phone_numbers.py), so the
testimonial goes back into rotation:

  1. F 备用 · re-create the single-image ad 「医生说他不会再长了」 → F back to 2 ads.
  2. C 见证证明 · put the card back at position 4 of the best-of carousel, restoring the intended
     order: split cover (01+02) → 平均一个月长1cm → 医生说不会再长 → 7个月12cm.
     Creatives are immutable, so this reads the live 4-card spec, inserts the new card, and swaps
     in a fresh ad.

Both new ads are created PAUSED, like everything else in the batch.

Idempotent-ish: if F already has a 医生说不会再长 ad, or C's carousel already has 5 cards, that
step is skipped rather than duplicated.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from adbot.clients.graph import GraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "sg_batch"

ADSET_F_BACKUP = "120257496435150093"
ADSET_C_PROOF = "120257496423660093"
AD_C_CAROUSEL_4CARD = "120257496863870093"      # the 4-card ad created by the removal fix

F_IMAGE = ASSETS / "f_backup" / "doctor_said_no" / "img.jpg"
C_CARD = ASSETS / "c_proof" / "review_best_of" / "card_04.jpg"

F_HEADLINE = "医生说他不会再长了，结果呢？"
F_DESCRIPTION = "免费线上课 · 被判「长不高」的孩子，后来长回来了"
F_CAPTION = """「医生说她骨龄快封闭了，最多就 149cm。」

几个月后，这位妈妈自己在群里发了消息：
女儿长了 3cm，现在比 151cm 的妈妈还要高 🎉

这不是我写的文案，是家长亲自截图分享的。

同一位妈妈的 4 岁儿子，以前每个月都感冒发烧、挑食，
身高体重都不及同龄孩子；
戒掉麦类和奶制品、调整体质之后，
不但不用每个月跑医院，几个月内还长高了 5cm。

你是不是也听过类似的话？
🔸 医生说骨龄快封闭了，孩子大概就这样了
🔸 每年长不到 2cm，中医西医都看过，就是没起色
🔸 全家为孩子的身高操碎心，却不知道还能做什么

我想告诉你的是：被判「不会再长」的孩子，我看过太多后来长回来了。

你好，我是马丁医师，来自台湾的专业儿童长高专家，
诊所和社区药局执业超过 10 年、中医跟学超过 10 年，
已帮助超过 6000 位家长解决孩子长不高的烦恼。

在这堂免费线上课里，你会学到：
✅ 中西医都没说清楚的长高关键
✅ 长不高的四大体质偏差
✅ 长高关键营养素的正确摄取
✅ 打开肠胃黄金吸收力
✅ 比跳绳更有效的科学增高运动
✅ 成长金三角：把身高、注意力、睡眠一起管好
✅ 儿童长高推拿手法

而且这些方法：
❌ 不逼孩子吃又黑又难吃的食物
❌ 不用把牛奶当水灌
❌ 不用每天疯狂跳绳

别让身高成为孩子一辈子的遗憾。

点下方按钮，马上免费报名《儿童长高方程式》👇"""

CARD_NAME = "医生说不会再长，结果逆转"
CARD_DESC = "18 岁大女儿长了 3cm"


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    acct = s.meta.account_path
    conv = s.meta.conversion_domain_bare or None
    link = s.meta.lead_destination.link_url
    cta = {"type": s.meta.call_to_action, "value": {"link": link}}
    done: List[str] = []

    # ── 1. F 备用 · re-create the single-image ad ────────────────────────────────
    try:
        existing = g._get_all(f"{ADSET_F_BACKUP}/ads", {"fields": "id,name", "limit": 50})
        if any("不会再长" in (a.get("name") or "") for a in existing):
            log.info("F · ad already present — skipping")
            done.append("F: already present, skipped")
        else:
            h = g.upload_image(acct, str(F_IMAGE))
            log.info("F · uploaded redacted image → %s", h)
            link_data = {"link": link, "image_hash": h, "message": F_CAPTION,
                         "name": F_HEADLINE, "description": F_DESCRIPTION, "call_to_action": cta}
            spec: Dict[str, Any] = {
                "name": f"{s.naming.prefix} | sg-权威反转-医生说他不会再长了",
                "object_story_spec": {"page_id": s.meta.page_id, "link_data": link_data}}
            if s.meta.instagram_user_id:
                spec["instagram_user_id"] = s.meta.instagram_user_id
            if s.meta.url_tags:
                spec["url_tags"] = s.meta.url_tags
            creative = g.create_adcreative(acct, **spec)
            ad = g.create_ad(acct, name=f"Single Image：{F_HEADLINE}", adset_id=ADSET_F_BACKUP,
                             creative={"creative_id": creative["id"]}, status="PAUSED",
                             conversion_domain=conv)
            log.info("F · + creative %s → ad %s (PAUSED)", creative["id"], ad["id"])
            done.append(f"F 备用: re-created ad {ad['id']} (redacted artwork) → F back to 2 ads")
    except GraphError as exc:
        log.error("!! F step failed: %s", exc)
        done.append(f"F: FAILED {exc}")

    # ── 2. C 见证证明 · put the card back at position 4 ──────────────────────────
    try:
        ad = g.get_object(AD_C_CAROUSEL_4CARD,
                          "id,name,adset_id,creative{id,name,object_story_spec}")
        creative = ad.get("creative") or {}
        story = json.loads(json.dumps(creative.get("object_story_spec") or {}))
        link_data = story.get("link_data") or {}
        children: List[Dict[str, Any]] = link_data.get("child_attachments") or []
        log.info("C · ad %s currently has %d card(s)", ad.get("id"), len(children))
        if len(children) >= 5:
            log.info("C · already 5 cards — skipping")
            done.append("C: already 5 cards, skipped")
        else:
            h = g.upload_image(acct, str(C_CARD))
            log.info("C · uploaded redacted card → %s", h)
            card = {"link": link, "image_hash": h, "name": CARD_NAME,
                    "description": CARD_DESC, "call_to_action": cta}
            children.insert(3, card)                     # cover(0,1) · 1cm(2) · [here] · 12cm
            link_data["child_attachments"] = children
            story["link_data"] = link_data

            spec = {"name": creative.get("name") or "review_best_of (5 cards)",
                    "object_story_spec": story}
            if s.meta.instagram_user_id:
                spec["instagram_user_id"] = s.meta.instagram_user_id
            if s.meta.url_tags:
                spec["url_tags"] = s.meta.url_tags
            new_creative = g.create_adcreative(acct, **spec)
            new_ad = g.create_ad(acct, name=ad.get("name") or "Carousel：7 个月，哥哥长了 12cm",
                                 adset_id=ad.get("adset_id") or ADSET_C_PROOF,
                                 creative={"creative_id": new_creative["id"]},
                                 status="PAUSED", conversion_domain=conv)
            g._request("DELETE", AD_C_CAROUSEL_4CARD)
            log.info("C · + creative %s (5 cards) → ad %s · deleted 4-card ad %s",
                     new_creative["id"], new_ad["id"], AD_C_CAROUSEL_4CARD)
            done.append(f"C 见证证明: carousel back to 5 cards · new ad {new_ad['id']} "
                        f"(4-card {AD_C_CAROUSEL_4CARD} deleted)")
    except GraphError as exc:
        log.error("!! C step failed: %s", exc)
        done.append(f"C: FAILED {exc}")

    log.info("═" * 88)
    for line in done:
        log.info("  • %s", line)
    final_summary(
        log, "Rina testimonial restored with the phone number painted out: F back to 2 ads, C's "
             "best-of carousel back to 5 cards in the intended order. Batch is 18 ads across 6 "
             "campaigns again, all PAUSED. Spot-check both previews in Ads Manager — the redacted "
             "strip should read as ordinary bubble padding, not a black bar.")


if __name__ == "__main__":
    main()
