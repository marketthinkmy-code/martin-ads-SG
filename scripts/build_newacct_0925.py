"""Port the approved board to the NEW ad account (operator's A/B test, 25 Sep).

Operator: "我建议这些全部你都开在新的 ads account，让我测试看看 是不是 ads manager 的问题…
命名，pixels，landing page 全部都一样，只是开在新的 ads manager" — business 2229316547221347,
new account act_1179668409969241.

What ports (the approved 0925 proposal):
    V12 15歲以上五六種方法      own campaign            RM150/day
    V1 流鼻涕 + Hook 9         shared campaign (as-is)  RM50 + RM30
    老 Hook 7 担心孩子的高度     1-5-5 campaign name      RM50/day
    新片 5 支测试               1 campaign · 1 adset     RM100/day · 5 ads

Mechanics: creatives and videos are ACCOUNT-SCOPED, so each source ad's video is pulled
back via its CDN `source` url and re-uploaded to the new account; body/title/CTA/url_tags
are read from the old creative and recreated verbatim; campaign/ad set/ad names copied
exactly (sheet UTM attribution keeps folding by name); targeting cloned from each old ad
set with custom-audience components STRIPPED (audiences don't exist in the new account —
logged loudly per ad set); promoted_object (pixel + event) copied as-is (same pixel).

Preflight hard-aborts unless: token reaches the new account, account ACTIVE, currency MYR.
Funding-source and pixel visibility are checked and warned. Campaigns are created PAUSED
(ad sets/ads ACTIVE) — the operator flips 4 campaigns to start the test. Idempotent via
state/entities_newacct_0925.json; rate-limit exits 75 and a re-dispatch resumes.

NOTE: the daily rules monitor watches ONLY the old account; this new board is manual
until the operator asks for monitor coverage.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import requests

from adbot.clients.graph import GraphError, TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

NEW_ACCT = "act_1179668409969241"
STATE_PATH = Path("state") / "entities_newacct_0925.json"
TEST_STATE = Path("state") / "entities_test155_fr_0921.json"

# chain key → (source ad id in the OLD account, daily budget cents on the NEW account)
CHAINS: List[Dict[str, Any]] = [
    {"key": "v12", "src_ad": "120258109011660093", "budget": 15000},
    {"key": "v1", "src_ad": "120258109022800093", "budget": 5000, "share_camp": "reopen"},
    {"key": "hook9", "src_ad": "120258109019740093", "budget": 3000, "share_camp": "reopen"},
    {"key": "hook7old", "src_ad": "120258299537590093", "budget": 5000},
]
TEST_BUDGET = 10000


def strip_audiences(t: Dict[str, Any], log, label: str) -> Dict[str, Any]:
    t = dict(t)
    dropped = []
    for f in ("custom_audiences", "excluded_custom_audiences"):
        if t.pop(f, None):
            dropped.append(f)
    if dropped:
        log.info("   ⚠️ %s: 去掉了 %s（受众是老账户资产，新账户没有）", label, ", ".join(dropped))
        rest = [k for k in ("flexible_spec", "interests", "behaviors") if t.get(k)]
        if not rest:
            log.info("   ⚠️ %s: 去掉受众后没有兴趣定向了 — 这条在新账户等于 Broad", label)
    return t


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    m = s.meta
    conv = m.conversion_domain_bare or None

    # ── preflight ───────────────────────────────────────────────────────────────
    acct_info = g.get_object(NEW_ACCT, "name,account_status,currency,funding_source_details")
    log.info("新账户: %r · status %s · currency %s · funding %s",
             acct_info.get("name"), acct_info.get("account_status"),
             acct_info.get("currency"),
             (acct_info.get("funding_source_details") or {}).get("display_string", "∅ 未绑卡?"))
    if int(acct_info.get("account_status") or 0) != 1:
        log.error("新账户状态不是 ACTIVE(1) — 停止。请在 BM 里检查账户状态。")
        sys.exit(1)
    if (acct_info.get("currency") or "") != "MYR":
        log.error("新账户货币是 %s 不是 MYR — 预算数字含义不同，停止。要按这个货币建请给预算换算。",
                  acct_info.get("currency"))
        sys.exit(1)
    if not acct_info.get("funding_source_details"):
        log.info("⚠️ 没读到付款方式 — 建好也可能不投递，记得在新账户绑卡。")
    try:
        pixels = {p.get("id") for p in g._get_all(f"{NEW_ACCT}/adspixels", {"fields": "id"})}
        po_probe = g.get_object(CHAINS[0]["src_ad"], "adset_id")
        src_po = g.get_object(po_probe["adset_id"], "promoted_object").get("promoted_object") or {}
        if src_po.get("pixel_id") and src_po["pixel_id"] not in pixels:
            log.info("⚠️ pixel %s 不在新账户的 adspixels 列表（可能仍可用，若 adset 创建报错 → 去 BM 把 pixel 分享给新账户）",
                     src_po.get("pixel_id"))
    except Exception as exc:  # noqa: BLE001
        log.info("pixel 预检读不了（%s）— 建 adset 时见真章", str(exc)[:100])

    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}

    def persist() -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    def read_source(ad_id: str) -> Dict[str, Any]:
        ad = g.get_object(ad_id, "name,adset_id,campaign_id,"
                                 "creative{id,url_tags,object_story_spec}")
        aset = g.get_object(ad["adset_id"],
                            "name,targeting,optimization_goal,billing_event,bid_strategy,"
                            "promoted_object")
        camp = g.get_object(ad["campaign_id"], "name,objective")
        story = (ad.get("creative") or {}).get("object_story_spec") or {}
        vd = story.get("video_data") or {}
        return {"ad_name": ad["name"], "adset_name": aset["name"],
                "camp_name": camp["name"], "objective": camp.get("objective"),
                "targeting": aset.get("targeting") or {},
                "optimization_goal": aset.get("optimization_goal"),
                "billing_event": aset.get("billing_event") or "IMPRESSIONS",
                "bid_strategy": aset.get("bid_strategy") or "LOWEST_COST_WITHOUT_CAP",
                "promoted_object": aset.get("promoted_object") or {},
                "url_tags": (ad.get("creative") or {}).get("url_tags"),
                "video_id": vd.get("video_id"), "title": vd.get("title"),
                "message": vd.get("message"), "cta": vd.get("call_to_action")}

    def port_video(old_video_id: str, name: str, cache_key: str) -> str:
        vids = st.setdefault("videos", {})
        if vids.get(cache_key):
            return vids[cache_key]
        src = g.get_object(old_video_id, "source").get("source")
        if not src:
            raise RuntimeError(f"video {old_video_id} 拿不到 source url")
        path = Path(f"/tmp/{cache_key}.mp4")
        with requests.get(src, stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(path, "wb") as fh:
                for chunk in r.iter_content(1 << 20):
                    fh.write(chunk)
        log.info("   ↓ %s %.1f MB → 上传新账户…", cache_key, path.stat().st_size / 1_048_576)
        new_id = g.upload_video(NEW_ACCT, str(path), name=name)
        path.unlink(missing_ok=True)
        vids[cache_key] = new_id
        persist()
        return new_id

    def port_creative(srcinfo: Dict[str, Any], cache_key: str) -> str:
        crs = st.setdefault("creatives", {})
        if crs.get(cache_key):
            return crs[cache_key]
        new_vid = port_video(srcinfo["video_id"], srcinfo["ad_name"], cache_key)
        thumb = g.get_video_thumbnail(new_vid)
        vdata: Dict[str, Any] = {"video_id": new_vid, "title": srcinfo["title"],
                                 "message": srcinfo["message"],
                                 "call_to_action": srcinfo["cta"]}
        if thumb:
            vdata["image_url"] = thumb
        story: Dict[str, Any] = {"page_id": m.page_id, "video_data": vdata}
        if m.instagram_user_id:
            story["instagram_user_id"] = m.instagram_user_id
        fields: Dict[str, Any] = {"name": srcinfo["ad_name"], "object_story_spec": story}
        if srcinfo.get("url_tags"):
            fields["url_tags"] = srcinfo["url_tags"]
        cid = g.create_adcreative(NEW_ACCT, **fields)["id"]
        crs[cache_key] = cid
        persist()
        log.info("   + creative %s (%s)", cid, cache_key)
        return cid

    camps_new = st.setdefault("campaigns", {})

    def ensure_campaign(name: str, objective: str, cache_key: str) -> str:
        if camps_new.get(cache_key):
            return camps_new[cache_key]
        fields = {"name": name, "objective": objective or m.objective,
                  "buying_type": "AUCTION", "status": "PAUSED",
                  "special_ad_categories": m.special_ad_categories,
                  "is_adset_budget_sharing_enabled": False}
        if m.regional_regulated_categories:
            fields["regional_regulated_categories"] = m.regional_regulated_categories
        cid = g.create_campaign(NEW_ACCT, **fields)["id"]
        camps_new[cache_key] = cid
        persist()
        log.info("+ campaign %s %r (PAUSED)", cid, name)
        time.sleep(1.0)
        return cid

    def ensure_chain(cache_key: str, srcinfo: Dict[str, Any], campaign_id: str,
                     budget: int, creative_id: str, extra_ads: List | None = None) -> None:
        units = st.setdefault("units", {})
        rec = units.setdefault(cache_key, {})
        if not rec.get("adset_id"):
            targeting = strip_audiences(srcinfo["targeting"], log, srcinfo["adset_name"])
            fields = {"name": srcinfo["adset_name"], "campaign_id": campaign_id,
                      "optimization_goal": srcinfo["optimization_goal"],
                      "billing_event": srcinfo["billing_event"],
                      "promoted_object": srcinfo["promoted_object"],
                      "targeting": targeting, "status": "ACTIVE",
                      "daily_budget": budget, "bid_strategy": srcinfo["bid_strategy"]}
            if m.regional_regulated_categories:
                fields["regional_regulated_categories"] = m.regional_regulated_categories
            if m.regional_regulation_identities:
                fields["regional_regulation_identities"] = m.regional_regulation_identities
            rec["adset_id"] = g.create_adset(NEW_ACCT, **fields)["id"]
            persist()
            log.info("+ adset %s %r RM%d/day", rec["adset_id"], srcinfo["adset_name"],
                     budget // 100)
            time.sleep(1.0)
        ads_list = [(srcinfo["ad_name"], creative_id)] + (extra_ads or [])
        rec.setdefault("ads", {})
        for ad_name, cr in ads_list:
            if rec["ads"].get(ad_name):
                continue
            ad = g.create_ad(NEW_ACCT, name=ad_name, adset_id=rec["adset_id"],
                             creative={"creative_id": cr}, status="ACTIVE",
                             conversion_domain=conv)
            rec["ads"][ad_name] = ad["id"]
            persist()
            log.info("+ ad %s %r", ad["id"], ad_name)
            time.sleep(1.0)

    # ── the four single chains ─────────────────────────────────────────────────
    for ch in CHAINS:
        log.info("═" * 96)
        info = read_source(ch["src_ad"])
        log.info("PORT %s ← old ad %s %r", ch["key"], ch["src_ad"], info["ad_name"][:36])
        camp_key = ch.get("share_camp") or ch["key"]
        cid = ensure_campaign(info["camp_name"], info["objective"], camp_key)
        cr = port_creative(info, ch["key"])
        ensure_chain(ch["key"], info, cid, ch["budget"], cr)

    # ── the 5-ad test chain (one adset, five ads) ──────────────────────────────
    log.info("═" * 96)
    test = json.loads(TEST_STATE.read_text())
    first_key = "hook1"
    order = ["hook1", "nh4", "xh7", "xh3", "xh6"]
    infos = {k: read_source(test["ads"][k]) for k in order}
    tcid = ensure_campaign(infos[first_key]["camp_name"], infos[first_key]["objective"], "test")
    extra = []
    for k in order[1:]:
        extra.append((infos[k]["ad_name"], port_creative(infos[k], f"test_{k}")))
    ensure_chain("test", infos[first_key], tcid, TEST_BUDGET,
                 port_creative(infos[first_key], "test_hook1"), extra_ads=extra)

    log.info("═" * 96)
    for key, cid in camps_new.items():
        info = g.get_object(cid, "name,status,effective_status")
        log.info("▸ %-8s campaign %s %s/%s %r", key, cid, info.get("status"),
                 info.get("effective_status"), (info.get("name") or "")[:54])
    final_summary(log, f"New-account port complete on {NEW_ACCT}: 4 campaigns (PAUSED) · "
                       f"5 chains · 9 ads · same names/pixel/landing/url_tags · audiences "
                       f"stripped where noted. Operator flips the campaigns to start; "
                       f"daily-rules monitor does NOT cover this account yet.")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min; run is idempotent.", exc)
        sys.exit(75)
