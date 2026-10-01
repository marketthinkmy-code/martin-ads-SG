"""Execute the 10/1 CPA verdict (operator: 执行).

① PAUSE every live copy on the NEW account of the three no-sale burners
   (ad level only — ad sets/campaigns untouched):
       Hook 1：今晚回家检查三件事   30d RM1,435 · 0 单
       Hook 4：保健品叫你丢掉       30d RM791   · 0 单
       Hook 7：算给你看            30d RM410   · 0 单
② REVIVE two 30d-qualified sellers as PAUSED ads for review (new same-targeting
   ad set per campaign, CBO so no budget math; creatives reuse the newest old post):
       MAR Video 5: 林書豪 story（9/30 成交 · 30d CPA RM405） → FAMILY | 1-3-3 new ads
       Hook 2：你還在把麵包當早餐？（30d CPA RM633）          → MILK | 1-3-3 new ads
③ DIAGNOSE (read-only) why BROAD WOMEN | CPA 好的广告 spends nothing — statuses and
   issues logged, nothing changed there (operator hand-built it; report, don't fix).
Idempotent via state/exec_1001.json; rate limit exits 75, re-dispatch resumes.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from adbot import cpa
from adbot.clients.graph import GraphError, TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

NEW_ACCT = "act_1179668409969241"
STATE_PATH = Path("state") / "exec_1001.json"
PAUSE_NAMES = ["Hook 1：今晚回家检查三件事", "Hook 4：保健品叫你丢掉", "Hook 7：算给你看"]
REVIVE = [
    {"key": "linshuhao", "name": "MAR Video 5: 林書豪 story", "camp_frag": "family | 1-3-3"},
    {"key": "breadhook2", "name": "Hook 2：你還在把麵包當早餐？", "camp_frag": "milk | 1-3-3"},
]


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    m = s.meta
    old_acct = m.account_path
    conv = m.conversion_domain_bare or None

    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}

    def persist() -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    # ── ① pause the three burners (every live copy, ad level) ──────────────────
    pause_keys = {cpa.ad_key(n): n for n in PAUSE_NAMES}
    new_ads = g._get_all(f"{NEW_ACCT}/ads",
                         {"fields": "id,name,effective_status,adset_id,campaign{name}",
                          "limit": 500})
    paused = st.setdefault("paused", {})
    log.info("① 关三支无单烧钱王（只动广告层）")
    for a in new_ads:
        k = cpa.ad_key(a.get("name") or "")
        if k in pause_keys and a.get("effective_status") == "ACTIVE":
            g._request("POST", a["id"], data={"status": "PAUSED"})
            camp = ((a.get("campaign") or {}).get("name") or "?")[:44]
            paused[a["id"]] = f"{a.get('name')} @ {camp}"
            persist()
            log.info("  ⏸ paused ad %s %r（campaign %s）", a["id"], a.get("name"), camp)
            time.sleep(0.5)
    if not paused:
        log.info("  （没有找到需要关的 ACTIVE 拷贝）")

    # ── ② revive two qualified sellers, PAUSED for review ──────────────────────
    ads_index = []
    for acct in (old_acct, NEW_ACCT):
        for a in g._get_all(f"{acct}/ads", {"fields": "id,name,created_time", "limit": 500}):
            ads_index.append((a.get("created_time") or "", a["id"],
                              cpa.ad_key(a.get("name") or ""), (a.get("name") or "").strip()))
    ads_index.sort(reverse=True)

    def locate(name: str):
        k = cpa.ad_key(name)
        for _c, ad_id, kk, disp in ads_index:
            if kk != k:
                continue
            try:
                cr = (g.get_object(ad_id, "creative{effective_object_story_id,url_tags}")
                      .get("creative") or {})
            except GraphError:
                continue
            if cr.get("effective_object_story_id"):
                return disp, cr["effective_object_story_id"], cr.get("url_tags")
        return None, None, None

    camps = g._get_all(f"{NEW_ACCT}/campaigns",
                       {"fields": "id,name,effective_status,bid_strategy", "limit": 200})
    adsets = g._get_all(f"{NEW_ACCT}/adsets",
                        {"fields": "id,name,status,campaign_id,targeting,promoted_object,"
                                   "optimization_goal,billing_event,bid_amount", "limit": 500})
    log.info("② 复活两支达标单王（新 ad set · 广告 PAUSED 验收）")
    for r in REVIVE:
        rec = st.setdefault(r["key"], {})
        camp = next((c for c in camps if r["camp_frag"] in cpa.norm(c.get("name") or "")
                     and c.get("effective_status") == "ACTIVE"), None)
        if camp is None:
            log.error("  ✗ %s：找不到 ACTIVE campaign 含 %r — 跳过", r["key"], r["camp_frag"])
            continue
        tpl = next((a for a in adsets if a.get("campaign_id") == camp["id"]
                    and a.get("status") == "ACTIVE" and a.get("targeting")), None)
        if tpl is None:
            log.error("  ✗ %s：campaign %s 里没有可克隆的 ACTIVE ad set — 跳过",
                      r["key"], camp["id"])
            continue
        disp, post, tags = locate(r["name"])
        if not post:
            log.error("  ✗ %s：两账户都找不到 %r 的可复用帖 — 跳过", r["key"], r["name"])
            continue
        if not rec.get("creative_id"):
            fields: Dict[str, Any] = {"name": disp, "object_story_id": post}
            if tags or m.url_tags:
                fields["url_tags"] = tags or m.url_tags
            rec["creative_id"] = g.create_adcreative(NEW_ACCT, **fields)["id"]
            persist()
            log.info("  + creative %s（%s ← 老帖 %s）", rec["creative_id"], r["key"], post)
            time.sleep(1.0)
        if not rec.get("adset_id"):
            fields = {"name": tpl.get("name"), "campaign_id": camp["id"],
                      "optimization_goal": tpl.get("optimization_goal"),
                      "billing_event": tpl.get("billing_event") or "IMPRESSIONS",
                      "promoted_object": tpl.get("promoted_object") or {},
                      "targeting": tpl.get("targeting"), "status": "ACTIVE"}
            if tpl.get("bid_amount"):
                fields["bid_amount"] = tpl["bid_amount"]
            if m.regional_regulated_categories:
                fields["regional_regulated_categories"] = m.regional_regulated_categories
            if m.regional_regulation_identities:
                fields["regional_regulation_identities"] = m.regional_regulation_identities
            try:
                rec["adset_id"] = g.create_adset(NEW_ACCT, **fields)["id"]
                log.info("  + adset %s %r（campaign %r bid_strategy %s · CBO）",
                         rec["adset_id"], tpl.get("name"),
                         (camp.get("name") or "")[:40], camp.get("bid_strategy"))
            except GraphError as exc:
                rec["adset_id"] = tpl["id"]
                log.info("  · 新 ad set 建不了（%s）— PAUSED 广告直接放进现有 ad set %s %r",
                         str(exc)[:130], tpl["id"], tpl.get("name"))
            persist()
            time.sleep(1.0)
        if not rec.get("ad_id"):
            ad = g.create_ad(NEW_ACCT, name=disp, adset_id=rec["adset_id"],
                             creative={"creative_id": rec["creative_id"]},
                             status="PAUSED", conversion_domain=conv)
            rec["ad_id"] = ad["id"]
            persist()
            time.sleep(1.0)
        eff = g.get_object(rec["ad_id"], "effective_status").get("effective_status")
        log.info("  ▸ %s ad %s %r eff %s（你开）", r["key"], rec["ad_id"], disp, eff)

    # ── ③ BROAD WOMEN diagnosis (read-only) ────────────────────────────────────
    log.info("③ BROAD WOMEN 零消耗诊断（只读）")
    bw = next((c for c in camps if "broad women" in cpa.norm(c.get("name") or "")), None)
    if bw is None:
        log.info("  找不到 BROAD WOMEN campaign")
    else:
        info = g.get_object(bw["id"], "name,status,effective_status,daily_budget")
        log.info("  campaign %s %s/%s · 预算 RM%s", bw["id"], info.get("status"),
                 info.get("effective_status"), int(info.get("daily_budget") or 0) // 100)
        for aset in (a for a in adsets if a.get("campaign_id") == bw["id"]):
            ainfo = g.get_object(aset["id"], "name,status,effective_status,daily_budget")
            log.info("  ── adset %s %r %s/%s · RM%s", aset["id"], ainfo.get("name"),
                     ainfo.get("status"), ainfo.get("effective_status"),
                     int(ainfo.get("daily_budget") or 0) // 100)
        for a in new_ads:
            aset_ids = {x["id"] for x in adsets if x.get("campaign_id") == bw["id"]}
            if a.get("adset_id") in aset_ids:
                det = g.get_object(a["id"], "name,status,effective_status,issues_info")
                log.info("     ▸ ad %s %r %s/%s issues=%s", a["id"], det.get("name"),
                         det.get("status"), det.get("effective_status"),
                         json.dumps(det.get("issues_info") or [], ensure_ascii=False)[:160])

    final_summary(log, f"Executed: {len(paused)} burner copies paused; revivals "
                       f"{', '.join(k for k in ('linshuhao', 'breadhook2') if st.get(k, {}).get('ad_id'))} "
                       f"built PAUSED for review; BROAD WOMEN diagnosed read-only.")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min; run is idempotent.", exc)
        sys.exit(75)
