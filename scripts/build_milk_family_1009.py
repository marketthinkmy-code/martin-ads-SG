"""倒掉牛奶 back into the HK FAMILY audience (operator, 9 Oct: 是我关的，建).

Why: 倒掉牛奶 sells (SG 2 sales in 30d) but its ENGAGED WOMEN ad set on the old SG account
went cold this week (RM192, 0 registrations) and the operator paused it. In the HK account
the same post did 9 registrations at CPL 74 in 30d. Plan item 6: give it the FAMILY audience
that 林書豪 runs in, RM50/day of its own.

How: inside the live HK campaign "[SG] 儿童长高方程式 | FAMILY | 1-3-3 new ads" (ABO), add ONE
new ad set cloned from the FAMILY template ad set (same targeting / optimisation /
promoted_object), daily budget RM50, created PAUSED for 验收 — 林書豪's own ad set keeps its
RM100 untouched. One ad inside it, named exactly "Hook 3：倒掉牛奶" so the sales sheet keeps
folding onto the same creative, built on the existing page post that earned the most
registrations in the last 30 days (HK first, old-SG fallback). Idempotent via
state/entities_milk_family_1009.json; Meta throttle exits 75.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from adbot.clients.graph import GraphError, TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.monitor_cpl import extract_results, result_action_type
from adbot.settings import load_settings

STATE_PATH = Path("state") / "entities_milk_family_1009.json"
HK_ACCT = "act_1179668409969241"
SG_ACCT = "act_1024930575770087"
TEMPLATE_ADSET = "120250067332510335"        # HK · FAMILY (林書豪 lives here, RM100)
AD_NAME = "Hook 3：倒掉牛奶"                   # keep the exact name: sheet folding + history
ADSET_NAME = "FAMILY · 倒掉牛奶"
DAILY_MINOR = 5000                           # RM50/day


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    m = s.meta
    token = result_action_type(m.conversion_event)
    conv = m.conversion_domain_bare or None
    today = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()
    d30 = today - dt.timedelta(days=30)
    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}

    def persist() -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    # ── 1. the template ad set and its campaign ─────────────────────────────────
    tpl = g.get_object(TEMPLATE_ADSET, "name,campaign_id,targeting,promoted_object,optimization_goal,"
                                       "billing_event,bid_strategy,daily_budget,effective_status")
    camp = g.get_object(str(tpl.get("campaign_id")), "name,effective_status,daily_budget")
    if camp.get("daily_budget"):
        log.error("❌ campaign %s 是 CBO（有 campaign 预算），新 ad set 拿不到自己的 RM50 —— 停止。", camp.get("id"))
        sys.exit(1)
    t = copy.deepcopy(tpl.get("targeting") or {})
    if not t:
        log.error("❌ 模板 ad set %s 没有 targeting —— 停止。", TEMPLATE_ADSET)
        sys.exit(1)
    ig = t.get("instagram_positions")
    if ig and "explore_home" in ig and "explore" not in ig:
        t["instagram_positions"] = list(ig) + ["explore"]
    ints = [x.get("name") for fs in t.get("flexible_spec") or [] for kind in
            ("interests", "behaviors", "family_statuses") for x in fs.get(kind) or []]
    log.info("模板 ad set %s %r · RM%d · %s · campaign %s %r (%s, ABO)", TEMPLATE_ADSET, tpl.get("name"),
             int(tpl.get("daily_budget") or 0) // 100, tpl.get("effective_status"), camp.get("id"),
             camp.get("name"), camp.get("effective_status"))
    log.info("受众：%s-%s · Adv+ %s · %s", t.get("age_min"), t.get("age_max"),
             (t.get("targeting_automation") or {}).get("advantage_audience"), "/".join(ints[:6]) or "broad")

    # ── 2. which 倒掉牛奶 post? the one with the most registrations in 30d ──────
    if not st.get("post"):
        cands: List[Dict[str, Any]] = []
        for label, acct in (("HK", HK_ACCT), ("SG老", SG_ACCT)):
            ins: Dict[str, List[float]] = {}
            for r in g._get_all(f"{acct}/insights",
                                {"level": "ad", "limit": 500, "fields": "ad_id,spend,actions",
                                 "time_range": json.dumps({"since": d30.isoformat(), "until": today.isoformat()})}):
                ins[r.get("ad_id")] = [float(r.get("spend") or 0), extract_results(r.get("actions"), token)]
            for a in g._get_all(f"{acct}/ads", {"fields": "id,name,status,effective_status,created_time,"
                                                           "creative{id,effective_object_story_id,url_tags}",
                                                 "limit": 500}):
                if "倒掉牛奶" not in (a.get("name") or ""):
                    continue
                cr = a.get("creative") or {}
                sp, ld = ins.get(a["id"], [0.0, 0.0])
                cands.append({"acct": label, "ad": a["id"], "name": a.get("name"), "status": a.get("effective_status"),
                              "post": cr.get("effective_object_story_id"), "creative": cr.get("id"),
                              "spend30": round(sp, 2), "leads30": int(ld), "created": (a.get("created_time") or "")[:10]})
        for c in sorted(cands, key=lambda x: (-x["leads30"], -x["spend30"])):
            log.info("  候选 %-4s ad %s %s · post %s · 30d RM%.2f %dL · 建 %s", c["acct"], c["ad"], c["status"],
                     c["post"], c["spend30"], c["leads30"], c["created"])
        with_post = [c for c in cands if c.get("post")]
        if not with_post:
            log.error("❌ 两个账户都找不到带帖子的倒掉牛奶广告 —— 停止，未建任何东西。")
            sys.exit(1)
        best = max(with_post, key=lambda x: (x["leads30"], x["spend30"]))
        st["post"], st["post_source"] = best["post"], {k: best[k] for k in ("acct", "ad", "spend30", "leads30")}
        persist()
    log.info("用帖子 %s（来源 %s）", st["post"], st.get("post_source"))

    # ── 3. creative on the HK account (post reuse; Meta de-dupes identical creatives) ──
    if not st.get("creative"):
        fields: Dict[str, Any] = {"name": AD_NAME, "object_story_id": st["post"]}
        if m.url_tags:
            fields["url_tags"] = m.url_tags
        st["creative"] = g.create_adcreative(HK_ACCT, **fields)["id"]
        persist()
        log.info("+ creative %s", st["creative"])
        time.sleep(0.8)

    # ── 4. the new ad set, PAUSED, RM50 of its own ───────────────────────────────
    aid: Optional[str] = st.get("adset")
    if aid:
        try:
            eff = g.get_object(aid, "effective_status").get("effective_status")
        except GraphError:
            eff = "DELETED"
        if eff in ("DELETED", "ARCHIVED"):
            aid = None
    if not aid:
        fields = {"name": ADSET_NAME, "campaign_id": camp.get("id"), "daily_budget": DAILY_MINOR,
                  "optimization_goal": tpl.get("optimization_goal"),
                  "billing_event": tpl.get("billing_event") or "IMPRESSIONS",
                  "promoted_object": tpl.get("promoted_object") or {},
                  "targeting": t, "status": "PAUSED"}
        if tpl.get("bid_strategy"):
            fields["bid_strategy"] = tpl["bid_strategy"]
        if m.regional_regulated_categories:
            fields["regional_regulated_categories"] = m.regional_regulated_categories
        if m.regional_regulation_identities:
            fields["regional_regulation_identities"] = m.regional_regulation_identities
        aid = g.create_adset(HK_ACCT, **fields)["id"]
        st["adset"] = aid
        persist()
        log.info("+ adset %s %r RM%d/day (PAUSED，验收后开)", aid, ADSET_NAME, DAILY_MINOR // 100)
        time.sleep(1.0)

    # ── 5. the ad (ACTIVE inside the PAUSED ad set: one switch to go live) ───────
    if not st.get("ad"):
        ad = g.create_ad(HK_ACCT, name=AD_NAME, adset_id=aid, creative={"creative_id": st["creative"]},
                         status="ACTIVE", conversion_domain=conv)
        st["ad"] = ad["id"]
        persist()
        time.sleep(0.8)
    eff = g.get_object(st["ad"], "effective_status").get("effective_status")
    log.info("    ▸ ad %s %r eff %s", st["ad"], AD_NAME, eff)
    final_summary(log, f"倒掉牛奶 → HK FAMILY: adset {st['adset']} (PAUSED, RM{DAILY_MINOR // 100}) · "
                       f"ad {st['ad']} ({eff}) · post {st['post']} · 林書豪 ad set untouched")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — state saved, re-dispatch in ~30 min.", exc)
        sys.exit(75)
