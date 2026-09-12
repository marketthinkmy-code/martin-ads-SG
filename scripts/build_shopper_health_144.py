"""Shopper & Health Interests 1-4-4: ONE new campaign, 4 interest ad sets x 4 proven ads.

Operator's spec (12 Sep, restated and confirmed "① 换 Hook 7 ② A ③ 直接跑"):
    · 1 NEW ABO campaign: [SG] 儿童长高方程式 | Shopper & Health Interests | 1-4-4
    · 4 ad sets, RM50/day each (+RM200/day total), named by targeting, ACTIVE immediately:
        1. Engaged Shoppers      — behavior 6071631541183
        2. Vitamins              — interests 6803120807074 (Vitamins & nutritional
                                   supplements) + 6003331809777 (Folic acid)
        3. Health & Wellness     — interests 6003258544357 + 6003384248805
        4. Healthy Diet & Food   — interests 6003382102565 + 6003198972065 + 6003420915231
      (Option A: the Supplement set became Healthy Diet & Food — Meta's only topical
      supplement interest is the same 6803120807074, two sets would fight each other.
      Healthy diet moved out of set 3 so sets 3/4 stay disjoint.)
    · EVERY ad set carries the SAME four proven sellers (existing creatives reused, social
      proof pooled; exact historical ad names kept for sheet attribution):
        15岁以上还有机会长高吗 (25 SG sales) · Hook 3 准备早餐面包 (13) ·
        Video 5 林書豪story (11) · Hook 7 担心高度没跟上 (10 · CPA RM839)
      — 我不会买牛奶 swapped out for Hook 7 on the operator's word.
    · Copy stays as the historical posts carry it (facts update deferred, operator's rule).
    · Scale stays manual per ad; the 11 Sep daily rules govern it automatically.

Idempotent via state/entities_shopper_health_144.json — re-dispatch resumes. If a legacy
creative id is rejected on a new ad ("(#400) website URL required"), the ad falls back to a
fresh creative wrapping the same page post (effective_object_story_id) — same post, same
social proof.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from adbot.clients.graph import GraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

STATE_PATH = Path("state") / "entities_shopper_health_144.json"
CAMPAIGN_NAME = "[SG] 儿童长高方程式 | Shopper & Health Interests | 1-4-4"
DAILY_MINOR = 5000

ADS: List[Dict[str, str]] = [   # proven sellers — creative reused from the rep ad
    {"key": "v15plus", "src_ad": "120250914933320093"},   # 15岁以上还有机会长高吗 · 25 SG
    {"key": "hook3bread", "src_ad": "120227243598650093"},  # Hook 3 准备早餐面包 · 13 SG
    {"key": "v5lin", "src_ad": "120247184595700093"},     # Video 5 林書豪story · 11 SG
    {"key": "hook7", "src_ad": "120242606093200093"},     # Hook 7 担心高度没跟上 · 10 SG
    # 12 Sep "A & B": Hook 7's old post is WhatsApp-bound (number banned) — option A adds
    # the CLEAN Video 1 Learn More rebuild (6 SG sales · CPA RM623, CTA → SG landing);
    # option B (Hook 7 rebuilt with a fresh Learn More creative) lands after copy approval.
    {"key": "v1learn", "src_ad": "120257935200220093"},   # V1 流鼻涕 Learn More 版 · 6 SG
]

# 12 Sep operator approved ("上") — option B: Hook 7 rebuilt on its original video with a
# fresh Learn More creative (the old post's WhatsApp CTA is banned). Current copy rules:
# 马丁医师 · 10,000+ 位孩子 · 5-17岁 · no URL in body · no hashtags · no price.
HOOK7_TITLE = "🔴 孩子的身高，跟上年龄了吗？"
HOOK7_BODY = """📏 担心孩子的高度，没跟得上年龄该有的高度？

尤其适合这些家长：
🛑 孩子一年长不到 6cm
🛑 骨龄超前 / 落后
🛑 性早熟
🛑 睡不深、注意力不集中
🛑 课业压力大，越坐越"矮"

大家好，我是马丁医师 🇹🇼
台湾儿童长高专家，中西医整合经验超过 10 年。

🌍 我已经帮助台湾、新加坡、马来西亚、澳洲、加拿大等地
超过 10,000+ 位孩子健康长高——
其中很多，是被认为"很难再长高"的孩子。

💡 如果你：
👉 担心父母不高，孩子跟着长不高
👉 试过网上的偏方、保健品、运动，都没动静
👉 中医西医都看了，还是不见效

放心，作为一位父亲，我懂你的心情。
❌ 不打针、不逼孩子吞难吃的补品
✅ 只用简单、健康、有科学根据的方法——
先把身体调好，营养吸收得进去，身高自然跟上来。

✨ 我把整套方法放进一堂免费的线上课程：
✅ 5-17 岁孩子的黄金长高期，到底在什么时候
✅ 怎么科学管理身高，不错过关键节点
✅ 哪些营养和运动真正有效，让长高变简单
✅ 成长金三角：身高、注意力、睡眠一起管

⏳ 生长板一旦闭合，就再也追不回来了。
👇 点击下方按钮，立即免费报名，我们课程见！"""

ADSETS: List[Dict[str, Any]] = [
    {"key": "shoppers", "name": "Engaged Shoppers",
     "flex": [{"behaviors": [{"id": "6071631541183", "name": "Engaged shoppers"}]}]},
    {"key": "vitamins", "name": "Vitamins",
     "flex": [{"interests": [
         {"id": "6803120807074", "name": "Vitamins and nutritional supplements"},
         {"id": "6003331809777", "name": "Folic acid"}]}]},
    {"key": "wellness", "name": "Health & Wellness",
     "flex": [{"interests": [
         {"id": "6003258544357", "name": "Health & wellness"},
         {"id": "6003384248805", "name": "Fitness and wellness"}]}]},
    {"key": "diet", "name": "Healthy Diet & Food",
     "flex": [{"interests": [
         {"id": "6003382102565", "name": "Healthy diet"},
         {"id": "6003198972065", "name": "Healthy food"},
         {"id": "6003420915231", "name": "Health club"}]}]},
]


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    m = s.meta
    acct = m.account_path
    conv = m.conversion_domain_bare or None
    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}

    def persist() -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, indent=2, ensure_ascii=False) + "\n")

    # ── resolve the four source creatives BEFORE creating anything ──────────────
    srcs: Dict[str, Any] = st.setdefault("sources", {})
    for a in ADS:
        rec = srcs.get(a["key"]) or {}
        if not rec.get("creative_id"):
            info = g.get_object(a["src_ad"],
                                "name,creative{id,effective_object_story_id}")
            cr = info.get("creative") or {}
            if not cr.get("id"):
                raise SystemExit(f"!! source ad {a['src_ad']} has no creative — aborting.")
            rec = {"name": info.get("name"), "creative_id": str(cr["id"]),
                   "post_id": cr.get("effective_object_story_id") or ""}
            srcs[a["key"]] = rec
            persist()
        log.info("── %-10s %r creative %s post %s", a["key"], rec["name"],
                 rec["creative_id"], rec.get("post_id") or "?")

    def creative_for(key: str) -> str:
        """The creative to bind — operator-approved rebuild first, then post-wrap fallback,
        else the source ad's own creative."""
        rec = srcs[key]
        return (rec.get("rebuild_creative_id") or rec.get("fallback_creative_id")
                or rec["creative_id"])

    def make_fallback(key: str) -> str:
        rec = srcs[key]
        if rec.get("fallback_creative_id"):
            return rec["fallback_creative_id"]
        if not rec.get("post_id"):
            raise SystemExit(f"!! {key}: legacy creative rejected and no post id to wrap.")
        fields: Dict[str, Any] = {"name": f"{rec['name']} (post reuse)",
                                  "object_story_id": rec["post_id"]}
        if m.url_tags:
            fields["url_tags"] = m.url_tags
        rec["fallback_creative_id"] = g.create_adcreative(acct, **fields)["id"]
        persist()
        log.info("   %s: legacy creative rejected → new post-wrap creative %s",
                 key, rec["fallback_creative_id"])
        return rec["fallback_creative_id"]

    # ── probe the blocked Hook 7 source so the operator can approve a rebuild ───
    # (option B: same video, fresh Learn More creative — copy needs operator preview)
    if (srcs.get("hook7") or {}).get("blocked") \
            and not (srcs["hook7"].get("probe") or {}).get("video_id"):
        try:
            cr = g.get_object(srcs["hook7"]["creative_id"],
                              "video_id,body,title,object_story_spec,asset_feed_spec,"
                              "effective_object_story_id")
            spec0 = cr.get("object_story_spec") or {}
            vd = spec0.get("video_data") or {}
            afs = cr.get("asset_feed_spec") or {}
            vid = (cr.get("video_id") or vd.get("video_id")
                   or ((afs.get("videos") or [{}])[0].get("video_id")) or "")
            msg = (cr.get("body") or vd.get("message")
                   or ((afs.get("bodies") or [{}])[0].get("text")) or "")
            title0 = (cr.get("title") or vd.get("title")
                      or ((afs.get("titles") or [{}])[0].get("text")) or "")
            cta0 = ((vd.get("call_to_action") or {}).get("type")
                    or (afs.get("call_to_action_types") or [None])[0])
            if not msg:                      # last resort: the page post itself
                try:
                    post = g.get_object(srcs["hook7"]["post_id"],
                                        "message,attachments{media_type,target{id}}")
                    msg = post.get("message") or ""
                    att = ((post.get("attachments") or {}).get("data") or [{}])[0]
                    if not vid and (att.get("media_type") == "video"):
                        vid = (att.get("target") or {}).get("id") or ""
                except Exception as exc2:  # noqa: BLE001
                    log.info("── hook7 post read failed: %s", exc2)
            srcs["hook7"]["probe"] = {"video_id": vid, "title": title0, "cta": cta0}
            persist()
            log.info("── hook7 rebuild probe: video_id=%s cta=%s title=%r", vid, cta0, title0)
            log.info("── hook7 original body ↓↓↓\n%s\n↑↑↑ body ends", msg)
        except Exception as exc:  # noqa: BLE001
            log.info("── hook7 probe failed: %s", exc)

    # ── option B (operator "上"): rebuild Hook 7 — original video, approved Learn More copy
    h7 = srcs.get("hook7") or {}
    if h7.get("blocked") and (h7.get("probe") or {}).get("video_id") \
            and not h7.get("rebuild_creative_id"):
        vid = h7["probe"]["video_id"]
        thumb = g.get_video_thumbnail(vid)
        vdata: Dict[str, Any] = {
            "video_id": vid, "title": HOOK7_TITLE, "message": HOOK7_BODY,
            "call_to_action": {"type": m.call_to_action,
                               "value": {"link": m.lead_destination.link_url}}}
        if thumb:
            vdata["image_url"] = thumb
        story: Dict[str, Any] = {"page_id": m.page_id, "video_data": vdata}
        if m.instagram_user_id:
            story["instagram_user_id"] = m.instagram_user_id
        fields = {"name": f"{h7['name']} (Learn More rebuild)", "object_story_spec": story}
        if m.url_tags:
            fields["url_tags"] = m.url_tags
        h7["rebuild_creative_id"] = g.create_adcreative(acct, **fields)["id"]
        persist()
        log.info("── hook7: + Learn More rebuild creative %s (video %s)",
                 h7["rebuild_creative_id"], vid)

    # ── campaign ────────────────────────────────────────────────────────────────
    if st.get("campaign_id"):
        log.info("── reuse campaign %s", st["campaign_id"])
    else:
        fields = {"name": CAMPAIGN_NAME, "objective": m.objective, "buying_type": "AUCTION",
                  "status": "ACTIVE", "special_ad_categories": m.special_ad_categories,
                  "is_adset_budget_sharing_enabled": False}
        if m.regional_regulated_categories:
            fields["regional_regulated_categories"] = m.regional_regulated_categories
        st["campaign_id"] = g.create_campaign(acct, **fields)["id"]
        persist()
        log.info("── + campaign %s %r", st["campaign_id"], CAMPAIGN_NAME)

    base_spec = {
        "geo_locations": {"countries": m.targeting.countries or ["SG"]},
        "age_min": m.targeting.age_min, "age_max": m.targeting.age_max,
        "targeting_automation": {"advantage_audience": 1},
        "excluded_custom_audiences": [{"id": str(c)} for c in
                                      (m.targeting.excluded_custom_audiences or [])],
        "locales": m.targeting.locales or [1004],
    }

    # ── 4 ad sets × 4 ads ───────────────────────────────────────────────────────
    rows: List[str] = []
    groups: Dict[str, Any] = st.setdefault("adsets", {})
    for aset in ADSETS:
        log.info("═" * 88)
        rec: Dict[str, Any] = groups.setdefault(aset["key"], {})
        if not rec.get("adset_id"):
            spec = dict(base_spec)
            spec["flexible_spec"] = aset["flex"]
            fields = {"name": aset["name"], "campaign_id": st["campaign_id"],
                      "optimization_goal": m.optimization_goal,
                      "billing_event": "IMPRESSIONS", "promoted_object": m.promoted_object,
                      "targeting": spec, "status": "ACTIVE", "daily_budget": DAILY_MINOR,
                      "bid_strategy": "LOWEST_COST_WITHOUT_CAP"}
            if m.regional_regulated_categories:
                fields["regional_regulated_categories"] = m.regional_regulated_categories
            if m.regional_regulation_identities:
                fields["regional_regulation_identities"] = m.regional_regulation_identities
            rec["adset_id"] = g.create_adset(acct, **fields)["id"]
            persist()
        log.info("▸ %-20s adset %s · RM50/day", aset["name"], rec["adset_id"])
        ads_rec: Dict[str, Any] = rec.setdefault("ads", {})
        for a in ADS:
            if srcs[a["key"]].get("blocked") and not srcs[a["key"]].get("rebuild_creative_id"):
                log.info("     %-10s SKIPPED — %s", a["key"], srcs[a["key"]]["blocked"])
                continue
            if not ads_rec.get(a["key"]):
                name = srcs[a["key"]]["name"]
                try:
                    ad = g.create_ad(acct, name=name, adset_id=rec["adset_id"],
                                     creative={"creative_id": creative_for(a["key"])},
                                     status="ACTIVE", conversion_domain=conv)
                except GraphError as exc:
                    msg = str(exc).lower()
                    if "whatsapp" in msg:
                        # the source post's CTA is WhatsApp-bound (number banned) — this
                        # creative cannot be reused at all; skip the slot in EVERY set and
                        # let the operator pick a replacement (same class as old Video 1).
                        srcs[a["key"]]["blocked"] = f"WhatsApp-bound source: {exc}"
                        persist()
                        log.info("     %-10s BLOCKED — %s", a["key"], exc)
                        continue
                    if "url" not in msg:
                        raise
                    ad = g.create_ad(acct, name=name, adset_id=rec["adset_id"],
                                     creative={"creative_id": make_fallback(a["key"])},
                                     status="ACTIVE", conversion_domain=conv)
                ads_rec[a["key"]] = ad["id"]
                persist()
            fin = g._request("GET", ads_rec[a["key"]], params={"fields": "effective_status"})
            log.info("     %-10s ad %s · eff %s", a["key"], ads_rec[a["key"]],
                     fin.get("effective_status"))
            rows.append(f"{aset['key']}/{a['key']}({fin.get('effective_status')})")

    log.info("═" * 88)
    final_summary(
        log, f"Shopper & Health 1-4-4 live: campaign {st['campaign_id']} · 4 ad sets "
             f"(RM50/day each, named by targeting) · 16 ads over 4 proven creatives — "
             f"{'; '.join(rows)}. +RM200/day, running immediately; the 11 Sep daily rules "
             f"(CPL>95 → -30%, RM142.50 zero-reg kill) govern it automatically.")


if __name__ == "__main__":
    main()
