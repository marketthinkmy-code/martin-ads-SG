"""HEALTH & WELLNESS 1-3-3 (29 Sep): NEW account · CBO RM80 · PAUSED.

Operator: 建 Health & Wellness 那条 — the missing third proven targeting (16 lifetime
sales on the old account) in their hand-built 1-3-3 series.

Mirrors the operator's own template exactly: the FULL targeting of their MILK ad set
(120250067491610335 — SG · 25-65 · female · locales · Adv+ ON · auto placements ·
both exclusion audiences) is cloned and ONLY the flexible_spec (interest block) is
swapped for the old account's proven H&W ad set (120256984987300093). Structure:
1 campaign CBO RM80/day (PAUSED) → 3 identical 'HEALTH & WELLNESS' ad sets → 1 ad each,
creatives reuse existing page posts (engagement pools):
    Video: 什麼樣的孩子基本上不會再長高   60d 2单 · CPA RM341 (top-2 of the 60d list)
    Hook 6：没有人会告诉你               7-day test CPL RM20 (best) — never given volume
    Video 4：每天记录身高，却看不懂成长信号  fresh, untested
Idempotent via state/entities_hw_0929.json; rate limit exits 75, re-dispatch resumes.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from adbot.clients.graph import GraphError, TransientGraphError
from adbot.commands import graph_client
from adbot.logging import final_summary, get_logger
from adbot.settings import load_settings

NEW_ACCT = "act_1179668409969241"
TEMPLATE_ADSET = "120250067491610335"      # operator's MILK ad set — the 1-3-3 template
SRC_HW_ADSET = "120256984987300093"        # old acct Health & Wellness · 16 lifetime sales
STATE_PATH = Path("state") / "entities_hw_0929.json"
CAMPAIGN_NAME = "[SG] 儿童长高方程式 | HEALTH & WELLNESS | 1-3-3 new ads"
ADSET_NAME = "HEALTH & WELLNESS"
CBO_MINOR = 8000

ADS: List[Dict[str, str]] = [
    {"key": "shenme", "name": "Video: 什麼樣的孩子基本上不會再長高",
     "post": "341825319024143_122192843480485585"},
    {"key": "hook6", "name": "Hook 6：没有人会告诉你",
     "post": "341825319024143_122197861238485585"},
    {"key": "video4", "name": "Video 4：每天记录身高，却看不懂成长信号",
     "post": "341825319024143_122197328660485585"},
]


def main() -> None:
    log = get_logger()
    s = load_settings()
    g = graph_client(s)
    m = s.meta
    conv = m.conversion_domain_bare or None

    tpl = g.get_object(TEMPLATE_ADSET, "name,targeting,promoted_object,optimization_goal,"
                                       "billing_event")
    hw = g.get_object(SRC_HW_ADSET, "name,targeting")
    targeting = dict(tpl.get("targeting") or {})
    hw_flex = (hw.get("targeting") or {}).get("flexible_spec") or []
    if not hw_flex:
        log.error("H&W 源 adset %s 没有 flexible_spec — 停止。", SRC_HW_ADSET)
        sys.exit(1)
    targeting["flexible_spec"] = hw_flex
    ints = [e.get("name", "?") for spec in hw_flex for e in (spec.get("interests") or [])]
    log.info("模板=operator MILK adset（geo %s · age %s-%s · 女 · Adv+ %s · 排除 %d）",
             (targeting.get("geo_locations") or {}).get("countries"),
             targeting.get("age_min"), targeting.get("age_max"),
             (targeting.get("targeting_automation") or {}).get("advantage_audience"),
             len(targeting.get("excluded_custom_audiences") or []))
    log.info("兴趣组换成 H&W（源 %r）: %s", hw.get("name"), ", ".join(ints)[:150])

    st: Dict[str, Any] = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}

    def persist() -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2))

    if st.get("campaign_id"):
        try:
            eff = g.get_object(st["campaign_id"], "effective_status").get("effective_status")
        except GraphError:
            eff = "DELETED"
        if eff in ("DELETED", "ARCHIVED"):
            st = {}
    if not st.get("campaign_id"):
        fields = {"name": CAMPAIGN_NAME, "objective": m.objective,
                  "buying_type": "AUCTION", "status": "PAUSED",
                  "special_ad_categories": m.special_ad_categories,
                  "daily_budget": CBO_MINOR,
                  "bid_strategy": "LOWEST_COST_WITHOUT_CAP"}
        if m.regional_regulated_categories:
            fields["regional_regulated_categories"] = m.regional_regulated_categories
        st["campaign_id"] = g.create_campaign(NEW_ACCT, **fields)["id"]
        persist()
        log.info("+ campaign %s %r CBO RM%d/day (PAUSED)", st["campaign_id"],
                 CAMPAIGN_NAME, CBO_MINOR // 100)
        time.sleep(1.0)

    creatives = st.setdefault("creatives", {})
    for a in ADS:
        if creatives.get(a["key"]):
            continue
        fields: Dict[str, Any] = {"name": a["name"], "object_story_id": a["post"]}
        if m.url_tags:
            fields["url_tags"] = m.url_tags
        creatives[a["key"]] = g.create_adcreative(NEW_ACCT, **fields)["id"]
        persist()
        log.info("+ creative %s（%s ← 老帖 %s）", creatives[a["key"]], a["key"], a["post"])
        time.sleep(1.0)

    st.setdefault("adsets", {})
    st.setdefault("ads", {})
    rows = []
    for a in ADS:
        if not st["adsets"].get(a["key"]):
            fields = {"name": ADSET_NAME, "campaign_id": st["campaign_id"],
                      "optimization_goal": tpl.get("optimization_goal"),
                      "billing_event": tpl.get("billing_event") or "IMPRESSIONS",
                      "promoted_object": tpl.get("promoted_object") or {},
                      "targeting": targeting, "status": "ACTIVE"}
            if m.regional_regulated_categories:
                fields["regional_regulated_categories"] = m.regional_regulated_categories
            if m.regional_regulation_identities:
                fields["regional_regulation_identities"] = m.regional_regulation_identities
            st["adsets"][a["key"]] = g.create_adset(NEW_ACCT, **fields)["id"]
            persist()
            log.info("+ adset %s %r (CBO)", st["adsets"][a["key"]], ADSET_NAME)
            time.sleep(1.0)
        if not st["ads"].get(a["key"]):
            ad = g.create_ad(NEW_ACCT, name=a["name"], adset_id=st["adsets"][a["key"]],
                             creative={"creative_id": creatives[a["key"]]},
                             status="ACTIVE", conversion_domain=conv)
            st["ads"][a["key"]] = ad["id"]
            persist()
            time.sleep(1.0)
        eff = g.get_object(st["ads"][a["key"]], "effective_status").get("effective_status")
        log.info("▸ %s ad %s %r eff %s", a["key"], st["ads"][a["key"]], a["name"], eff)
        rows.append(f"{a['key']}:{eff}")

    final_summary(log, f"H&W 1-3-3 built PAUSED on {NEW_ACCT}: campaign {st['campaign_id']} "
                       f"CBO RM{CBO_MINOR // 100}/day · 3 ad sets · {'; '.join(rows)}. "
                       f"Operator flips to start; standard rules apply (no hold).")


if __name__ == "__main__":
    try:
        main()
    except TransientGraphError as exc:
        get_logger().error("RATE LIMITED: %s — re-dispatch in ~30 min; run is idempotent.", exc)
        sys.exit(75)
