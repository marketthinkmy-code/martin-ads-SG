"""复活单王 (26 Sep): NEW account · 1-1-4 · RM80/day · PAUSED.

Operator: "上复活。为什么 Hook 3：想带孩子打生长激素 不建呢？" — the 1-1-3 proposal becomes
1-1-4: 生长激素 had no disqualifier (lifetime CPA RM820 ≈ V3's 821, and the
fear-of-hormone-injections angle is a hook family the current board doesn't cover),
it was only a top-3 cut. Budget scales RM60 → RM80 to keep RM20/ad.

Build, all on act_1179668409969241:
    Campaign 「[SG] 儿童长高方程式 | Food & Drink + Milk | 复活单王 | 1-1-4」 ABO, PAUSED.
    One ad set RM80/day — name/targeting/promoted_object cloned verbatim from the OLD
    account's Food & Drink + Milk winner ad set 120250912724510093 (26 lifetime sales,
    the best-converting targeting in account history; not yet used on the new account),
    audience entries filtered to what the new account can see.
    Four ads, exact historical names (sheet attribution folds by name), located at run
    time on the OLD account by folded-name match (newest copy with a reusable page post):
        Video 3：5岁到15岁的孩子          终身 7单 · CPA RM821 · 最后成交 2026-05-27
        APR VIDEO: HOOK 5               终身 5单 · CPA RM554 · 最后成交 2025-10-09
        MAR Single image 1：牛奶+面包     终身 4单 · CPA RM599 · 最后成交 2026-04-29
        Hook 3：想带孩子打生长激素?        终身 4单 · CPA RM820 · 最后成交 2026-04-02
    Creatives reuse the old posts (object_story_id → engagement pools across accounts,
    zero uploads); video re-upload fallback if a post can't be reused; a target that
    can't be built is skipped and recorded, never blocks the rest.

Standard rules once flipped (zero-reg kill, 30d CPA discipline), NO cpl_hold. Idempotent
via state/entities_revival_0926.json; rate limit exits 75, re-dispatch resumes.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from adbot import cpa
from adbot.clients.graph import GraphError, TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

NEW_ACCT = "act_1179668409969241"
SRC_ADSET = "120250912724510093"       # OLD acct · Food & Drink + Milk … · 26 lifetime sales
STATE_PATH = Path("state") / "entities_revival_0926.json"
CAMPAIGN_NAME = "[SG] 儿童长高方程式 | Food & Drink + Milk | 复活单王 | 1-1-4"
DAILY_MINOR = 8000

# key → exact sheet/board name (folded-name match finds every old-account copy)
TARGETS: List[Dict[str, str]] = [
    {"key": "v3_515", "name": "Video 3：5岁到15岁的孩子", "hint": "5岁到15岁"},
    {"key": "apr_hook5", "name": "APR VIDEO: HOOK 5", "hint": "apr video"},
    {"key": "mar_bread", "name": "MAR Single image 1：牛奶+面包", "hint": "牛奶+面包"},
    {"key": "hook3_gh", "name": "Hook 3：想带孩子打生长激素?", "hint": "生长激素"},
]


def strip_audiences(t: Dict[str, Any], log, label: str, available: set) -> Dict[str, Any]:
    """Keep audience entries the NEW account can see (operator shared them); drop the rest."""
    t = dict(t)
    for f in ("custom_audiences", "excluded_custom_audiences"):
        entries = t.get(f) or []
        if not entries:
            continue
        kept = [e for e in entries if str(e.get("id")) in available]
        dropped = [str(e.get("id")) for e in entries if str(e.get("id")) not in available]
        if kept:
            t[f] = kept
        else:
            t.pop(f, None)
        if dropped:
            log.info("   ⚠️ %s: %s 里去掉了未共享的受众 %s（其余 %d 个保留）",
                     label, f, ", ".join(dropped), len(kept))
    return t


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    m = s.meta
    old_acct = m.account_path
    conv = m.conversion_domain_bare or None

    acct_info = g.get_object(NEW_ACCT, "name,account_status,currency")
    log.info("新账户: %r · status %s · currency %s", acct_info.get("name"),
             acct_info.get("account_status"), acct_info.get("currency"))
    if int(acct_info.get("account_status") or 0) != 1 or acct_info.get("currency") != "MYR":
        log.error("新账户不是 ACTIVE/MYR — 停止。")
        sys.exit(1)
    avail_aud = {str(a.get("id")) for a in g._get_all(
        f"{NEW_ACCT}/customaudiences", {"fields": "id", "limit": 200})}

    src = g.get_object(SRC_ADSET, "name,targeting,promoted_object,optimization_goal,"
                                  "billing_event,bid_strategy")
    targeting = src.get("targeting") or {}
    flex = targeting.get("flexible_spec") or []
    ints = [i.get("name") for spec in flex for i in (spec.get("interests") or [])]
    log.info("定向源（老账户单王 adset %s）: %r · ages %s-%s · interests %s · Adv+ %s",
             SRC_ADSET, src.get("name"), targeting.get("age_min"), targeting.get("age_max"),
             ", ".join(filter(None, ints))[:90] or "—",
             (targeting.get("targeting_automation") or {}).get("advantage_audience"))
    targeting = strip_audiences(targeting, log, src.get("name") or SRC_ADSET, avail_aud)
    log.info("   版位: platforms %s · fb %s · ig %s",
             targeting.get("publisher_platforms"), targeting.get("facebook_positions"),
             targeting.get("instagram_positions"))
    ig = targeting.get("instagram_positions")
    if ig and "explore_home" in ig and "explore" not in ig:
        targeting["instagram_positions"] = list(ig) + ["explore"]
        log.info("   ⚠️ 版位修正：源 ad set 选了 Explore home 没选 Explore（老规则允许，"
                 "现在建新 ad set 会被拒）— 按 Meta 报错指示补上 explore，其余照抄")

    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}

    def persist() -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    old_ads = g._get_all(f"{old_acct}/ads",
                         {"fields": "id,name,created_time", "limit": 500})
    log.info("老账户共 %d 条广告 — 按折叠名定位四个单王…", len(old_ads))

    def locate(t: Dict[str, str]) -> Dict[str, Any]:
        k = cpa.ad_key(t["name"])
        matches = [a for a in old_ads if cpa.ad_key(a.get("name") or "") == k]
        if not matches:
            near = sorted({(a.get("name") or "").strip() for a in old_ads
                           if cpa.norm(t["hint"]) in cpa.norm(a.get("name") or "")})
            raise RuntimeError(f"老账户找不到同名广告 {t['name']!r}；相近名: {near[:6]}")
        matches.sort(key=lambda a: (a.get("created_time") or "", a["id"]), reverse=True)
        fallback: Optional[Dict[str, Any]] = None
        for a in matches:
            try:
                cr = (g.get_object(a["id"], "creative{id,url_tags,"
                                            "effective_object_story_id,object_story_spec}")
                      .get("creative") or {})
            except GraphError:
                continue
            info = {"ad_id": a["id"], "ad_name": (a.get("name") or "").strip(),
                    "created": a.get("created_time"),
                    "post_id": cr.get("effective_object_story_id"),
                    "url_tags": cr.get("url_tags"),
                    "story": cr.get("object_story_spec") or {}}
            if info["post_id"]:
                return info
            vd = (info["story"].get("video_data") or {})
            if fallback is None and vd.get("video_id"):
                fallback = info
        if fallback is None:
            raise RuntimeError(f"{len(matches)} 个同名拷贝都没有可复用的 post/video")
        return fallback

    def make_creative(t: Dict[str, str], info: Dict[str, Any]) -> str:
        crs = st.setdefault("creatives", {})
        if crs.get(t["key"]):
            return crs[t["key"]]
        if info.get("post_id"):
            try:
                fields: Dict[str, Any] = {"name": info["ad_name"],
                                          "object_story_id": info["post_id"]}
                if info.get("url_tags"):
                    fields["url_tags"] = info["url_tags"]
                cid = g.create_adcreative(NEW_ACCT, **fields)["id"]
                crs[t["key"]] = cid
                persist()
                log.info("   + creative %s（复用老帖 %s ← ad %s %s — engagement 共池）",
                         cid, info["post_id"], info["ad_id"], info["created"])
                time.sleep(1.0)
                return cid
            except GraphError as exc:
                log.info("   · 老帖复用失败（%s）— 退回重传视频路线", str(exc)[:140])
        vd = (info["story"].get("video_data") or {})
        if not vd.get("video_id"):
            raise RuntimeError("老帖不可复用且不是视频贴（单图不走重传）— 需要人工看一眼")
        vids = st.setdefault("videos", {})
        new_vid = vids.get(t["key"])
        if not new_vid:
            src_url = g.get_object(vd["video_id"], "source").get("source")
            if not src_url:
                raise RuntimeError(f"video {vd['video_id']} 没有 CDN source，拿不到源文件")
            path = Path(f"/tmp/{t['key']}.mp4")
            with requests.get(src_url, stream=True, timeout=600) as r:
                r.raise_for_status()
                with open(path, "wb") as fh:
                    for chunk in r.iter_content(1 << 20):
                        fh.write(chunk)
            log.info("   ↓ %.1f MB → 上传新账户…", path.stat().st_size / 1_048_576)
            new_vid = g.upload_video(NEW_ACCT, str(path), name=info["ad_name"])
            path.unlink(missing_ok=True)
            vids[t["key"]] = new_vid
            persist()
        thumb = g.get_video_thumbnail(new_vid)
        vdata = {k: v for k, v in
                 {"video_id": new_vid, "title": vd.get("title"),
                  "message": vd.get("message"),
                  "call_to_action": vd.get("call_to_action")}.items() if v}
        if thumb:
            vdata["image_url"] = thumb
        story: Dict[str, Any] = {"page_id": m.page_id, "video_data": vdata}
        if m.instagram_user_id:
            story["instagram_user_id"] = m.instagram_user_id
        fields = {"name": info["ad_name"], "object_story_spec": story}
        if info.get("url_tags"):
            fields["url_tags"] = info["url_tags"]
        cid = g.create_adcreative(NEW_ACCT, **fields)["id"]
        crs[t["key"]] = cid
        persist()
        log.info("   + creative %s（重传视频 %s）", cid, new_vid)
        return cid

    # ── locate + creatives (skip-and-record per target) ────────────────────────
    skipped = st.setdefault("skipped", {})
    built: List[Dict[str, str]] = []
    for t in TARGETS:
        log.info("═" * 96)
        log.info("REVIVE %s %r", t["key"], t["name"])
        try:
            info = locate(t)
            log.info("   源: old ad %s（%s · post %s）", info["ad_id"], info["created"],
                     info.get("post_id") or "∅")
            make_creative(t, info)
            st.setdefault("sources", {})[t["key"]] = {
                "ad_id": info["ad_id"], "post_id": info.get("post_id")}
            built.append({"key": t["key"], "ad_name": info["ad_name"]})
            skipped.pop(t["key"], None)
            persist()
        except RuntimeError as exc:
            log.error("✗ %s 跳过：%s", t["key"], exc)
            skipped[t["key"]] = str(exc)
            persist()
    if not built:
        log.error("四个都没建成 — 见上面的原因；不建 campaign。")
        sys.exit(1)

    # ── campaign (PAUSED) · adset · ads ────────────────────────────────────────
    if st.get("campaign_id"):
        try:
            eff = g.get_object(st["campaign_id"], "effective_status").get("effective_status")
        except GraphError:
            eff = "DELETED"
        if eff in ("DELETED", "ARCHIVED"):
            st.pop("campaign_id", None)
            st.pop("adset_id", None)
            st.pop("ads", None)
    if not st.get("campaign_id"):
        fields = {"name": CAMPAIGN_NAME, "objective": m.objective,
                  "buying_type": "AUCTION", "status": "PAUSED",
                  "special_ad_categories": m.special_ad_categories,
                  "is_adset_budget_sharing_enabled": False}
        if m.regional_regulated_categories:
            fields["regional_regulated_categories"] = m.regional_regulated_categories
        st["campaign_id"] = g.create_campaign(NEW_ACCT, **fields)["id"]
        persist()
        log.info("+ campaign %s %r (PAUSED)", st["campaign_id"], CAMPAIGN_NAME)
        time.sleep(1.0)

    if not st.get("adset_id"):
        fields = {"name": src.get("name"), "campaign_id": st["campaign_id"],
                  "optimization_goal": src.get("optimization_goal"),
                  "billing_event": src.get("billing_event") or "IMPRESSIONS",
                  "promoted_object": src.get("promoted_object") or {},
                  "targeting": targeting, "status": "ACTIVE",
                  "daily_budget": DAILY_MINOR,
                  "bid_strategy": src.get("bid_strategy") or "LOWEST_COST_WITHOUT_CAP"}
        if m.regional_regulated_categories:
            fields["regional_regulated_categories"] = m.regional_regulated_categories
        if m.regional_regulation_identities:
            fields["regional_regulation_identities"] = m.regional_regulation_identities
        st["adset_id"] = g.create_adset(NEW_ACCT, **fields)["id"]
        persist()
        log.info("+ adset %s %r RM%d/day", st["adset_id"], src.get("name"),
                 DAILY_MINOR // 100)
        time.sleep(1.0)

    st.setdefault("ads", {})
    rows = []
    for b in built:
        if not st["ads"].get(b["key"]):
            ad = g.create_ad(NEW_ACCT, name=b["ad_name"], adset_id=st["adset_id"],
                             creative={"creative_id": st["creatives"][b["key"]]},
                             status="ACTIVE", conversion_domain=conv)
            st["ads"][b["key"]] = ad["id"]
            persist()
            time.sleep(1.0)
        eff = g.get_object(st["ads"][b["key"]], "effective_status").get("effective_status")
        log.info("▸ %s ad %s %r eff %s", b["key"], st["ads"][b["key"]], b["ad_name"], eff)
        rows.append(f"{b['key']}:{eff}")
    if skipped:
        log.error("跳过清单: %s", json.dumps(skipped, ensure_ascii=False))

    final_summary(log, f"复活单王 1-1-{len(built)} built PAUSED on {NEW_ACCT}: campaign "
                       f"{st['campaign_id']} · adset {st['adset_id']} RM{DAILY_MINOR // 100}"
                       f"/day (Food & Drink + Milk clone) · {'; '.join(rows)}"
                       f"{' · skipped: ' + ', '.join(skipped) if skipped else ''}. Operator "
                       f"flips the campaign to start; standard rules apply (no hold).")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min; run is idempotent.", exc)
        sys.exit(75)
